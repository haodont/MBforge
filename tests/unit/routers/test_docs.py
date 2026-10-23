from __future__ import annotations

import asyncio

from mbforge.api.http.documents import project_docs as docs


def test_wiki_pages_list_and_read(tmp_path, monkeypatch) -> None:
    """Wiki listing returns pages; reading one returns its slug/title/body."""
    (tmp_path / "README.md").write_text("# Wiki Home\n", encoding="utf-8")
    (tmp_path / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
    monkeypatch.setattr(docs, "_WIKI_ROOT", tmp_path)

    result = asyncio.run(docs.list_wiki_pages())

    assert [page.slug for page in result.pages] == ["readme", "architecture"]
    assert [page.title for page in result.pages] == ["Wiki Home", "Architecture"]

    (tmp_path / "pipeline.md").write_text("# Pipeline\n\nBody", encoding="utf-8")
    page = asyncio.run(docs.get_wiki_page("pipeline"))

    assert page.slug == "pipeline"
    assert page.title == "Pipeline"
    assert page.content.endswith("Body")
