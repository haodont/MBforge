# 业务配置 JSON-only 设计

## 目标
所有业务配置统一从 `settings.json` 读取，不再读取任何 `MBFORGE_*` 业务环境变量。旧的业务 env 字段直接忽略，不做兼容/迁移/告警。

## 范围

### 业务配置（移除 env 兜底）
- LLM：`provider`、`base_url`、`api_key`、`model`、`temperature`、`max_tokens`
- VLM / OCR：provider、base_url、api_key、model 等
- PageIndex LLM
- `model_cache_dir`
- `moldet.device`、`moldet.molscribe_dir`

### 保留的运行时/基础设施 env（白名单）
这些不属于业务配置，保持不动：
- `MBFORGE_HOST`、`FRONTEND_DIST`
- `MBFORGE_LOG_LEVEL`
- `MBFORGE_FORCE_CPU`
- `MBFORGE_IN_DOCKER`、`MBFORGE_NO_BROWSER`
- `HF_HOME`、`MODELSCOPE_CACHE`、`TORCH_HOME`、`HF_ENDPOINT`
- 系统级 `APPDATA`、`HOME`

## 改动清单

1. `src/mbforge/utils/config.py`
   - `AppConfig` 从 `BaseSettings` 改为 `BaseModel`。
   - 移除 `env_prefix="MBFORGE_"`。
   - `load_global_config` 行为不变：读 `settings.json`，缺失/损坏则回默认值并持久化。

2. `src/mbforge/agent/llm_factory.py`
   - 删除 `import os` 与 `os.environ.get("MBFORGE_LLM_API_KEY", "")`。
   - `_resolve_api_key` 改为 `arg or cfg_key`。
   - 优先级改为：`显式参数 > AppConfig.llm > 默认值`。
   - 更新 docstring。

3. `src/mbforge/routers/agent.py`
   - `ensure_initialized` 只检查 `cfg.api_key`，不再检查 `MBFORGE_LLM_API_KEY`。
   - 移除多余的 `import os`。

4. `src/mbforge/parsers/molecule/molscribe_inference/download.py`
   - 移除 `MBFORGE_MOLSCRIBE_DIR` env 兜底。
   - 改为读取 `load_global_config().moldet.get("molscribe_dir")` 或默认值。

5. `src/mbforge/core/resource_manager.py`
   - 移除 `MBFORGE_MODEL_CACHE_DIR` env 兜底。
   - 改为读取 `load_global_config().model_cache_dir`。

6. `src/mbforge/openkb/indexer.py`
   - 移除 `PAGEINDEX_API_KEY` env 兜底。
   - 改为读取 `load_global_config().pageindex_llm.api_key`。

7. `src/mbforge/backends/moldet_v2_ft.py`
   - 移除 `MBFORGE_DEVICE` env 兜底。
   - 改为读取 `load_global_config().moldet.get("device", "auto")`。

8. 测试
   - 更新 `tests/unit/test_moldet_device.py` 等依赖 env 的测试，改用 `update_settings` 注入配置。
   - 新增断言：`AppConfig` 不再受 `MBFORGE_LLM_API_KEY` 等业务 env 影响。

9. 文档
   - 更新 `.env.template`：删除业务配置变量，或标注“已弃用，请通过 Settings UI 配置”。
   - 更新 `docs/` 中涉及 env 配置的说明。

## 错误处理
- 缺少必需字段（如 `llm.api_key`）时，由 `create_llm` 抛出 `ValueError`，提示通过 Settings UI 配置。
- 不检测、不告警、不迁移旧业务 env。

## 不做的
- 不在启动时扫描旧 env 并提示。
- 不自动把旧 env 写入 `settings.json`。
- 不保留任何业务 env 作为 fallback。
