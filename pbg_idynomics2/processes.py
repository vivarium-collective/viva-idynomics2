"""IDynoMiCS-2 process-bigraph wrapper.

Wraps the real ``idynomics.Simulator`` (loaded into the JVM via JPype) as a
process-bigraph ``Process``.  Each ``update(state, interval)`` advances the
simulator by approximately ``interval`` minutes of simulated time, then emits:

* per-solute average concentration deltas (so sibling processes can also
  contribute to those stores additively);
* the change in agent population since the previous step.

Input ports let an upstream bigraph push absolute external solute
concentrations into the iDynoMiCS environment before stepping.
"""

from __future__ import annotations

import os
from pathlib import Path

from process_bigraph import Process

from . import jvm as _jvm
from . import runtime


class IDynoMiCS2Process(Process):
    """Bridge process for IDynoMiCS-2.

    Inputs
    ------
    external_concentrations : map[string, float]
        Absolute external solute concentrations (e.g. mg/L) pushed into the
        chosen compartment's environment before each step.  Only solute names
        listed in ``config['solutes']`` are honored.

    Outputs
    -------
    average_concentrations : map[string, float]
        Per-solute change in average concentration since the previous step
        (composable ``float`` delta).
    population : float
        Change in agent count in the compartment since the previous step.
    time : float
        Simulator's current time after this step (replace semantics via
        ``overwrite[float]`` to expose absolute simulated time without
        accumulating deltas).
    """

    config_schema = {
        "protocol_path": {"_type": "string", "_default": ""},
        "compartment": {"_type": "string", "_default": "biofilm-compartment"},
        # If empty, all solutes registered in the compartment are tracked.
        "solutes": {"_type": "list[string]", "_default": []},
        # If non-empty, override JAR discovery.
        "jar_path": {"_type": "string", "_default": ""},
        # If non-empty, set as cwd while iDynoMiCS reads default.cfg and writes results.
        "working_dir": {"_type": "string", "_default": ""},
    }

    def __init__(self, config=None, core=None):
        super().__init__(config=config, core=core)
        self._sim = None
        self._compartment = None
        self._env = None
        self._agents = None
        self._timer = None
        self._solute_names: list[str] = []
        self._prev_concns: dict[str, float] = {}
        self._prev_pop: int = 0
        self._initialized = False

    # ----- bigraph-schema port surface -----

    def inputs(self):
        return {"external_concentrations": "map[string,float]"}

    def outputs(self):
        return {
            "average_concentrations": "map[string,float]",
            "population": "float",
            "time": "overwrite[float]",
        }

    def initial_state(self):
        # Run lazy init so we can report initial concentrations / population.
        self._ensure_initialized()
        return {
            "average_concentrations": dict(self._prev_concns),
            "population": float(self._prev_pop),
            "time": float(self._timer.getCurrentTime()),
        }

    # ----- bridge mechanics -----

    def _ensure_initialized(self):
        if self._initialized:
            return

        jar = self.config.get("jar_path") or None
        _jvm.start_jvm(jar=jar)

        protocol = self.config["protocol_path"]
        if not protocol:
            raise ValueError("config['protocol_path'] is required (path to iDynoMiCS XML protocol).")
        protocol_path = str(Path(protocol).resolve())
        if not Path(protocol_path).exists():
            raise FileNotFoundError(f"protocol file not found: {protocol_path}")

        working_dir = self.config.get("working_dir")
        if not working_dir:
            # iDynoMiCS reads default.cfg + config/ from cwd; the cached
            # release ships these.  Falling back to it silences the
            # FileNotFoundException stack trace at startup and keeps results
            # contained.
            release_root = runtime.release_root()
            if (release_root / "default.cfg").exists():
                working_dir = str(release_root)
        if working_dir:
            Path(working_dir).mkdir(parents=True, exist_ok=True)

        from jpype import JClass, JString

        Idynomics = JClass("idynomics.Idynomics")
        prev_cwd = os.getcwd()
        try:
            if working_dir:
                os.chdir(working_dir)
            Idynomics.setupSimulator(JString(protocol_path))
        finally:
            if working_dir:
                os.chdir(prev_cwd)

        self._sim = Idynomics.simulator
        if not bool(self._sim.isReadyForLaunch()):
            raise RuntimeError(
                f"iDynoMiCS simulator not ready for launch from protocol {protocol_path}"
            )
        self._sim.initialRun()

        comp_name = self.config["compartment"]
        if not bool(self._sim.hasCompartment(comp_name)):
            raise RuntimeError(
                f"compartment {comp_name!r} not found in simulator. "
                f"Check config['compartment'] against your protocol."
            )
        self._compartment = self._sim.getCompartment(comp_name)
        self._env = self._compartment.environment
        self._agents = self._compartment.agents
        self._timer = self._sim.timer

        configured = list(self.config.get("solutes") or [])
        all_names = [str(n) for n in self._env.getSoluteNames()]
        if configured:
            missing = [n for n in configured if n not in all_names]
            if missing:
                raise RuntimeError(
                    f"solutes {missing} not present in compartment {comp_name!r}; "
                    f"available: {all_names}"
                )
            self._solute_names = configured
        else:
            self._solute_names = all_names

        self._prev_concns = self._read_concentrations()
        self._prev_pop = int(self._agents.getNumAllAgents())
        self._initialized = True

    def _read_concentrations(self) -> dict[str, float]:
        return {
            name: float(self._env.getAverageConcentration(name))
            for name in self._solute_names
        }

    # ----- public accessors for spatial state -----

    def spatial_snapshot(self) -> dict:
        """Return a full snapshot of compartment state: solute grids + agent positions.

        Useful for visualization and post-processing.  Calls into the JVM, so
        keep this off any hot inner loop if you don't need it.

        Returns
        -------
        dict with keys:
            ``time``: float, current simulator time.
            ``shape``: dict with ``num_voxels`` (list of ints) and
                ``dimension_lengths`` (list of floats).
            ``solutes``: dict ``name -> {"grid": list[list[list[float]]],
                "average": float}``.
            ``agents``: list of dicts ``{"position": [x, y, z], "species": str
                or None, "mass": float or None}``.
        """
        self._ensure_initialized()
        from jpype import JClass
        ArrayType = JClass("grid.ArrayType")

        shape = self._compartment.environment.getShape()
        try:
            num_voxels = [int(n) for n in shape.getDimensionLengths()]
        except Exception:
            num_voxels = []
        try:
            dim_lengths = [float(d) for d in shape.getDimensionLengths()]
        except Exception:
            dim_lengths = []

        solutes_out = {}
        for name in self._solute_names:
            try:
                grid = self._env.getSoluteGrid(name)
            except Exception:
                continue
            try:
                arr = grid.getArray(ArrayType.CONCN)
                grid_list = [[[float(v) for v in row] for row in plane] for plane in arr]
            except Exception:
                grid_list = []
            solutes_out[name] = {
                "grid": grid_list,
                "average": float(self._env.getAverageConcentration(name)),
            }

        agents_out = []
        try:
            located = self._agents.getAllLocatedAgents()
        except Exception:
            located = []
        for agent in located:
            try:
                body = agent.get("body")
                if body is None:
                    continue
                center = body.getCenter(shape)
                pos = [float(c) for c in center]
            except Exception:
                continue
            try:
                species = agent.get("species")
                species = str(species) if species is not None else None
            except Exception:
                species = None
            try:
                mass = agent.get("mass")
                mass = float(mass) if mass is not None else None
            except Exception:
                mass = None
            agents_out.append({"position": pos, "species": species, "mass": mass})

        return {
            "time": float(self._timer.getCurrentTime()),
            "shape": {"num_voxels": num_voxels, "dimension_lengths": dim_lengths},
            "solutes": solutes_out,
            "agents": agents_out,
        }

    def update(self, state, interval):
        self._ensure_initialized()

        # Push upstream concentrations into iDynoMiCS before stepping.
        external = state.get("external_concentrations") or {}
        for name, value in external.items():
            if name in self._solute_names:
                self._env.setAllConcentration(name, float(value))

        # Step the simulator until we've advanced by ~interval (in iDynoMiCS time units).
        t0 = float(self._timer.getCurrentTime())
        target = t0 + float(interval)
        # Extend the end-of-sim if our target exceeds it.
        if target > float(self._timer.getEndOfSimulation()):
            self._timer.setEndOfSimulation(target)

        # Loop until current time reaches the target. Each step advances by stepSize.
        step_size = float(self._timer.getTimeStepSize())
        if step_size <= 0.0:
            raise RuntimeError("iDynoMiCS timer step size is non-positive; check protocol.")
        # Floor to nearest step; guard against runaway interval.
        max_steps = max(1, int((float(interval) / step_size) + 0.5))
        for _ in range(max_steps):
            if not bool(self._sim.active()):
                break
            self._sim.step()

        concns = self._read_concentrations()
        pop = int(self._agents.getNumAllAgents())

        d_concns = {n: concns[n] - self._prev_concns.get(n, concns[n]) for n in concns}
        d_pop = float(pop - self._prev_pop)
        self._prev_concns = concns
        self._prev_pop = pop

        return {
            "average_concentrations": d_concns,
            "population": d_pop,
            "time": float(self._timer.getCurrentTime()),
        }
