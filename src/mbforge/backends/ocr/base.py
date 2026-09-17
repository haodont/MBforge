"""Abstract OCR backend interface.

All cloud OCR backends expose a single synchronous entry point
`extract_text(image: bytes) -> OCRResult` so the fallback chain can call
them uniformly. Backends that are async (submit + poll)
internally block until completion.

Backends also accept an optional cooperative ``cancel_check`` and poll it
between blocking requests (poll iterations, retries, image downloads). A
request already in flight is never interrupted; the loop stops before the
next one. The check is surfaced as :class:`OCRCancelledError` so the
fallback chain cannot mistake a cancellation for a provider failure.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field

#: A cooperative cancellation checkpoint: raises when the owning task was
#: cancelled, otherwise returns immediately. Declared here rather than imported
#: from ``mbforge.pipeline.cancellation`` because backends sit below the
#: pipeline layer and must not depend on it.
CancelCheck = Callable[[], None]


class OCRCancelledError(RuntimeError):
    """Raised by an OCR backend when its cooperative checkpoint fired.

    The pipeline translates this into its own cancellation error at the
    boundary; the chain re-raises it instead of falling through to the next
    backend.
    """


def check_cancelled(cancel_check: CancelCheck | None) -> None:
    """Poll ``cancel_check``, re-raising whatever it raises as a cancel.

    A checkpoint signals cancellation by raising; the backend does not know
    (and must not import) the pipeline's exception type, so any exception the
    checkpoint produces is normalized to :class:`OCRCancelledError`.
    """
    if cancel_check is None:
        return
    try:
        cancel_check()
    except OCRCancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — checkpoint raises to signal cancel
        raise OCRCancelledError(str(exc)) from exc


@dataclass
class LayoutSpan:
    """One layout block from an OCR result (text line or figure region).

    ``bbox`` is in PDF points with a bottom-left origin (matching
    PyMuPDF's convention for native text blocks), so MoleCode insertion
    can compare it directly against molecule detection bboxes.

    ``block_type`` follows the pipeline ``extract_text.TextSpan`` convention:
    0 = text, 1 = image/figure, 2 = table.
    """

    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 (bottom-left)
    block_type: int = 0


@dataclass
class OCRResult:
    """Outcome of a single OCR attempt.

    `text` is the extracted plain text (page-level). On failure,
    `text` is empty and `error` describes why.

    `spans` carries the layout blocks (text, table, and figure regions) when
    the backend can produce them; MoleCode insertion uses them to anchor
    molecule blocks near their figure instead of falling back to the
    page end. Empty for backends without layout information.

    `raw_output` contains the backend's complete structured response when it
    is available, so callers do not lose layout, table, formula, image,
    score, or resource URL fields.
    """

    text: str
    error: str | None = None
    spans: list[LayoutSpan] = field(default_factory=list)
    raw_output: dict | None = None
    backend: str | None = None
    chain_attempts: int = 0
    elapsed_ms: int = 0


@dataclass(frozen=True)
class CloudOCRConfig:
    """Normalized configuration shared by cloud OCR backends."""

    api_key: str
    base_url: str
    model: str

    @classmethod
    def from_config(
        cls,
        config: dict | None,
        *,
        base_url_default: str,
        model_default: str,
        base_url_key: str = "base_url",
        model_key: str = "model",
    ) -> CloudOCRConfig:
        """Build a normalized cloud OCR config from raw settings.

        Normalization covers the usual scaffolding: strip whitespace,
        apply defaults, remove a trailing slash from the base URL, and
        fall back to ``model_default`` when the configured model is empty.
        """
        cfg = config or {}
        api_key = (cfg.get("api_key") or "").strip()
        base_url = (cfg.get(base_url_key) or "").strip() or base_url_default
        base_url = base_url.rstrip("/")
        model = (cfg.get(model_key) or model_default).strip()
        return cls(api_key=api_key, base_url=base_url, model=model)

    def is_configured(self) -> bool:
        """Return True when an API key is present."""
        return bool(self.api_key)

    def auth_headers(self, content_type: str | None = None) -> dict[str, str]:
        """Return the ``Authorization`` header, optionally with ``Content-Type``."""
        headers: dict[str, str] = {"Authorization": f"Bearer {self.api_key}"}
        if content_type is not None:
            headers["Content-Type"] = content_type
        return headers


class OCRBackend(abc.ABC):
    """Base class for OCR backends."""

    #: Stable identifier used in settings & priority chain.
    name: str = ""

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """Return True iff the backend has everything it needs to run."""

    @abc.abstractmethod
    def extract_text(
        self, image: bytes, *, cancel_check: CancelCheck | None = None
    ) -> OCRResult:
        """Run OCR on a single page image.

        `image` is PNG-encoded bytes (or whatever PyMuPDF produced).
        Implementations should raise on transport errors and return
        OCRResult(error=...) on logical failures (auth, quota, etc.)
        so the chain can fall through to the next backend.

        ``cancel_check`` is polled between blocking requests; a backend that
        observes it raises :class:`OCRCancelledError` instead of returning a
        result, so the chain aborts rather than trying the next provider.
        """
