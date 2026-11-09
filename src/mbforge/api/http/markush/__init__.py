"""HTTP API for the Markush review queue.

Endpoints (all under ``/api/v1/markush``):

- ``POST /list`` — paginated queue listing with optional filters.
- ``POST /get`` — fetch one candidate with its evidence chain and
  decision log.
- ``POST /decide`` — apply a ``confirm_*`` / ``reject`` / ``reopen``
  action with optimistic-lock versioning.
- ``POST /update`` — edit SMILES / labels / role of a pending candidate.

Domain errors (ReviewNotFoundError / ReviewConflictError /
ReviewTransitionError) inherit MBForgeError and are handled by the central
exception handler; routers only ``raise`` them and let the framework turn the
status code + error_code into JSON.
"""

from __future__ import annotations

from fastapi import APIRouter

from mbforge.api.http.markush import review

router = APIRouter()
router.include_router(review.router)

__all__ = ["router"]
