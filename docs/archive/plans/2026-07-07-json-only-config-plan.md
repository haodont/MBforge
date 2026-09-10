# 业务配置 JSON-only Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 MBForge 所有业务配置只从 `settings.json` 读取，移除 `MBFORGE_*` 业务环境变量兜底。

**Architecture:** 把 `AppConfig` 从 `BaseSettings` 改回 `BaseModel`，去掉 `env_prefix`；再逐个清理 LLM、MolScribe 目录、PageIndex、moldet device 等业务模块里的 `os.environ.get` 兜底，统一走 `load_global_config()`。运行时/基础设施 env（host、log level、force_cpu、docker、HF_HOME 等）保留。

**Tech Stack:** Python 3.12, Pydantic 2, pytest, ruff

## Global Constraints
- 只移除业务配置 env 兜底；运行时/基础设施 env 白名单保留。
- 旧的业务 env 字段直接忽略，不做兼容/迁移/告警。
- 所有改动必须通过 `uv run ruff check src/ tests/` 和 `uv run pytest tests/unit/ -q`。
- 提交粒度：一个业务模块 = 一个 commit（config / llm / molscribe / pageindex / moldet_v2_ft / tests）。

---

### Task 1: `AppConfig` 改为 JSON-only

**Files:**
- Modify: `src/mbforge/utils/config.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: 无
- Produces: `AppConfig` 不再读取 `MBFORGE_*` 业务 env；`load_global_config()` 行为不变。

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_config.py` 新增：

```python
class TestEnvIgnored:
    def test_business_env_vars_ignored(
        self, tmp_settings: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MBFORGE_LLM_API_KEY", "sk-env")
        monkeypatch.setenv("MBFORGE_LLM_MODEL", "gpt-env")
        cfg = load_global_config()
        assert cfg.llm.api_key == ""
        assert cfg.llm.model == "gpt-4o-mini"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/unit/test_config.py::TestEnvIgnored::test_business_env_vars_ignored -v
```

Expected: FAIL（当前 `AppConfig` 仍可能读 env）。

- [ ] **Step 3: 修改 `AppConfig` 基类**

在 `src/mbforge/utils/config.py`：

```python
# 删除
from pydantic_settings import BaseSettings, SettingsConfigDict

# 保留
from pydantic import BaseModel, ConfigDict, Field
```

把：

```python
class AppConfig(BaseSettings):
    """全局应用配置 — 唯一 schema."""

    model_config = SettingsConfigDict(
        env_prefix="MBFORGE_",
        extra="ignore",
    )
```

改为：

```python
class AppConfig(BaseModel):
    """全局应用配置 — 唯一 schema."""

    model_config = ConfigDict(extra="ignore")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/utils/config.py tests/unit/test_config.py
git commit -m "refactor(config): make AppConfig JSON-only, drop env_prefix"
```

---

### Task 2: LLM factory 移除 env 兜底

**Files:**
- Modify: `src/mbforge/agent/llm_factory.py`
- Test: `tests/unit/test_llm_factory.py`

**Interfaces:**
- Consumes: `AppConfig.llm` from `load_global_config()`
- Produces: `create_llm` / `create_llm_from_settings` 不再读取 `MBFORGE_LLM_*`

- [ ] **Step 1: 重写测试为 cfg-only**

完整替换 `tests/unit/test_llm_factory.py` 内容：

```python
"""P1.2 — LLM factory 只读 cfg.llm，不读任何 MBFORGE_LLM_* env."""

from __future__ import annotations

from pathlib import Path

import pytest

from mbforge.utils import config as cfg_mod
from mbforge.utils.config import (
    reset_config_cache,
    update_settings,
)


@pytest.fixture
def tmp_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = tmp_path / "settings.json"
    legacy_cfg = tmp_path / "config.json"
    legacy_gui = tmp_path / "gui_state.json"
    monkeypatch.setattr(cfg_mod, "_SETTINGS_PATH", settings)
    monkeypatch.setattr(cfg_mod, "_LEGACY_PATHS", (legacy_cfg, legacy_gui))
    reset_config_cache()
    yield tmp_path
    reset_config_cache()


class TestCreateLlmFromSettings:
    def test_reads_from_cfg(self, tmp_settings: Path) -> None:
        update_settings({
            "llm": {
                "provider": "openai_compatible",
                "model": "gpt-4o",
                "api_key": "sk-test",
                "base_url": "https://api.test/v1",
            }
        })
        from mbforge.agent.llm_factory import create_llm_from_settings

        llm = create_llm_from_settings()
        assert llm.model_name == "gpt-4o"
        assert llm.openai_api_key.get_secret_value() == "sk-test"
        assert "api.test" in str(llm.openai_api_base)

    def test_env_ignored(self, tmp_settings: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        update_settings({
            "llm": {
                "provider": "openai_compatible",
                "api_key": "sk-ui",
                "model": "gpt-ui",
            }
        })
        monkeypatch.setenv("MBFORGE_LLM_API_KEY", "sk-env")
        monkeypatch.setenv("MBFORGE_LLM_MODEL", "gpt-env")
        from mbforge.agent.llm_factory import create_llm_from_settings

        llm = create_llm_from_settings()
        assert llm.openai_api_key.get_secret_value() == "sk-ui"
        assert llm.model_name == "gpt-ui"

    def test_missing_api_key_raises(
        self, tmp_settings: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for key in (
            "MBFORGE_LLM_PROVIDER",
            "MBFORGE_LLM_MODEL",
            "MBFORGE_LLM_API_KEY",
            "MBFORGE_LLM_BASE_URL",
        ):
            monkeypatch.delenv(key, raising=False)
        from mbforge.agent.llm_factory import create_llm

        with pytest.raises(ValueError, match="api_key required"):
            create_llm(provider="openai_compatible")

    def test_explicit_arg_wins(self, tmp_settings: Path) -> None:
        update_settings({"llm": {"api_key": "sk-cfg"}})
        from mbforge.agent.llm_factory import create_llm

        llm = create_llm(provider="openai_compatible", api_key="sk-explicit")
        assert llm.openai_api_key.get_secret_value() == "sk-explicit"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/unit/test_llm_factory.py -v
```

Expected: 部分 FAIL（env fallback 测试失败或新 env_ignored 失败）。

- [ ] **Step 3: 修改 `llm_factory.py`**

在 `src/mbforge/agent/llm_factory.py`：

1. 删除 `import os`。
2. 更新模块 docstring：

```python
"""LLM factory — creates LangChain chat models from config.

Supports: openai, anthropic, ollama, openai_compatible.

优先级（自上而下）：
  1. 显式参数
  2. ``AppConfig.llm`` (Settings UI 写入 → ``settings.json``)
  3. 硬编码默认值

不再读取 ``MBFORGE_LLM_*`` 环境变量；所有业务配置统一走 ``settings.json``。
"""
```

3. 修改 `_resolve_api_key`：

```python
def _resolve_api_key(arg: str, cfg_key: str) -> str:
    """arg > cfg."""
    return arg or cfg_key
```

4. 修改错误提示，去掉 env 提及：

```python
raise ValueError(
    "api_key required for OpenAI-compatible provider "
    "(set via Settings UI)"
)
```

两处（openai_compatible 与 anthropic）都改。

5. 更新 `create_llm` docstring：

```python
"""Create a LangChain chat model.

Priority: explicit args > AppConfig.llm > defaults.
"""
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/unit/test_llm_factory.py -v
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/agent/llm_factory.py tests/unit/test_llm_factory.py
git commit -m "refactor(agent): read LLM config only from settings.json"
```

---

### Task 3: Agent router 初始化不再检查 env

**Files:**
- Modify: `src/mbforge/routers/agent.py`
- Test: `tests/unit/test_routers_smoke.py`（已有，无需新增）

**Interfaces:**
- Consumes: `AppConfig.llm`
- Produces: `AgentState.ensure_initialized` 只在 `cfg.api_key` 为空时进入 stub mode。

- [ ] **Step 1: 修改 `ensure_initialized`**

在 `src/mbforge/routers/agent.py` 的 `ensure_initialized` 中：

删除：

```python
import os
```

把：

```python
api_key = os.environ.get("MBFORGE_LLM_API_KEY", "")
if not api_key:
    logger.info("No LLM API key configured — agent running in stub mode")
    return
```

改为：

```python
cfg = load_global_config().llm
if not cfg.api_key:
    logger.info("No LLM API key configured — agent running in stub mode")
    return
```

并确保 `from ..utils.config import load_global_config` 已导入。

- [ ] **Step 2: 运行测试确认通过**

```bash
uv run pytest tests/unit/test_routers_smoke.py::TestAgentEndpoints -v
```

Expected: PASS（`test_agent_init_ready_when_llm_configured` 通过，`test_agent_init` 返回 false）。

- [ ] **Step 3: Commit**

```bash
git add src/mbforge/routers/agent.py
git commit -m "refactor(agent): drop MBFORGE_LLM_API_KEY env check in router init"
```

---

### Task 4: MolScribe 目录移除 env 兜底

**Files:**
- Modify: `src/mbforge/parsers/molecule/molscribe_inference/download.py`
- Test: `tests/unit/test_molscribe_dir.py`

**Interfaces:**
- Consumes: `cfg.moldet["molscribe_dir"]`
- Produces: `get_model_dir()` 不再读取 `MBFORGE_MOLSCRIBE_DIR`。

- [ ] **Step 1: 重写测试**

完整替换 `tests/unit/test_molscribe_dir.py`：

```python
"""P1.4 — MolScribe 模型目录只走 cfg.moldet.molscribe_dir."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mbforge.utils import config as cfg_mod
from mbforge.utils.config import (
    reset_config_cache,
    update_settings,
)


@pytest.fixture
def tmp_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = tmp_path / "settings.json"
    legacy_cfg = tmp_path / "config.json"
    legacy_gui = tmp_path / "gui_state.json"
    monkeypatch.setattr(cfg_mod, "_SETTINGS_PATH", settings)
    monkeypatch.setattr(cfg_mod, "_LEGACY_PATHS", (legacy_cfg, legacy_gui))
    reset_config_cache()
    yield tmp_path
    reset_config_cache()


class TestGetModelDirCfgFirst:
    def test_cfg_used(self, tmp_settings: Path) -> None:
        from mbforge.parsers.molecule.molscribe_inference import download

        update_settings({"moldet": {"molscribe_dir": "/cfg/path"}})
        assert download.get_model_dir() == Path("/cfg/path")

    def test_resource_manager_used_when_cfg_empty(
        self, tmp_settings: Path
    ) -> None:
        from mbforge.parsers.molecule.molscribe_inference import download

        with patch(
            "mbforge.core.resource_manager.ResourceManager.get_molscribe_path",
            return_value=Path("/rust/path"),
        ):
            assert download.get_model_dir() == Path("/rust/path")

    def test_fallback_to_cache_dir(self, tmp_settings: Path) -> None:
        from mbforge.parsers.molecule.molscribe_inference import download

        with patch(
            "mbforge.core.resource_manager.ResourceManager.get_molscribe_path",
            return_value=None,
        ):
            result = download.get_model_dir()
            assert result.name == "MolScribe"

    def test_env_ignored(self, tmp_settings: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from mbforge.parsers.molecule.molscribe_inference import download

        monkeypatch.setenv("MBFORGE_MOLSCRIBE_DIR", "/env/path")
        result = download.get_model_dir()
        assert "env" not in str(result).lower() or result.name == "MolScribe"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/unit/test_molscribe_dir.py -v
```

Expected: 含 FAIL（env 测试失败）。

- [ ] **Step 3: 修改 `download.py`**

在 `src/mbforge/parsers/molecule/molscribe_inference/download.py`：

1. 删除 `import os`。
2. 更新 `get_model_dir` 为：

```python
def get_model_dir() -> Path:
    """获取 MolScribe 模型目录.

    优先级:
      1. ``cfg.moldet["molscribe_dir"]`` (Settings UI)
      2. ``ResourceManager.get_molscribe_path()`` (读 Rust resolved_paths.json)
      3. 缓存目录 ``<model_cache_dir>/MolScribe``
      4. 兜底 ``~/mbforge/models/MolScribe``
    """
    cfg = load_global_config()
    cfg_dir = cfg.moldet.get("molscribe_dir")
    if cfg_dir:
        return Path(cfg_dir)

    try:
        from mbforge.core.resource_manager import ResourceManager
        path = ResourceManager.get_molscribe_path()
        if path is not None:
            return path.parent if path.is_file() else path
    except ImportError:
        pass

    try:
        from mbforge.utils.paths import get_model_cache_dir
        return Path(get_model_cache_dir()) / "MolScribe"
    except ImportError:
        return Path.home() / "mbforge" / "models" / "MolScribe"
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/unit/test_molscribe_dir.py -v
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/parsers/molecule/molscribe_inference/download.py tests/unit/test_molscribe_dir.py
git commit -m "refactor(molscribe): drop MBFORGE_MOLSCRIBE_DIR env fallback"
```

---

### Task 5: PageIndex indexer 移除 env 兜底

**Files:**
- Modify: `src/mbforge/openkb/indexer.py`
- Test: 新建 `tests/unit/test_openkb_indexer.py`

**Interfaces:**
- Consumes: `cfg.pageindex_llm.api_key`
- Produces: `PageIndexClient` 初始化时 `api_key=cfg.pageindex_llm.api_key or None`

- [ ] **Step 1: 新建测试**

创建 `tests/unit/test_openkb_indexer.py`：

```python
"""PageIndex indexer 配置读取测试."""

from __future__ import annotations

from pathlib import Path

import pytest

from mbforge.utils import config as cfg_mod
from mbforge.utils.config import (
    reset_config_cache,
    update_settings,
)


@pytest.fixture
def tmp_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = tmp_path / "settings.json"
    legacy_cfg = tmp_path / "config.json"
    legacy_gui = tmp_path / "gui_state.json"
    monkeypatch.setattr(cfg_mod, "_SETTINGS_PATH", settings)
    monkeypatch.setattr(cfg_mod, "_LEGACY_PATHS", (legacy_cfg, legacy_gui))
    reset_config_cache()
    yield tmp_path
    reset_config_cache()


class TestPageIndexClientConfig:
    def test_uses_cfg_api_key(
        self, tmp_settings: Path, monkeypatch: pytest.MonPatch
    ) -> None:
        update_settings({"pageindex_llm": {"api_key": "sk-pi", "model": "gpt-4o-mini"}})
        self._mock_pageindex(monkeypatch)
        from mbforge.openkb.indexer import PageIndexWrapper

        wrapper = PageIndexWrapper(str(tmp_settings / "openkb"))
        client = wrapper._get_client()
        assert client.api_key == "sk-pi"
        assert client.model == "gpt-4o-mini"

    def test_env_pageindex_api_key_ignored(
        self, tmp_settings: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        update_settings({"pageindex_llm": {"api_key": "", "model": "gpt-4o-mini"}})
        monkeypatch.setenv("PAGEINDEX_API_KEY", "sk-env")
        self._mock_pageindex(monkeypatch)
        from mbforge.openkb.indexer import PageIndexWrapper

        wrapper = PageIndexWrapper(str(tmp_settings / "openkb"))
        client = wrapper._get_client()
        assert client.api_key is None

    def _mock_pageindex(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys

        fake = type(sys)("pageindex")

        class FakeClient:
            def __init__(self, api_key, model, storage_path):
                self.api_key = api_key
                self.model = model
                self.storage_path = storage_path

            def collection(self):
                return self

        fake.PageIndexClient = FakeClient
        monkeypatch.setitem(sys.modules, "pageindex", fake)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/unit/test_openkb_indexer.py -v
```

Expected: FAIL（当前仍读 env）。

- [ ] **Step 3: 修改 `indexer.py`**

在 `src/mbforge/openkb/indexer.py`：

1. 删除 `import os`。
2. 把 `_get_client` 改为：

```python
def _get_client(self) -> Any:
    if self._client is not None:
        return self._client

    cfg = load_global_config().pageindex_llm

    try:
        from pageindex import PageIndexClient
    except ImportError as err:
        raise RuntimeError(
            "pageindex package not installed. Run: uv add pageindex"
        ) from err

    self._storage_path.mkdir(parents=True, exist_ok=True)
    self._client = PageIndexClient(
        api_key=cfg.api_key or None,
        model=cfg.model,
        storage_path=str(self._storage_path),
    )
    return self._client
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/unit/test_openkb_indexer.py -v
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/openkb/indexer.py tests/unit/test_openkb_indexer.py
git commit -m "refactor(openkb): drop PAGEINDEX_API_KEY env fallback"
```

---

### Task 6: moldet_v2_ft 设备配置移除 env 兜底

**Files:**
- Modify: `src/mbforge/backends/moldet_v2_ft.py`
- Test: 新建 `tests/unit/test_moldet_v2_ft_device.py`

**Interfaces:**
- Consumes: `cfg.moldet["device"]`
- Produces: `MolDetv2FTDetector.device` 不再读取 `MBFORGE_DEVICE`。

- [ ] **Step 1: 新建测试**

创建 `tests/unit/test_moldet_v2_ft_device.py`：

```python
"""MolDetv2-FT device 只走 cfg.moldet.device."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mbforge.utils import config as cfg_mod
from mbforge.utils.config import (
    reset_config_cache,
    update_settings,
)


@pytest.fixture
def tmp_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = tmp_path / "settings.json"
    legacy_cfg = tmp_path / "config.json"
    legacy_gui = tmp_path / "gui_state.json"
    monkeypatch.setattr(cfg_mod, "_SETTINGS_PATH", settings)
    monkeypatch.setattr(cfg_mod, "_LEGACY_PATHS", (legacy_cfg, legacy_gui))
    reset_config_cache()
    yield tmp_path
    reset_config_cache()


class TestDeviceConfig:
    def test_device_from_cfg(
        self, tmp_settings: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        update_settings({"moldet": {"device": "cuda:0"}})
        monkeypatch.setenv("MBFORGE_DEVICE", "cpu")
        from mbforge.backends.moldet_v2_ft import MolDetv2FTDetector

        with (
            patch("mbforge.backends.moldet_v2_ft._has_ultralytics", return_value=True),
            patch.object(
                MolDetv2FTDetector, "_resolve_model_path", return_value=Path("/tmp/best.pt")
            ),
            patch("mbforge.backends.moldet_v2_ft.YOLO"),
        ):
            det = MolDetv2FTDetector()
            assert det.device == "cuda:0"

    def test_default_auto_when_cfg_empty(
        self, tmp_settings: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mbforge.backends.moldet_v2_ft import MolDetv2FTDetector

        with (
            patch("mbforge.backends.moldet_v2_ft._has_ultralytics", return_value=True),
            patch.object(
                MolDetv2FTDetector, "_resolve_model_path", return_value=Path("/tmp/best.pt")
            ),
            patch("mbforge.backends.moldet_v2_ft.YOLO"),
        ):
            det = MolDetv2FTDetector()
            assert det.device == "auto"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/unit/test_moldet_v2_ft_device.py -v
```

Expected: FAIL（当前读 env）。

- [ ] **Step 3: 修改 `moldet_v2_ft.py`**

在 `src/mbforge/backends/moldet_v2_ft.py`：

1. 删除 `import os`。
2. 新增：

```python
from mbforge.utils.config import load_global_config
```

3. 把：

```python
self.device = device or os.getenv("MBFORGE_DEVICE", "auto")
```

改为：

```python
self.device = device or load_global_config().moldet.get("device", "auto")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/unit/test_moldet_v2_ft_device.py -v
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/backends/moldet_v2_ft.py tests/unit/test_moldet_v2_ft_device.py
git commit -m "refactor(moldet): drop MBFORGE_DEVICE env fallback in v2_ft"
```

---

### Task 7: 修正 resource_manager 过时 docstring

**Files:**
- Modify: `src/mbforge/core/resource_manager.py`

**Interfaces:**
- 无代码行为变更，仅注释对齐现实。

- [ ] **Step 1: 修改两处 docstring**

`_check_model_snapshot` 上方的注释：

```python
"""检查 snapshot 类型模型是否已下载.

按目录优先级顺序搜索:
1. MBForge 缓存目录（由 settings.json 的 model_cache_dir 决定）
2. HF_HOME
3. MODELSCOPE_CACHE（env + 默认）
4. TORCH_HOME
"""
```

`_check_model_file` 上方的注释：

```python
"""检查单文件/snapshot 类型模型是否已下载.

搜索顺序: MBForge cache → HF_HOME → MODELSCOPE_CACHE → TORCH_HOME
每个目录下同时搜索直接文件、子目录和 ModelScope 新旧 SDK 布局。
"""
```

- [ ] **Step 2: Commit**

```bash
git add src/mbforge/core/resource_manager.py
git commit -m "docs(resource_manager): remove stale MBFORGE_MODEL_CACHE_DIR env mention"
```

---

### Task 8: 全量验证

- [ ] **Step 1: Lint**

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/ --check
```

Expected: All checks passed。

- [ ] **Step 2: 单元测试**

```bash
uv run pytest tests/unit/ -q
```

Expected: 全部 PASS。

- [ ] **Step 3: Commit（如只有格式修复）**

```bash
git commit -am "style: ruff format fixes"
```

---

## Spec Coverage Check

- `AppConfig` JSON-only ✅ Task 1
- LLM factory 不读 `MBFORGE_LLM_*` ✅ Task 2
- Agent router 不检查 `MBFORGE_LLM_API_KEY` ✅ Task 3
- MolScribe 目录不读 `MBFORGE_MOLSCRIBE_DIR` ✅ Task 4
- PageIndex 不读 `PAGEINDEX_API_KEY` ✅ Task 5
- moldet_v2_ft 不读 `MBFORGE_DEVICE` ✅ Task 6
- 过时 docstring 清理 ✅ Task 7
- 全量 lint/test 验证 ✅ Task 8

## Placeholder Scan

无 TBD / TODO / 待实现占位；每个任务含完整代码与命令。
