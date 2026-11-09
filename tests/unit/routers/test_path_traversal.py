"""Path-traversal hardening for routers listed in Task 1.1.

These tests assert that user-supplied ``library_root``, ``doc_id``,
``pdf_path``, ``rel_path``, and upload ``filename`` values cannot escape
the configured library storage layout.

Covered routers:

* moldet router — ``POST /api/v1/moldet/extract-pdf`` and
  ``POST /api/v1/moldet/extract-pdf-page``
* detection-cache router — ``POST /api/v1/detection-cache/get`` and
  ``POST /api/v1/detection-cache/save``
* library router — ``POST /api/v1/library/import`` and
  ``GET /api/v1/library/documents/{doc_id}/crop``
* pdf router — ``POST /api/v1/pdf/render-pages``

Each test loops over its payload table so one collected item still covers
every rejection variant for its endpoint family.
"""

from pathlib import Path

from fastapi.testclient import TestClient

_TRAVERSAL_DOC_IDS = [
    "../etc/passwd",
    "..\\Windows\\System32",
    "foo/bar",
    "foo\\bar",
]

_MALICIOUS_LIBRARY_ROOTS = [
    "..",
    "/etc",
    "C:/Windows",
]

_TRAVERSAL_PDF_PATHS = [
    "../etc/passwd",
    "..\\Windows\\System32",
    "foo/../../../etc/passwd",
]

_TRAVERSAL_CROP_PATHS = [
    "../etc/passwd",
    "../../secret",
    "sub/../../../secret",
]


def _assert_rejected(
    response,
    case: str,
    *,
    error_code: str = "invalid_path",
    status: int = 400,
) -> None:
    """A rejected path keeps the MBForgeError envelope: success=False + error_code."""
    assert response.status_code == status, f"{case}: {response.text}"
    data = response.json()
    assert data["success"] is False, case
    assert data["error_code"] == error_code, case


def test_moldet_extract_pdf_rejects_traversal_doc_id_and_foreign_root(
    app_client: TestClient, tmp_library: Path
) -> None:
    """``doc_id`` traversal variants and a foreign ``library_root`` are rejected."""
    cases = [(value, {"doc_id": value, "page": 1}) for value in _TRAVERSAL_DOC_IDS]
    cases += [
        (root, {"doc_id": "doc1", "page": 1, "library_root": root})
        for root in _MALICIOUS_LIBRARY_ROOTS
    ]
    for case, payload in cases:
        response = app_client.post(
            "/api/v1/moldet/extract-pdf",
            json={"library_root": str(tmp_library), **payload},
        )
        _assert_rejected(response, f"doc_id={case!r}")


def test_moldet_extract_pdf_page_rejects_traversal_doc_id_and_direct_pdf_path(
    app_client: TestClient, tmp_library: Path, sample_pdf: Path
) -> None:
    """The page endpoint rejects both a foreign root and an outside ``pdf_path``."""
    for root in _MALICIOUS_LIBRARY_ROOTS:
        response = app_client.post(
            "/api/v1/moldet/extract-pdf-page",
            json={"library_root": root, "doc_id": "doc1", "page": 1},
        )
        _assert_rejected(response, f"library_root={root!r}")

    # A caller-supplied absolute pdf_path outside the library root is rejected.
    response = app_client.post(
        "/api/v1/moldet/extract-pdf-page",
        json={"pdf_path": str(sample_pdf), "page": 1},
    )
    _assert_rejected(response, f"pdf_path={sample_pdf}")


def test_detection_cache_get_rejects_traversal_doc_id_and_foreign_root(
    app_client: TestClient, tmp_library: Path
) -> None:
    """Cache reads reject ``doc_id`` traversal variants and a foreign root."""
    cases = [(value, {"doc_id": value, "page": 1}) for value in _TRAVERSAL_DOC_IDS]
    cases += [
        (root, {"doc_id": "doc1", "page": 1, "library_root": root})
        for root in _MALICIOUS_LIBRARY_ROOTS
    ]
    for case, payload in cases:
        response = app_client.post(
            "/api/v1/detection-cache/get",
            json={"library_root": str(tmp_library), **payload},
        )
        _assert_rejected(response, f"doc_id={case!r}")


def test_detection_cache_save_rejects_malicious_doc_id(
    app_client: TestClient, tmp_library: Path
) -> None:
    """A traversal ``doc_id`` inside a detection batch is rejected on save."""
    response = app_client.post(
        "/api/v1/detection-cache/save",
        json={
            "library_root": str(tmp_library),
            "detections": [
                {
                    "mol_id": "mol-1",
                    "doc_id": "../etc/passwd",
                    "page": 1,
                    "bbox_x0": 0.0,
                    "bbox_y0": 0.0,
                    "bbox_x1": 1.0,
                    "bbox_y1": 1.0,
                    "crop_relpath": "crop.png",
                    "conf_moldet": 0.9,
                    "conf_molscribe": 0.8,
                }
            ],
        },
    )
    _assert_rejected(response, "detections[0].doc_id='../etc/passwd'")


def test_library_import_rejects_traversal_filename_and_ignores_client_root(
    app_client: TestClient, tmp_library: Path, sample_pdf: Path
) -> None:
    """Uploads cannot traverse, dotted names are legal, client roots are ignored."""
    for filename in (
        "../passwd",
        "..\\autoexec.bat",
        "sub/../passwd.pdf",
        "sub/./file.pdf",
    ):
        with sample_pdf.open("rb") as f:
            response = app_client.post(
                "/api/v1/library/import",
                files={"file": (filename, f, "application/pdf")},
            )
        _assert_rejected(response, f"filename={filename!r}")

    # ``..`` inside a segment (not a traversal segment) is a legal filename.
    response = app_client.post(
        "/api/v1/library/import",
        files={"file": ("report..pdf", b"%PDF-1.4 dotted pdf", "application/pdf")},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["success"] is True
    assert data["document"]["file_name"] == "report..pdf"

    # A client-supplied library_root cannot redirect where the import lands:
    # the route takes no library_root at all, so the file lands in the
    # configured library regardless.
    for root in _MALICIOUS_LIBRARY_ROOTS:
        with sample_pdf.open("rb") as f:
            response = app_client.post(
                "/api/v1/library/import",
                files={"file": ("sample.pdf", f, "application/pdf")},
                data={"library_root": root},
            )
        assert response.status_code == 200, response.text
        doc_id = response.json()["document"]["doc_id"]
        assert (tmp_library / "storage" / doc_id / "sample.pdf").is_file(), root


def test_pdf_render_pages_rejects_outside_paths_and_accepts_in_library(
    app_client: TestClient, tmp_library: Path, sample_pdf: Path
) -> None:
    """Only PDFs inside the library root render; traversal/outside paths are rejected."""
    for pdf_path in _TRAVERSAL_PDF_PATHS:
        response = app_client.post(
            "/api/v1/pdf/render-pages",
            json={"library_root": str(tmp_library), "pdf_path": pdf_path},
        )
        _assert_rejected(response, f"pdf_path={pdf_path!r}")

    # An absolute PDF path outside the library root must be rejected.
    outside_pdf = tmp_library.parent / "outside.pdf"
    outside_pdf.write_bytes(sample_pdf.read_bytes())
    response = app_client.post(
        "/api/v1/pdf/render-pages",
        json={"pdf_path": str(outside_pdf)},
    )
    _assert_rejected(response, f"pdf_path={outside_pdf}")

    # Both an absolute in-library path and a library-relative path render.
    inside_pdf = tmp_library / "sample.pdf"
    inside_pdf.write_bytes(sample_pdf.read_bytes())
    for pdf_path in (str(inside_pdf), "sample.pdf"):
        response = app_client.post(
            "/api/v1/pdf/render-pages",
            json={"library_root": str(tmp_library), "pdf_path": pdf_path},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["success"] is True, pdf_path
        assert len(data["pages"]) == 2, pdf_path


def test_library_crop_rejects_traversal_rel_path(
    app_client: TestClient, tmp_library: Path, sample_pdf: Path
) -> None:
    """Crop reads refuse any ``rel_path`` that escapes the document folder."""
    with sample_pdf.open("rb") as f:
        resp = app_client.post(
            "/api/v1/library/import",
            files={"file": ("sample.pdf", f, "application/pdf")},
        )
    assert resp.status_code == 200
    doc_id = resp.json()["document"]["doc_id"]

    for rel_path in _TRAVERSAL_CROP_PATHS:
        response = app_client.get(
            f"/api/v1/library/documents/{doc_id}/crop",
            params={"rel_path": rel_path, "library_root": str(tmp_library)},
        )
        _assert_rejected(
            response,
            f"rel_path={rel_path!r}",
            error_code="path_traversal",
            status=403,
        )
