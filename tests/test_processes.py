"""Unit + integration tests for the IDynoMiCS-2 wrapper.

Most tests need a running JVM with the iDynoMiCS JAR; we mark them as
``skip`` if the JAR or a JDK 11+ aren't available so the suite still passes
on a thin CI image.  ``test_smoke_no_jvm`` verifies the schema surface
without starting the JVM.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pbg_idynomics2 import IDynoMiCS2Process, runtime

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = REPO_ROOT / "protocols" / "simple.xml"


def _jvm_available() -> bool:
    return runtime.jvm_library_path() is not None


def _jar_available() -> bool:
    if os.environ.get("PBG_IDYNOMICS2_OFFLINE"):
        return runtime.jar_path().exists()
    # In normal mode the runtime will fetch on demand; treat as available.
    return True


JVM_REASON = "Java 11+ JVM not found on this machine"
JAR_REASON = "iDynoMiCS-2 JAR not cached and PBG_IDYNOMICS2_OFFLINE is set"


def test_smoke_no_jvm():
    """Schemas are reportable without starting the JVM."""
    # We don't instantiate (would require core); just confirm class metadata.
    assert "protocol_path" in IDynoMiCS2Process.config_schema
    assert "compartment" in IDynoMiCS2Process.config_schema


@pytest.mark.skipif(not _jvm_available(), reason=JVM_REASON)
@pytest.mark.skipif(not _jar_available(), reason=JAR_REASON)
def test_initial_state(tmp_path):
    """initial_state runs the simulator's setup and reports starting concentrations."""
    from process_bigraph import allocate_core

    core = allocate_core()
    proc = IDynoMiCS2Process(
        config={
            "protocol_path": str(PROTOCOL),
            "compartment": "biofilm-compartment",
            "solutes": ["solute", "oxygen"],
            "working_dir": str(tmp_path),
        },
        core=core,
    )
    state = proc.initial_state()
    assert "average_concentrations" in state
    assert "population" in state
    assert "time" in state
    assert set(state["average_concentrations"].keys()) == {"solute", "oxygen"}
    # simple.xml has 30 agents at spawn, but iDynoMiCS may double-spawn or
    # split before initialRun; assert a positive population, not an exact count.
    assert state["population"] > 0


@pytest.mark.skipif(not _jvm_available(), reason=JVM_REASON)
@pytest.mark.skipif(not _jar_available(), reason=JAR_REASON)
def test_step_changes_state(tmp_path):
    """Driving the bridge for a few intervals advances the simulator."""
    from process_bigraph import allocate_core

    core = allocate_core()
    proc = IDynoMiCS2Process(
        config={
            "protocol_path": str(PROTOCOL),
            "compartment": "biofilm-compartment",
            "solutes": ["solute", "oxygen"],
            "working_dir": str(tmp_path),
        },
        core=core,
    )
    t0 = proc.initial_state()["time"]
    update = proc.update({"external_concentrations": {}}, interval=540.0)  # 3 steps
    assert proc._timer.getCurrentTime() > t0
    assert isinstance(update["population"], float)
    # Total population should not have collapsed to zero in the first three steps.
    assert proc._prev_pop > 0
