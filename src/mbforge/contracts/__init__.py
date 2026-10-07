"""Neutral contracts shared across layers.

Request/read models that a lower layer (``db`` or a port) must reference live
here rather than in ``service``, so ``db``/ports never import a use case.
The owning ``service`` DTO modules re-export these names for their existing
callers.
"""
