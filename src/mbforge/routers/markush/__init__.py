"""HTTP API for the Markush review queue.

Endpoints (all under ``/api/v1/markush``):

- ``POST /list`` — paginated queue listing with optional filters.
- ``POST /get`` — fetch one candidate with its evidence chain and
  decision log.
- ``POST /decide`` — apply a ``confirm_*`` / ``reject`` / ``reopen``
  action with optimistic-lock versioning.
- ``POST /update`` — edit SMILES / labels / role of a pending candidate.
- ``POST /enumeration/preview`` — count theoretical combinations without
  running the enumeration.
- ``POST /enumeration/run`` — bounded deterministic enumeration.
- ``POST /enumeration/results`` — list the candidates produced by a run.
- ``POST /generated/decide`` — confirm or reject a generated candidate;
  ``confirm`` promotes it into the ``molecules`` table.
- Sites/options/mounts CRUD — see the endpoints below.

Domain errors (ReviewNotFoundError / ReviewConflictError /
ReviewTransitionError / MarkushSiteError) inherit MBForgeError and are
handled by the central exception handler; routers only ``raise`` them
and let the framework turn the status code + error_code into JSON.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import enumeration, mounts, options, review, sites

router = APIRouter()
router.include_router(review.router)
router.include_router(sites.router)
router.include_router(options.router)
router.include_router(mounts.router)
router.include_router(enumeration.router)

__all__ = ["router"]
