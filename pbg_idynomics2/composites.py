"""Helpers for assembling process-bigraph documents with the IDynoMiCS-2 wrapper."""

from __future__ import annotations

from pathlib import Path


def build_document(
    protocol_path: str | Path,
    *,
    compartment: str = "biofilm-compartment",
    solutes: list[str] | None = None,
    interval: float = 180.0,
    working_dir: str | Path | None = None,
    process_address: str = "local:IDynoMiCS2Process",
    initial_external: dict[str, float] | None = None,
) -> dict:
    """Return a minimal Composite document wiring a single IDynoMiCS-2 process to stores.

    ``interval`` is in the simulator's time units (minutes for typical biofilm
    protocols like ``simple.xml``).
    """
    protocol_path = str(Path(protocol_path).resolve())
    config = {
        "protocol_path": protocol_path,
        "compartment": compartment,
        "solutes": list(solutes or []),
    }
    if working_dir:
        config["working_dir"] = str(Path(working_dir).resolve())

    document = {
        "idynomics": {
            "_type": "process",
            "address": process_address,
            "config": config,
            "interval": float(interval),
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
            "external_concentrations": dict(initial_external or {}),
            "average_concentrations": {},
            "population": 0.0,
            "time": 0.0,
        },
    }
    return document
