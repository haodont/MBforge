# Agent P1 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden agent initialization, conversation history, streaming errors, and session lifecycle without changing public route shapes.

**Architecture:** Keep existing LangGraph and in-process session store. Add provider-aware initialization predicates and configuration fingerprinting to `AgentState`; make failed invocations transactional with respect to history; return explicit busy errors and preserve stream status. Defer persistence/auth backend redesign.

**Tech Stack:** Python 3.12, FastAPI, LangGraph, LangChain, Pydantic, pytest, asyncio.

---

### Task 1: Provider-aware agent initialization

**Files:**
- Modify: `src/mbforge/routers/agent.py:45-96`
- Test: `tests/unit/agent/test_agent_router.py`

- [ ] **Step 1: Write failing tests**

Add tests proving Ollama initializes without an API key, non-Ollama providers without a key remain `NOT_CONFIGURED`, and changing persisted provider/model/key rebuilds the cached agent.

- [ ] **Step 2: Run tests and verify expected failures**

Run: `uv run pytest tests/unit/agent/test_agent_router.py -q -k 'ollama or config_change'`
Expected: failures showing Ollama is incorrectly treated as unconfigured and cached agent is reused.

- [ ] **Step 3: Implement minimal state fingerprinting**

Add a private fingerprint derived from provider, model, base URL, API-key presence, temperature, max tokens, and timeout. In `ensure_initialized()`, load config once, allow `ollama` without key, and rebuild when fingerprint differs. Keep initialization under `self.lock`; assign fully built components only after all factories succeed.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/unit/agent/test_agent_router.py -q -k 'ollama or config_change'`
Expected: PASS.

- [ ] **Step 5: Commit atomic change**

```bash
git add src/mbforge/routers/agent.py tests/unit/agent/test_agent_router.py
git commit -m "fix(agent): refresh state when LLM settings change"
```

### Task 2: Transactional chat history

**Files:**
- Modify: `src/mbforge/routers/agent.py:246-335,338-420`
- Test: `tests/unit/agent/test_agent_router.py`

- [ ] **Step 1: Write failing tests**

Add tests proving unavailable initialization leaves no user message, provider failure leaves no user or `[Agent error]` assistant message, and successful calls append exactly one user plus one assistant message.

- [ ] **Step 2: Run tests and verify expected failures**

Run: `uv run pytest tests/unit/agent/test_agent_router.py -q -k 'history or error_message'`
Expected: failures showing user/error markers are persisted.

- [ ] **Step 3: Implement transactional append**

Build `lc_messages` from existing history plus the candidate user message without mutating `session.messages`. Append the user message only after initialization succeeds; append assistant content only after a successful invocation. On failure, leave history unchanged while still releasing the generation claim.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/unit/agent/test_agent_router.py -q -k 'history or error_message'`
Expected: PASS.

- [ ] **Step 5: Commit atomic change**

```bash
git add src/mbforge/routers/agent.py tests/unit/agent/test_agent_router.py
git commit -m "fix(agent): keep failed chats out of history"
```

### Task 3: Provider defaults and model argument compatibility

**Files:**
- Modify: `src/mbforge/agent/llm_factory.py:37-113`
- Test: `tests/unit/agent/test_llm_factory.py`

- [ ] **Step 1: Write failing tests**

Add tests proving Anthropic without an explicit model raises a clear configuration error, and that Anthropic construction does not pass unsupported `temperature` when configured for a reasoning model. Preserve OpenAI/Ollama forwarding tests.

- [ ] **Step 2: Run tests and verify expected failures**

Run: `uv run pytest tests/unit/agent/test_llm_factory.py -q -k 'anthropic or temperature'`
Expected: failures against retired default model and unconditional parameter forwarding.

- [ ] **Step 3: Implement explicit Anthropic model requirement and parameter filtering**

For `provider == "anthropic"`, require `llm_cfg.model` or explicit `model`; raise `ValueError("model required for Anthropic provider ...")` when absent. Build kwargs first and omit `temperature` for configured reasoning-model identifiers; pass remaining timeout/max_tokens values unchanged.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/unit/agent/test_llm_factory.py -q -k 'anthropic or temperature'`
Expected: PASS.

- [ ] **Step 5: Commit atomic change**

```bash
git add src/mbforge/agent/llm_factory.py tests/unit/agent/test_llm_factory.py
git commit -m "fix(agent): require supported Anthropic model config"
```

### Task 4: Explicit busy lifecycle responses

**Files:**
- Modify: `src/mbforge/routers/agent.py:191-215`
- Modify: `src/mbforge/models/agent.py:16-23,69-73`
- Test: `tests/unit/agent/test_agent_router.py`

- [ ] **Step 1: Write failing tests**

Add tests proving busy clear/delete return `AgentErrorResponse` with `SESSION_BUSY`, while idle clear removes messages and idle delete removes the session. Change history model default to `Field(default_factory=list)` and add a model isolation test.

- [ ] **Step 2: Run tests and verify expected failures**

Run: `uv run pytest tests/unit/agent/test_agent_router.py tests/unit/test_agent_models.py -q -k 'busy or clear or destroy or default'`
Expected: failures because busy operations currently return success and model default is mutable syntax.

- [ ] **Step 3: Implement explicit response contracts**

Change clear/delete return annotations to `AgentSessionOkResponse | AgentErrorResponse`; return `SESSION_BUSY` when generation is claimed; preserve successful idle behavior. Replace `messages = []` with `Field(default_factory=list)`.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/unit/agent/test_agent_router.py tests/unit/test_agent_models.py -q -k 'busy or clear or destroy or default'`
Expected: PASS.

- [ ] **Step 5: Commit atomic change**

```bash
git add src/mbforge/routers/agent.py src/mbforge/models/agent.py tests/unit/agent/test_agent_router.py tests/unit/test_agent_models.py
git commit -m "fix(agent): report busy session lifecycle operations"
```

### Task 5: Cross-task verification

**Files:**
- No production changes.
- Test: `tests/unit/agent/test_agent_router.py`, `tests/unit/agent/test_graph.py`, `tests/unit/agent/test_llm_factory.py`, `tests/unit/agent/test_tools.py`

- [ ] **Step 1: Run agent unit suite**

Run: `uv run pytest tests/unit/agent -q`
Expected: exit code 0; report exact failures if environment prevents completion.

- [ ] **Step 2: Run lint and type checks for changed Python files**

Run: `uv run ruff check src/mbforge/agent src/mbforge/routers/agent.py src/mbforge/models/agent.py tests/unit/agent`
Expected: exit code 0.

- [ ] **Step 3: Review diff and status**

Run: `git diff --check` and `git status --short`.
Expected: no whitespace errors; only intended files changed.
