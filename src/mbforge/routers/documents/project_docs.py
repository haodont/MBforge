"""Read-only repository project documentation endpoints.

Serves Markdown pages from the repository's ``docs/wiki`` directory through
the Settings documentation center. Pages are listed by slug and returned
with auto-derived titles; no writes or mutations are allowed.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from ...utils.errors import FileAccessError, NotFoundError, ValidationError

router = APIRouter()

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_WIKI_ROOT = Path(__file__).resolve().parents[3] / "docs" / "wiki"


class WikiPageSummary(BaseModel):
    slug: str
    title: str


class WikiIndexResponse(BaseModel):
    pages: list[WikiPageSummary]


class WikiPageResponse(WikiPageSummary):
    content: str


def _page_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or fallback
    return fallback


def _wiki_files() -> list[Path]:
    if not _WIKI_ROOT.is_dir():
        raise FileAccessError(f"Wiki directory not found: {_WIKI_ROOT}")
    return sorted(
        _WIKI_ROOT.glob("*.md"),
        key=lambda path: (path.stem.lower() != "readme", path.name.lower()),
    )


def _read_page(slug: str) -> WikiPageResponse:
    if not _SLUG_RE.fullmatch(slug):
        raise ValidationError("invalid wiki page slug")

    path = next(
        (item for item in _wiki_files() if item.stem.lower() == slug.lower()),
        None,
    )
    if path is None:
        raise NotFoundError(f"Wiki page not found: {slug}")

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FileAccessError(
            f"Cannot read wiki page: {path}", detail=str(exc)
        ) from exc

    canonical_slug = path.stem.lower()
    return WikiPageResponse(
        slug=canonical_slug,
        title=_page_title(content, path.stem),
        content=content,
    )


@router.get("", response_model=WikiIndexResponse)
async def list_wiki_pages() -> WikiIndexResponse:
    """List Markdown pages in the repository's project documentation."""
    pages = await asyncio.to_thread(
        lambda: [
            WikiPageSummary(
                slug=path.stem.lower(),
                title=_page_title(path.read_text(encoding="utf-8"), path.stem),
            )
            for path in _wiki_files()
        ]
    )
    return WikiIndexResponse(pages=pages)


@router.get("/{slug}", response_model=WikiPageResponse)
async def get_wiki_page(slug: str) -> WikiPageResponse:
    """Return one repository project documentation page as Markdown."""
    return await asyncio.to_thread(_read_page, slug)
