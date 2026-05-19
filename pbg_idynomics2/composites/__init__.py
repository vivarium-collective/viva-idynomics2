"""Composite generators for pbg-idynomics2.

Importing this package side-effect-registers every ``@composite_generator``
below so ``discover_generators()`` (and the dashboard's Composites tab) can
find them.
"""

from . import biofilm  # noqa: F401  — registers @composite_generator decorators

from .biofilm import idynomics2_biofilm, idynomics2_chemostat

__all__ = ["idynomics2_biofilm", "idynomics2_chemostat"]
