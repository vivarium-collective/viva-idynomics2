"""Composite-generator integration: drive the bigraph end-to-end."""

from __future__ import annotations

from pathlib import Path

import pytest

from pbg_idynomics2 import runtime
from pbg_idynomics2.composites import idynomics2_biofilm


REPO_ROOT = Path(__file__).resolve().parents[1]


def _jvm_available() -> bool:
    return runtime.jvm_library_path() is not None


def test_generator_is_registered():
    """The @composite_generator decorator should register the function in _REGISTRY."""
    from viva_superpowers.composite_generator import _REGISTRY
    matches = [eid for eid in _REGISTRY if eid.endswith(".idynomics2_biofilm")]
    assert matches, (
        "idynomics2_biofilm not in composite-generator registry; "
        f"have: {list(_REGISTRY)[:5]}"
    )


@pytest.mark.skipif(not _jvm_available(), reason="Java 11+ JVM not available")
def test_generator_runs(tmp_path):
    """The decorated generator produces a runnable Composite document."""
    from process_bigraph import Composite, allocate_core

    core = allocate_core()
    # The decorator leaves the original function callable; passing kwargs
    # exercises the same code path the dashboard's build_generator would.
    document = idynomics2_biofilm(core=core, protocol="simple", interval=180.0)
    sim = Composite({"state": document}, core=core)
    sim.run(540.0)  # three iDynoMiCS steps
    proc_state = sim.state["idynomics"]["instance"]._prev_pop
    assert proc_state > 0
