"""MBForge Web Application — FastAPI factory.

Pure-Python backend serving both the API and the React frontend.
Replaces the Tauri/Rust shell with a standard web application.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from mbforge.foundation.errors import MBForgeError
from mbforge.foundation.logger import (
    configure_uvicorn_access_logging,
    get_logger,
    push_diagnostic,
    reset_request_path,
    set_request_path,
)
from mbforge.foundation.paths import APP_VERSION

logger = get_logger("mbforge.app")


def _is_expected_client_disconnect(context: dict[str, object]) -> bool:
    """Identify Windows' normal SSE client-close transport reset."""
    exc = context.get("exception")
    if not isinstance(exc, ConnectionResetError):
        return False
    return (
        getattr(exc, "winerror", None) == 10054
        or getattr(exc, "errno", None) == 10054
        or 10054 in exc.args
    )


def _development_frontend_origins() -> list[str]:
    """Return the local Vite origins allowed to make direct API requests."""
    port = os.environ.get("MBFORGE_FRONTEND_PORT", "5173")
    configured_host = os.environ.get("MBFORGE_FRONTEND_HOST")
    hosts = {"localhost", "127.0.0.1"}
    if configured_host:
        hosts.add(configured_host)
    return [f"http://{host}:{port}" for host in sorted(hosts)]


def _log_prewarm_done(task: asyncio.Task[dict[str, str]]) -> None:
    """Surface background prewarm failures instead of losing them."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("Background model prewarm failed: %s", exc)


class SPAStaticFiles(StaticFiles):
    """Serve the React entry point for client-side routes."""

    async def get_response(self, path: str, scope):  # type: ignore[no-untyped-def]
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # API paths must keep their normal JSON 404 behavior. Static asset
            # paths with an extension should also remain genuine 404s.
            if exc.status_code != 404 or path.startswith("api/") or Path(path).suffix:
                raise
            return await super().get_response("index.html", scope)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info("MBForge web application starting...")

    loop = asyncio.get_running_loop()
    previous_loop_exception_handler = loop.get_exception_handler()

    def handle_loop_exception(
        current_loop: asyncio.AbstractEventLoop, context: dict[str, object]
    ) -> None:
        if _is_expected_client_disconnect(context):
            logger.debug(
                "Client connection reset during transport cleanup: %s",
                context.get("message", "connection reset"),
            )
            return
        if previous_loop_exception_handler is not None:
            previous_loop_exception_handler(current_loop, context)
        else:
            current_loop.default_exception_handler(context)

    loop.set_exception_handler(handle_loop_exception)

    # Start the durable queue worker for the configured library so rows
    # orphaned by a previous crash/restart are reclaimed and drained.
    from mbforge.adapters.runtime.ingest import worker
    from mbforge.foundation.config import load_global_config

    cfg = load_global_config()
    port = int(os.environ.get("MBFORGE_PORT", "18792"))

    # Register this process and sweep stale entries
    if cfg.library_root:
        from mbforge.adapters.persistence.sqlite.database import DatabaseManager

        # The queue worker assumes the unified database schema already exists.
        # Initialize it before scheduling the worker so a newly created or
        # previously empty library.db cannot reach the reclaim query first.
        DatabaseManager.get(cfg.library_root).initialize()

        from mbforge.adapters.runtime.process import ProcessRegistry, find_orphans, reap

        registry = ProcessRegistry.get(cfg.library_root)
        registry.register("server", port=port)
        registry.sweep_stale()

        # Auto-reap blocking orphans (if enabled in config)
        auto_reap = getattr(cfg.process, "auto_reap_orphans", True)
        if auto_reap:
            orphans = find_orphans(cfg.library_root, port)
            for candidate in [o for o in orphans if o.blocking]:
                result = reap(candidate, dry_run=False, grace=5.0)
                logger.info(
                    "Auto-reaped orphan PID %d: %s — %s",
                    candidate.pid,
                    result.action,
                    result.reason,
                )

        worker.ensure_queue_worker(cfg.library_root)

    prewarm_task: asyncio.Task[dict[str, str]] | None = None
    if os.environ.get("MBFORGE_PREWARM_MODELS") == "1":
        from mbforge.adapters.inference.prewarm import prewarm_models

        # Fire-and-forget: prewarm must not delay first-request handling.
        prewarm_task = asyncio.create_task(asyncio.to_thread(prewarm_models))
        prewarm_task.add_done_callback(_log_prewarm_done)
    try:
        yield
    finally:
        logger.info("MBForge shutting down...")
        # Cancel only tasks this application owns. Sweeping asyncio.all_tasks()
        # would also cancel the uvicorn server task that is awaiting this
        # shutdown, aborting graceful shutdown with a CancelledError traceback.
        if prewarm_task is not None and not prewarm_task.done():
            prewarm_task.cancel()

        # Ordered shutdown: workers → executor drain → backends → registry
        from mbforge.adapters.runtime.process import orchestrate_shutdown

        await orchestrate_shutdown(timeout=30.0)

        loop.set_exception_handler(previous_loop_exception_handler)
        logger.info("Shutdown complete")


# ---------------------------------------------------------------------------
# Request-path middleware + central exception handlers
# ---------------------------------------------------------------------------
#
# Production runs through this factory, so central handlers cover every
# `include_router` route on the main app (including molparser / models /
# pdf-render). The standalone model sidecar (`mbforge.server:app`) was
# removed — the main app registers the same local-model routers itself.


async def _request_path_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Push the current request path into a ContextVar so JSON file logs
    and the diagnostic ring buffer can attach it without API changes."""
    token = set_request_path(request.url.path)
    try:
        return await call_next(request)
    finally:
        reset_request_path(token)


def _severity_to_level(severity: str) -> int:
    return {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "fatal": logging.CRITICAL,
    }.get(severity, logging.ERROR)


async def _mbforge_error_handler(request: Request, exc: MBForgeError) -> JSONResponse:
    """Central handler for MBForgeError + subclasses.

    Logs at the level implied by `exc.severity`, pushes a record into the
    diagnostic ring buffer, and returns a JSON body the front-end can
    introspect via `AppError`.
    """
    level = _severity_to_level(exc.severity)
    logger.log(
        level,
        "MBForgeError on %s: %s [%s/%s]",
        request.url.path,
        exc.message,
        exc.error_code,
        exc.category,
        extra={
            "mbforge_error_code": exc.error_code,
            "mbforge_status_code": exc.status_code,
            "mbforge_severity": exc.severity,
            "mbforge_category": exc.category,
            "mbforge_context": exc.context,
        },
        exc_info=isinstance(exc, Exception),
    )
    push_diagnostic(
        {
            "level": logging.getLevelName(level),
            "logger": "mbforge.app.exception_handler",
            "message": exc.message,
            "error_code": exc.error_code,
            "status_code": exc.status_code,
            "severity": exc.severity,
            "category": exc.category,
            "context": exc.context,
        }
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.message,
            "detail": exc.detail,
            "error_code": exc.error_code,
            "severity": exc.severity,
            "category": exc.category,
            "context": exc.context,
            "timestamp": time.time(),
        },
    )


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for non-MBForgeError exceptions. Always fatal, generic code."""
    logger.error(
        "Unhandled on %s: %s",
        request.url.path,
        exc,
        exc_info=True,
        extra={
            "mbforge_error_code": "internal_error",
            "mbforge_status_code": 500,
            "mbforge_severity": "fatal",
            "mbforge_category": "unhandled",
            "mbforge_context": {"exception_type": type(exc).__name__},
        },
    )
    push_diagnostic(
        {
            "level": "CRITICAL",
            "logger": "mbforge.app.exception_handler",
            "message": str(exc) or type(exc).__name__,
            "error_code": "internal_error",
            "status_code": 500,
            "severity": "fatal",
            "category": "unhandled",
            "context": {"exception_type": type(exc).__name__},
        }
    )
    # Operator-friendly default; do not leak stack frames to the client.
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
            "error_code": "internal_error",
            "severity": "fatal",
            "category": "unhandled",
            "context": {},
            "timestamp": time.time(),
        },
    )


def create_app(serve_frontend: bool | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    serve_frontend:
        When ``True``, mount the React build (from ``frontend/dist`` or the
        ``FRONTEND_DIST`` / PyInstaller location) at the root path so a
        single port can serve both API and SPA. When ``False``, only the
        API is exposed; the SPA is expected to be served by Vite on
        :5173. When ``None`` (the default), the value falls back to the
        ``MBFORGE_SERVE_FRONTEND`` env var (``"1"`` → True, otherwise
        False). Tests can pass an explicit value to opt in/out without
        touching process-wide state.
    """
    # The composition root is the only place that selects persistence
    # implementations.  Application code consumes the repository port and
    # never constructs DatabaseManager itself.
    from mbforge.adapters.persistence.sqlite.repositories import create_repositories
    from mbforge.adapters.runtime.provider import create_runtime_provider
    from mbforge.application.ports import (
        configure_repository_factory,
        configure_runtime_provider,
    )

    configure_repository_factory(create_repositories)
    configure_runtime_provider(create_runtime_provider())
    configure_uvicorn_access_logging()
    app = FastAPI(
        title="MBForge",
        description="Molecular Science AI Workbench",
        version=APP_VERSION,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_development_frontend_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handlers run before route resolution returns, capturing
    # errors thrown anywhere in the main app graph.
    app.add_exception_handler(MBForgeError, _mbforge_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)

    # Request-path ContextVar middleware (must be added before any
    # router-level middleware to ensure it covers all routes).
    app.middleware("http")(_request_path_middleware)

    # Register all routers
    from mbforge.interfaces.http import agent, markush, review
    from mbforge.interfaces.http.documents import (
        activity,
        documents,
        library,
        notes,
        pdf,
        pdf_render,
    )
    from mbforge.interfaces.http.documents import (
        project_docs as docs_router,
    )
    from mbforge.interfaces.http.molecule import (
        chem,
        moldet,
        molecule,
        molparser,
        sar,
    )
    from mbforge.interfaces.http.pipeline import detection_cache, pipeline
    from mbforge.interfaces.http.system import (
        diagnostics,
        events,
        health,
        models,
        readiness,
        resource,
        settings,
    )

    app.include_router(library.router, prefix="/api/v1/library", tags=["library"])
    app.include_router(
        activity.router, prefix="/api/v1/activities", tags=["activities"]
    )
    app.include_router(documents.router, prefix="/api/v1/documents", tags=["documents"])
    app.include_router(pipeline.router, prefix="/api/v1/pipeline", tags=["pipeline"])
    app.include_router(molecule.router, prefix="/api/v1/molecule", tags=["molecule"])
    app.include_router(chem.router, prefix="/api/v1/chem", tags=["chem"])
    app.include_router(
        detection_cache.router, prefix="/api/v1/detection-cache", tags=["detection"]
    )
    app.include_router(notes.router, prefix="/api/v1/notes", tags=["notes"])
    app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(readiness.router, prefix="/api/v1", tags=["readiness"])
    app.include_router(
        readiness.diagnostics_router,
        prefix="/api/v1/diagnostics",
        tags=["diagnostics"],
    )
    app.include_router(resource.router, prefix="/api/v1", tags=["resource"])
    app.include_router(events.router, prefix="/api/v1/events", tags=["events"])
    app.include_router(pdf.router, prefix="/api/v1/pdf", tags=["pdf"])
    app.include_router(sar.router, prefix="/api/v1/sar", tags=["sar"])
    app.include_router(markush.router, prefix="/api/v1/markush", tags=["markush"])
    app.include_router(review.router, prefix="/api/v1/review", tags=["review"])
    app.include_router(agent.router, prefix="/api/v1/agent", tags=["agent-tools"])
    app.include_router(
        diagnostics.router, prefix="/api/v1/diagnostics", tags=["diagnostics"]
    )
    app.include_router(docs_router.router, prefix="/api/v1/docs/pages", tags=["docs"])
    # Local model routes — registered on the main app with correct prefixes.
    # Do NOT mount a model-server FastAPI app under /api/v1/models: a separate
    # assembly with absolute /api/v1/* prefixes would double-prefix.
    app.include_router(moldet.router, prefix="/api/v1/moldet", tags=["moldet"])
    app.include_router(molparser.router, prefix="/api/v1/molparser", tags=["molparser"])
    app.include_router(models.router, prefix="/api/v1/models", tags=["models"])
    # pdf_render adds /render-pages only; /figure-bboxes lives on pdf.router
    # (registered above) with the hardened library_root/doc_id contract.
    app.include_router(pdf_render.router, prefix="/api/v1/pdf", tags=["pdf-render"])

    # Serve React frontend in production
    # Priority: FRONTEND_DIST env > dev path
    _env_dist = os.environ.get("FRONTEND_DIST")
    if _env_dist:
        frontend_dist = Path(_env_dist)
    else:
        frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
    # Mount the React build only when explicitly requested. Dev mode keeps
    # the Vite server (5173) and the API server (18792) separated; set
    # MBFORGE_SERVE_FRONTEND=1 (or pass serve_frontend=True) to serve the
    # bundle from the API port (single-port / production deployments).
    if serve_frontend is None:
        serve_frontend = os.environ.get("MBFORGE_SERVE_FRONTEND", "0") == "1"
    if serve_frontend and frontend_dist.exists():
        app.mount(
            "/",
            SPAStaticFiles(directory=str(frontend_dist), html=True),
            name="frontend",
        )
        logger.info("Frontend served from API: %s", frontend_dist)
    elif serve_frontend and not frontend_dist.exists():
        logger.warning(
            "MBFORGE_SERVE_FRONTEND=1 but %s does not exist; skipping mount",
            frontend_dist,
        )
    else:
        logger.info(
            "Frontend not mounted (set MBFORGE_SERVE_FRONTEND=1 to serve from API port)"
        )

    return app


app = create_app()
