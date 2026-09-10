"""Abstract OCR backend interface.

All cloud OCR backends expose a single synchronous entry point
`extract_text(image: bytes) -> str` so the fallback chain can call
them uniformly. Backends that are async (submit + poll)
internally block until completion.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


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

    `images` maps image filenames (e.g. ``abc123.jpg``) to bytes for
    figures extracted from OCR result ZIPs. Backends that do not
    produce images leave it empty.

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
    images: dict[str, bytes] = field(default_factory=dict)
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
    def extract_text(self, image: bytes) -> OCRResult:
        """Run OCR on a single page image.

        `image` is PNG-encoded bytes (or whatever PyMuPDF produced).
        Implementations should raise on transport errors and return
        OCRResult(error=...) on logical failures (auth, quota, etc.)
        so the chain can fall through to the next backend.
        """
