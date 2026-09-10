# Agent 短期边界完善实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持单用户、单进程应用模型不变的前提下，收紧 Agent 应用边界，保证项目路径、会话并发、事件协议、错误语义和工具依赖可控可测。

**Architecture:** 保留当前 LangGraph `create_react_agent`，不重写为显式 `StateGraph`，不引入多用户鉴权或持久化会话。新增轻量运行时边界：会话创建统一解析 `library_root`，每个会话串行执行一次 generation；Agent 内部事件转换为稳定 SSE 协议；工具通过 core/service API 调用业务能力；Agent 初始化失败和未配置状态显式返回。所有改动先由后端单元测试锁定行为，再补前端事件消费测试。

**Tech Stack:** Python 3.12、FastAPI、LangGraph、LangChain、SQLite/现有 LibraryLayout、React 19、TypeScript、pytest、Vitest、Ruff。

## 范围与非目标

### 本期范围

- 单用户桌面应用边界。
- `library_root` 统一解析、规范化、校验。
- 同一 session 的 chat/stream generation 串行化。
- 统一 Agent SSE 事件名称和成功/失败终态。
- 显式区分未配置、初始化失败、工具错误、Provider 错误。
- 移除 Agent tool 对 HTTP Router 的直接依赖。
- 配置变更后的 Agent runtime reset/rebuild。
- 补齐关键单元测试和前端协议测试。

### 非目标

- 不实现用户认证、session owner、多租户隔离。
- 不把 `SessionStore` 迁移到 SQLite。
- 不引入 LangGraph checkpointer。
- 不把 `create_react_agent` 改成自定义 StateGraph。
- 不修改前端 `Promise.all` 等无关业务并发行为。

## 文件结构

| 文件 | 责任 |
|---|---|
| `src/mbforge/routers/agent.py` | Agent HTTP 边界、runtime 状态、session generation 串行化、错误响应和 SSE 映射。 |
| `src/mbforge/agent/sessions.py` | 单进程会话数据及每会话并发控制。 |
| `src/mbforge/agent/graph.py` | LangGraph 创建和内部事件转换，不承担 HTTP 响应格式。 |
| `src/mbforge/agent/tools.py` | Agent 工具适配；只依赖 core/service，不依赖 HTTP Router。 |
| `src/mbforge/core/` 或现有分子业务 service 文件 | 提供 Router 与 Agent 共用的分子搜索业务接口；沿用现有领域 API，不复制实现。 |
| `src/mbforge/models/agent.py` | 明确 Agent 状态、事件、错误字段的 Pydantic 模型。 |
| `frontend/src/api/http/agent.ts` | 消费稳定 SSE 事件，处理 tool/error/done，保证 Promise 生命周期正确。 |
| `frontend/src/components/discover/ChatTab.tsx` | 正确维护 loading、取消重复发送、展示 Agent 错误。 |
| `tests/unit/agent/test_agent_router.py` | session 边界、并发、错误状态、事件协议测试。 |
| `tests/unit/agent/test_graph.py` | LangGraph 事件转换测试。 |
| `tests/unit/agent/test_tools.py` | 工具业务边界和失败语义测试。 |
| `frontend/src/api/http/__tests__/agent.test.ts` | 前端 SSE 协议、错误和完成语义测试。 |
| `frontend/src/components/discover/ChatTab.test.tsx` | loading 与重复发送行为测试；若现有测试基础设施支持则新增。 |

---

### Task 1: 固定 Agent 边界与状态模型

**Files:**
- Modify: `src/mbforge/models/agent.py`
- Modify: `src/mbforge/routers/agent.py`
- Test: `tests/unit/agent/test_agent_router.py`

- [ ] **Step 1: 定义初始化状态和错误字段**

为 Agent 初始化和聊天错误建立明确的有限状态，不再用普通 assistant 文本表达系统错误。至少支持：

```python
class AgentStatus(str, Enum):
    READY = "ready"
    NOT_CONFIGURED = "not_configured"
    INITIALIZATION_FAILED = "initialization_failed"

class AgentErrorCode(str, Enum):
    NOT_CONFIGURED = "agent_not_configured"
    INITIALIZATION_FAILED = "agent_initialization_failed"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_BUSY = "session_busy"
    TOOL_ERROR = "tool_error"
    LLM_PROVIDER_ERROR = "llm_provider_error"
    INTERNAL_ERROR = "internal_error"
```

保留现有响应字段兼容性；新增字段必须有默认值，避免破坏现有前端调用。

- [ ] **Step 2: 让 `ensure_initialized()` 返回状态而非静默 stub**

在 `AgentState` 增加 `status` 和 `last_error`。规则：

- 没有 API key 时返回 `NOT_CONFIGURED`。
- LLM、工具或 graph 创建失败时记录日志并返回 `INITIALIZATION_FAILED`。
- 成功创建后返回 `READY`。
- 不把异常转换成普通 assistant 消息。

日志保留完整异常上下文；HTTP 响应返回稳定 `error_code` 和用户可读 `message`，不泄露 API key 或内部堆栈。

- [ ] **Step 3: 增加状态测试**

在 `tests/unit/agent/test_agent_router.py` 添加：

```python
def test_agent_init_reports_not_configured_without_api_key(...):
    ...

def test_agent_init_reports_initialization_failure(...):
    ...

def test_agent_chat_returns_structured_not_configured_error(...):
    ...
```

测试断言不得依赖具体日志文本，只断言状态、错误码、HTTP 响应结构。

- [ ] **Step 4: 运行边界测试**

```bash
uv run pytest tests/unit/agent/test_agent_router.py -q
```

预期：原有测试和新增状态测试全部通过。

---

### Task 2: 统一解析 `library_root` 并保护工具边界

**Files:**
- Modify: `src/mbforge/routers/agent.py`
- Modify: `src/mbforge/agent/tools.py`
- Test: `tests/unit/agent/test_agent_router.py`
- Test: `tests/unit/agent/test_tools.py`

- [ ] **Step 1: 会话创建和项目更新统一调用 resolver**

`POST /session` 不再直接保存 `body.library_root`。统一调用现有 `resolve_library_root()`，保存规范化后的路径；空路径按当前单用户默认配置规则处理，非法或不存在路径返回结构化验证错误。

`PUT /session/{session_id}/project` 使用相同逻辑，避免创建和更新产生不同路径语义。

- [ ] **Step 2: 工具只接受已验证的运行时路径**

保留 LangGraph `configurable` 传递方式，但 `tools.py` 的 `_get_library_root()` 必须拒绝空值和未规范化路径；工具不能自行接受任意新路径。优先从 session runtime 传递已验证路径；若当前接口暂时只能传路径，则在进入工具前完成同一 resolver 校验。

不要修改数据库 schema，不构造 `.mbforge`、`storage` 等内部路径。

- [ ] **Step 3: 解耦 `molecule_search` 的 Router 依赖**

把 `tools.py:69-79` 对 `routers.molecule.mol_search` 的调用替换为现有 core/service 分子搜索 API。HTTP Router 和 Agent tool 都调用同一业务函数；工具不得构造 HTTP request model，也不得依赖 HTTP response model。

若当前没有合适 service，新增最小领域函数，输入为 `library_root`、`query`、`top_k`，输出为普通业务数据结构；Router 负责 Pydantic 响应转换，tool 负责 JSON 序列化。

- [ ] **Step 4: 增加路径和依赖边界测试**

覆盖：

- 会话创建保存规范化路径。
- 非法路径被拒绝。
- 工具缺少路径返回明确错误。
- 分子搜索 tool 调用 core/service，而非 Router。
- 现有成功搜索响应不变。

- [ ] **Step 5: 运行 Agent 工具测试**

```bash
uv run pytest tests/unit/agent/test_agent_router.py tests/unit/agent/test_tools.py -q
```

预期：全部通过，且不出现路径越权或 Router 依赖回归。

---

### Task 3: 增加 session generation 串行化

**Files:**
- Modify: `src/mbforge/agent/sessions.py`
- Modify: `src/mbforge/routers/agent.py`
- Test: `tests/unit/agent/test_agent_router.py`

- [ ] **Step 1: 给 `AgentSession` 增加 generation 锁和生命周期字段**

保留进程内 `SessionStore`，增加：

```python
lock: asyncio.Lock = field(default_factory=asyncio.Lock)
last_access_at: float = field(default_factory=time.time)
```

删除未使用的 `agent`、`llm` 字段，避免误导为每个 session 持有独立模型。

- [ ] **Step 2: chat 和 stream 共享同一 generation 锁**

一次请求的边界必须包含：

```text
获取 session
→ 获取 session.lock
→ 追加 user message
→ 快照历史
→ 调用 Agent
→ 追加 assistant message 或结构化失败结果
→ 释放 session.lock
```

同一 session 的第二个并发请求不得同时调用 LLM。根据现有 API 选择：

- 非流式 chat 可等待锁；
- SSE 请求不能无限等待，超时后返回 `SESSION_BUSY`；
- clear/delete/project update 与 generation 使用同一锁，避免清空或切换项目时破坏正在运行的历史。

- [ ] **Step 3: 增加并发和重入测试**

测试使用 fake Agent，设置事件 barrier，验证两个并发请求最多只有一次同时执行；验证 assistant 消息顺序稳定；验证 stream 和 chat 共享锁；验证 session 删除或 clear 不会在 generation 中途破坏状态。

- [ ] **Step 4: 运行并发回归**

```bash
uv run pytest tests/unit/agent/test_agent_router.py -q
```

预期：并发测试稳定通过，重复运行不少于两次。

---

### Task 4: 统一 LangGraph 到 SSE 的事件协议

**Files:**
- Modify: `src/mbforge/agent/graph.py`
- Modify: `src/mbforge/routers/agent.py`
- Modify: `src/mbforge/models/agent.py`
- Modify: `frontend/src/api/http/agent.ts`
- Modify: `frontend/src/components/discover/ChatTab.tsx`
- Test: `tests/unit/agent/test_graph.py`
- Test: `tests/unit/agent/test_agent_router.py`
- Test: `frontend/src/api/http/__tests__/agent.test.ts`

- [ ] **Step 1: 固定内部事件到 HTTP 事件的映射**

统一事件集合：

```text
start
 tool_call
 tool_result
 delta
 error
 done
```

推荐 HTTP SSE payload：

```json
{"type":"delta","content":"..."}
{"type":"tool_call","tool":"kb_search","args":{} }
{"type":"tool_result","tool":"kb_search","output":"..."}
{"type":"error","code":"tool_error","message":"...","recoverable":true}
{"type":"done","ok":true}
```

`done.ok=false` 时必须带 `error` 或 `code`。禁止只发送模糊的 `done` 掩盖错误。

- [ ] **Step 2: graph 层保持内部格式，Router 负责 wire format**

`stream_agent_response()` 只负责 LangGraph 事件转换和异常分类；Router 负责 SSE 编码、字段命名和终态。未接入的自定义异常必须补齐，或按异常类型统一映射为 `tool_error`/`llm_provider_error`/`internal_error`。

- [ ] **Step 3: 前端消费所有事件**

`agent.ts` 处理：

- `delta`：追加回答。
- `tool_call`：更新工具执行状态。
- `tool_result`：更新工具结果状态。
- `error`：保存并展示错误。
- `done`：仅在事件完成后 resolve；`ok=false` 时 reject 或返回显式失败对象。

修复当前 stream client 提前 resolve 的问题，Promise 必须在 `done`、`error` 或连接异常时结束。

- [ ] **Step 4: 修复 ChatTab loading 与重复发送**

发送前设置 `isLoading=true`，完成或失败后在 `finally` 清理。发送期间禁止第二次发送；组件卸载时关闭连接。不要改变现有消息展示结构之外的 UI 范围。

- [ ] **Step 5: 运行后端和前端协议测试**

```bash
uv run pytest tests/unit/agent/test_graph.py tests/unit/agent/test_agent_router.py -q
npm --prefix frontend run test -- --run src/api/http/__tests__/agent.test.ts
```

预期：后端事件映射、SSE 错误终态、前端 Promise 生命周期全部通过。

---

### Task 5: 配置变更触发 Agent runtime reset/rebuild

**Files:**
- Modify: `src/mbforge/routers/agent.py`
- Modify: `src/mbforge/agent/llm_factory.py`（仅在需要暴露配置指纹时）
- Modify: Settings 保存配置的现有 Router（定位后最小修改）
- Test: `tests/unit/agent/test_agent_router.py`
- Test: 现有 Settings/LLM 测试文件

- [ ] **Step 1: 定义 runtime reset 入口**

保留全局单例 AgentState，但为其增加受锁保护的 `reset()`/`invalidate()`。reset 必须等待或拒绝正在进行的 generation，不能在请求中途把 `agent` 替换为 `None`。

- [ ] **Step 2: 在 LLM 设置保存成功后失效 runtime**

只在设置持久化成功后调用 AgentState invalidate；设置保存失败不得清除当前可用 Agent。下一次 `/init`、chat 或 stream 触发 lazy rebuild。

- [ ] **Step 3: 测试配置生命周期**

覆盖：

- 设置保存后旧 Agent 不再使用。
- 设置保存失败时旧 Agent 仍可用。
- reset 与初始化并发时不产生半初始化状态。
- 无 API key 的新配置返回 `NOT_CONFIGURED`。

- [ ] **Step 4: 运行相关测试**

```bash
uv run pytest tests/unit/agent/ tests/unit/test_settings.py -q
```

若仓库不存在 `tests/unit/test_settings.py`，改用实际 Settings 测试路径，并在交付记录中列出实际命令。

---

### Task 6: 完成短期验证与边界审查

**Files:** none（verification only）

- [ ] **Step 1: 运行 Agent 后端测试**

```bash
uv run pytest tests/unit/agent/ -q
```

- [ ] **Step 2: 运行受影响后端测试**

```bash
uv run pytest tests/unit/routers/test_molecule.py tests/unit/agent/ -q
```

使用仓库实际存在的分子 Router 测试路径；若路径不同，以 `tests/unit/routers/` 中对应文件替换。

- [ ] **Step 3: 运行前端 Agent 测试与类型检查**

```bash
npm --prefix frontend run test -- --run
npm --prefix frontend exec tsc -- --noEmit
```

- [ ] **Step 4: 运行 Ruff**

```bash
uv run ruff check src/mbforge/agent src/mbforge/routers/agent.py src/mbforge/models/agent.py tests/unit/agent
uv run ruff format --check src/mbforge/agent src/mbforge/routers/agent.py src/mbforge/models/agent.py tests/unit/agent
```

- [ ] **Step 5: 进行最终边界检查**

确认以下事实：

- 未添加多用户认证或 session owner 逻辑。
- 未将会话存储迁移到数据库。
- 未重写 LangGraph 为显式 StateGraph。
- `library_root` 不再由未验证的会话创建输入直接进入工具。
- 同一 session 不会并发调用 Agent。
- SSE 错误不会被普通 `done` 掩盖。
- Agent tool 不再导入 HTTP Router。
- 设置失败不会破坏当前可用 Agent。

## 实施顺序与交付策略

建议拆为 3 个原子提交，避免一次改动过大：

1. `fix(agent): enforce runtime and library boundaries`  
   包含 Task 1、Task 2。
2. `fix(agent): serialize session generations`  
   包含 Task 3。
3. `fix(agent): stabilize agent event protocol`  
   包含 Task 4、Task 5 及对应测试。

每个提交只暂存本任务文件，不包含工作区已有无关改动。不要自动提交计划文件；计划只作为执行依据。

## 计划自审

- 需求覆盖：聚焦单用户短期边界，不包含多用户隔离、持久化会话、StateGraph 重写。
- 可回滚性：路径边界、会话锁、协议、runtime reset 分成独立任务和提交。
- 可验证性：每个任务有针对性测试，最终有后端、前端、lint、类型检查。
- 依赖一致性：Agent tool 目标依赖 core/service；Router 负责 HTTP/Pydantic；LangGraph 负责 Agent 执行和内部事件。
- 无占位内容：所有步骤给出明确文件、行为、命令和验收条件。
