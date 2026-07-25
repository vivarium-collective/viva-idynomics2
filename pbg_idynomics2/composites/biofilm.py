"""Composite generators for IDynoMiCS-2 biofilm simulations."""

from __future__ import annotations

from pathlib import Path

from viva_superpowers.composite_generator import composite_generator

from .. import runtime

# Repo-vendored protocols if running from a development checkout.
_REPO_PROTOCOL_DIR = Path(__file__).resolve().parent.parent.parent / "protocols"


def _resolve_protocol(protocol: str) -> str:
    """Resolve a protocol arg to an absolute path.

    Accepts an absolute path, a relative path, or a bare protocol name.
    For bare names we check (in order):

    1. ``<repo>/protocols/<name>.xml`` if we're in a dev checkout,
    2. ``~/.cache/pbg-idynomics2/iDynoMiCS-2-<tag>/protocol/<name>.xml`` —
       the upstream protocol library bundled in the release zip.

    The second path is populated lazily by
    :func:`pbg_idynomics2.runtime.ensure_release` on first JVM start.
    """
    if "/" in protocol or protocol.endswith(".xml"):
        p = Path(protocol).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        return str(p)
    repo_path = _REPO_PROTOCOL_DIR / f"{protocol}.xml"
    if repo_path.is_file():
        return str(repo_path.resolve())
    cached = runtime.release_root() / "protocol" / f"{protocol}.xml"
    return str(cached.resolve())


@composite_generator(
    name="idynomics2_biofilm",
    description=(
        "Single-compartment IDynoMiCS-2 biofilm wired to four stores: "
        "external_concentrations (input), average_concentrations / "
        "population / time (outputs)."
    ),
    parameters={
        "protocol": {
            "type": "string", "default": "simple",
            "description":
                "Protocol name (resolved against pbg-idynomics2/protocols/<name>.xml) "
                "or an absolute path to an iDynoMiCS XML protocol.",
        },
        "compartment": {
            "type": "string", "default": "biofilm-compartment",
            "description": "Name of the compartment to drive within the protocol.",
        },
        "interval": {
            "type": "float", "default": 180.0,
            "description":
                "PBG step size in the protocol's time units (minutes for simple.xml).",
        },
    },
)
def idynomics2_biofilm(core=None, *, protocol="simple",
                       compartment="biofilm-compartment", interval=180.0):
    """Wire one IDynoMiCS-2 process to four stores + a RAM emitter."""
    return {
        "idynomics": {
            "_type": "process",
            "address": "local:IDynoMiCS2Process",
            "config": {
                "protocol_path": _resolve_protocol(protocol),
                "compartment": compartment,
            },
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
            "external_concentrations": {},
            "average_concentrations": {},
            "population": 0.0,
            "time": 0.0,
        },
        "emitter": {
            "_type": "step",
            "address": "local:RAMEmitter",
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


@composite_generator(
    name="idynomics2_chemostat",
    description=(
        "IDynoMiCS-2 chemostat compartment (dimensionless, ODE-driven). "
        "Same port surface as the biofilm generator — useful for pulsed "
        "feed studies via the external_concentrations input."
    ),
    parameters={
        "protocol": {
            "type": "string", "default": "chemostat",
            "description":
                "Protocol shipped under pbg-idynomics2/protocols/<name>.xml or absolute path.",
        },
        "compartment": {
            "type": "string", "default": "chemostat",
            "description": "Chemostat compartment name in the protocol.",
        },
        "interval": {
            "type": "float", "default": 1.0,
            "description": "PBG step size (the bundled chemostat.xml uses dt=1).",
        },
    },
)
def idynomics2_chemostat(core=None, *, protocol="chemostat",
                          compartment="chemostat", interval=1.0):
    # idynomics2_biofilm is the raw decorated function (the decorator returns
    # fn unchanged), so we can call it directly.
    return idynomics2_biofilm(
        core=core, protocol=protocol, compartment=compartment, interval=interval
    )
