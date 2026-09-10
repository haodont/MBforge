# P0 缺陷修复设计文档

> **日期**: 2026-07-09  
> **来源**: `docs/analysis/project-defects-analysis-2026-07-09.md`  
> **范围**: 只执行 P0（本周止血），同时为 P1–P3 制定 roadmap。

---

## Goal

修复缺陷报告中的 3 个 P0 问题，使项目进入可持续迭代状态：

1. 删除 `frontend/tsconfig.json` 中非法的 `"noCheck": true`。
2. 在 `src/mbforge/server.py` 中实现后台异步模型预热。
3. 为 19 个 FastAPI routers 补齐冒烟测试。

---

## Background

- `tsconfig.json` 存在 `"noCheck": true`，这不是 TypeScript 编译器标准选项，导致配置意图不明、ESLint 报警。
- `server.py:_prewarm()` 是空函数，MolDet/MolScribe 首次请求时才加载，用户上传 PDF 后等待 5–30s 无反馈。
- 133 个 Python 文件只有 28 个测试，19 个 routers 无集成测试，回归风险高。

---

## Scope

### 本次执行（P0）

| # | 任务 | 文件 | 验证方式 |
|---|---|---|---|
| 1 | 修复 tsconfig 配置 | `frontend/tsconfig.json` | `cd frontend && npx tsc --noEmit` |
| 2 | 实现模型预热 | `src/mbforge/server.py:_prewarm()` + `src/mbforge/app.py:lifespan` | `uv run pytest tests/unit/test_server_prewarm.py -v` |
| 3 | 路由冒烟测试 | `tests/unit/test_routers_smoke.py` | `uv run pytest tests/unit/test_routers_smoke.py -v` |

### 不执行（仅规划）

P1–P3 的问题见文末 roadmap，本次不改：Ruff lint、SSE 重连、API key 脱敏、`nvidia-smi` 异步化、文档同步、全局状态重构、依赖版本收紧、性能基准、前端打包优化。

---

## Design

### 1. tsconfig.json 配置修复

**改动**: 删除 `"noCheck": true` 这一行。

**保留**: 已有 `"skipLibCheck": true` 继续生效，用于跳过 `node_modules` 类型检查。

**效果**: `npx tsc --noEmit` 仍通过，配置合法，ESLint 不再报警。

---

### 2. 模型预热

**位置**: `src/mbforge/server.py:_prewarm()` 实现，并在 `src/mbforge/app.py:lifespan` 中调用。

**策略**:

- `_prewarm()` 定义在 `server.py`，供独立启动 model server 时使用。
- 由于 `server.py` 以 `Mount("/api/v1/models", model_server)` 挂载到主应用，Starlette 不会触发子应用 lifespan，因此主应用 `app.py:lifespan` 中也通过 `loop.run_in_executor(None, _prewarm)` 后台调用它。
- 依次触发 MolDetv2FT 和 MolScribe 的懒加载，使它们在第一次真实请求前完成初始化。
- 所有异常只记录 warning，不抛错，避免模型缺失时服务无法启动。

**伪代码**:

```python
def _prewarm() -> None:
    """Prewarm local model backends in the background."""
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
```

**验证**:

- 单元测试：mock `get_moldet_ft` 和 `load_molscribe`，断言 `_prewarm` 依次调用二者，且第二个调用在第一个失败后仍执行。
- 集成验证：启动 server，日志中出现 `Prewarming ...`，首次 `/api/v1/moldet/*` 请求响应时间显著降低。

---

### 3. 路由冒烟测试

**测试入口**: `tests/unit/test_routers_smoke.py`。

**覆盖对象**:

- 主应用 `app.py:create_app()` 中的 18 个 `include_router`。
- 挂载的 `server.py` model_server（`/api/v1/models/*`）。

**每个 router 的最小断言**:

- 至少一条 `200 OK` 路径（GET 健康/列表/配置等无副作用 endpoint）。
- 至少一条 `404 Not Found` 或 `422 Unprocessable Entity` 错误路径。

**依赖处理**:

- 需要 library_root 的路由：使用 `tmp_path` 创建临时项目目录，通过依赖注入或 monkeypatch `load_global_config` 指向临时目录。
- 需要模型负载的 endpoint：仅验证路由可达性（返回 200/422/500 均可），不验证模型结果正确性。
- 真实外部服务（OCR cloud、LLM）全部 mock 或跳过。

**工具**:

- `fastapi.testclient.TestClient` 同步客户端。
- 不启动真实 uvicorn，保持测试快速稳定。

---

## Testing Strategy

- **单元测试**: `test_server_prewarm.py` + 扩展后的 `test_routers_smoke.py`。
- **类型检查**: `cd frontend && npx tsc --noEmit`。
- **Python 测试**: `uv run pytest tests/unit/test_server_prewarm.py tests/unit/test_routers_smoke.py -v`。
- **回归**: 执行 `uv run pytest tests/ -q` 和 `cd frontend && npm run test`（或 `npx vitest run`），确认不引入新的失败。

---

## Rollback & Risk

| 改动 | 风险 | 回滚方式 |
|---|---|---|
| 删除 `noCheck` | 低；`skipLibCheck` 保留 | Revert 该 commit |
| `_prewarm` 实现 | 低；异常被捕获，不阻塞启动 | Revert 该 commit |
| 新增冒烟测试 | 中；可能暴露已有隐藏错误 | 单独 revert test commit，修复后再合并 |

---

## Roadmap（P1–P3）

| 阶段 | 时间 | 内容 |
|---|---|---|
| P1 | 7/16–8/9 | Ruff lint 清零、SSE 重连、API key 脱敏、`resource_manager` 中 `nvidia-smi` 异步化 |
| P2 | 8/9–8/30 | 文档-代码同步、全局状态 `AppState` 重构、依赖版本收紧、OpenKB 性能基准 |
| P3 | Q3 | 前端打包体积优化、死代码清理、国际化准备 |

---

## Decision Log

1. **范围**: 只执行 P0，P1–P3 出 roadmap 但不改代码。
2. **预热位置**: `_prewarm()` 实现在 `server.py`；主应用 `app.py:lifespan` 也调用它，因为挂载的子应用 lifespan 不会自动执行。
3. **冒烟测试范围**: 主应用 18 routers + model_server mount，每个 router 至少 1 条成功 + 1 条错误路径。
4. **脏工作区**: 执行 P0 前先 commit 当前所有工作进度作为 checkpoint。
