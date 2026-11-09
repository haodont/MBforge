# Capability 平台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 MBForge 的程序功能收敛成一层可被任意 agent 调用的 capability API，专利提取作为异步能力暴露；现有 Node agent 成为第一个客户端。

**Architecture:** Python `service/capabilities` 定义唯一的能力注册表与处理器，HTTP 适配器只做鉴权/序列化。能力 = 用户级任务，不是路由镜像。写能力由 `X-MBForge-Token` 控制；只读模式不加载 token。专利提取只暴露“提交 run + 查状态 + 读结果”，不暴露内部阶段。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、现有 service use cases、pytest；Node agent 使用 `@mariozechner/pi-coding-agent` + TypeBox。

---

## 范围与非目标

**v1 能力面**

只读：

- `resolve_document`
- `get_document`
- `get_document_markdown`
- `list_evidence`
- `get_patent_result`
- `search_molecules`
- `get_run`

写（需 token）：

- `import_pdf`
- `submit_extraction`
- `reingest_document`
- `cancel_run`
- `retry_run`

**非目标**

- 不做 MCP 适配器；HTTP 是唯一入口。
- 不把 `pipeline` 内部阶段拆成可调用工具。
- 不暴露删除文档、清空库、任意路径读取。
- 不新增数据库 schema。
- 不改动 pipeline 的确定性执行。

## 测试策略（覆盖 AGENTS.md）

AGENTS.md 明确“结构和类型优先，测试不是目标”。本计划只新增两类契约测试：

1. 注册表契约：名称唯一、输入/输出 schema 可生成、`mutating` 与模式校验。
2. HTTP 鉴权契约：无 token 写能力 403、有效 token 放行到业务校验、guide 生成 token 文件。

单独处理器的业务细节不逐个写测试；通过 Pydantic 类型、`ruff`、`compileall` 和一个手工 smoke 流程验证。不要为每个 handler 复制同一套断言。

## 文件结构

```text
src/mbforge/
  foundation/
    capability_token.py          # token 文件生成/校验（新增）
    errors.py                    # 新增 CapabilityForbiddenError
  service/
    capabilities/
      __init__.py                # 导出注册表 API，触发 read/write 注册
      registry.py                # Capability/Context/Result + register/invoke
      read.py                    # 7 个只读能力
      write.py                   # 5 个写能力
  api/http/
    capabilities.py              # manifest/guide/invoke 三个端点（新增）
  server/
    app.py                       # 注册 capabilities router
agent/src/
  capabilities.ts                # 从 manifest 动态生成工具（新增）
  server.ts                      # 使用 capability 工具，删除 moleculeSearchTool
  tool.ts                        # 删除
tests/unit/capabilities/
  test_registry.py               # 注册表/模式契约
  test_capability_http.py        # HTTP 签名/鉴权契约
```

---

## Task 0: 基线确认

**Files:** 无

- [ ] **Step 1: 确认工作区状态**

Run: `git status --short`
Expected: 只显示本计划文件（如果已存在则忽略），没有未预期的源码改动。

- [ ] **Step 2: 确认现有检查通过**

Run: `uv run pytest tests/unit/architecture/test_layer_boundaries.py -q`
Expected: PASS。任何新增 `service` 代码都不能 import `db` / `api` / `server`。

- [ ] **Step 3: 确认 Node agent 可构建**

Run: `npm --prefix agent run build`
Expected: PASS。

---

## Task 1: 注册表与错误类型

**Files:**
- Create: `src/mbforge/service/capabilities/__init__.py`
- Create: `src/mbforge/service/capabilities/registry.py`
- Modify: `src/mbforge/foundation/errors.py`

- [ ] **Step 1: 在 `foundation/errors.py` 增加写能力禁用错误**

在 `NotFoundError` 之后加入：

```python
class CapabilityForbiddenError(MBForgeError):
    """Raised when a mutating capability is invoked without edit mode."""

    status_code = 403
    error_code = "capability_forbidden"
```

- [ ] **Step 2: 写 `service/capabilities/registry.py`**

```python
"""Capability registry — the single source of truth for agent-callable tasks.

Capabilities are user-level operations, not HTTP route mirrors. Adapters
(HTTP today) validate transport concerns; this module owns the mode guard,
input validation, and output type check.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from mbforge.foundation.errors import (
    CapabilityForbiddenError,
    NotFoundError,
    ValidationError,
)

CapabilityMode = Literal["readonly", "edit"]


@dataclass(frozen=True)
class CapabilityContext:
    """Server-resolved invocation context; callers never supply ``library_root``."""

    library_root: str
    mode: CapabilityMode


@dataclass(frozen=True)
class CapabilityResult:
    """One capability response plus explicit truncation metadata."""

    data: BaseModel
    truncated: bool = False
    next_offset: int | None = None


@dataclass(frozen=True)
class Capability:
    """One agent-callable task and its typed contract."""

    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    mutating: bool
    handler: Callable[[CapabilityContext, Any], Awaitable[CapabilityResult]]


_REGISTRY: dict[str, Capability] = {}


def register(capability: Capability) -> None:
    """Register one capability; duplicate names are a programming error."""
    if capability.name in _REGISTRY:
        raise RuntimeError(f"duplicate capability: {capability.name}")
    _REGISTRY[capability.name] = capability


def all_capabilities() -> tuple[Capability, ...]:
    """Return capabilities in registration order (deterministic manifests)."""
    return tuple(_REGISTRY.values())


def get_capability(name: str) -> Capability:
    capability = _REGISTRY.get(name)
    if capability is None:
        raise NotFoundError("unknown capability", detail=name)
    return capability


async def invoke(
    name: str,
    context: CapabilityContext,
    payload: dict[str, Any],
) -> CapabilityResult:
    """Validate mode/input, run the handler, and enforce the output type."""
    capability = get_capability(name)
    if capability.mutating and context.mode != "edit":
        raise CapabilityForbiddenError(
            "capability requires edit mode",
            detail="send X-MBForge-Token for mutating capabilities",
        )
    try:
        request = capability.input_model.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidationError("invalid capability input", detail=str(exc)) from exc
    result = await capability.handler(context, request)
    if not isinstance(result.data, capability.output_model):
        raise RuntimeError(
            f"{name} returned {type(result.data).__name__}, "
            f"expected {capability.output_model.__name__}"
        )
    return result
```

- [ ] **Step 3: 写 `service/capabilities/__init__.py`**

```python
"""Agent-callable capability registry."""

from .registry import (
    Capability,
    CapabilityContext,
    CapabilityMode,
    CapabilityResult,
    all_capabilities,
    get_capability,
    invoke,
    register,
)

__all__ = [
    "Capability",
    "CapabilityContext",
    "CapabilityMode",
    "CapabilityResult",
    "all_capabilities",
    "get_capability",
    "invoke",
    "register",
]
```

- [ ] **Step 4: 验证分层与类型**

Run: `uv run python -m compileall -q src/mbforge`
Expected: PASS。

Run: `uv run pytest tests/unit/architecture/test_layer_boundaries.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/foundation/errors.py src/mbforge/service/capabilities/registry.py src/mbforge/service/capabilities/__init__.py
git commit -m "feat(capabilities): add typed capability registry"
```

---

## Task 2: Token 文件

**Files:**
- Create: `src/mbforge/foundation/capability_token.py`

- [ ] **Step 1: 写 token helper**

```python
"""Capability token storage.

The token is a local intent guard, not a strong security boundary: any process
running as the same OS user can read the file. It separates read-only callers
from callers that explicitly opt into mutating capabilities.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path


def capability_token_path(library_root: str | Path) -> Path:
    """Return the token path for one library."""
    return Path(library_root).expanduser().resolve() / ".mbforge" / "capability-token"


def ensure_capability_token(library_root: str | Path) -> str:
    """Create the token on first use and return it."""
    path = capability_token_path(library_root)
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass

    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return path.read_text(encoding="utf-8").strip()
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token)
    return token


def verify_capability_token(
    library_root: str | Path,
    presented: str | None,
) -> bool:
    """Return True only when ``presented`` matches the stored token."""
    if not presented:
        return False
    path = capability_token_path(library_root)
    try:
        expected = path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return bool(expected) and secrets.compare_digest(presented, expected)
```

- [ ] **Step 2: 验证 Windows 行为**

Run: `uv run python -c "from pathlib import Path; from mbforge.foundation.capability_token import ensure_capability_token, verify_capability_token; p=Path('.tmp/token-check'); p.mkdir(parents=True, exist_ok=True); t=ensure_capability_token(p); print(len(t), verify_capability_token(p, t), verify_capability_token(p, 'bad'))"`
Expected: `>= 32 True False`（Windows 的 `chmod 0600` 可能只影响只读位；token 文件仍受当前用户 ACL 保护）。

- [ ] **Step 3: Commit**

```bash
git add src/mbforge/foundation/capability_token.py
git commit -m "feat(capabilities): add local capability token"
```

---

## Task 3: 只读能力

**Files:**
- Create: `src/mbforge/service/capabilities/read.py`
- Modify: `src/mbforge/service/capabilities/__init__.py`

- [ ] **Step 1: 写模型与处理器**

```python
"""Read-only capabilities exposed to agents."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, Field

from mbforge.foundation.errors import NotFoundError
from mbforge.foundation.layout import LibraryLayout
from mbforge.service.capabilities.registry import (
    Capability,
    CapabilityContext,
    CapabilityResult,
    register,
)
from mbforge.service.use_cases.documents import source_evidence
from mbforge.service.use_cases.documents.library import LibraryStore
from mbforge.service.use_cases.documents.patent_facts import load_patent_facts
from mbforge.service.use_cases.molecule.queries import search_molecules
from mbforge.service.use_cases.pipeline import ingest


class DocumentMatch(BaseModel):
    doc_id: str
    title: str
    file_name: str
    page_count: int
    status: str


class ResolveDocumentInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=512)
    limit: int = Field(5, ge=1, le=20)


class ResolveDocumentOutput(BaseModel):
    matches: list[DocumentMatch]


class GetDocumentInput(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=128)


class GetDocumentOutput(BaseModel):
    doc_id: str
    title: str
    file_name: str
    page_count: int
    status: str
    created_at: str
    has_markdown: bool
    has_patent_facts: bool


class GetDocumentMarkdownInput(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=128)
    offset: int = Field(0, ge=0)
    max_chars: int = Field(20000, ge=1000, le=200000)


class GetDocumentMarkdownOutput(BaseModel):
    doc_id: str
    content: str
    offset: int
    next_offset: int | None


class ListEvidenceInput(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=128)
    page: int | None = Field(None, ge=1)
    kind: str | None = Field(None, max_length=32)
    offset: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=200)


class EvidenceItem(BaseModel):
    evidence_id: str
    page: int
    kind: str
    raw_text: str
    bbox: list[float]


class ListEvidenceOutput(BaseModel):
    items: list[EvidenceItem]


class GetPatentResultInput(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=128)
    offset: int = Field(0, ge=0)
    limit: int = Field(20, ge=1, le=100)


class PatentFactCounts(BaseModel):
    sections: int
    entries: int
    synthesis_steps: int
    assay_methods: int
    examples: int
    measurements: int
    issues: int


class GetPatentResultOutput(BaseModel):
    doc_id: str
    run_id: str
    stats: dict[str, Any]
    counts: PatentFactCounts
    sections: list[dict[str, Any]]
    entries: list[dict[str, Any]]


class SearchMoleculesInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=512)
    mode: Literal["auto", "text", "substructure", "similarity"] = "auto"
    top_k: int = Field(10, ge=1, le=50)
    similarity_threshold: float = Field(0.5, ge=0.0, le=1.0)


class SearchMoleculesOutput(BaseModel):
    items: list[dict[str, Any]]


class GetRunInput(BaseModel):
    run_id: str = Field(..., min_length=1, max_length=128)


class RunNode(BaseModel):
    stage: str
    status: str


class GetRunOutput(BaseModel):
    run_id: str
    doc_id: str | None
    status: str
    nodes: list[RunNode]


async def resolve_document(
    context: CapabilityContext, request: ResolveDocumentInput
) -> CapabilityResult:
    def _search() -> list[dict[str, Any]]:
        store = LibraryStore.get(context.library_root)
        exact = store.load_document(request.query)
        documents = [exact] if exact is not None else store.search_documents(request.query)
        return [document.to_dict() for document in documents[: request.limit]]

    rows = await asyncio.to_thread(_search)
    return CapabilityResult(
        data=ResolveDocumentOutput(matches=[DocumentMatch(**row) for row in rows])
    )


async def get_document(
    context: CapabilityContext, request: GetDocumentInput
) -> CapabilityResult:
    store = LibraryStore.get(context.library_root)
    document = await asyncio.to_thread(store.load_document, request.doc_id)
    if document is None:
        raise NotFoundError("document not found", detail=request.doc_id)

    layout = LibraryLayout(context.library_root)
    payload = document.to_dict()
    payload["has_markdown"] = layout.document_md(request.doc_id).is_file()
    payload["has_patent_facts"] = (
        layout.storage_dir(request.doc_id) / "patent_facts.json"
    ).is_file()
    return CapabilityResult(data=GetDocumentOutput(**payload))


async def get_document_markdown(
    context: CapabilityContext, request: GetDocumentMarkdownInput
) -> CapabilityResult:
    path = LibraryLayout(context.library_root).document_md(request.doc_id)
    if not path.is_file():
        raise NotFoundError(
            "document markdown not available", detail=request.doc_id
        )
    text = await asyncio.to_thread(path.read_text, encoding="utf-8")
    chunk = text[request.offset : request.offset + request.max_chars]
    next_offset = (
        request.offset + request.max_chars
        if request.offset + request.max_chars < len(text)
        else None
    )
    return CapabilityResult(
        data=GetDocumentMarkdownOutput(
            doc_id=request.doc_id,
            content=chunk,
            offset=request.offset,
            next_offset=next_offset,
        ),
        truncated=next_offset is not None,
        next_offset=next_offset,
    )


async def list_evidence(
    context: CapabilityContext, request: ListEvidenceInput
) -> CapabilityResult:
    records = await asyncio.to_thread(
        source_evidence.list_evidence,
        context.library_root,
        request.doc_id,
        request.page,
        request.kind,
    )
    page = records[request.offset : request.offset + request.limit]
    next_offset = (
        request.offset + request.limit
        if request.offset + request.limit < len(records)
        else None
    )
    return CapabilityResult(
        data=ListEvidenceOutput(
            items=[EvidenceItem(**record.to_dict()) for record in page]
        ),
        truncated=next_offset is not None,
        next_offset=next_offset,
    )


async def get_patent_result(
    context: CapabilityContext, request: GetPatentResultInput
) -> CapabilityResult:
    facts = await asyncio.to_thread(
        load_patent_facts, context.library_root, request.doc_id
    )
    if facts is None:
        raise NotFoundError("patent facts not available", detail=request.doc_id)

    entries = facts.entries[request.offset : request.offset + request.limit]
    next_offset = (
        request.offset + request.limit
        if request.offset + request.limit < len(facts.entries)
        else None
    )
    counts = PatentFactCounts(
        sections=len(facts.sections),
        entries=len(facts.entries),
        synthesis_steps=len(facts.synthesis_steps),
        assay_methods=len(facts.assay_methods),
        examples=len(facts.examples),
        measurements=len(facts.measurements),
        issues=len(facts.issues),
    )
    return CapabilityResult(
        data=GetPatentResultOutput(
            doc_id=facts.doc_id,
            run_id=facts.run_id,
            stats=facts.stats,
            counts=counts,
            sections=[section.model_dump() for section in facts.sections],
            entries=entries,
        ),
        truncated=next_offset is not None,
        next_offset=next_offset,
    )


async def search_molecules_capability(
    context: CapabilityContext, request: SearchMoleculesInput
) -> CapabilityResult:
    items = await asyncio.to_thread(
        search_molecules,
        context.library_root,
        request.query,
        request.top_k,
        request.mode,
        request.similarity_threshold,
    )
    return CapabilityResult(data=SearchMoleculesOutput(items=items))


async def get_run(
    context: CapabilityContext, request: GetRunInput
) -> CapabilityResult:
    tasks = await ingest.list_tasks(context.library_root)
    rows = [task for task in tasks if task.get("run_id") == request.run_id]
    if not rows:
        raise NotFoundError("run not found", detail=request.run_id)

    status = await asyncio.to_thread(
        ingest.fetch_run_status, context.library_root, request.run_id
    )
    return CapabilityResult(
        data=GetRunOutput(
            run_id=request.run_id,
            doc_id=rows[0].get("doc_id"),
            status=status or "unknown",
            nodes=[
                RunNode(stage=str(row.get("stage", "")), status=str(row.get("status", "")))
                for row in rows
            ],
        )
    )


register(
    Capability(
        name="resolve_document",
        description="Find library documents by exact doc_id or by title/file-name substring.",
        input_model=ResolveDocumentInput,
        output_model=ResolveDocumentOutput,
        mutating=False,
        handler=resolve_document,
    )
)
register(
    Capability(
        name="get_document",
        description="Return one document's metadata and whether Markdown/Patent facts exist.",
        input_model=GetDocumentInput,
        output_model=GetDocumentOutput,
        mutating=False,
        handler=get_document,
    )
)
register(
    Capability(
        name="get_document_markdown",
        description="Read a chunk of the assembled document Markdown.",
        input_model=GetDocumentMarkdownInput,
        output_model=GetDocumentMarkdownOutput,
        mutating=False,
        handler=get_document_markdown,
    )
)
register(
    Capability(
        name="list_evidence",
        description="List canonical source evidence for one document page or kind.",
        input_model=ListEvidenceInput,
        output_model=ListEvidenceOutput,
        mutating=False,
        handler=list_evidence,
    )
)
register(
    Capability(
        name="get_patent_result",
        description="Return Patent facts summary plus a page of compound entries.",
        input_model=GetPatentResultInput,
        output_model=GetPatentResultOutput,
        mutating=False,
        handler=get_patent_result,
    )
)
register(
    Capability(
        name="search_molecules",
        description="Search the active molecule library by text, substructure, or similarity.",
        input_model=SearchMoleculesInput,
        output_model=SearchMoleculesOutput,
        mutating=False,
        handler=search_molecules_capability,
    )
)
register(
    Capability(
        name="get_run",
        description="Return one pipeline run's aggregated status and stage nodes.",
        input_model=GetRunInput,
        output_model=GetRunOutput,
        mutating=False,
        handler=get_run,
    )
)
```

- [ ] **Step 2: 在 `__init__.py` 注册 read 模块**

在 `__init__.py` 的 `registry` import 之后加入：

```python
from . import read as _read  # noqa: F401 — registers read capabilities
```

- [ ] **Step 3: 验证导入与类型**

Run: `uv run python -c "from mbforge.service.capabilities import all_capabilities; print([c.name for c in all_capabilities()])"`
Expected: 输出包含 7 个只读能力名，无异常。

- [ ] **Step 4: 跑分层检查**

Run: `uv run pytest tests/unit/architecture/test_layer_boundaries.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/service/capabilities/read.py
git commit -m "feat(capabilities): add read-only capabilities"
```

---

## Task 4: 写能力

**Files:**
- Create: `src/mbforge/service/capabilities/write.py`
- Modify: `src/mbforge/service/capabilities/__init__.py`

- [ ] **Step 1: 写模型、路径校验与处理器**

```python
"""Mutating capabilities; every handler requires edit mode at the registry."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from mbforge.foundation.errors import (
    ConflictError,
    NotFoundError,
    PathTraversalError,
    ValidationError,
)
from mbforge.service.capabilities.registry import (
    Capability,
    CapabilityContext,
    CapabilityResult,
    register,
)
from mbforge.service.use_cases.documents.library import LibraryStore
from mbforge.service.use_cases.pipeline import ingest

_ACTIVE_RUN_STATUSES = {"pending", "processing", "blocked"}


class ImportPdfInput(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)
    title: str = Field("", max_length=512)


class ImportPdfOutput(BaseModel):
    doc_id: str
    title: str
    file_name: str
    status: str


class SubmitExtractionInput(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=128)


class SubmitExtractionOutput(BaseModel):
    run_id: str
    doc_id: str


class ReingestDocumentInput(BaseModel):
    doc_id: str = Field(..., min_length=1, max_length=128)


class ReingestDocumentOutput(BaseModel):
    run_id: str
    doc_id: str


class RunActionInput(BaseModel):
    run_id: str = Field(..., min_length=1, max_length=128)


class RunActionOutput(BaseModel):
    run_id: str
    updated: int


def _resolve_import_path(library_root: str, raw: str) -> Path:
    """Resolve a path only inside the active library (no arbitrary filesystem)."""
    if not raw.strip():
        raise ValidationError("path is required")
    root = Path(library_root).resolve()
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PathTraversalError(
            "path escapes the library root", detail=str(resolved)
        ) from exc
    if not resolved.is_file():
        raise NotFoundError("PDF not found", detail=str(resolved))
    return resolved


async def _active_run_id(library_root: str, doc_id: str) -> str | None:
    tasks = await ingest.list_tasks(library_root)
    for task in tasks:
        if task.get("doc_id") == doc_id and task.get("status") in _ACTIVE_RUN_STATUSES:
            return str(task.get("run_id") or "")
    return None


async def import_pdf(
    context: CapabilityContext, request: ImportPdfInput
) -> CapabilityResult:
    path = _resolve_import_path(context.library_root, request.path)
    store = LibraryStore.get(context.library_root)
    document = await asyncio.to_thread(store.add_document, path, request.title)
    return CapabilityResult(data=ImportPdfOutput(**document.to_dict()))


async def submit_extraction(
    context: CapabilityContext, request: SubmitExtractionInput
) -> CapabilityResult:
    store = LibraryStore.get(context.library_root)
    document = await asyncio.to_thread(store.load_document, request.doc_id)
    if document is None:
        raise NotFoundError("document not found", detail=request.doc_id)
    active = await _active_run_id(context.library_root, request.doc_id)
    if active:
        raise ConflictError(
            "document already has an active run", detail=active
        )
    run_id = await ingest.enqueue(context.library_root, request.doc_id)
    return CapabilityResult(
        data=SubmitExtractionOutput(run_id=run_id, doc_id=request.doc_id)
    )


async def reingest_document(
    context: CapabilityContext, request: ReingestDocumentInput
) -> CapabilityResult:
    store = LibraryStore.get(context.library_root)
    document = await asyncio.to_thread(store.load_document, request.doc_id)
    if document is None:
        raise NotFoundError("document not found", detail=request.doc_id)
    active = await _active_run_id(context.library_root, request.doc_id)
    if active:
        raise ConflictError("document already has an active run", detail=active)
    await asyncio.to_thread(store.clear_pipeline_data, request.doc_id)
    run_id = await ingest.enqueue(context.library_root, request.doc_id)
    return CapabilityResult(
        data=ReingestDocumentOutput(run_id=run_id, doc_id=request.doc_id)
    )


async def cancel_run(
    context: CapabilityContext, request: RunActionInput
) -> CapabilityResult:
    result = await ingest.cancel_batch(context.library_root, [request.run_id])
    if result.updated == 0:
        raise NotFoundError("run not found", detail=request.run_id)
    return CapabilityResult(
        data=RunActionOutput(run_id=request.run_id, updated=result.updated)
    )


async def retry_run(
    context: CapabilityContext, request: RunActionInput
) -> CapabilityResult:
    result = await ingest.retry_batch(context.library_root, [request.run_id])
    if result.updated == 0:
        raise NotFoundError("run not found", detail=request.run_id)
    return CapabilityResult(
        data=RunActionOutput(run_id=request.run_id, updated=result.updated)
    )


register(
    Capability(
        name="import_pdf",
        description="Register a PDF already inside the active library directory.",
        input_model=ImportPdfInput,
        output_model=ImportPdfOutput,
        mutating=True,
        handler=import_pdf,
    )
)
register(
    Capability(
        name="submit_extraction",
        description="Submit a registered document to the Extract -> Markdown -> Patent pipeline.",
        input_model=SubmitExtractionInput,
        output_model=SubmitExtractionOutput,
        mutating=True,
        handler=submit_extraction,
    )
)
register(
    Capability(
        name="reingest_document",
        description="Clear pipeline outputs and submit the document again.",
        input_model=ReingestDocumentInput,
        output_model=ReingestDocumentOutput,
        mutating=True,
        handler=reingest_document,
    )
)
register(
    Capability(
        name="cancel_run",
        description="Cancel an active pipeline run.",
        input_model=RunActionInput,
        output_model=RunActionOutput,
        mutating=True,
        handler=cancel_run,
    )
)
register(
    Capability(
        name="retry_run",
        description="Retry failed or cancelled nodes of a pipeline run.",
        input_model=RunActionInput,
        output_model=RunActionOutput,
        mutating=True,
        handler=retry_run,
    )
)
```

- [ ] **Step 2: 在 `__init__.py` 注册 write 模块**

加入：

```python
from . import write as _write  # noqa: F401 — registers write capabilities
```

- [ ] **Step 3: 验证注册表包含读写能力**

Run: `uv run python -c "from mbforge.service.capabilities import all_capabilities; print([(c.name, c.mutating) for c in all_capabilities()])"`
Expected: 12 项；5 项 `mutating=True`。

- [ ] **Step 4: Commit**

```bash
git add src/mbforge/service/capabilities/write.py
git commit -m "feat(capabilities): add mutating capabilities"
```

---

## Task 5: HTTP 适配器

**Files:**
- Create: `src/mbforge/api/http/capabilities.py`

- [ ] **Step 1: 写路由**

```python
"""HTTP adapter for the capability registry.

Read-only calls need no credential. Mutating calls require the library's
capability token in ``X-MBForge-Token``; the registry re-checks this so a new
adapter cannot accidentally bypass the mode guard.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from mbforge.foundation.capability_token import (
    capability_token_path,
    ensure_capability_token,
    verify_capability_token,
)
from mbforge.foundation.layout import resolve_library_root
from mbforge.service.capabilities import (
    CapabilityContext,
    all_capabilities,
    invoke,
)

router = APIRouter()


class CapabilityInfo(BaseModel):
    name: str
    description: str
    mutating: bool
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


class CapabilityManifest(BaseModel):
    success: bool = True
    capabilities: list[CapabilityInfo]
    token_path: str


class CapabilityResponse(BaseModel):
    success: bool = True
    capability: str
    data: dict[str, Any]
    truncated: bool = False
    next_offset: int | None = None


def _context(request: Request) -> CapabilityContext:
    root = str(resolve_library_root(None))
    token = request.headers.get("x-mbforge-token")
    mode = "edit" if verify_capability_token(root, token) else "readonly"
    return CapabilityContext(library_root=root, mode=mode)


def _guide(token_path: str) -> str:
    lines = [
        "# MBForge capabilities",
        "",
        "Base URL: `http://127.0.0.1:18792`",
        "",
        "## Modes",
        "- `readonly`: omit `X-MBForge-Token`. Mutating capabilities return 403.",
        "- `edit`: read the token file and send `X-MBForge-Token`.",
        f"Token file: `{token_path}`",
        "",
        "## Invoke",
        "POST `/api/v1/capabilities/{name}` with a JSON body matching the input schema.",
        "A successful response wraps the result in `data`.",
        "",
    ]
    for capability in all_capabilities():
        mode = "edit" if capability.mutating else "readonly"
        schema = json.dumps(capability.input_model.model_json_schema(), indent=2)
        lines.extend(
            [
                f"### `{capability.name}`",
                "",
                capability.description,
                "",
                f"Mode: `{mode}`",
                "",
                "```json",
                schema,
                "```",
                "",
            ]
        )
    return "\n".join(lines)


@router.get("", response_model=CapabilityManifest)
async def capability_manifest() -> CapabilityManifest:
    root = str(resolve_library_root(None))
    return CapabilityManifest(
        capabilities=[
            CapabilityInfo(
                name=capability.name,
                description=capability.description,
                mutating=capability.mutating,
                input_schema=capability.input_model.model_json_schema(),
                output_schema=capability.output_model.model_json_schema(),
            )
            for capability in all_capabilities()
        ],
        token_path=str(capability_token_path(root)),
    )


@router.get("/guide", response_class=PlainTextResponse)
async def capability_guide() -> str:
    root = str(resolve_library_root(None))
    token_path = capability_token_path(root)
    try:
        ensure_capability_token(root)
    except OSError:
        # A read-only library can still serve the guide; writes will fail.
        pass
    return _guide(str(token_path))


@router.post("/{name}", response_model=CapabilityResponse)
async def capability_invoke(
    name: str,
    payload: dict[str, Any] = Body(...),
    context: CapabilityContext = Depends(_context),
) -> CapabilityResponse:
    result = await invoke(name, context, payload)
    return CapabilityResponse(
        capability=name,
        data=result.data.model_dump(mode="json"),
        truncated=result.truncated,
        next_offset=result.next_offset,
    )
```

- [ ] **Step 2: 手工验证路由顺序**

Run: `uv run python -c "from mbforge.api.http.capabilities import router; print([(r.path, sorted(r.methods or [])) for r in router.routes])"`
Expected: 包含 `('', ['GET'])`、`('/guide', ['GET'])`、`('/{name}', ['POST'])`。

- [ ] **Step 3: Commit**

```bash
git add src/mbforge/api/http/capabilities.py
git commit -m "feat(capabilities): expose HTTP capability adapter"
```

---

## Task 6: 组合根与文档

**Files:**
- Modify: `src/mbforge/server/app.py:347`
- Modify: `src/mbforge/server/app.py:403`
- Modify: `README.md`
- Modify: `TODO/INDEX.md`
- Modify: `docs/wiki/architecture.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: 注册 router**

在 `server/app.py` 的 router import 中加入 `capabilities`：

```python
from mbforge.api.http import agent, capabilities, markush, review
```

在 `agent.router` 注册之后加入：

```python
app.include_router(
    capabilities.router,
    prefix="/api/v1/capabilities",
    tags=["capabilities"],
)
```

- [ ] **Step 2: 更新 `README.md`**

在 Agent/开发章节后加一节：

```markdown
## Capability API

MBForge exposes agent-callable capabilities under `/api/v1/capabilities`.
`GET /api/v1/capabilities` returns the manifest; `GET /api/v1/capabilities/guide`
returns a Markdown guide with input schemas. Read-only calls need no credential.
Mutating calls require `X-MBForge-Token`; the token is created at
`{library_root}/.mbforge/capability-token` and is read by the harness only in
edit mode. Patent extraction is asynchronous: `submit_extraction` returns a
`run_id`, then poll `get_run` and read `get_patent_result`.
```

- [ ] **Step 3: 更新 `TODO/INDEX.md`**

在 Active plans 中加入：

```markdown
- [Capability platform](../docs/plan-capability-platform.md)
```

- [ ] **Step 4: 更新 `docs/wiki/architecture.md`**

在 layer 描述中加入一句：

```markdown
`service/capabilities/` is the single registry of agent-callable tasks; the
HTTP adapter under `api/http/capabilities.py` only authenticates, validates
transport input, and serializes the registry response.
```

- [ ] **Step 5: 更新 `AGENTS.md`**

在 Project Structure 的 `service/` 说明中补充：

```markdown
`service/capabilities/` owns the agent-callable capability registry; adapters
must call `invoke()` and never reimplement mode checks or handlers.
```

- [ ] **Step 6: 验证应用可导入**

Run: `uv run python -c "from mbforge.server.app import app; print(len(app.routes))"`
Expected: 无异常。

- [ ] **Step 7: Commit**

```bash
git add src/mbforge/server/app.py README.md TODO/INDEX.md docs/wiki/architecture.md AGENTS.md
git commit -m "feat(capabilities): wire capability API and document it"
```

---

## Task 7: 契约测试

**Files:**
- Create: `tests/unit/capabilities/test_registry.py`
- Create: `tests/unit/capabilities/test_capability_http.py`

- [ ] **Step 1: 写注册表契约测试**

```python
"""Contract tests for the capability registry."""

from __future__ import annotations

import asyncio

import pytest

from mbforge.foundation.errors import CapabilityForbiddenError
from mbforge.service.capabilities import (
    CapabilityContext,
    all_capabilities,
    invoke,
)


def test_capability_names_are_unique_and_schemas_generate() -> None:
    capabilities = all_capabilities()
    names = [capability.name for capability in capabilities]
    assert len(names) == len(set(names))
    assert {"resolve_document", "submit_extraction", "get_patent_result"} <= set(names)
    for capability in capabilities:
        assert capability.input_model.model_json_schema()
        assert capability.output_model.model_json_schema()


def test_readonly_mode_rejects_mutating_capability() -> None:
    with pytest.raises(CapabilityForbiddenError):
        asyncio.run(
            invoke(
                "submit_extraction",
                CapabilityContext(library_root="/tmp/library", mode="readonly"),
                {"doc_id": "missing"},
            )
        )
```

- [ ] **Step 2: 写 HTTP 鉴权契约测试**

```python
"""HTTP contract tests for capability auth and discovery."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_manifest_lists_read_and_write_capabilities(app_client: TestClient) -> None:
    response = app_client.get("/api/v1/capabilities")
    assert response.status_code == 200
    body = response.json()
    names = {item["name"] for item in body["capabilities"]}
    assert {"resolve_document", "submit_extraction"} <= names
    assert Path(body["token_path"]).parts[-2:] == (".mbforge", "capability-token")


def test_guide_creates_token_file(
    app_client: TestClient, tmp_library: Path
) -> None:
    response = app_client.get("/api/v1/capabilities/guide")
    assert response.status_code == 200
    assert "submit_extraction" in response.text
    assert (tmp_library / ".mbforge" / "capability-token").is_file()


def test_write_capability_requires_edit_token(app_client: TestClient) -> None:
    response = app_client.post(
        "/api/v1/capabilities/submit_extraction",
        json={"doc_id": "missing"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "capability_forbidden"


def test_valid_token_reaches_business_validation(
    app_client: TestClient, tmp_library: Path
) -> None:
    app_client.get("/api/v1/capabilities/guide")
    token = (tmp_library / ".mbforge" / "capability-token").read_text(encoding="utf-8").strip()
    response = app_client.post(
        "/api/v1/capabilities/submit_extraction",
        json={"doc_id": "missing"},
        headers={"x-mbforge-token": token},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


def test_unknown_capability_returns_404(app_client: TestClient) -> None:
    response = app_client.post("/api/v1/capabilities/not_a_capability", json={})
    assert response.status_code == 404
```

- [ ] **Step 3: 跑测试**

Run: `uv run pytest tests/unit/capabilities -q`
Expected: 全部 PASS。

Run: `uv run pytest tests/unit/architecture/test_layer_boundaries.py -q`
Expected: PASS。

- [ ] **Step 4: Commit**

```bash
git add tests/unit/capabilities
git commit -m "test(capabilities): cover manifest and edit-mode guard"
```

---

## Task 8: CLI 优先接入 + 现有 Node agent

CLI 是 v1 的 agent 呈现形式；`server.ts` 保留为前端兼容入口。两者共用同一套能力工具与模型配置，避免 CLI/HTTP 两套会话逻辑。

**Files:**
- Create: `agent/src/capabilities.ts`
- Create: `agent/src/runtime.ts`
- Create: `agent/src/cli.ts`
- Modify: `agent/src/server.ts`
- Modify: `agent/package.json`
- Delete: `agent/src/tool.ts`

- [ ] **Step 1: 写 `agent/src/capabilities.ts`**

```ts
import { readFile } from 'node:fs/promises'

import { Type } from '@mariozechner/pi-ai'
import { defineTool } from '@mariozechner/pi-coding-agent'

interface CapabilityInfo {
  name: string
  description: string
  mutating: boolean
  input_schema: Record<string, unknown>
}

interface CapabilityManifest {
  success: boolean
  capabilities: CapabilityInfo[]
  token_path: string
}

export type AgentMode = 'readonly' | 'edit'

const backendBaseUrl = (): string =>
  process.env.MBFORGE_BACKEND_URL ??
  `http://${process.env.MBFORGE_BACKEND_HOST ?? '127.0.0.1'}:${process.env.MBFORGE_BACKEND_PORT ?? '18792'}`

async function readToken(path: string): Promise<string> {
  return (await readFile(path, 'utf8')).trim()
}

export async function loadCapabilityTools(mode: AgentMode) {
  const response = await fetch(`${backendBaseUrl()}/api/v1/capabilities`)
  if (!response.ok) {
    throw new Error(`capability manifest failed (${response.status})`)
  }
  const manifest = (await response.json()) as CapabilityManifest
  if (!manifest.success || !Array.isArray(manifest.capabilities)) {
    throw new Error('invalid capability manifest')
  }
  const tokenPath = process.env.MBFORGE_CAPABILITY_TOKEN_FILE ?? manifest.token_path

  return manifest.capabilities
    .filter((capability) => mode === 'edit' || !capability.mutating)
    .map((capability) =>
      defineTool({
        name: capability.name,
        label: capability.name,
        description: capability.description,
        parameters: Type.Unsafe<Record<string, unknown>>(capability.input_schema),
        async execute(_toolCallId, params, signal) {
          const headers: Record<string, string> = {
            'content-type': 'application/json',
          }
          if (mode === 'edit' && capability.mutating) {
            headers['x-mbforge-token'] = await readToken(tokenPath)
          }
          const result = await fetch(
            `${backendBaseUrl()}/api/v1/capabilities/${capability.name}`,
            {
              method: 'POST',
              headers,
              body: JSON.stringify(params),
              signal,
            },
          )
          if (!result.ok) {
            const detail = (await result.text()).slice(0, 400)
            throw new Error(`capability ${capability.name} failed (${result.status}): ${detail}`)
          }
          const payload = (await result.json()) as { success?: boolean; data?: unknown }
          if (!payload.success) {
            throw new Error(`capability ${capability.name} returned an error`)
          }
          return {
            content: [{ type: 'text', text: JSON.stringify(payload.data ?? null) }],
            details: payload,
          }
        },
      }),
    )
}
```

- [ ] **Step 2: 写 `agent/src/runtime.ts`**

把 `server.ts` 里的模型配置与会话创建原样迁出，并让 CLI/HTTP 共用：

```ts
import { readFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { join } from 'node:path'

import {
  AuthStorage,
  createAgentSession,
  createExtensionRuntime,
  ModelRegistry,
  type AgentSession,
  type ResourceLoader,
  SessionManager,
  SettingsManager,
} from '@mariozechner/pi-coding-agent'
import type { Api, Model } from '@mariozechner/pi-ai'

import { loadCapabilityTools, type AgentMode } from './capabilities.js'

export interface AgentLlmConfig {
  provider: string
  model: string
  apiKey: string
  baseUrl: string
  maxTokens: number
  requestTimeoutMs: number
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null
    ? (value as Record<string, unknown>)
    : {}
}

function stringValue(value: unknown, fallback: string, maxLength = 512): string {
  if (typeof value !== 'string') return fallback
  const trimmed = value.trim()
  return trimmed.length > 0 && trimmed.length <= maxLength ? trimmed : fallback
}

function numberValue(value: unknown, fallback: number, min: number, max: number): number {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.min(max, Math.max(min, value))
    : fallback
}

function defaultBaseUrl(provider: string): string {
  if (provider === 'deepseek') return 'https://api.deepseek.com/v1'
  if (provider === 'ollama') return 'http://127.0.0.1:11434/v1'
  if (provider === 'anthropic') return 'https://api.anthropic.com'
  return 'https://api.openai.com/v1'
}

async function loadPersistedLlmConfig(): Promise<Record<string, unknown>> {
  const settingsPath =
    process.env.MBFORGE_SETTINGS_PATH ?? join(homedir(), 'MBForge', 'settings.json')
  try {
    const parsed = JSON.parse(await readFile(settingsPath, 'utf8')) as unknown
    return asRecord(asRecord(parsed).llm)
  } catch {
    return {}
  }
}

function mergeConfig(raw: unknown, persisted: Record<string, unknown>): Record<string, unknown> {
  const value = asRecord(raw)
  const merged = { ...persisted }
  for (const [key, candidate] of Object.entries(value)) {
    if (candidate !== '' && candidate !== '***') merged[key] = candidate
  }
  return merged
}

export function readConfig(
  raw: unknown,
  persisted: Record<string, unknown>,
): AgentLlmConfig {
  const value = mergeConfig(raw, persisted)
  const provider = stringValue(
    value.provider ?? process.env.MBFORGE_AGENT_PROVIDER,
    'openai_compatible',
    80,
  ).toLowerCase()
  const apiKey = stringValue(
    value.api_key ?? value.apiKey ?? process.env.MBFORGE_AGENT_API_KEY,
    provider === 'ollama' ? 'ollama' : '',
    4096,
  )
  const model = stringValue(
    value.model ?? process.env.MBFORGE_AGENT_MODEL,
    'gpt-4o-mini',
    256,
  )
  const baseUrl = stringValue(
    value.base_url ?? value.baseUrl ?? process.env.MBFORGE_AGENT_BASE_URL,
    defaultBaseUrl(provider),
    2048,
  ).replace(/\/$/, '')
  const requestTimeoutSeconds = numberValue(
    value.request_timeout ?? process.env.MBFORGE_AGENT_REQUEST_TIMEOUT,
    60,
    1,
    600,
  )

  if (provider !== 'ollama' && !apiKey) {
    throw new Error('An API key is required for the configured LLM provider')
  }

  return {
    provider,
    model,
    apiKey,
    baseUrl,
    maxTokens: Math.round(
      numberValue(value.max_tokens ?? value.maxTokens, 4096, 256, 32768),
    ),
    requestTimeoutMs: Math.round(requestTimeoutSeconds * 1000),
  }
}

export async function readPersistedConfig(raw: unknown): Promise<AgentLlmConfig> {
  return readConfig(raw, await loadPersistedLlmConfig())
}

function createConfiguredModel(config: AgentLlmConfig): {
  authStorage: AuthStorage
  modelRegistry: ModelRegistry
  model: Model<Api>
} {
  const authStorage = AuthStorage.inMemory()
  const modelRegistry = ModelRegistry.inMemory(authStorage)
  const api: Api = config.provider === 'anthropic' ? 'anthropic-messages' : 'openai-completions'
  const providerName = `mbforge-${config.provider}`

  modelRegistry.registerProvider(providerName, {
    name: config.provider,
    api,
    baseUrl: config.baseUrl,
    apiKey: config.apiKey,
    authHeader: api === 'openai-completions',
    models: [
      {
        id: config.model,
        name: config.model,
        api,
        reasoning: false,
        input: ['text'],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 131072,
        maxTokens: config.maxTokens,
        compat:
          api === 'openai-completions'
            ? {
                supportsStore: false,
                supportsDeveloperRole: false,
                supportsReasoningEffort: false,
                supportsUsageInStreaming: false,
                maxTokensField: 'max_tokens',
              }
            : undefined,
      },
    ],
  })

  const model = modelRegistry.find(providerName, config.model)
  if (!model) throw new Error('Could not register the configured LLM model')
  return { authStorage, modelRegistry, model }
}

export async function createSession(
  config: AgentLlmConfig,
  mode: AgentMode,
): Promise<AgentSession> {
  const { authStorage, modelRegistry, model } = createConfiguredModel(config)
  const settingsManager = SettingsManager.inMemory({
    compaction: { enabled: false },
    retry: {
      enabled: false,
      provider: { timeoutMs: config.requestTimeoutMs, maxRetries: 0 },
    },
    defaultThinkingLevel: 'off',
  })
  const capabilityTools = await loadCapabilityTools(mode)
  const resourceLoader: ResourceLoader = {
    getExtensions: () => ({ extensions: [], errors: [], runtime: createExtensionRuntime() }),
    getSkills: () => ({ skills: [], diagnostics: [] }),
    getPrompts: () => ({ prompts: [], diagnostics: [] }),
    getThemes: () => ({ themes: [], diagnostics: [] }),
    getAgentsFiles: () => ({ agentsFiles: [] }),
    getSystemPrompt: () =>
      'You are the MBForge molecular-science assistant. ' +
      `You are in ${mode} mode. ` +
      (mode === 'edit'
        ? 'Mutating capabilities are available; use them only when the task requires changing library state. '
        : 'Only read-only capabilities are available; never attempt to change library state. ') +
      'Search the library before making claims. Separate source-backed facts from hypotheses, ' +
      'cite returned identifiers, and never claim a search result is a validated design recommendation.',
    getAppendSystemPrompt: () => [],
    extendResources: () => {},
    reload: async () => {},
  }

  const { session } = await createAgentSession({
    model,
    thinkingLevel: 'off',
    authStorage,
    modelRegistry,
    settingsManager,
    resourceLoader,
    sessionManager: SessionManager.inMemory(),
    tools: capabilityTools.map((tool) => tool.name),
    customTools: capabilityTools,
  })
  if (!session.getAllTools().some((tool) => tool.name === 'resolve_document')) {
    session.dispose()
    throw new Error('MBForge capability tools were not registered')
  }
  return session
}
```

- [ ] **Step 3: 写 `agent/src/cli.ts`**

```ts
import { stdin as input, stdout as output } from 'node:process'
import { createInterface } from 'node:readline/promises'

import type { AgentSession } from '@mariozechner/pi-coding-agent'

import type { AgentMode } from './capabilities.js'
import { createSession, readPersistedConfig } from './runtime.js'

interface CliArgs {
  mode: AgentMode
  prompt?: string
  tokenFile?: string
}

function usage(): string {
  return [
    'Usage: mbforge-agent [--mode readonly|edit] [--prompt <text>] [--token-file <path>]',
    '',
    '  --mode        readonly (default) or edit; edit enables mutating capabilities',
    '  --prompt, -p  run one prompt and exit',
    '  --token-file  capability token path (default: manifest token_path)',
  ].join('\n')
}

function parseArgs(argv: string[]): CliArgs {
  let mode: AgentMode =
    process.env.MBFORGE_AGENT_MODE === 'edit' ? 'edit' : 'readonly'
  let prompt: string | undefined
  let tokenFile = process.env.MBFORGE_CAPABILITY_TOKEN_FILE

  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index]
    if (argument === '--mode') {
      const value = argv[++index]
      if (value !== 'readonly' && value !== 'edit') {
        throw new Error('--mode must be readonly or edit')
      }
      mode = value
    } else if (argument === '--prompt' || argument === '-p') {
      prompt = argv[++index]
    } else if (argument === '--token-file') {
      tokenFile = argv[++index]
    } else if (argument === '--help' || argument === '-h') {
      console.log(usage())
      process.exit(0)
    } else {
      throw new Error(`unknown argument: ${argument}`)
    }
  }

  if (tokenFile) process.env.MBFORGE_CAPABILITY_TOKEN_FILE = tokenFile
  return { mode, prompt, tokenFile }
}

async function promptOnce(session: AgentSession, message: string): Promise<void> {
  const unsubscribe = session.subscribe((event) => {
    if (event.type === 'message_update' && event.assistantMessageEvent.type === 'text_delta') {
      process.stdout.write(event.assistantMessageEvent.delta)
    } else if (event.type === 'tool_execution_start') {
      process.stderr.write(`\n[tool] ${event.toolName} start\n`)
    } else if (event.type === 'tool_execution_end') {
      process.stderr.write(`[tool] ${event.toolName} ${event.isError ? 'error' : 'done'}\n`)
    }
  })
  try {
    await session.prompt(message, { expandPromptTemplates: false })
  } finally {
    unsubscribe()
    process.stdout.write('\n')
  }
  const error = session.agent.state.errorMessage
  if (error) throw new Error(error)
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2))
  const config = await readPersistedConfig({})
  const session = await createSession(config, args.mode)
  let readline: ReturnType<typeof createInterface> | undefined

  process.on('SIGINT', () => {
    if (session.isStreaming) {
      void session.abort()
      return
    }
    session.dispose()
    process.exit(0)
  })

  try {
    if (args.prompt) {
      await promptOnce(session, args.prompt)
      return
    }

    readline = createInterface({ input, output })
    console.log(`MBForge agent (${args.mode}). /exit to quit.`)
    for (;;) {
      const line = (await readline.question('mbforge> ')).trim()
      if (!line) continue
      if (line === '/exit' || line === '/quit') break
      if (line === '/mode') {
        console.log(args.mode)
        continue
      }
      try {
        await promptOnce(session, line)
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error)
        console.error(`error: ${detail}`)
      }
    }
  } finally {
    readline?.close()
    session.dispose()
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error))
  process.exitCode = 1
})
```

- [ ] **Step 4: 更新 `agent/package.json` scripts**

```json
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "check": "tsc -p tsconfig.json --noEmit",
    "start": "node dist/server.js",
    "cli": "node dist/cli.js",
    "dev:cli": "npm run build && npm run cli"
  }
```

- [ ] **Step 5: 修改 `agent/src/server.ts`**

删除：

```ts
import { moleculeSearchTool } from './tool.js'
```

把模型配置与会话创建函数从 `server.ts` 删除（`AgentLlmConfig`、`asRecord`、`stringValue`、`numberValue`、`defaultBaseUrl`、`loadPersistedLlmConfig`、`mergeConfig`、`readConfig`、`createConfiguredModel`、`createSession`），改为：

```ts
import { createSession, readPersistedConfig, type AgentLlmConfig } from './runtime.js'
```

`getSession` 中创建会话改为：

```ts
async function getSession(sessionId: string, config: AgentLlmConfig): Promise<SessionEntry> {
  const signature = JSON.stringify(config)
  const existing = sessions.get(sessionId)
  if (existing && existing.signature === signature) return existing
  existing?.session.dispose()

  const mode = process.env.MBFORGE_AGENT_MODE === 'edit' ? 'edit' : 'readonly'
  const session = await createSession(config, mode)
  const entry: SessionEntry = { config, signature, session, tail: Promise.resolve() }
  sessions.set(sessionId, entry)
  while (sessions.size > maxSessions) {
    const oldest = sessions.keys().next().value
    if (!oldest) break
    const evicted = sessions.get(oldest)
    evicted?.session.dispose()
    sessions.delete(oldest)
  }
  return entry
}
```

`handleChat` 中读取配置改为：

```ts
const config = await readPersistedConfig(input.config ?? existing?.config)
```

同时删除 `server.ts` 中不再使用的 imports：`readFile`、`homedir`、`join`、`AuthStorage`、`createAgentSession`、`createExtensionRuntime`、`ModelRegistry`、`ResourceLoader`、`SettingsManager`、`Api`、`Model`。

删除 `agent/src/tool.ts`。

- [ ] **Step 6: 确认检查位置**

工具存在性检查只保留在 `runtime.ts` 的 `createSession` 内；`server.ts` 不再保留自己的 `createSession` 或 `getAllTools` 检查。搜索确认：

Run: `rg -n "getAllTools|molecule_search" agent/src`
Expected: 只命中 `runtime.ts` 的 `resolve_document` 检查；无 `molecule_search`。

- [ ] **Step 7: 构建与类型检查**

Run: `npm --prefix agent run build`
Expected: PASS。

Run: `npm --prefix agent run check`
Expected: PASS。

- [ ] **Step 8: CLI smoke**

先启动后端（`uv run python -m mbforge --no-browser`），再执行：

```bash
curl -s http://127.0.0.1:18792/api/v1/capabilities/guide >/dev/null
npm --prefix agent run build
node agent/dist/cli.js --mode readonly --prompt "Find a document named sample.pdf and report its status."
```

Expected: stdout 输出流式回答；stderr 出现 `[tool] resolve_document start/done` 或 `get_document`；进程正常退出。只读模式下写能力不会出现在工具列表。

再验证 edit 模式：

```bash
node agent/dist/cli.js --mode edit --token-file library/.mbforge/capability-token --prompt "List the first 3 documents."
```

Expected: 能成功调用只读能力；令牌被读取时不打印明文。

- [ ] **Step 9: HTTP 手工 smoke**

Run:

```bash
npm --prefix frontend run dev:all
```

然后打开 Agent 页面，发送：

```text
Find a document named sample.pdf and tell me whether its patent facts are ready.
```

Expected: 工具调用日志出现 `resolve_document`（或 `get_document`），回答引用返回的 `doc_id`/`status`；不应再出现 `molecule_search`。

- [ ] **Step 10: Commit**

```bash
git add agent/src/capabilities.ts agent/src/runtime.ts agent/src/cli.ts agent/src/server.ts agent/package.json
git rm agent/src/tool.ts
git commit -m "feat(agent): add CLI-first capability client"
```

---

## Task 9: 最终验证

**Files:** 无

- [ ] **Step 1: 后端静态检查**

Run: `uv run ruff check src tests`
Expected: PASS。

Run: `uv run ruff format src tests --check`
Expected: PASS。

Run: `uv run python -m compileall -q src/mbforge`
Expected: PASS。

- [ ] **Step 2: 目标测试**

Run: `uv run pytest tests/unit/capabilities tests/unit/architecture/test_layer_boundaries.py -q`
Expected: 全部 PASS。

- [ ] **Step 3: 手工 capability smoke**

启动后端（`uv run python -m mbforge --no-browser`）后执行：

```bash
curl -s http://127.0.0.1:18792/api/v1/capabilities
curl -s http://127.0.0.1:18792/api/v1/capabilities/guide
curl -s -X POST http://127.0.0.1:18792/api/v1/capabilities/submit_extraction \
  -H 'content-type: application/json' \
  -d '{"doc_id":"missing"}'
```

Expected:

- manifest 含 12 个能力；
- guide 含 token 路径与输入 schema；
- 无 token 的写调用返回 403 `capability_forbidden`。

- [ ] **Step 4: 带 token 的写调用 smoke**

```bash
TOKEN=$(cat library/.mbforge/capability-token)
curl -s -X POST http://127.0.0.1:18792/api/v1/capabilities/submit_extraction \
  -H "content-type: application/json" \
  -H "x-mbforge-token: $TOKEN" \
  -d '{"doc_id":"missing"}'
```

Expected: 404 `not_found`（说明已通过模式校验，进入业务校验）。

- [ ] **Step 5: 报告**

记录：

- 实际执行的命令与结果；
- 未验证项（例如没有可用真实 PDF 时，`import_pdf`/`submit_extraction` 的成功路径只做了类型与鉴权验证）；
- 与计划的偏差。

---

## 自查记录

- **Spec coverage:** 12 个 v1 能力全部有对应 handler；manifest/guide/token/readonly/edit/异步 run 语义均有任务覆盖。
- **Placeholder scan:** 无 TBD/TODO；每个代码步骤给出完整实现。
- **Type consistency:** `CapabilityContext`/`CapabilityResult`/`CapabilityResponse` 名称在注册表、适配器、测试中一致；`submit_extraction` 返回 `run_id`，`get_run` 以 `run_id` 查询。
- **Scope check:** 单一能力平台，不含 MCP、删除能力或 pipeline 内部阶段工具化。
```
