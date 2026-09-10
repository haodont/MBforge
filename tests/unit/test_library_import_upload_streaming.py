"""Streaming upload tests for ``POST /api/v1/library/import``.

The import route used to call ``await file.read()`` and then check the size
limit, which buffered the entire request body in memory before any rejection
could happen — making it trivial for a malicious or buggy client to exhaust
server RAM. The fix streams the body to a temp file in 1 MiB chunks and
rejects as soon as the running byte total exceeds ``MAX_UPLOAD_BYTES``.

These tests pin the three observable properties of that contract:

1. A small upload still succeeds and lands in storage.
2. An oversize upload is rejected with HTTP 413 *before* the handler reads
   the full body — proven by counting how many times ``file.read`` is
   called.
3. The temp file used for streaming is removed on both the success and
   the failure paths.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile


def test_import_upload_small_succeeds(
    app_client: TestClient, tmp_library: Path
) -> None:
    """A 1 MiB body should round-trip through the streaming path."""
    body = b"%PDF-1.4 " + b"x" * (1024 * 1024 - 8)  # exactly 1 MiB
    resp = app_client.post(
        "/api/v1/library/import",
        data={"title": "Small PDF"},
        files={"file": ("small.pdf", io.BytesIO(body), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    doc_id = data["document"]["doc_id"]

    # Document lands in canonical storage with the original bytes preserved.
    saved = tmp_library / "storage" / doc_id / "small.pdf"
    assert saved.is_file()
    assert saved.read_bytes() == body


async def test_import_upload_oversize_rejected_early(
    tmp_library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Oversize body must be rejected before the handler drains it.

    We lower ``MAX_UPLOAD_BYTES`` to 5 MiB, feed the route a virtual
    100 MiB body that yields 1 MiB per ``read`` call, and assert the
    handler stopped calling ``read`` after a small number of calls — far
    short of the 100 reads the body would require if it were drained.
    """
    from mbforge.routers.documents import library as library_router
    from mbforge.services.documents import library as library_service
    from mbforge.utils import config

    # Lower the upload cap for this test.
    monkeypatch.setattr(library_service, "MAX_UPLOAD_BYTES", 5 * 1024 * 1024)

    # The route resolves the active library root through ``config.load_global_config``;
    # patch it the same way the ``app_client`` fixture does so the import lands
    # in our temp library regardless of how we invoke the handler.
    original_load = config.load_global_config

    class _PatchedLoad:
        def __call__(self):
            cfg = original_load()
            cfg.library_root = str(tmp_library)
            return cfg

        def cache_clear(self):
            original_load.cache_clear()

    monkeypatch.setattr(config, "load_global_config", _PatchedLoad())

    class CountingBody:
        """Simulates a 100 MiB body that yields 1 MiB of zeros per read call.

        The body is virtual — we never allocate 100 MiB. The handler only
        reads 1 MiB at a time, so after ~6 calls it should reject.
        """

        CHUNK = 1024 * 1024
        TOTAL_CHUNKS = 100  # virtual 100 MiB body

        def __init__(self) -> None:
            self._emitted = 0
            self.read_count = 0
            self.bytes_emitted = 0

        def read(self, size: int = -1) -> bytes:
            self.read_count += 1
            if self._emitted >= self.TOTAL_CHUNKS:
                return b""
            if size is None or size < 0:
                size = self.CHUNK
            size = min(size, self.CHUNK)
            self._emitted += 1
            self.bytes_emitted += size
            return b"\x00" * size

    body = CountingBody()
    upload = UploadFile(filename="big.pdf", file=body)  # type: ignore[arg-type]

    with pytest.raises(library_service.UploadTooLargeError):
        await library_router.library_import(file=upload, title="", library_root=None)

    # The handler must have stopped reading well before exhausting the body.
    # With a 5 MiB cap and 1 MiB chunks, 6 reads cross the limit (5 MiB
    # accepted, 6th pushes the total over). Allow a little slack but keep
    # the upper bound well below the 100 reads the full body would need.
    assert body.read_count < 10, (
        f"handler kept reading after exceeding limit: {body.read_count} calls"
    )
    assert body.bytes_emitted < 10 * 1024 * 1024
    assert body.read_count < body.TOTAL_CHUNKS

    # Temp file was cleaned up on the failure path.
    tmp_dir = tmp_library / "tmp"
    leftover = list(tmp_dir.iterdir()) if tmp_dir.exists() else []
    assert leftover == [], f"temp file not cleaned after oversize: {leftover}"


def test_import_upload_temp_file_cleaned_on_success(
    app_client: TestClient, tmp_library: Path
) -> None:
    """A successful upload must not leave a temp file behind."""
    body = b"%PDF-1.4 streaming cleanup"
    resp = app_client.post(
        "/api/v1/library/import",
        files={"file": ("clean.pdf", io.BytesIO(body), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text

    tmp_dir = tmp_library / "tmp"
    leftover = list(tmp_dir.iterdir()) if tmp_dir.exists() else []
    assert leftover == [], f"temp file not cleaned on success: {leftover}"
