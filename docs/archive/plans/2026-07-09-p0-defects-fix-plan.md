# P0 缺陷修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复缺陷报告中的 3 个 P0 问题：`tsconfig.json` 非法配置、`server.py` 模型预热缺失、19 个 FastAPI routers 无冒烟测试。

**Architecture:** 前端只做单行配置删除；后端在 `server.py` 中实现 `_prewarm()`，并在 `app.py` 主应用 `lifespan` 中后台调用它（因为 Starlette mount 不会触发子应用 lifespan）；测试层使用 `fastapi.testclient.TestClient` 覆盖主应用 19 个 `include_router` 与挂载的 model_server，每个 router 至少断言 1 条成功路径与 1 条错误路径。

**Tech Stack:** Python 3.11+, FastAPI, pytest, fastapi.testclient.TestClient, TypeScript/Vite, ruff.

## Global Constraints

- 使用 `uv run` 执行 Python 命令，使用 `npm --prefix frontend` 执行前端命令。
- 不修改现有 API 契约；所有改动必须向后兼容。
- 模型预热异常必须被捕获，不能阻塞服务启动。
- 测试不能写入真实用户 `settings.json`（已有 `conftest.py` 的 `_isolate_global_state` fixture 保障）。
- 冒烟测试不依赖真实模型/外部网络；需要模型或外部服务的 endpoint 只验证路由可达性或错误路径。
- 每个子任务独立 commit，便于单独 revert。

---

## Task 0: 提交当前工作进度作为 checkpoint

**Files:**
- Modify: `.gitignore`（可选，若决定排除 `.kimi-code/` 和 `.agents/skills/caveman/`）
- 操作: 所有已修改/未跟踪的项目文件

**Interfaces:**
- Consumes: 当前 git working tree 的未提交改动。
- Produces: 一个干净的、可作为 rollback 基线的 commit。

- [ ] **Step 1: 检查工作区状态**

Run: `git status --short`
Expected: 看到 `M`、`D`、`??` 等未提交改动。

- [ ] **Step 2: 排除本地工具状态目录（如需要）**

如果 `.kimi-code/` 和 `.agents/skills/caveman/` 不应进入仓库，在 `.gitignore` 追加：

```gitignore
# Local plugin/tool state
.kimi-code/
.agents/skills/caveman/
```

Run: `git add .gitignore && git commit -m "chore(git): ignore local plugin state"`
Expected: `.gitignore` 提交成功。

- [ ] **Step 3: 添加所有项目相关改动并提交**

Run:
```bash
git add AGENTS.md CLAUDE.md uv.lock

git add src/ tests/ frontend/ docs/ 2>/dev/null || true

git add --ignore-errors \
  src/mbforge/backends/ocr/rapidocr_adapter.py \
  src/mbforge/pipeline/organizer.py \
  src/mbforge/routers/legacy_models.py \
  frontend/src/components/settings/PageindexLlmSection.tsx \
  test_pipeline_lib/ \
  tests/unit/pipeline/test_extract_text.py \
  tests/unit/pipeline/test_organizer.py \
  tests/unit/test_coref_ocr_integration.py \
  tests/unit/test_openkb_adapter.py \
  tests/unit/test_rapidocr_adapter.py \
  tests/test_logger_closed_stdout.py

git commit -m "checkpoint: save work-in-progress before P0 defect fixes

- Preserve refactor progress on main branch
- P0 fixes will start from this clean baseline"
```
Expected: `git status --short` 只剩本地工具目录（若已忽略则为空）。

---

## Task 1: 修复 `frontend/tsconfig.json` 的 `"noCheck"`

**Files:**
- Modify: `frontend/tsconfig.json:13`

**Interfaces:**
- Consumes: TypeScript 编译器配置。
- Produces: 合法的 `tsconfig.json`，`npx tsc --noEmit` 通过。

- [ ] **Step 1: 删除非法配置行**

```json
// frontend/tsconfig.json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals", "vite/client"],
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["src"]
}
```

- [ ] **Step 2: 类型检查验证**

Run: `cd frontend && npx tsc --noEmit`
Expected: 命令退出码 0（无新增类型错误；允许既有 baseline 失败，但本次只关注不引入新错误）。

- [ ] **Step 3: Commit**

Run:
```bash
git add frontend/tsconfig.json
git commit -m "fix(frontend): remove invalid noCheck from tsconfig.json

- noCheck is not a standard TS compiler option
- skipLibCheck is already enabled"
```
Expected: commit 成功。

---

## Task 2: 在 `server.py` 实现模型后台预热

**Files:**
- Modify: `src/mbforge/server.py:46-47`
- Modify: `src/mbforge/app.py:33-55`
- Create: `tests/unit/test_server_prewarm.py`

**Interfaces:**
- Consumes: `mbforge.backends.moldet_v2_ft.get_moldet_ft()` 和 `mbforge.backends.molscribe.load`。
- Produces: `_prewarm()` 在 `server.py` 中实现，并在 `app.py` 主应用 `lifespan` 中后台调用；失败被捕获并记录 warning。

- [ ] **Step 1: 实现 `_prewarm()`**

Replace:
```python
def _prewarm() -> None:
    pass  # MolDet/MolScribe are lazy-loaded on first use
```

With:
```python
def _prewarm() -> None:
    """Prewarm local model backends in the background.

    Runs inside lifespan via loop.run_in_executor so startup is not blocked.
    Failures are logged as warnings and do not prevent the app from starting.
    """
    try:
        logger.info("Prewarming MolDet...")
        from .backends.moldet_v2_ft import get_moldet_ft

        get_moldet_ft()
    except Exception as e:
        logger.warning("MolDet prewarm failed (non-fatal): %s", e)

    try:
        logger.info("Prewarming MolScribe...")
        from .backends.molscribe import load as load_molscribe

        load_molscribe()
    except Exception as e:
        logger.warning("MolScribe prewarm failed (non-fatal): %s", e)

    logger.info("Model prewarm complete")
```

- [ ] **Step 2: 在 `app.py` lifespan 中调用 `_prewarm()`**

Because `server.py` is mounted under `/api/v1/models`, Starlette does not run its lifespan when the main app starts. Add the prewarm call to the main app's lifespan.

In `src/mbforge/app.py`, locate the `lifespan` function and change:

```python
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, check_environment)
    try:
        yield
```

To:

```python
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, check_environment)
    # Prewarm local models in the background; failures are non-fatal.
    from .server import _prewarm

    loop.run_in_executor(None, _prewarm)
    try:
        yield
```

- [ ] **Step 3: 编写单元测试**

Create `tests/unit/test_server_prewarm.py`:

```python
"""Tests for server.py model prewarm."""

from unittest.mock import patch

from mbforge.server import _prewarm


class TestPrewarm:
    def test_prewarm_calls_moldet_and_molscribe(self):
        with (
            patch("mbforge.server.get_moldet_ft") as mock_moldet,
            patch("mbforge.server.load_molscribe") as mock_molscribe,
        ):
            _prewarm()

        mock_moldet.assert_called_once()
        mock_molscribe.assert_called_once()

    def test_prewarm_continues_after_moldet_failure(self):
        with (
            patch("mbforge.server.get_moldet_ft") as mock_moldet,
            patch("mbforge.server.load_molscribe") as mock_molscribe,
        ):
            mock_moldet.side_effect = RuntimeError("model not found")
            _prewarm()

        mock_moldet.assert_called_once()
        mock_molscribe.assert_called_once()

    def test_prewarm_continues_after_molscribe_failure(self):
        with (
            patch("mbforge.server.get_moldet_ft") as mock_moldet,
            patch("mbforge.server.load_molscribe") as mock_molscribe,
        ):
            mock_molscribe.side_effect = RuntimeError("model not found")
            _prewarm()

        mock_moldet.assert_called_once()
        mock_molscribe.assert_called_once()
```

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/unit/test_server_prewarm.py -v`
Expected: 3 tests PASSED.

- [ ] **Step 5: Commit**

Run:
```bash
git add src/mbforge/server.py src/mbforge/app.py tests/unit/test_server_prewarm.py
git commit -m "feat(server): background prewarm for MolDet and MolScribe

- _prewarm triggers lazy model loading in lifespan executor
- app.py lifespan calls _prewarm because mounted server.py lifespan is not run
- Failures are non-fatal and logged as warnings"
```
Expected: commit 成功。

---

## Task 3: 扩展路由冒烟测试覆盖全部 19 routers + model_server

**Files:**
- Modify: `tests/unit/test_routers_smoke.py`

**Interfaces:**
- Consumes: `mbforge.app.create_app()` 返回的 FastAPI app（含 19 个 include_router + model_server mount）。
- Produces: 每个 router 至少 1 条成功 + 1 条错误路径的冒烟测试。

- [ ] **Step 1: 在现有文件末尾追加缺失 router 的测试类**

Append to `tests/unit/test_routers_smoke.py`:

```python
class TestDocumentsEndpoints:
    def test_doc_list_empty(self, tmp_path):
        c = _client()
        r = c.post("/api/v1/documents/list", json={"library_root": str(tmp_path)})
        assert r.status_code == 200
        assert r.json().get("success") is True
        assert r.json()["documents"] == []

    def test_doc_delete_missing_doc_id(self, tmp_path):
        c = _client()
        r = c.post("/api/v1/documents/delete", json={"library_root": str(tmp_path)})
        assert r.status_code == 200
        assert r.json().get("success") is False


class TestCorefEndpoints:
    def test_figure_labels_missing_params(self):
        c = _client()
        r = c.post("/api/v1/coref/figure-labels", json={})
        assert r.status_code == 422

    def test_predictions_missing_params(self):
        c = _client()
        r = c.post("/api/v1/coref/predictions", json={})
        assert r.status_code == 422


class TestSarEndpoints:
    def test_find_scaffold(self):
        c = _client()
        r = c.post("/api/v1/sar/find-scaffold", json={"smiles": "CCO"})
        assert r.status_code == 200

    def test_decompose_missing_smiles(self):
        c = _client()
        r = c.post("/api/v1/sar/decompose", json={})
        assert r.status_code == 200


class TestOcrEndpoints:
    def test_chain_status(self):
        c = _client()
        r = c.get("/api/v1/ocr/chain-status")
        assert r.status_code == 200
        assert "backends" in r.json()

    def test_uniparser_stub(self):
        c = _client()
        r = c.post("/api/v1/ocr/test-uniparser", json={})
        assert r.status_code == 200
        assert r.json()["ok"] is False


class TestPdfEndpoints:
    def test_classify_pdf(self):
        c = _client()
        r = c.post("/api/v1/pdf/classify", json={"path": ""})
        assert r.status_code == 200
        assert "pdf_type" in r.json()

    def test_inspect_pdf_missing_body(self):
        c = _client()
        r = c.post("/api/v1/pdf/inspect", json={})
        assert r.status_code == 200


class TestEventsEndpoints:
    def test_stream_route_registered(self):
        app = create_app()
        paths = {route.path for route in app.routes}
        assert "/api/v1/events/stream" in paths


class TestMoldetApiEndpoints:
    def test_coref_ft_missing_image(self):
        c = _client()
        r = c.post("/api/v1/moldet/coref_ft", json={})
        assert r.status_code == 422

    def test_extract_pdf_page_missing_path(self):
        c = _client()
        r = c.post("/api/v1/moldet/extract-pdf-page", json={})
        assert r.status_code == 422

    def test_removed_endpoint_returns_gone(self):
        c = _client()
        r = c.post("/api/v1/moldet/detect-page", json={})
        assert r.status_code == 410


class TestModelServerEndpoints:
    def test_models_health(self):
        c = _client()
        r = c.get("/api/v1/models/health")
        assert r.status_code == 200

    def test_models_environment_check(self):
        c = _client()
        r = c.get("/api/v1/models/environment/check")
        assert r.status_code == 200

    def test_models_test_missing_model_id(self):
        c = _client()
        r = c.post("/api/v1/models/test", json={})
        assert r.status_code == 200
        assert r.json().get("success") is False

    def test_models_render_missing_smiles(self):
        c = _client()
        r = c.post("/api/v1/models/mol/render", json={})
        assert r.status_code == 200
        assert r.json().get("success") is False
```

- [ ] **Step 2: 运行冒烟测试**

Run: `uv run pytest tests/unit/test_routers_smoke.py -v`
Expected: 所有新增与既有测试通过；若有既有失败，记录并与本次新增失败区分。

- [ ] **Step 3: 运行全量单元测试回归**

Run: `uv run pytest tests/unit/ -q`
Expected: 无新增失败（允许 pre-existing 失败保持原状）。

- [ ] **Step 4: Commit**

Run:
```bash
git add tests/unit/test_routers_smoke.py
git commit -m "test(routers): smoke tests for all 19 routers + model_server

- Add coverage for documents, coref, sar, ocr, pdf, events, moldet_api
- Add model_server health/env/test/render smoke tests
- Each router has at least one success and one error path"
```
Expected: commit 成功。

---

## Task 4: 最终验证

**Files:**
- 无新文件；验证既有改动。

**Interfaces:**
- Consumes: Task 1-3 的改动。
- Produces: 通过前端类型检查、Python 单元测试、Ruff 检查的 P0 基线。

- [ ] **Step 1: 前端类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 退出码 0。

- [ ] **Step 2: Python 冒烟测试 + 新增测试**

Run: `uv run pytest tests/unit/test_server_prewarm.py tests/unit/test_routers_smoke.py -v`
Expected: 全部通过。

- [ ] **Step 3: Ruff 检查（确保本次文件无新增 lint）**

Run: `uv run ruff check src/mbforge/server.py tests/unit/test_server_prewarm.py tests/unit/test_routers_smoke.py`
Expected: 无新增错误（允许既有 baseline 失败）。

- [ ] **Step 4: 全量测试回归（可选，用于记录 baseline）**

Run: `uv run pytest tests/ -q`
Expected: 记录通过/跳过/失败数量；确认无新增失败。

- [ ] **Step 5: 汇总报告 commit（可选）**

如果验证后有文档/进度需要更新：

```bash
git add docs/superpowers/plans/2026-07-09-p0-defects-fix-plan.md docs/superpowers/specs/2026-07-09-p0-defects-fix-design.md
git commit -m "docs(plan): mark P0 implementation plan complete

- tsconfig fixed
- server prewarm implemented
- router smoke tests expanded"
```

---

## Rollback Commands

| 场景 | 命令 |
|---|---|
| tsconfig 改错 | `git revert <tsconfig-fix-commit-sha>` |
| prewarm 导致启动问题 | `git revert <prewarm-commit-sha>` 或临时把 `_prewarm()` 改回 `pass` |
| 冒烟测试引入失败 | `git revert <router-tests-commit-sha>`，修复后重新 cherry-pick |
| 需要回滚到 checkpoint | `git reset --hard <checkpoint-commit-sha>`（会丢失 checkpoint 后的工作，慎用） |

---

## P1–P3 Roadmap（仅记录，本次不执行）

- **P1（7/16–8/9）**: Ruff lint 清零、SSE 重连、API key 脱敏、`resource_manager` 中 `nvidia-smi` 异步化。
- **P2（8/9–8/30）**: 文档-代码同步、`AppState` 全局状态重构、依赖版本收紧、OpenKB 性能基准。
- **P3（Q3）**: 前端打包体积优化、死代码清理、国际化准备。
