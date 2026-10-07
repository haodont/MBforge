"""Cross-layer ports (contracts satisfied by adapters).

These protocols live below ``service`` so concrete adapters (``db``) can
implement them without importing the layer above.
"""
