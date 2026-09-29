"""HTTP endpoint routers for the MBForge API.

Each submodule exposes one or more ``APIRouter`` instances that the main
FastAPI factory mounts under ``/api/v1/``. Routers are imported here so the
application can discover and register them in one place.
"""
