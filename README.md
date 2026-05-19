# pbg-idynomics2

Process-bigraph wrapper for **IDynoMiCS 2.0**, the Kreft Lab's Java-based
individual-based model (IBM) of microbial biofilms.

This package binds the real iDynoMiCS-2 simulator (loaded into a JVM through
JPype) as a [process-bigraph](https://github.com/vivarium-collective/process-bigraph)
`Process`, so an iDynoMiCS biofilm can be composed with other simulators
(metabolism, chemistry, environment, controllers) inside a single bigraph.

> The wrapper does **not** ship a mock — it drives the actual `idynomics.Simulator`
> from the upstream
> [iDynoMiCS-2 July 2025 release](https://github.com/kreft/iDynoMiCS-2/releases/tag/Release-2025-07).

## Prerequisites

- Python 3.10+
- **Java 11+** (`brew install openjdk@11` on macOS; `apt install openjdk-11-jdk`
  on Debian/Ubuntu).  iDynoMiCS-2 is compiled for JDK 11.
- About 50 MB of disk for the cached JAR + protocol files.

## Installation

```bash
# From PyPI (recommended, once published):
pip install pbg-idynomics2
# or with uv:
uv pip install pbg-idynomics2

# For development (editable):
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

Once installed, processes register automatically via
`bigraph_schema.package.discover` — no manual `register_link()` calls are
needed.

## Quick start

```python
from process_bigraph import Composite, allocate_core, gather_emitter_results
from process_bigraph.emitter import RAMEmitter

core = allocate_core()
core.register_link("ram-emitter", RAMEmitter)

document = {
    "idynomics": {
        "_type": "process",
        "address": "local:IDynoMiCS2Process",
        "config": {
            "protocol_path": "/abs/path/to/protocols/simple.xml",
            "compartment": "biofilm-compartment",
            "solutes": ["solute", "oxygen"],
        },
        "interval": 180.0,  # one iDynoMiCS step (minutes)
        "inputs": {
            "external_concentrations": ["stores", "external_concentrations"],
        },
        "outputs": {
            "average_concentrations": ["stores", "average_concentrations"],
            "population": ["stores", "population"],
            "time": ["stores", "time"],
        },
    },
    "stores": {
        "external_concentrations": {},
        "average_concentrations": {},
        "population": 0.0,
        "time": 0.0,
    },
    "emitter": {
        "_type": "step",
        "address": "local:ram-emitter",
        "config": {"emit": {
            "average_concentrations": "map[string,float]",
            "population": "float",
            "time": "float",
        }},
        "inputs": {
            "average_concentrations": ["stores", "average_concentrations"],
            "population": ["stores", "population"],
            "time": ["stores", "time"],
        },
    },
}

sim = Composite({"state": document}, core=core)
sim.run(1800.0)            # 1800 minutes of simulated biofilm growth
print(gather_emitter_results(sim))
```

The first call downloads the iDynoMiCS-2 release zip
(~12 MB) to `~/.cache/pbg-idynomics2/`.  Override with
`PBG_IDYNOMICS2_CACHE` or `PBG_IDYNOMICS2_JAR`.

## API

| Class | Kind | Inputs | Outputs |
| --- | --- | --- | --- |
| `IDynoMiCS2Process` | `Process` | `external_concentrations: map[string,float]` | `average_concentrations: map[string,float]` (deltas), `population: float` (delta), `time: overwrite[float]` |

### Config

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `protocol_path` | string | (required) | Path to an iDynoMiCS XML protocol. |
| `compartment` | string | `"biofilm-compartment"` | Name of the compartment to read/write. |
| `solutes` | list[string] | `[]` (all) | Solute names to track; empty = all in the compartment. |
| `jar_path` | string | `""` | Override JAR location (else uses cache). |
| `working_dir` | string | `""` | Set as cwd while iDynoMiCS reads its config / writes results. |

### Port semantics

* **`external_concentrations`** is *absolute*: each step it is pushed into
  `EnvironmentContainer.setAllConcentration(...)`.  Unconnected → iDynoMiCS
  evolves under its own boundary conditions.
* **`average_concentrations`** emits the **delta** since the previous step so
  another process can also write to the same store (e.g. a sibling chemistry
  module producing/consuming solute).  Concrete schema is `map[string,float]`
  — composable.
* **`population`** likewise emits the agent-count delta.
* **`time`** is `overwrite[float]` — replace semantics, since it represents the
  simulator's clock, not a quantity sibling processes accumulate into.

## Architecture

```
PBG bigraph                        JVM
┌─────────────────────┐         ┌────────────────────────┐
│ stores              │  set/   │ idynomics.Simulator    │
│   external_concns ──┼─►get   ►│   timer (Timer)        │
│   avg_concns ◄──────┼── delta │   getCompartment(name) │
│   population ◄──────┼── delta │     .environment       │
│   time ◄────────────┼── abs   │       getAverageCon..  │
│                     │         │     .agents.numAgents  │
│ idynomics (Process) │── step()│                        │
└─────────────────────┘         └────────────────────────┘
```

The bridge is bidirectional: upstream stores push absolute solute
concentrations down into iDynoMiCS before each `Simulator.step()`; the
post-step concentrations and populations come back out as composable deltas.

## Demo

```bash
source .venv/bin/activate
python demo/demo_report.py
```

Generates `demo/report.html` with:

* baseline biofilm growth under `simple.xml`
* a chemostat configuration (`chemostat.xml`)
* a coupled run where an upstream "feed" is dialed up partway through

The report opens automatically.

## Limitations and assumptions

* The JVM in a Python process **cannot be cleanly restarted** — this is a JPype
  / OpenJDK constraint, not an iDynoMiCS one.  One simulator per Python
  process.
* iDynoMiCS time is in **minutes** for the bundled protocols.  Pick `interval`
  to match the timer's `stepSize` for clean stepping; the bridge rounds.
* `solutes` must be names actually defined in the compartment.  Boundary-only
  solutes (`boundary><solute>`) are not separately addressable.
* Results files written by iDynoMiCS (XML state, log) land relative to cwd
  unless `working_dir` is set.

## Upstream

* Code: <https://github.com/kreft/iDynoMiCS-2>
* Reference: Kreft *et al.*, *PLOS Computational Biology* 2023,
  *journal.pcbi.1011303*.
