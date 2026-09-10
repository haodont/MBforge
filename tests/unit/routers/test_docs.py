from __future__ import annotations

import asyncio

from mbforge.routers.documents import project_docs as docs


def test_list_wiki_pages_returns_sorted_titles(tmp_path, monkeypatch) -> None:
    (tmp_path / "README.md").write_text("# Wiki Home\n", encoding="utf-8")
    (tmp_path / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
    monkeypatch.setattr(docs, "_WIKI_ROOT", tmp_path)

    result = asyncio.run(docs.list_wiki_pages())

    assert [page.slug for page in result.pages] == ["readme", "architecture"]
    assert [page.title for page in result.pages] == ["Wiki Home", "Architecture"]


def test_get_wiki_page_reads_markdown(tmp_path, monkeypatch) -> None:
    (tmp_path / "pipeline.md").write_text("# Pipeline\n\nBody", encoding="utf-8")
    monkeypatch.setattr(docs, "_WIKI_ROOT", tmp_path)

    result = asyncio.run(docs.get_wiki_page("pipeline"))

    assert result.slug == "pipeline"
    assert result.title == "Pipeline"
    assert result.content.endswith("Body")
