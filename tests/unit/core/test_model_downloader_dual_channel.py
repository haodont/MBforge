"""Dual-channel model download: ModelScope first, HuggingFace fallback."""

from __future__ import annotations

from pathlib import Path

from mbforge.server import resource_manager as rm
from mbforge.server.models.assets import downloader as md
from mbforge.server.resource_manager import ResourceManager, ResourceStatus

_FILES = ("moldet_v2_yolo26n_960_doc.pt", "moldet_v2_yolo26n_640_general.pt")


def _fake_cache(tmp_path: Path) -> Path:
    """Write the catalog's moldet weight files under the snapshot dir."""
    dest = tmp_path / "MolDetv2"
    dest.mkdir(parents=True, exist_ok=True)
    for name in _FILES:
        (dest / name).write_bytes(b"weights")
    return dest


def test_ensure_falls_back_to_hf_when_modelscope_fails(
    monkeypatch, tmp_path: Path
) -> None:
    """MS channel returning False must trigger the HuggingFace fallback."""
    monkeypatch.setattr(
        md,
        "_download_model_from_modelscope",
        lambda info, callback: False,
    )
    hf_calls: dict[str, int] = {"n": 0}

    def _fake_hf(info, callback) -> bool:
        hf_calls["n"] += 1
        _fake_cache(tmp_path)
        return True

    monkeypatch.setattr(md, "_download_model_from_hf", _fake_hf)
    monkeypatch.setattr(rm, "_get_model_cache_dir", lambda: tmp_path)

    result = ResourceManager.ensure("moldet")
    assert hf_calls["n"] == 1
    assert result.status == ResourceStatus.READY
    assert result.local_path


def test_ensure_uses_modelscope_first_when_it_succeeds(
    monkeypatch, tmp_path: Path
) -> None:
    """A successful ModelScope download must not call the HF channel."""
    ms_calls: dict[str, int] = {"n": 0}

    def _fake_ms(info, callback) -> bool:
        ms_calls["n"] += 1
        _fake_cache(tmp_path)
        return True

    monkeypatch.setattr(md, "_download_model_from_modelscope", _fake_ms)
    monkeypatch.setattr(
        md,
        "_download_model_from_hf",
        lambda info, callback: (_ for _ in ()).throw(AssertionError("HF must not run")),
    )
    monkeypatch.setattr(rm, "_get_model_cache_dir", lambda: tmp_path)

    result = ResourceManager.ensure("moldet")
    assert ms_calls["n"] == 1
    assert result.status == ResourceStatus.READY


def test_ensure_fails_when_both_channels_fail(monkeypatch, tmp_path: Path) -> None:
    """When MS and HF both fail, ensure reports not_found (no crash)."""
    monkeypatch.setattr(
        md,
        "_download_model_from_modelscope",
        lambda info, callback: False,
    )
    monkeypatch.setattr(
        md,
        "_download_model_from_hf",
        lambda info, callback: False,
    )
    monkeypatch.setattr(rm, "_get_model_cache_dir", lambda: tmp_path)

    result = ResourceManager.ensure("moldet")
    assert result.status == ResourceStatus.NOT_FOUND


# ── Direct-HTTP channel ──────────────────────────────────────────────
#
# The catalog lists every file a snapshot model needs, so the direct-HTTP path
# must download those files without relying on a repo listing. It also replaced
# the retired ``/repo/tree`` listing endpoint, whose 404 used to read as
# "no files" and failed the download before anything was fetched.


class _FakeResponse:
    def __init__(self, *, json_data=None, content: bytes = b"") -> None:
        self.status_code = 200
        self._json = json_data
        self.content = content
        self.headers = {"Content-Length": str(len(content))}

    def json(self):
        return self._json

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, _size: int):
        yield self.content


def test_modelscope_http_download_uses_catalog_files_without_listing(
    monkeypatch, tmp_path: Path
) -> None:
    """Every catalog file is fetched by path, even when listing fails.

    A missing/unusable listing must not abort the download: the catalog manifest
    is authoritative, so the files are still requested and the snapshot verifies.
    """
    from mbforge.server.models.assets import downloader as md

    info = rm.RESOURCE_CATALOG["moldet"]
    requested: list[str] = []

    def _fake_get(url, *, params=None, stream=False, timeout=300, **kwargs):
        if "/repo/files" in url:
            return _FakeResponse(json_data={"Data": {"Files": []}})
        requested.append(params["FilePath"])
        return _FakeResponse(content=b"w" * 16)

    monkeypatch.setattr(md, "_get", _fake_get)

    dest = tmp_path / info.local_name
    dest.mkdir()
    assert md._modelscope_direct_http(info, dest, lambda _e: None)
    assert requested == list(info.files)
    for name in info.files:
        assert (dest / name).is_file()


def test_hf_tls_failure_retries_without_verification(monkeypatch) -> None:
    """A certificate-trust failure retries unverified; other errors propagate.

    A local HTTPS-intercepting proxy presents an untrusted certificate
    intermittently. Downloads must degrade to an unverified retry for that case
    only — a genuine transport error is not silently retried.
    """
    import requests

    from mbforge.server.models.assets import downloader as md

    calls: list[bool] = []

    def _fake_get(url, **kwargs):
        calls.append(bool(kwargs.get("verify", True)))
        if len(calls) == 1:
            raise requests.exceptions.SSLError(
                "SSL: CERTIFICATE_VERIFY_FAILED certificate verify failed"
            )
        return "ok"

    monkeypatch.setattr(md.requests, "get", _fake_get)
    assert md._get("https://example.invalid/x") == "ok"
    assert calls == [True, False]

    calls.clear()

    def _fake_get_transport_error(url, **kwargs):
        calls.append(True)
        raise requests.exceptions.ConnectionError("connection reset")

    monkeypatch.setattr(md.requests, "get", _fake_get_transport_error)
    try:
        md._get("https://example.invalid/x")
    except requests.exceptions.ConnectionError:
        pass
    else:  # pragma: no cover — must re-raise
        raise AssertionError("transport errors must propagate, not be retried")
    assert calls == [True]
