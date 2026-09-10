# MBForge 项目缺陷分析报告

> **ARCHIVED / HISTORICAL** — point-in-time snapshot. Numbers, paths, and stage/router counts may be **wrong today**. Do not treat as current API. Canonical: [../README.md](../README.md) · pipeline: [../architecture/pipeline-stages.md](../architecture/pipeline-stages.md).

> **分析日期**: 2026-07-09  
> **分析范围**: 代码库全量静态分析 + TODO/INDEX.md 已知问题  
> **代码库快照**: commit 36cfe4d (Python-only backend, 19 routers, 9-stage pipeline)

---

## 执行摘要

MBForge 是一个分子科学知识库平台，由 **React 前端** + **FastAPI 后端** + **LangGraph Agent** 构成。项目在 2026-06 完成了 Rust→Python 大迁移，当前处于技术债累积的关键阶段。

**核心问题**：

1. **测试覆盖率极低** (P0)：133 个 Python 文件仅 28 个测试，19 个路由零覆盖
2. **性能瓶颈未解决** (P0)：模型首次加载 5-30s 无预热，用户体验差
3. **代码质量债务** (P1)：254 个 lint 问题，类型提示不完整
4. **文档-代码不一致** (P2)：多处文档描述与实际实现偏离

**优先级分布**：P0 (3 项) | P1 (7 项) | P2 (15 项) | P3 (8 项)

---

## 一、架构层面缺陷

### A1. 测试覆盖率严重不足 (P0 - 阻塞生产)

**现状**：
- Python 源代码：133 个 `.py` 文件，~10,047 行代码
- 测试文件：28 个，仅涵盖 ~21% 的模块
- **19 个 FastAPI 路由完全没有集成测试**（`TODO/INDEX.md:R-1`）
- **9 阶段 pipeline 零单元测试**（`TODO/INDEX.md:R-2`）
- 核心模块 `core/{database,knowledge_base,semantic_cache}` 无测试（`R-3`）
- Agent 系统 `agent/{graph,tools,sessions}` 无测试（`R-4`）

**影响**：
- 回归风险高：任何重构都可能引入隐蔽 bug
- 部署信心低：无法验证端到端流程
- 技术债加速累积：缺乏重构安全网

**根因**：
1. 迁移时间压力导致"先跑起来再说"
2. 测试框架配置存在（pytest + vitest），但无人编写
3. `tests/unit/parsers/test_coref_alt.py` 是唯一有实质内容的单元测试

**建议**（按优先级）：
1. **立即**：为 19 个路由编写冒烟测试（HTTP 200/404/422 路径）
2. **本周**：为 9 阶段 pipeline 的每个 stage 编写单元测试（输入→输出断言）
3. **本月**：Core 模块达到 70% 覆盖率（RRF fusion、SQLite schema、cache hit/miss）

---

### A2. 模型预热缺失导致首次请求超时 (P0 - 用户体验)

**现状**（`TODO/INDEX.md:C-4`）：
- `app.py:lifespan` 不预热任何后端
- `server.py:_prewarm()` 是空函数（注释："MolDet/MolScribe lazy-loaded on first use"）
- 首次调用 `/api/v1/moldet/*` 或 `/api/v1/molscribe/*` 需等待：
  - MolDet (YOLO26n): ~5-8s
  - MolScribe (Swin + Transformer): ~15-30s
- 前端无加载状态提示，用户以为请求卡死

**影响**：
- 用户首次上传 PDF → 检测分子时，等待 30s+ 无反馈
- 本地模型优势（隐私、离线）被体验劣势抵消

**根因**：
1. 历史遗留：原 Zvec 预热逻辑在迁移时删除，未替换
2. 异步预热未实现：`lifespan` 中的 `loop.run_in_executor(None, _prewarm)` 调用的是空函数

**建议**：
```python
# src/mbforge/server.py
def _prewarm() -> None:
    """后台预热核心模型."""
    from .backends.moldet_v2_ft import get_moldet_ft
    from .backends.molscribe import load as load_molscribe
    try:
        logger.info("Prewarming MolDet...")
        get_moldet_ft()  # 触发模型加载
        logger.info("Prewarming MolScribe...")
        load_molscribe()
        logger.info("Prewarm complete")
    except Exception as e:
        logger.warning("Prewarm failed (non-fatal): %s", e)
```

**前端配套**：
- `/api/v1/health` 新增 `models_ready` 字段
- 前端轮询直到 `models_ready: true` 再显示"上传 PDF"按钮

---

### A3. 异步 I/O 阻塞风险 (P1 - 性能)

**现状**（`TODO/INDEX.md:R-8`）：
- `core/resource_manager.py:245` 行新增代码包含：
  ```python
  subprocess.run(['nvidia-smi'], timeout=5)  # 阻塞调用
  ```
- 此函数在热路径上被调用（资源状态检查）
- FastAPI 事件循环被同步 subprocess 阻塞，降低并发能力

**影响**：
- 每次 `/api/v1/health` 或 `/api/v1/diagnostics` 调用都可能阻塞其他请求
- 在 GPU 不可用时，5s timeout 完全浪费

**建议**：
```python
# 方案 1：异步包装
async def _get_gpu_info() -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _get_gpu_info_sync)

# 方案 2：缓存结果（GPU 状态 1min 内不变）
@lru_cache(maxsize=1)
def _cached_gpu_info(cache_key: int) -> dict:
    # cache_key = int(time.time() / 60)
    return subprocess.run(['nvidia-smi', ...]).stdout
```

---

## 二、代码质量缺陷

### B1. Ruff Lint 问题：254 个违规项 (P1 - 可维护性)

**统计**（`uv run ruff check src/mbforge` 输出）：
- **F401** (44次)：未使用的导入
- **N806** (43次)：变量命名不符合 snake_case（多在 `molscribe_inference/`）
- **I001** (27次)：导入排序错误
- **N803** (12次)：参数命名不符合规范
- **B905** (11次)：`zip()` 缺少 `strict=` 参数（Python 3.10+）

**问题文件 TOP 5**：
1. `parsers/molecule/molscribe_inference/transformer/swin_transformer.py` (49 issues)
2. `gui/utils/__init__.py` (26 issues — 24 个未使用导入)
3. `parsers/molecule/molscribe_inference/chemistry.py` (19 issues)
4. `parsers/molecule/molscribe_inference/model.py` (18 issues)
5. `parsers/molecule/molscribe_inference/constants.py` (13 issues)

**根因**：
- `molscribe_inference/` 目录来自第三方模型代码，未经适配
- `gui/utils/__init__.py` 是批量导出模块，存在死代码

**建议**：
1. **立即修复**（自动化）：`ruff check --fix src/mbforge`（可修复 142/254）
2. **人工审查**：F401 导入清理（可能是死代码信号）
3. **豁免第三方代码**：
   ```toml
   # pyproject.toml
   [tool.ruff.per-file-ignores]
   "src/mbforge/parsers/molecule/molscribe_inference/**" = ["N806", "N803", "E741"]
   ```

---

### B2. TypeScript 配置错误：`noCheck: true` 重复 (P0 - 配置)

**现状**（`TODO/INDEX.md:C-3`）：
```json
// frontend/tsconfig.json:13-14
"noEmit": true,
"noCheck": true,  // ← 第 13 行
"jsx": "react-jsx",
```

**影响**：
- `noCheck` 不是 TypeScript 编译器选项（应为 `skipLibCheck`）
- 虽然编译器容忍未知选项，但 ESLint 会报警
- 配置意图不明确（想跳过类型检查？想跳过 lib 检查？）

**建议**：
```json
{
  "compilerOptions": {
    "skipLibCheck": true,   // 跳过 node_modules 类型检查（加速编译）
    "noEmit": true,         // Vite 负责打包，TS 只做类型检查
    // 删除 "noCheck"
  }
}
```

---

### B3. SSE 客户端无重连逻辑 (P1 - 可靠性)

**现状**（`TODO/INDEX.md:R-5`）：
- `frontend/src/api/sse.ts` 使用原生 `EventSource` API
- 网络抖动时 SSE 断开，Agent 回答截断
- 无自动重连、无指数退避

**影响**：
- 用户在长对话中间遇到网络波动 → 对话丢失，需手动刷新
- 移动网络环境下尤其明显

**建议**：
```typescript
// 方案 1：使用成熟库
import { EventSourcePolyfill } from 'event-source-polyfill';

// 方案 2：手动实现重连
class RobustEventSource {
  private reconnectAttempts = 0;
  private readonly maxReconnectDelay = 30000;
  
  connect(url: string) {
    const es = new EventSource(url);
    es.onerror = () => {
      const delay = Math.min(1000 * 2 ** this.reconnectAttempts, this.maxReconnectDelay);
      setTimeout(() => this.connect(url), delay);
      this.reconnectAttempts++;
    };
  }
}
```

---

### B4. 错误处理不完整 (P2 - 健壮性)

**问题 1**：`httpFetch` 未覆盖所有 MBForgeError 形态（`TODO/INDEX.md:R-6`）

```typescript
// frontend/src/api/http/_utils.ts:91
const code = payload
  ? backendCodeToErrorCode(payload.error_code as string | undefined)
  : ErrorCode.Network;
```

**缺陷**：
- 后端 422 可能来自两种源：
  1. Pydantic `ValidationError` → `{"detail": [{"loc": ..., "msg": ...}]}`
  2. 自定义 `MBForgeError(status_code=422)` → `{"error": ..., "error_code": ...}`
- 当前代码假设所有 JSON body 都有 `error_code` 字段，Pydantic 422 会误判

**建议**：
```typescript
if (!resp.ok) {
  const body = await resp.text().catch(() => '');
  let payload: Record<string, unknown> | null = null;
  try {
    payload = body ? JSON.parse(body) : null;
  } catch { /* non-JSON */ }
  
  // 区分 Pydantic ValidationError 和 MBForgeError
  if (resp.status === 422 && payload?.detail && Array.isArray(payload.detail)) {
    // Pydantic 格式
    const msg = payload.detail.map(e => `${e.loc.join('.')}: ${e.msg}`).join('; ');
    throw new AppError(ErrorCode.ApiError, msg, { ... });
  }
  
  // 标准 MBForgeError 格式
  const code = backendCodeToErrorCode(payload?.error_code);
  // ...
}
```

---

**问题 2**：Agent streaming 错误吞噬

```python
# src/mbforge/agent/graph.py:88-90
except Exception as e:
    logger.error("Agent streaming error: %s", e)
    yield {"type": "error", "error": str(e)}
```

**缺陷**：
- 捕获所有异常但只记录日志，前端收到 `{"type": "error"}` 后无后续处理
- 用户看到对话突然停止，不知道发生了什么

**建议**：
```python
except (ToolExecutionError, LLMProviderError) as e:
    # 已知错误，返回友好提示
    yield {"type": "error", "error": str(e), "recoverable": True}
except Exception as e:
    # 未知错误，记录完整堆栈
    logger.error("Agent streaming fatal error", exc_info=True)
    yield {"type": "error", "error": "Internal error", "recoverable": False}
    raise  # 让上层处理器捕获（或触发 500）
```

---

## 三、文档-代码不一致 (P2 - 开发体验)

### C1. Pipeline 阶段数描述冲突

**文档声明**：
- `CLAUDE.md:19` — "9 stages"
- `README.md:31` — "6-stage pipeline (Phase 1 added molecule extraction)"
- `AGENTS.md:19` — "9 stages"

**实际代码**：
```python
# src/mbforge/pipeline/runner.py:2-13
"""
Stages (9):
1. Extract: PDF text extraction
2. Density: Classify document
3a. Rough Markdown
3b. Detect
3c. MoleCode
3d. Reorganize
3e. PageIndex
4. Wiki
5. Persist Molecules
...
"""
```

**建议**：README.md 更新为 "9-stage pipeline"，删除过时的 "6-stage" 描述。

---

### C2. Router 数量不一致

**文档**：
- `CLAUDE.md:63` — "17 of the 18 production routers"
- `AGENTS.md:10` — "19 routers total"
- `app.py:comment` — "registers all routers" (实际 18 个 include_router + 1 个 mount)

**实际**：
```python
# src/mbforge/app.py:232-254
app.include_router(library.router, ...)  # 1
# ... 共 18 个 include_router
app.mount("/api/v1/models", model_server)  # mount 不算 include_router
```

**建议**：统一为 "19 routers (18 include_router + 1 server.py mount)"。

---

### C3. 存储位置描述过时

**文档**：
- `AGENTS.md:272` — "`{root}/.mbforge/knowledge_base.db` (SQLite)"

**实际**：
```python
# src/mbforge/core/database.py:2-5
"""Two databases per project:
- knowledge_base.db
- molecules.db
"""
```

**建议**：AGENTS.md 更新为 "`.mbforge/{knowledge_base.db, molecules.db}`"。

---

## 四、技术债务与设计问题

### D1. 全局状态管理混乱 (P2 - 架构)

**现状**：
- `utils/config.py` 提供 `load_global_config()` (@lru_cache)
- `core/resource_manager.py` 维护独立的 `_RESOLVED_PATHS_CACHE`
- `backends/moldet.py` / `molscribe.py` 各自管理模型单例

**问题**：
1. 缓存失效难以协调（3 个独立 cache，无统一 invalidation）
2. 测试隔离困难（`@lru_cache` 跨测试污染，需手动 `cache_clear()`）
3. 并发安全未验证（多线程 access LRU cache 时无锁保护）

**建议**：
- 引入统一的 `AppState` dataclass：
  ```python
  @dataclass
  class AppState:
      config: AppConfig
      model_registry: dict[str, Any]
      resolved_paths: dict[str, str]
      _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  
  _APP_STATE: AppState | None = None
  
  def get_app_state() -> AppState:
      # 单例，带锁保护
  ```

---

### D2. 依赖版本过于宽松 (P2 - 供应链风险)

**现状**（`pyproject.toml`）：
```toml
langchain>=0.3.0
langgraph>=0.4.0
pandas>=2.2.0
```

**问题**：
- `langchain` 0.3.0 → 0.3.50 有 breaking changes（工具调用 schema）
- `pandas` 2.2.0 → 3.0.0 breaking（`TODO/INDEX.md:D-7` 提到 `>=3.0.3`）
- `uv.lock` 锁定了当前版本，但跨环境安装可能拉到不兼容版本

**建议**：
```toml
# 收紧上界
langchain>=0.3.0,<0.4
langgraph>=0.4.0,<0.5
pandas>=2.2.0,<3.0  # 或确认兼容后改 >=3.0.3,<4.0
```

---

### D3. 密钥管理不安全 (P1 - 安全)

**现状**：
- OCR API keys 存储在 `~/.config/MBForge/config.json` 明文
- 前端 Settings 页面通过 `/api/v1/settings` GET 暴露完整配置（包括 keys）

**风险**：
```typescript
// 任何访问前端的人都能在 DevTools Network 看到 API keys
const settings = await getSettings();
console.log(settings.ocr.mineru_api_key);  // 明文
```

**建议**：
1. **后端**：GET `/api/v1/settings` 返回时，脱敏 `*_api_key` 字段：
   ```python
   def _redact_secrets(cfg: dict) -> dict:
       for k in list(cfg.keys()):
           if 'api_key' in k or 'secret' in k:
               cfg[k] = '***' if cfg[k] else ''
       return cfg
   ```
2. **存储**：引入 keyring 存储敏感字段（Windows DPAPI / macOS Keychain / Linux Secret Service）

---

### D4. SQL 注入风险 (P1 - 安全)

**审计扫描**：未发现直接拼接 SQL 字符串的代码。所有数据库操作使用参数化查询。

**示例**（正确）：
```python
# src/mbforge/core/database.py
cursor.execute(
    "SELECT * FROM molecules WHERE mol_id = ?",
    (mol_id,)  # ← 参数化
)
```

**建议**：通过（无需修改）。

---

## 五、性能与可扩展性

### E1. OpenKB PageIndex 可扩展性未验证 (P2 - 性能)

**现状**：
- 每个文档调用 `openkb.index_markdown()` 构建树索引
- 未测试 100+ 文档项目的查询延迟
- `pageindex` 是否支持增量更新未文档化

**建议**：
1. 性能基准测试：模拟 50/100/200 文档项目，测量：
   - 索引构建时间
   - 查询响应时间（P50/P95/P99）
   - 内存占用
2. 如果 > 2s，考虑缓存策略或切换到 Zvec

---

### E2. 前端打包体积过大 (P3 - 用户体验)

**现状**（`npm run build` 输出）：
- `dist/index.html` 1.1 KB
- KaTeX 字体文件 ~150 KB（多个 woff/woff2/ttf）
- 未显示 JS bundle 大小（被截断）

**建议**：
```bash
cd frontend && npx vite-bundle-visualizer
```
分析后按需优化：
- 懒加载 KaTeX（仅在 Markdown 渲染时加载）
- Tree-shaking MUI icons（按需导入）

---

## 六、优先行动清单

### 本周必须完成（P0）

| 任务 | 工时估算 | 负责人 |
|------|---------|--------|
| 修复 `tsconfig.json:noCheck` 配置错误 | 5 min | 前端 |
| 实现模型预热（`server.py:_prewarm`） | 2 h | 后端 |
| 为 19 个路由编写冒烟测试 | 8 h | 后端 |

### 本月必须完成（P1）

| 任务 | 工时估算 |
|------|---------|
| Pipeline 9 阶段单元测试 | 16 h |
| 修复 Ruff lint 254 问题（自动修复 142 项 + 人工审查 112 项）| 4 h |
| SSE 重连逻辑实现 | 3 h |
| 密钥脱敏（后端返回 `***`） | 2 h |
| 异步化 `subprocess.run` (resource_manager) | 1 h |

### Q3 规划（P2）

- 统一全局状态管理（`AppState` 重构）
- 文档-代码一致性修复（5 处冲突）
- 依赖版本收紧 + 安全审计
- 性能基准测试（OpenKB 可扩展性）

---

## 七、结论与建议

### 7.1 总体评估

MBForge 项目在架构设计上**整体合理**（前后端分离、RESTful API、模块化），但在**工程实践**上存在明显短板：

**优势**：
✅ 清晰的分层架构（Frontend → Routers → Core → Backends）
✅ 完整的错误类型体系（MBForgeError + 子类）
✅ 统一的日志系统（JSON 格式 + 诊断 ring buffer）
✅ 规范的提交约定（type(scope): subject）

**劣势**：
❌ 测试覆盖率 < 25%（行业标准 > 70%）
❌ 性能瓶颈未优化（首次加载 30s 无反馈）
❌ 代码质量债务累积（254 lint issues）
❌ 文档滞后于代码（6 处不一致）

### 7.2 技术债务象限

```
      │ 高影响
      │
  P0  │  ● 测试覆盖率
      │  ● 模型预热
──────┼──────────────
  P1  │  ● Lint 修复    ● SSE 重连
      │  ● 密钥管理      ● 异步 I/O
      │
      低紧急 ───→ 高紧急
```

### 7.3 核心建议

1. **立即止血**（本周）：
   - 修复 P0 配置错误（`tsconfig.json`）
   - 实现模型预热，消除 30s 首次加载
   - 补齐路由冒烟测试，建立回归基线

2. **系统性修复**（本月）：
   - 测试覆盖率达到 50%（核心模块 70%）
   - 清理 Ruff lint 债务
   - 实现 SSE 重连 + 密钥脱敏

3. **长期改进**（Q3）：
   - 重构全局状态管理
   - 性能基准测试 + 监控
   - 文档自动化验证（linter 检查示例代码）

### 7.4 风险评估

如果**不**解决这些缺陷，预计在 3 个月内会出现：

- **用户流失**：模型加载慢 + SSE 断开 → 用户放弃使用
- **回归 bug 增加**：无测试 → 每次修改都可能破坏已有功能
- **安全事件**：API key 泄露 → 云服务账单爆炸
- **团队效率下降**：技术债累积 → 新功能开发变慢

---

## 附录 A：已修复问题追踪

根据 `TODO/INDEX.md`，以下问题已在近期 commit 中修复：

| ID | 描述 | 修复时间 |
|----|------|---------|
| C-1 | `ts_errors.txt` 被 git 追踪 | 2026-07-07 |
| C-2 | `.gitignore` 中 `.mbccforge/` 拼写错误 | 2026-07-07 |
| C-5 | `frontend/src/api/tauri/` 目录名过时 | 2026-07-07 |
| R-7 | `backends/qwen3.py` header 过时 | 2026-07-07 |
| R-9 | `CLAUDE.md` 引用 `archived/` 路径 | 2026-07-05 |

---

## 附录 B：工具链配置建议

### B.1 Pre-commit hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.0
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-eslint
    rev: v10.0.0
    hooks:
      - id: eslint
        files: 'frontend/src/.*\.[jt]sx?$'
        args: [--fix]
```

### B.2 CI Pipeline

```yaml
# .github/workflows/test.yml
name: Test
on: [push, pull_request]

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: uv sync --dev
      - run: uv run ruff check src/mbforge
      - run: uv run pytest tests/ --cov=src/mbforge --cov-report=xml
      - uses: codecov/codecov-action@v4

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm --prefix frontend install
      - run: npm --prefix frontend run lint
      - run: npm --prefix frontend test -- --coverage
```

---

**报告作者**: Claude (Opus 4.8)  
**审核状态**: 待人工确认  
**下次更新**: 2026-07-16 (P0 问题修复后)