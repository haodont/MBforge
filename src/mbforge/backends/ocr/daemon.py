"""Persistent crop-label OCR daemon (standalone process).

Runs RapidOCR (default torch engine on CUDA) inside a long-lived process so
the model and any warm-up cost are paid once and kept resident, instead of
being laundered through the MBForge main process. Spawned as a lightweight
FastAPI app; the in-process ``label_reader`` fails over to it when
``moldet.ocr_mode == "daemon"``.

Endpoints
---------
``GET  /health``
    ``{"status": "ready", "engine": "torch", "device_id": 0}``.
``POST /v1/ocr``
    Body: raw image bytes. Returns ``{"reads": [[text, conf, bbox, isolated],
    ...]}``, identical to ``crop_labels.extract_label_reads``.

Run standalone::

    python -m mbforge.backends.ocr.daemon --port 18799 --device-id 0

The daemon builds the engine from the *configured* ``moldet.ocr_engine`` on
the first request and keeps one thread-safe-serialized engine (RapidOCR
torch is not thread-safe, so reads are served serially behind a lock).
"""

from __future__ import annotations

import threading

import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ...utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Engine lifecycle (inside the daemon process)
# ---------------------------------------------------------------------------

_engine_lock = threading.Lock()
_engine = None
_engine_name_cache: str = "torch"


def _configured_engine_name() -> str:
    from .crop_labels import _engine_name

    return _engine_name()


def _get_engine():
    """Lazily create and cache the daemon's engine (serialized reads)."""
    global _engine, _engine_name_cache
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from .crop_labels import _create_engine

                _engine_name_cache = _configured_engine_name()
                logger.info(
                    "OCR daemon creating engine=%s on device %d",
                    _engine_name_cache,
                    _device_id,
                )
                _engine = _create_engine(_engine_name_cache, device_id=_device_id)
    return _engine


_device_id = 0


def build_app(device_id: int = 0) -> FastAPI:
    """Build the OCR daemon FastAPI app bound to a CUDA device."""
    global _device_id
    _device_id = device_id

    from .crop_labels import _label_reads_from_result

    app = FastAPI(title="mbforge-ocr", version="1.0", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ready", "engine": _engine_name_cache, "error": ""}

    @app.post("/v1/ocr")
    async def ocr(request: Request) -> JSONResponse:
        body = await request.body()
        if not body:
            return JSONResponse(status_code=400, content={"error": "empty body"})
        try:
            from PIL import Image

            image = Image.open(__import__("io").BytesIO(body)).convert("L")
        except Exception:
            return JSONResponse(status_code=400, content={"error": "invalid image"})
        try:
            engine = _get_engine()
            if engine is None:
                return JSONResponse(
                    status_code=503,
                    content={"error": "no usable OCR backend available"},
                )
            arr = np.asarray(image.convert("RGB"))
            # The daemon is its own process, so its GPU gate is independent of
            # the main process; reads serialize on the local engine lock.
            with _engine_lock:
                result = engine(arr)
            reads = _label_reads_from_result(result)
        except Exception as exc:
            logger.warning("OCR daemon read failed: %s", exc)
            return JSONResponse(status_code=500, content={"error": str(exc)})
        return JSONResponse(
            content={
                "reads": [[text, conf, box, iso] for text, conf, box, iso in reads]
            }
        )

    return app


def main() -> None:
    """``python -m mbforge.backends.ocr.daemon`` entrypoint."""
    import argparse

    import uvicorn

    from ...utils.logger import configure_uvicorn_access_logging

    parser = argparse.ArgumentParser(description="MBForge crop-label OCR daemon")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18799)
    parser.add_argument("--device-id", type=int, default=0)
    args = parser.parse_args()

    configure_uvicorn_access_logging()
    logger.info(
        "Starting OCR daemon on %s:%d (device %d)", args.host, args.port, args.device_id
    )
    uvicorn.run(
        build_app(args.device_id), host=args.host, port=args.port, log_level="warning"
    )


if __name__ == "__main__":
    main()
