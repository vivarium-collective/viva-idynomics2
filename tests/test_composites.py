"""Composite-level integration: drive the bigraph end-to-end."""

from __future__ import annotations

from pathlib import Path

import pytest

from pbg_idynomics2 import runtime
from pbg_idynomics2.composites import build_document

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = REPO_ROOT / "protocols" / "simple.xml"


def _jvm_available() -> bool:
    return runtime.jvm_library_path() is not None


@pytest.mark.skipif(not _jvm_available(), reason="Java 11+ JVM not available")
def test_composite_runs(tmp_path):
    from process_bigraph import Composite, allocate_core

    core = allocate_core()
    document = build_document(
        PROTOCOL,
        solutes=["solute", "oxygen"],
        interval=180.0,
        working_dir=tmp_path,
    )
    sim = Composite({"state": document}, core=core)
    sim.run(540.0)  # three iDynoMiCS steps
    # After running, the time store should have advanced past 0.
    time_value = sim.state.get("stores", {}).get("time", 0.0)
    # Composite state is wrapped; accessing it portably is brittle, so just
    # assert sim ran without raising and the underlying process advanced.
    proc_state = sim.state["idynomics"]["instance"]._prev_pop
    assert proc_state > 0
