# Python 后端 Phase 0 测试补齐实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 Python 后端关键路径测试，修复 1 个失败集成测试，使 `src/mbforge` 总体覆盖率从 40% 提升到 ≥42%，`core/` ≥60%，`routers/` ≥30%，`pipeline/organizer.py` ≥60%。

**Architecture:** 沿数据流 `file_scanner → library → knowledge_base/semantic_cache → pipeline/organizer → routers → openkb` 编写测试；外部 LLM/OCR 全部 mock；数据库与文件系统使用真实临时资源；每个任务独立可验证。

**Tech Stack:** pytest, pytest-asyncio, fastapi.testclient.TestClient, unittest.mock, 真实 SQLite, tmp_path。

## Global Constraints

- Python 包管理使用 **uv**，执行使用 `uv run`。
- 测试路径：`tests/unit/**/test_*.py`，集成测试：`tests/integration/test_*.py`。
- 所有模块必须使用 `from __future__ import annotations`。
- 不使用 bare `except:`；错误处理继承 `MBForgeError`。
- 不调用真实 LLM/OCR/模型；全部通过 monkeypatch/mock 替换。
- 数据库使用真实 SQLite，但文件必须放在 `tmp_path` 下，不污染用户目录。
- 新增代码需通过 `uv run ruff check src/ tests/`。
- 每个 task 结束时运行对应测试并提交（commit）。

---

## File Structure

| 文件 | 动作 | 说明 |
|---|---|---|
| `tests/integration/test_pipeline_flow.py` | 修改 | 修复失败集成测试断言 |
| `tests/conftest.py` | 修改 | 新增 `mock_llm_client`、`app_client`、`in_memory_kb`、`in_memory_semantic_cache` |
| `tests/unit/core/test_file_scanner.py` | 创建 | `core/file_scanner.py` 单元测试 |
| `tests/unit/core/test_library.py` | 创建 | `core/library.py` 单元测试 |
| `tests/unit/core/test_knowledge_base.py` | 创建 | `core/knowledge_base.py` 单元测试 |
| `tests/unit/core/test_semantic_cache.py` | 创建 | `core/semantic_cache.py` 单元测试 |
| `tests/unit/pipeline/test_organizer.py` | 创建 | `pipeline/organizer.py` 单元测试 |
| `tests/unit/routers/test_library.py` | 创建 | `routers/library.py` 业务测试 |
| `tests/unit/routers/test_knowledge_base.py` | 创建 | `routers/knowledge_base.py` 业务测试 |
| `tests/unit/routers/test_coref.py` | 创建 | `routers/coref.py` 业务测试 |
| `tests/unit/routers/test_moldet_api.py` | 创建 | `routers/moldet_api.py` 业务测试 |
| `tests/unit/routers/test_molecule.py` | 创建 | `routers/molecule.py` 业务测试 |
| `tests/unit/openkb/test_config.py` | 创建 | `openkb/config.py` 单元测试 |
| `tests/unit/openkb/test_query.py` | 创建 | `openkb/query.py` 单元测试 |
| `tests/unit/openkb/test_compiler.py` | 创建 | `openkb/compiler.py` 单元测试 |

---

## Task 1: 修复失败集成测试

**Files:**
- Modify: `tests/integration/test_pipeline_flow.py:56-66`
- Test: `tests/integration/test_pipeline_flow.py`

**Interfaces:**
- Consumes: `run_pipeline()` returns `PipelineResult`; storage layout under `{library_root}/storage/{doc_id}/`.
- Produces: 断言允许文本-only 文档不生成 `reorganized.md`。

### 背景

当前 `test_full_pipeline_text_only_document` 失败，因为文本-only 文档没有分子，pipeline 跳过 Reorganization，未生成 `reorganized.md`。

### 决策

按设计文档方案 A：调整测试断言，允许文本-only 文档不生成 `reorganized.md`，改为断言 `report.json` 中 `reorganized` 阶段状态为 `skipped`。

### 步骤

- [ ] **Step 1: 检查当前 pipeline 报告格式**

运行：
```bash
uv run pytest tests/integration/test_pipeline_flow.py::test_full_pipeline_text_only_document -v
```

查看 `report.json` 输出，确认 `reorganized` 阶段的状态字段名（如 `stages.reorganized.status` 或 `stage_results.reorganize.status`）。

- [ ] **Step 2: 修改测试断言**

将 `tests/integration/test_pipeline_flow.py` 中：

```python
assert (storage_dir / "reorganized.md").exists()
```

替换为：

```python
# Text-only documents skip reorganization when no molecules are detected.
report = json.loads((storage_dir / "report.json").read_text(encoding="utf-8"))
if report.get("doc_kind") == "text_only":
    assert report.get("stages", {}).get("reorganize", {}).get("status") == "skipped"
else:
    assert (storage_dir / "reorganized.md").exists()
```

具体字段路径以实际 `report.json` 为准。

- [ ] **Step 3: 运行集成测试**

```bash
uv run pytest tests/integration/test_pipeline_flow.py -v
```

Expected: 2 tests PASS。

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_pipeline_flow.py
git commit -m "test(integration): allow text-only docs to skip reorganize.md"
```

---

## Task 2: 共享测试 Fixtures

**Files:**
- Modify: `tests/conftest.py`
- Test: 后续 tasks 使用

**Interfaces:**
- Produces:
  - `mock_llm_client(model: str, prompt: str) -> str`：返回固定 LLM 响应。
  - `app_client(tmp_library) -> TestClient`：已 monkeypatch 全局 config 的 FastAPI client。
  - `in_memory_kb(tmp_library) -> KnowledgeBase`：已初始化的 KB 实例。
  - `in_memory_semantic_cache(tmp_library) -> SemanticCache`：已初始化的 cache 实例。

### 步骤

- [ ] **Step 1: 添加 fixtures**

在 `tests/conftest.py` 追加：

```python
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_llm_client() -> Any:
    """Return a fake LLM completion function."""

    def _client(model: str, prompt: str) -> str:
        # Minimal deterministic reorganize: return the prompt body after the system prompt.
        if "Document:" in prompt:
            return prompt.split("Document:", 1)[-1].split("Reorganized:")[0].strip()
        return "Summary line"

    return _client


@pytest.fixture
def app_client(tmp_library: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """FastAPI TestClient with global config pointing to a temp library."""
    from mbforge.app import app
    from mbforge.utils import config

    original_load = config.load_global_config

    def _load_temp():
        cfg = original_load()
        cfg.library_root = str(tmp_library)
        return cfg

    monkeypatch.setattr(config, "load_global_config", _load_temp)
    return TestClient(app)


@pytest.fixture
def in_memory_kb(tmp_library: Path) -> Any:
    """Initialize a KnowledgeBase in a temp library."""
    from mbforge.core.database import DatabaseManager

    db = DatabaseManager.get(str(tmp_library))
    db.initialize()
    return db


@pytest.fixture
def in_memory_semantic_cache(tmp_library: Path) -> Any:
    """Initialize semantic cache tables in a temp library."""
    from mbforge.core.database import DatabaseManager

    db = DatabaseManager.get(str(tmp_library))
    db.initialize()
    return str(tmp_library)
```

- [ ] **Step 2: 验证 fixtures 可加载**

```bash
uv run pytest tests/unit/core/test_database.py -v
```

Expected: 现有测试仍通过，无 fixture 加载错误。

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test(fixtures): add mock_llm_client, app_client, in_memory_kb, in_memory_semantic_cache"
```

---

## Task 3: `core/file_scanner.py` 测试

**Files:**
- Create: `tests/unit/core/test_file_scanner.py`
- Test: `tests/unit/core/test_file_scanner.py`

**Interfaces:**
- Consumes: `scan_library_files(root, recursive=False)` and `build_file_tree(root)`.
- Produces: 断言返回的相对路径、过滤规则、树结构。

### 步骤

- [ ] **Step 1: 编写测试**

```python
from __future__ import annotations

from pathlib import Path

from mbforge.core.file_scanner import (
    SUPPORTED_EXTS,
    FileNode,
    build_file_tree,
    scan_library_files,
)


def test_scan_library_files_non_recursive(tmp_path: Path) -> None:
    (tmp_path / "a.pdf").write_text("pdf")
    (tmp_path / "b.md").write_text("md")
    (tmp_path / "ignored.exe").write_text("exe")
    result = scan_library_files(tmp_path, recursive=False)
    assert result == ["a.pdf", "b.md"]


def test_scan_library_files_recursive_skips_hidden_and_skip_dirs(tmp_path: Path) -> None:
    (tmp_path / "doc.pdf").write_text("pdf")
    nested = tmp_path / "subdir"
    nested.mkdir()
    (nested / "inner.txt").write_text("txt")
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "secret.pdf").write_text("pdf")
    skip = tmp_path / "node_modules"
    skip.mkdir()
    (skip / "bad.pdf").write_text("pdf")
    result = scan_library_files(tmp_path, recursive=True)
    assert "doc.pdf" in result
    assert "subdir/inner.txt" in result
    assert not any(r.startswith(".hidden") for r in result)
    assert not any("node_modules" in r for r in result)


def test_scan_library_files_missing_root(tmp_path: Path) -> None:
    result = scan_library_files(tmp_path / "does_not_exist")
    assert result == []


def test_build_file_tree(tmp_path: Path) -> None:
    (tmp_path / "paper.pdf").write_text("pdf")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "notes.md").write_text("md")
    tree = build_file_tree(tmp_path)
    names = {n.name for n in tree}
    assert "paper.pdf" in names
    doc_node = next((n for n in tree if n.name == "docs"), None)
    assert doc_node is not None
    assert any(c.name == "notes.md" for c in doc_node.children)


def test_build_file_tree_empty(tmp_path: Path) -> None:
    assert build_file_tree(tmp_path) == []
    assert build_file_tree(tmp_path / "missing") == []
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/unit/core/test_file_scanner.py -v
```

Expected: 5 tests PASS。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/core/test_file_scanner.py
git commit -m "test(core): add file_scanner unit tests"
```

---

## Task 4: `core/library.py` 测试

**Files:**
- Create: `tests/unit/core/test_library.py`
- Test: `tests/unit/core/test_library.py`

**Interfaces:**
- Consumes: `LibraryStore.get(root)`, `add_document`, `add_uploaded_file`, `get_document`, `delete_document`, `list_documents`, `search_documents`, `create_collection`, `delete_collection`, `get_collection_tree`, `add_to_collection`, `doc_count`。
- Produces: 断言 document/collection CRUD 和搜索行为。

### 步骤

- [ ] **Step 1: 编写测试**

```python
from __future__ import annotations

from pathlib import Path

import pytest

from mbforge.core.library import LibraryStore
from mbforge.utils.helpers import MBForgeError


def test_library_store_get_singleton(tmp_path: Path) -> None:
    store1 = LibraryStore.get(tmp_path)
    store2 = LibraryStore.get(tmp_path)
    assert store1 is store2


def test_add_document_and_get(tmp_path: Path) -> None:
    store = LibraryStore.get(tmp_path)
    src = tmp_path / "input.pdf"
    src.write_bytes(b"pdf content")
    doc = store.add_document(src, title="My Paper")
    assert doc.doc_id
    assert doc.title == "My Paper"
    retrieved = store.get_document(doc.doc_id)
    assert retrieved is not None
    assert retrieved.title == "My Paper"


def test_add_document_missing_file(tmp_path: Path) -> None:
    store = LibraryStore.get(tmp_path)
    with pytest.raises(MBForgeError):
        store.add_document(tmp_path / "missing.pdf")


def test_add_uploaded_file_and_dedup(tmp_path: Path) -> None:
    store = LibraryStore.get(tmp_path)
    doc1 = store.add_uploaded_file(b"same content", "a.pdf")
    with pytest.raises(MBForgeError):
        store.add_uploaded_file(b"same content", "b.pdf")


def test_delete_document(tmp_path: Path) -> None:
    store = LibraryStore.get(tmp_path)
    src = tmp_path / "input.pdf"
    src.write_bytes(b"pdf")
    doc = store.add_document(src)
    store.delete_document(doc.doc_id)
    assert store.get_document(doc.doc_id) is None


def test_list_and_search_documents(tmp_path: Path) -> None:
    store = LibraryStore.get(tmp_path)
    src = tmp_path / "input.pdf"
    src.write_bytes(b"pdf")
    store.add_document(src, title="Alpha Paper")
    assert len(store.list_documents()) == 1
    assert len(store.search_documents("Alpha")) == 1
    assert len(store.search_documents("Beta")) == 0


def test_collection_tree(tmp_path: Path) -> None:
    store = LibraryStore.get(tmp_path)
    root = store.create_collection("Root")
    child = store.create_collection("Child", parent_id=root.collection_id)
    tree = store.get_collection_tree()
    assert len(tree) == 1
    assert tree[0].collection_id == root.collection_id
    assert tree[0].children[0].collection_id == child.collection_id


def test_add_to_collection(tmp_path: Path) -> None:
    store = LibraryStore.get(tmp_path)
    src = tmp_path / "input.pdf"
    src.write_bytes(b"pdf")
    doc = store.add_document(src)
    col = store.create_collection("Col")
    store.add_to_collection(col.collection_id, doc.doc_id)
    docs = store.list_documents(collection_id=col.collection_id)
    assert len(docs) == 1
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/unit/core/test_library.py -v
```

Expected: 8 tests PASS。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/core/test_library.py
git commit -m "test(core): add LibraryStore CRUD and collection tests"
```

---

## Task 5: `core/knowledge_base.py` 测试

**Files:**
- Create: `tests/unit/core/test_knowledge_base.py`
- Test: `tests/unit/core/test_knowledge_base.py`

**Interfaces:**
- Consumes: `search(query, library_root, ...)`, `get_document_pages(library_root, doc_id, pages)`, `get_document_tree(library_root, doc_id)`。
- Produces: 断言缓存命中、搜索结果过滤、页面读取、树结构回退。

### 步骤

- [ ] **Step 1: 编写测试**

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from mbforge.core import knowledge_base as kb


def test_search_cache_hit(in_memory_semantic_cache: str) -> None:
    library_root = in_memory_semantic_cache
    kb.store_cache("query", library_root, [{"id": "cached"}])
    result = kb.search("query", library_root, use_cache=True)
    assert result["from_cache"] is True
    assert result["count"] == 1
    assert result["results"][0]["id"] == "cached"


def test_search_with_doc_id_filter(in_memory_semantic_cache: str, monkeypatch) -> None:
    library_root = in_memory_semantic_cache

    def _fake_search(*args, **kwargs):
        return {
            "results": [
                {"doc_id": "doc1", "text": "a"},
                {"doc_id": "doc2", "text": "b"},
            ],
            "answer": "",
        }

    with patch("mbforge.openkb.adapter.OpenKBAdapter.search", _fake_search):
        result = kb.search("q", library_root, doc_id_filter="doc1")
    assert len(result["results"]) == 1
    assert result["results"][0]["doc_id"] == "doc1"


def test_search_adapter_error(in_memory_semantic_cache: str, monkeypatch) -> None:
    library_root = in_memory_semantic_cache

    def _broken(*args, **kwargs):
        raise RuntimeError("openkb failed")

    with patch("mbforge.openkb.adapter.OpenKBAdapter.search", _broken):
        result = kb.search("q", library_root)
    assert result["results"] == []
    assert "error" in result


def test_get_document_pages(tmp_path: Path) -> None:
    from mbforge.core.artifact import ArtifactResolver

    library_root = str(tmp_path)
    pages_dir = ArtifactResolver(library_root).pages_dir("doc1")
    pages_dir.mkdir(parents=True)
    (pages_dir / "page_0001.txt").write_text("page one")
    (pages_dir / "page_0002.txt").write_text("page two")
    result = kb.get_document_pages(library_root, "doc1", pages=[1])
    assert len(result) == 1
    assert result[0]["page"] == 1


def test_get_document_tree_from_openkb_wiki(tmp_path: Path) -> None:
    from mbforge.core.layout import LibraryLayout

    library_root = str(tmp_path)
    summary = LibraryLayout(library_root).openkb_wiki_dir() / "summaries" / "doc1.md"
    summary.parent.mkdir(parents=True)
    summary.write_text("# Summary")
    result = kb.get_document_tree(library_root, "doc1")
    assert result is not None
    assert result[0]["source"] == "openkb_wiki"
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/unit/core/test_knowledge_base.py -v
```

Expected: 5 tests PASS。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/core/test_knowledge_base.py
git commit -m "test(core): add knowledge_base search and page tests"
```

---

## Task 6: `core/semantic_cache.py` 测试

**Files:**
- Create: `tests/unit/core/test_semantic_cache.py`
- Test: `tests/unit/core/test_semantic_cache.py`

**Interfaces:**
- Consumes: `check_cache(query, library_root)`, `store_cache(query, library_root, results)`, `invalidate_cache(library_root)`。
- Produces: 断言写入、命中、失效、大小写不敏感。

### 步骤

- [ ] **Step 1: 编写测试**

```python
from __future__ import annotations

from mbforge.core import semantic_cache as cache


def test_store_and_check_cache(in_memory_semantic_cache: str) -> None:
    root = in_memory_semantic_cache
    assert cache.check_cache("hello", root) is None
    cache.store_cache("hello", root, [{"id": 1}])
    assert cache.check_cache("hello", root) == [{"id": 1}]


def test_cache_is_case_and_whitespace_insensitive(in_memory_semantic_cache: str) -> None:
    root = in_memory_semantic_cache
    cache.store_cache("Hello World", root, [{"id": 2}])
    assert cache.check_cache("  hello world  ", root) == [{"id": 2}]


def test_cache_increments_hit_count(in_memory_semantic_cache: str) -> None:
    root = in_memory_semantic_cache
    cache.store_cache("q", root, [{"id": 3}])
    cache.check_cache("q", root)
    cache.check_cache("q", root)
    from mbforge.core.database import DatabaseManager

    db = DatabaseManager.get(root)
    with db.kb_conn() as conn:
        row = conn.execute(
            "SELECT hit_count FROM semantic_cache WHERE query_hash = ?",
            (cache._query_hash("q"),),
        ).fetchone()
    assert row["hit_count"] == 2


def test_invalidate_cache(in_memory_semantic_cache: str) -> None:
    root = in_memory_semantic_cache
    cache.store_cache("q", root, [{"id": 4}])
    cache.invalidate_cache(root)
    assert cache.check_cache("q", root) is None
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/unit/core/test_semantic_cache.py -v
```

Expected: 4 tests PASS。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/core/test_semantic_cache.py
git commit -m "test(core): add semantic_cache hit/miss/invalidate tests"
```

---

## Task 7: `pipeline/organizer.py` 测试

**Files:**
- Create: `tests/unit/pipeline/test_organizer.py`
- Test: `tests/unit/pipeline/test_organizer.py`

**Interfaces:**
- Consumes: `reorganize_with_llm(md_path, output_path, model)`, `_rule_based_reorganize(md_text)`, `_looks_degenerate(text, original)`, `_mol_to_molecode`, `insert_molecode_blocks`。
- Produces: 断言 LLM fallback、规则重组、退化检测、MoleCode 插入。

### 步骤

- [ ] **Step 1: 编写测试**

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from mbforge.pipeline.organizer import (
    _looks_degenerate,
    _rule_based_reorganize,
    insert_molecode_blocks,
    reorganize_with_llm,
)


def test_rule_based_reorganize_strips_page_markers() -> None:
    md = "<!-- PAGE 1 -->\nAbstract\n<!-- PAGE 2 -->\nDetails"
    out = _rule_based_reorganize(md)
    assert "<!-- PAGE" not in out
    assert "Abstract" in out


def test_rule_based_reorganize_promotes_headings() -> None:
    md = "ABSTRACT\n\nSome text"
    out = _rule_based_reorganize(md)
    assert "## Abstract" in out


def test_looks_degenerate_strips_molecode() -> None:
    original = "```molecode\ncontent\n```"
    out = "no molecode here"
    assert _looks_degenerate(out, original) is True


def test_reorganize_with_llm_fallback_on_short_text(tmp_path: Path) -> None:
    md = tmp_path / "in.md"
    out = tmp_path / "out.md"
    md.write_text("# Title\n\nSome content.", encoding="utf-8")
    with patch("mbforge.pipeline.organizer._llm_complete", return_value=None):
        reorganize_with_llm(str(md), str(out))
    assert out.exists()
    assert "# Title" in out.read_text(encoding="utf-8")


def test_reorganize_with_llm_uses_rule_fallback_when_output_too_short(tmp_path: Path) -> None:
    md = tmp_path / "in.md"
    out = tmp_path / "out.md"
    long_text = "Word " * 1000
    md.write_text(long_text, encoding="utf-8")
    with patch("mbforge.pipeline.organizer._llm_complete", return_value="short"):
        reorganize_with_llm(str(md), str(out))
    text = out.read_text(encoding="utf-8")
    assert len(text) > len("short")
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/unit/pipeline/test_organizer.py -v
```

Expected: 5 tests PASS。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/pipeline/test_organizer.py
git commit -m "test(pipeline): add organizer rule-based and LLM fallback tests"
```

---

## Task 8: Routers 业务测试

### Task 8.1: `routers/library.py`

**Files:**
- Create: `tests/unit/routers/test_library.py`
- Test: `tests/unit/routers/test_library.py`

**Interfaces:**
- Consumes: `app_client`, `tmp_library` fixtures；endpoints: `POST /import`, `POST /documents`, `POST /documents/delete`, `GET /documents/{doc_id}/file`, `GET /documents/{doc_id}/reorganized`, `POST /collections/create`, `POST /collections/list`, `POST /configure`。

### 步骤

- [ ] **Step 1: 编写测试**

```python
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_library_status(app_client: TestClient) -> None:
    resp = app_client.get("/api/v1/library/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert "root" in data


def test_library_configure(app_client: TestClient, tmp_path: Path) -> None:
    root = str(tmp_path / "new_lib")
    resp = app_client.post("/api/v1/library/configure", json={"root": root})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_library_import_and_list(app_client: TestClient) -> None:
    pdf_bytes = b"%PDF-1.4 fake pdf"
    resp = app_client.post(
        "/api/v1/library/import",
        data={"title": "Test Paper"},
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    doc_id = data["document"]["doc_id"]

    resp = app_client.post("/api/v1/library/documents", json={})
    assert resp.status_code == 200
    ids = {d["doc_id"] for d in resp.json()["documents"]}
    assert doc_id in ids


def test_library_get_document_file(app_client: TestClient) -> None:
    pdf_bytes = b"%PDF-1.4 fake pdf"
    resp = app_client.post(
        "/api/v1/library/import",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = resp.json()["document"]["doc_id"]
    resp = app_client.get(f"/api/v1/library/documents/{doc_id}/file")
    assert resp.status_code == 200
    assert resp.content == pdf_bytes


def test_library_collections(app_client: TestClient) -> None:
    resp = app_client.post("/api/v1/library/collections/create", json={"name": "My Col"})
    assert resp.status_code == 200
    col_id = resp.json()["collection"]["collection_id"]

    resp = app_client.post("/api/v1/library/collections/list", json={})
    assert any(c["collection_id"] == col_id for c in resp.json()["collections"])
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/unit/routers/test_library.py -v
```

Expected: 5 tests PASS。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/routers/test_library.py
git commit -m "test(routers): add library router business tests"
```

### Task 8.2: `routers/knowledge_base.py`

**Files:**
- Create: `tests/unit/routers/test_knowledge_base.py`
- Test: `tests/unit/routers/test_knowledge_base.py`

### 步骤

- [ ] **Step 1: 编写测试**

```python
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient


def test_kb_search_missing_params(app_client: TestClient) -> None:
    resp = app_client.post("/api/v1/kb/search", json={})
    assert resp.status_code == 200
    assert resp.json()["success"] is False


def test_kb_search_with_mocked_adapter(app_client: TestClient, tmp_path) -> None:
    with patch("mbforge.core.knowledge_base.search") as mock_search:
        mock_search.return_value = {
            "results": [{"doc_id": "d1", "text": "result"}],
            "answer": "",
            "count": 1,
            "from_cache": False,
        }
        resp = app_client.post(
            "/api/v1/kb/search",
            json={"query": "q", "library_root": str(tmp_path)},
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert len(resp.json()["results"]) == 1


def test_kb_pages_missing_params(app_client: TestClient) -> None:
    resp = app_client.post("/api/v1/kb/pages", json={})
    assert resp.status_code == 200
    assert resp.json()["success"] is False


def test_kb_wiki_list_empty(app_client: TestClient, tmp_path) -> None:
    resp = app_client.get(f"/api/v1/kb/wiki/list?library_root={tmp_path}")
    assert resp.status_code == 200
    assert resp.json()["summaries"] == []
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/unit/routers/test_knowledge_base.py -v
```

Expected: 4 tests PASS。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/routers/test_knowledge_base.py
git commit -m "test(routers): add knowledge_base router tests"
```

### Task 8.3: `routers/coref.py`

**Files:**
- Create: `tests/unit/routers/test_coref.py`
- Test: `tests/unit/routers/test_coref.py`

### 步骤

- [ ] **Step 1: 编写测试**

```python
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _make_fake_coref_result():
    mol = MagicMock()
    mol.category_id = 1
    mol.bbox = (0.1, 0.1, 0.2, 0.2)
    mol.score = 0.9
    label = MagicMock()
    label.category_id = 3
    label.bbox = (0.3, 0.3, 0.4, 0.4)
    label.score = 0.8
    result = MagicMock()
    result.bboxes = [mol, label]
    result.corefs = [(0, 1)]
    return result


def test_coref_figure_labels_validation(app_client: TestClient) -> None:
    resp = app_client.post("/api/v1/coref/figure-labels", json={})
    assert resp.status_code == 422


def test_coref_figure_labels_with_mock(app_client: TestClient, tmp_path, sample_pdf) -> None:
    import shutil

    lib = tmp_path / "lib"
    lib.mkdir()
    shutil.copy(sample_pdf, lib / "doc1.pdf")
    fake = _make_fake_coref_result()
    with patch("mbforge.routers.coref.detect_coref_via_ft_detector", return_value=fake), \
         patch("mbforge.routers.coref.RapidOCRCropAdapter.instance") as mock_adapter:
        mock_adapter.return_value.readtext_batch.return_value = ["Fig 1"]
        resp = app_client.post(
            "/api/v1/coref/figure-labels",
            json={"library_root": str(lib), "docId": "doc1", "page": 1},
        )
    assert resp.status_code == 200
    labels = resp.json()["labels"]
    assert len(labels) == 1
    assert labels[0]["label_text"] == "Fig 1"


def test_coref_predictions_with_mock(app_client: TestClient, tmp_path, sample_pdf) -> None:
    import shutil

    lib = tmp_path / "lib"
    lib.mkdir()
    shutil.copy(sample_pdf, lib / "doc1.pdf")
    fake = _make_fake_coref_result()
    with patch("mbforge.routers.coref.detect_coref_via_ft_detector", return_value=fake), \
         patch("mbforge.routers.coref.RapidOCRCropAdapter.instance") as mock_adapter:
        mock_adapter.return_value.readtext_batch.return_value = ["Fig 1"]
        resp = app_client.post(
            "/api/v1/coref/predictions",
            json={"library_root": str(lib), "docId": "doc1", "page": 1},
        )
    assert resp.status_code == 200
    preds = resp.json()["predictions"]
    assert len(preds) == 1
    assert preds[0]["source"] == "geometric_ft"
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/unit/routers/test_coref.py -v
```

Expected: 3 tests PASS。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/routers/test_coref.py
git commit -m "test(routers): add coref router tests with mocked FT/OCR"
```

### Task 8.4: `routers/moldet_api.py`

**Files:**
- Create: `tests/unit/routers/test_moldet_api.py`
- Test: `tests/unit/routers/test_moldet_api.py`

### 步骤

- [ ] **Step 1: 编写测试**

```python
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def test_extract_pdf_page_validation(app_client: TestClient) -> None:
    resp = app_client.post("/api/v1/moldet/extract-pdf-page", json={})
    assert resp.status_code == 422


def test_extract_pdf_page_with_mock(app_client: TestClient, sample_pdf) -> None:
    fake_mol = MagicMock()
    fake_mol.smiles = "CCO"
    fake_mol.confidence = 0.9
    fake_mol.bbox = [0, 0, 10, 10]
    fake_mol.page = 1
    with patch("mbforge.routers.moldet_api.get_moldet_ft") as mock_det, \
         patch("mbforge.routers.moldet_api.load_molscribe") as mock_mol:
        mock_det.return_value.detect_page.return_value = [MagicMock(bbox=[0,0,10,10], confidence=0.9)]
        mock_mol.return_value.predict.return_value = {"smiles": "CCO"}
        resp = app_client.post(
            "/api/v1/moldet/extract-pdf-page",
            json={"pdf_path": str(sample_pdf), "page": 1},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/unit/routers/test_moldet_api.py -v
```

Expected: 2 tests PASS。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/routers/test_moldet_api.py
git commit -m "test(routers): add moldet_api router smoke tests"
```

### Task 8.5: `routers/molecule.py`

**Files:**
- Create: `tests/unit/routers/test_molecule.py`
- Test: `tests/unit/routers/test_molecule.py`

### 步骤

- [ ] **Step 1: 编写测试**

```python
from __future__ import annotations

from fastapi.testclient import TestClient


def test_molecule_create_and_get(app_client: TestClient, tmp_path) -> None:
    root = str(tmp_path)
    resp = app_client.post(
        "/api/v1/molecule/create",
        json={"library_root": root, "smiles": "CCO", "name": "Ethanol"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    mol_id = data["mol_id"]

    resp = app_client.post(
        "/api/v1/molecule/get",
        json={"library_root": root, "mol_id": mol_id},
    )
    assert resp.status_code == 200
    assert resp.json()["molecule"]["smiles"] == "CCO"


def test_molecule_list_and_stats(app_client: TestClient, tmp_path) -> None:
    root = str(tmp_path)
    app_client.post(
        "/api/v1/molecule/create",
        json={"library_root": root, "smiles": "CCO", "source_type": "manual"},
    )
    resp = app_client.post(
        "/api/v1/molecule/list",
        json={"library_root": root, "page": 1, "page_size": 10},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    resp = app_client.post("/api/v1/molecule/stats", json={"library_root": root})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_molecule_update_and_delete(app_client: TestClient, tmp_path) -> None:
    root = str(tmp_path)
    resp = app_client.post(
        "/api/v1/molecule/create",
        json={"library_root": root, "smiles": "CCO"},
    )
    mol_id = resp.json()["mol_id"]
    resp = app_client.put(
        f"/api/v1/molecule/{mol_id}",
        json={"library_root": root, "name": "Updated"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    resp = app_client.post(
        "/api/v1/molecule/get",
        json={"library_root": root, "mol_id": mol_id},
    )
    assert resp.json()["molecule"]["name"] == "Updated"
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/unit/routers/test_molecule.py -v
```

Expected: 3 tests PASS。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/routers/test_molecule.py
git commit -m "test(routers): add molecule router CRUD tests"
```

---

## Task 9: `openkb/` 测试

### Task 9.1: `openkb/config.py`

**Files:**
- Create: `tests/unit/openkb/test_config.py`
- Test: `tests/unit/openkb/test_config.py`

### 步骤

- [ ] **Step 1: 编写测试**

```python
from __future__ import annotations

from mbforge.openkb.config import to_litellm_config, to_litellm_model
from mbforge.utils.config import LLMConfig


def test_to_litellm_model_passthrough_prefix() -> None:
    cfg = LLMConfig(model="openai/gpt-4")
    assert to_litellm_model(cfg) == "openai/gpt-4"


def test_to_litellm_model_ollama() -> None:
    cfg = LLMConfig(model="llama3", provider="ollama")
    assert to_litellm_model(cfg) == "ollama/llama3"


def test_to_litellm_model_openai_compatible() -> None:
    cfg = LLMConfig(model="custom", provider="openai_compatible", base_url="http://localhost:8000")
    assert to_litellm_model(cfg) == "openai/custom?api_base=http://localhost:8000"


def test_to_litellm_config_includes_api_key() -> None:
    cfg = LLMConfig(model="gpt-4", api_key="secret", temperature=0.5, max_tokens=100)
    config = to_litellm_config(cfg)
    assert config["model"] == "openai/gpt-4"
    assert config["api_key"] == "secret"
    assert config["temperature"] == 0.5
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/unit/openkb/test_config.py -v
```

Expected: 4 tests PASS。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/openkb/test_config.py
git commit -m "test(openkb): add config litellm mapping tests"
```

### Task 9.2: `openkb/query.py`

**Files:**
- Create: `tests/unit/openkb/test_query.py`
- Test: `tests/unit/openkb/test_query.py`

### 步骤

- [ ] **Step 1: 编写测试**

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mbforge.openkb import query as openkb_query


def test_extract_relevant_sources_empty(tmp_path: Path) -> None:
    result = openkb_query._extract_relevant_sources("test", str(tmp_path), 5)
    assert result == []


def test_extract_relevant_sources_scores(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    summaries = wiki / "summaries"
    summaries.mkdir(parents=True)
    (summaries / "doc1.md").write_text("# Title\nThis document mentions aspirin.")
    result = openkb_query._extract_relevant_sources("aspirin", str(wiki), 5)
    assert len(result) == 1
    assert result[0]["id"] == "doc1"
    assert result[0]["score"] > 0


def test_extract_title() -> None:
    assert openkb_query._extract_title("# Hello\nWorld") == "Hello"
    assert openkb_query._extract_title("No heading") == ""


def test_extract_pages() -> None:
    assert openkb_query._extract_pages("pages 5-10") == (5, 10)
    assert openkb_query._extract_pages("page 3") == (3, 3)
    assert openkb_query._extract_pages("no pages") == (None, None)


@pytest.mark.asyncio
async def test_search_wiki_openkb_missing(tmp_path: Path) -> None:
    with patch("mbforge.openkb.query.run_query", side_effect=ImportError("openkb")):
        with pytest.raises(RuntimeError):
            await openkb_query.search_wiki("q", str(tmp_path))
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/unit/openkb/test_query.py -v
```

Expected: 5 tests PASS。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/openkb/test_query.py
git commit -m "test(openkb): add query source extraction tests"
```

### Task 9.3: `openkb/compiler.py`

**Files:**
- Create: `tests/unit/openkb/test_compiler.py`
- Test: `tests/unit/openkb/test_compiler.py`

### 步骤

- [ ] **Step 1: 编写测试**

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mbforge.openkb.compiler import WikiCompiler


@pytest.mark.asyncio
async def test_compile_short_doc_creates_summary(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    docs = tmp_path / "documents"
    docs.mkdir(parents=True)
    (docs / "doc1.md").write_text("# Doc\nContent")
    compiler = WikiCompiler(str(wiki))
    with patch("mbforge.openkb.compiler.compile_short_doc") as mock_compile:
        await compiler.compile_document("Doc", "doc1", page_count=1)
    assert mock_compile.called


@pytest.mark.asyncio
async def test_compile_long_doc_uses_long_path(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    docs = tmp_path / "documents"
    docs.mkdir(parents=True)
    (docs / "doc1.md").write_text("# Doc\nContent")
    compiler = WikiCompiler(str(wiki))
    with patch("mbforge.openkb.compiler.compile_long_doc") as mock_compile:
        await compiler.compile_document("Doc", "doc1", page_count=100)
    assert mock_compile.called


def test_compiler_missing_openkb_raises(tmp_path: Path) -> None:
    compiler = WikiCompiler(str(tmp_path / "wiki"))
    with patch("mbforge.openkb.compiler.compile_short_doc", side_effect=ImportError("no openkb")):
        import asyncio
        with pytest.raises(RuntimeError):
            asyncio.run(compiler.compile_document("Doc", "doc1", page_count=1))
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/unit/openkb/test_compiler.py -v
```

Expected: 3 tests PASS。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/openkb/test_compiler.py
git commit -m "test(openkb): add wiki compiler routing tests"
```

---

## Task 10: 覆盖率验证与回归

**Files:**
- 全部新增/修改文件
- Test: `tests/` 全部

### 步骤

- [ ] **Step 1: 运行完整测试套件**

```bash
uv run pytest tests/ -q
```

Expected: 0 failures。

- [ ] **Step 2: 检查覆盖率**

```bash
uv run pytest tests/ --cov=src/mbforge --cov-report=term-missing
```

Expected:
- TOTAL ≥ 42%
- `core/` ≥ 60%
- `routers/` ≥ 30%
- `pipeline/organizer.py` ≥ 60%
- `openkb/config.py`, `openkb/query.py`, `openkb/compiler.py` ≥ 50%

- [ ] **Step 3: 静态检查**

```bash
uv run ruff check src/ tests/
```

Expected: 无新增错误。

- [ ] **Step 4: 最终提交**

如果覆盖率未达标，识别缺口最大的文件并补充测试；达标后：

```bash
git add docs/superpowers/plans/2026-07-11-backend-test-coverage-phase0-plan.md
git commit -m "docs(plan): add Phase 0 backend test coverage implementation plan"
```

---

## Self-Review Checklist

- [ ] Spec coverage: 每个设计文档中的模块都有对应 task。
- [ ] Placeholder scan: 无 "TBD/TODO/实现 later"。
- [ ] Type consistency: `app_client`、`in_memory_kb`、`in_memory_semantic_cache` 在各 task 中用法一致。
- [ ] Import paths: 所有 `from mbforge...` 与项目结构一致。
