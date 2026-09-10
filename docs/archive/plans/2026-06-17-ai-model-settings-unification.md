# AI 模型设置页风格统一与可编辑实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 LLM / Embedding / Reranker / VLM / OCR 五个 AI 模型设置子页统一为可编辑的卡片风格，并把 LLM 从只读环境变量驱动改为可编辑（环境变量优先，`config.json` 回退）。

**Architecture:** 后端 `MbforgeProviderConfig::from_app_config()` 保持无参签名，内部先读 `.env`、再回退到 `AppConfig::load()`，避免改动所有调用点。前端新增可复用 `ModelConfigCard` 组件，所有子页共享该组件渲染连接信息和高级参数，LLM 页在卡片内保留 Test 按钮。

**Tech Stack:** React 19 + TypeScript 6 + Vite 8 + react-i18next + Tauri + Rust

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src-tauri/src/core/agent/rig_adapter.rs` | LLM provider config resolution (env-first + config.json fallback) |
| `src-tauri/src/commands/llm.rs` | LLM status/test commands, updated comments |
| `frontend/src/components/settings/ModelConfigCard.tsx` | New reusable card component for all 5 model types |
| `frontend/src/components/settings/sections/AIModelsSection.tsx` | Refactored to render `ModelConfigCard` per tab |
| `frontend/src/components/settings/LlmStatusCard.tsx` | Deleted (functionality absorbed into ModelConfigCard) |
| `frontend/src/components/settings/LlmTab.tsx` | Unchanged wrapper (already delegates to AIModelsSection) |
| `frontend/src/i18n/locales/en.json` | New LLM editable field keys |
| `frontend/src/i18n/locales/zh-CN.json` | New LLM editable field keys |

---

## Task 1: Backend — env-first config resolution

**Files:**
- Modify: `src-tauri/src/core/agent/rig_adapter.rs:126-185`

### Step 1.1: Extract a validation helper

Add a private helper after the existing `first_nonempty` helper (around line 124):

```rust
impl MbforgeProviderConfig {
    fn validate_and_build(
        kind: MbforgeProviderKind,
        base_url: String,
        api_key: String,
        model: String,
        timeout_secs: u64,
    ) -> Result<Self, String> {
        if base_url.trim().is_empty() {
            return Err(format!(
                "LLM base_url is not configured. Set `MBFORGE_LLM_BASE_URL` in the project-root .env \
                 or in Settings > AI Models > LLM. Examples: https://api.openai.com/v1, \
                 https://openrouter.ai/api/v1, https://api.deepseek.com/v1, or a self-hosted \
                 llama.cpp server."
            ));
        }
        if api_key.trim().is_empty() {
            return Err(format!(
                "LLM api_key is not configured. Set `MBFORGE_LLM_API_KEY` in the project-root .env \
                 or in Settings > AI Models > LLM."
            ));
        }
        if model.trim().is_empty() {
            return Err(format!(
                "LLM model is not configured. Set `MBFORGE_LLM_MODEL` in the project-root .env \
                 or in Settings > AI Models > LLM."
            ));
        }
        Ok(Self {
            kind,
            base_url,
            api_key,
            model,
            timeout_secs,
            anthropic_betas: Vec::new(),
        })
    }
}
```

### Step 1.2: Replace `from_app_config` body with env + config fallback

Replace `pub fn from_app_config() -> Result<Self, String> { ... }` (lines 144–185) with:

```rust
    pub fn from_app_config() -> Result<Self, String> {
        // 1. Environment variables take precedence. If MBFORGE_LLM_PROVIDER is
        // set, we use the full env-driven config (existing behavior).
        if let Some(provider) = std::env::var("MBFORGE_LLM_PROVIDER")
            .ok()
            .filter(|s| !s.trim().is_empty())
        {
            let kind = match provider.as_str() {
                "anthropic" => MbforgeProviderKind::Anthropic,
                "deepseek" => MbforgeProviderKind::DeepSeek,
                "ollama" => MbforgeProviderKind::Ollama,
                _ => MbforgeProviderKind::OpenAICompatible,
            };
            let env = |k: &str| std::env::var(k).ok().filter(|s| !s.trim().is_empty());
            let base_url = env("MBFORGE_LLM_BASE_URL").unwrap_or_default();
            let api_key = env("MBFORGE_LLM_API_KEY").unwrap_or_default();
            let model = env("MBFORGE_LLM_MODEL").unwrap_or_default();
            let timeout_secs = env("MBFORGE_LLM_REQUEST_TIMEOUT")
                .and_then(|v| v.parse().ok())
                .unwrap_or(120);
            return Self::validate_and_build(kind, base_url, api_key, model, timeout_secs);
        }

        // 2. Fallback to config.json (Settings UI can edit these values).
        let config = crate::core::config::settings::AppConfig::load();
        let llm = &config.llm;
        let kind = match llm.provider.as_str() {
            "anthropic" => MbforgeProviderKind::Anthropic,
            "deepseek" => MbforgeProviderKind::DeepSeek,
            "ollama" => MbforgeProviderKind::Ollama,
            _ => MbforgeProviderKind::OpenAICompatible,
        };
        Self::validate_and_build(
            kind,
            llm.base_url.clone(),
            llm.api_key.clone(),
            llm.model_name.clone(),
            llm.request_timeout as u64,
        )
    }
```

### Step 1.3: Update module-level doc comment

Replace the paragraph in the module doc comment (around lines 21–25) from:

```rust
//! Both providers read the **full** LLM config from environment variables
//! (`MBFORGE_LLM_PROVIDER` / `MBFORGE_LLM_BASE_URL` / `MBFORGE_LLM_API_KEY`
//! / `MBFORGE_LLM_MODEL`). The Settings UI displays these values read-only
//! and runs a connectivity test on app load; it cannot override them.
```

with:

```rust
//! Both providers read the LLM config with the following precedence:
//!
//! 1. Environment variables (`MBFORGE_LLM_*`) if `MBFORGE_LLM_PROVIDER` is set.
//! 2. `AppConfig::load()` (i.e. `config.json` populated by Settings UI).
//!
//! The Settings UI can now edit provider, base URL, API key, model and
//! sampling parameters. Existing `.env` setups continue to win over UI values.
```

### Step 1.4: Update the doc comment on `from_app_config`

Replace the doc comment above `from_app_config` (lines 126–143) with:

```rust
    /// Build a config from environment variables (`.env` injected at startup)
    /// with a fallback to `config.json`.
    ///
    /// Resolution order:
    /// 1. If `MBFORGE_LLM_PROVIDER` is set in the environment, use all
    ///    `MBFORGE_LLM_*` env vars. This preserves backward compatibility for
    ///    users who currently configure LLM via `.env`.
    /// 2. Otherwise load `AppConfig` from `config.json` and use `AppConfig.llm`.
    ///    These values are editable in Settings > AI Models > LLM.
    ///
    /// If required fields are missing in both sources, returns an error.
```

### Step 1.5: Build the backend

Run:

```bash
cd /c/Users/10954/Desktop/MBForge/src-tauri
cargo check
```

Expected: no errors.

### Step 1.6: Commit

```bash
cd /c/Users/10954/Desktop/MBForge
git add src-tauri/src/core/agent/rig_adapter.rs
git commit -m "feat(settings): allow LLM config from config.json with env precedence"
```

---

## Task 2: Backend — update LLM status/test command comments

**Files:**
- Modify: `src-tauri/src/commands/llm.rs:1-8`

### Step 2.1: Update module doc comment

Replace the first doc comment block with:

```rust
//! Tauri commands that surface the active LLM config to the Settings UI and
//! run a connectivity probe against the provider's endpoint.
//!
//! The active config follows the precedence defined in
//! `MbforgeProviderConfig::from_app_config`: `.env` wins, then `config.json`.
//! The frontend calls `get_llm_env_config` to display the resolved values,
//! and `test_llm_connection` to verify the endpoint is reachable.
```

### Step 2.2: Rename `from_env` and update its comment

Replace `LlmEnvStatus::from_env` (lines 51–68) with:

```rust
    /// Read the currently active LLM config (env or config.json) and return a
    /// status view. Mirrors `MbforgeProviderConfig::from_app_config` precedence.
    fn from_active_config() -> Result<Self, String> {
        let cfg = MbforgeProviderConfig::from_app_config()?;
        Ok(Self {
            provider: cfg.kind.as_str().to_string(),
            base_url: cfg.base_url,
            api_key_set: !cfg.api_key.is_empty(),
            model: cfg.model,
            status: LlmLinkStatus::Ok, // configured — not yet probed
            error: None,
            http_status: None,
            latency_ms: None,
        })
    }
```

Update the two call sites inside `llm.rs`:
- Line 75 (`get_llm_env_config`): `LlmEnvStatus::from_env()` → `LlmEnvStatus::from_active_config()`
- Line 98 (`test_llm_connection`): `LlmEnvStatus::from_env()?` → `LlmEnvStatus::from_active_config()?`

### Step 2.3: Build the backend

Run:

```bash
cd /c/Users/10954/Desktop/MBForge/src-tauri
cargo check
```

Expected: no errors.

### Step 2.4: Commit

```bash
cd /c/Users/10954/Desktop/MBForge
git add src-tauri/src/commands/llm.rs
git commit -m "refactor(settings): align LLM status command with env/config precedence"
```

---

## Task 3: Frontend — create ModelConfigCard component

**Files:**
- Create: `frontend/src/components/settings/ModelConfigCard.tsx`

### Step 3.1: Write the component

```tsx
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getLlmEnvConfig, testLlmConnection, type LlmEnvStatus } from '../../api/tauri/agent'
import SettingSection, { SettingGroup, SettingItem } from '../ui/SettingSection'
import Button from '../ui/Button'
import Spinner from '../ui/Spinner'
import {
  NumberField,
  ProviderField,
  ToggleField,
} from './SettingRow'
import ApiKeyInput from './ApiKeyInput'
import { ModelSelector } from './ModelComponents'
import {
  EMBED_MODELS,
  LLM_MODELS,
  OCR_MODELS,
  PROVIDER_META,
  RERANK_MODELS,
  VLM_MODELS,
} from './modelConfigs'
import type { SettingsState } from './types'

type ModelType = 'llm' | 'embed' | 'rerank' | 'vlm' | 'ocr'

interface Props {
  modelType: ModelType
  title: string
  description?: string
  settings: SettingsState
  setSettings: React.Dispatch<React.SetStateAction<SettingsState>>
  showTest?: boolean
}

const STATUS_TONE: Record<NonNullable<LlmEnvStatus['status']>, 'ok' | 'warn' | 'error' | 'idle'> = {
  not_configured: 'warn',
  ok: 'ok',
  unreachable: 'error',
  http_error: 'error',
  auth_error: 'error',
}

const STATUS_COLOR: Record<'ok' | 'warn' | 'error' | 'idle', string> = {
  ok: '#10b981',
  warn: '#f59e0b',
  error: '#ef4444',
  idle: '#6b7280',
}

const providerOptions = (map: Record<string, unknown>) =>
  Object.keys(map).map(k => ({
    value: k,
    label: (PROVIDER_META[k] ?? { label: k }).label,
  }))

const getProviderMeta = (key: string) =>
  PROVIDER_META[key] ?? { label: key, defaultUrl: '', needsKey: false }

export default function ModelConfigCard({
  modelType,
  title,
  description,
  settings,
  setSettings,
  showTest,
}: Props) {
  const { t } = useTranslation()
  const [testStatus, setTestStatus] = useState<LlmEnvStatus | null>(null)
  const [testing, setTesting] = useState(false)

  // Load the current active LLM config once on mount (env or saved config).
  // This only reads the resolved config; it does not perform a network probe.
  useEffect(() => {
    if (!showTest) return
    let cancelled = false
    getLlmEnvConfig()
      .then(s => { if (!cancelled) setTestStatus(s) })
      .catch(() => { /* ignore initial load errors; user can hit Test */ })
    return () => { cancelled = true }
  }, [showTest])

  const update = <K extends keyof SettingsState>(key: K, value: SettingsState[K]) => {
    setSettings(s => ({ ...s, [key]: value }))
  }

  const runTest = async () => {
    setTesting(true)
    try {
      const s = await testLlmConnection()
      setTestStatus(s)
    } catch (e) {
      setTestStatus({
        provider: '',
        base_url: '',
        api_key_set: false,
        model: '',
        status: 'unreachable',
        error: e instanceof Error ? e.message : String(e),
        http_status: null,
        latency_ms: null,
      } as LlmEnvStatus)
    } finally {
      setTesting(false)
    }
  }

  const statusTone = testStatus ? STATUS_TONE[testStatus.status] : null
  const statusColor = statusTone ? STATUS_COLOR[statusTone] : undefined

  return (
    <div className="model-config-card" style={cardStyle}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 16 }}>
        <div>
          <h3 style={{ margin: '0 0 4px', fontSize: 15, fontWeight: 600 }}>{title}</h3>
          {description && (
            <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>{description}</p>
          )}
        </div>
        {showTest && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
            {testStatus && statusColor && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: '50%',
                    background: statusColor,
                    boxShadow: `0 0 6px ${statusColor}`,
                  }}
                />
                <span style={{ color: statusColor }}>{t(`settings.llmStatus.${testStatus.status}`)}</span>
                {testStatus.latency_ms != null && (
                  <span style={{ color: 'var(--text-muted)' }}>({testStatus.latency_ms} ms)</span>
                )}
              </div>
            )}
            <Button size="sm" variant="secondary" onClick={runTest} disabled={testing}>
              {testing ? <Spinner size={12} /> : t('settings.testConnection')}
            </Button>
          </div>
        )}
      </div>

      <SettingSection>
        <SettingGroup title={t('settings.connectionGroup')}>
          {modelType === 'llm' && (
            <>
              <ProviderField
                label={t('settings.llmProvider')}
                description={t('settings.llmProviderDesc')}
                provider={settings.llm_provider}
                onProviderChange={v => update('llm_provider', v)}
                baseUrl={settings.llm_base_url}
                onBaseUrlChange={v => update('llm_base_url', v)}
                apiKey={settings.llm_api_key}
                onApiKeyChange={v => update('llm_api_key', v)}
                providerOptions={providerOptions(LLM_MODELS)}
                needsKey={getProviderMeta(settings.llm_provider).needsKey}
                baseUrlPlaceholder={getProviderMeta(settings.llm_provider).defaultUrl}
              />
              <SettingItem title={t('settings.llmModel')} layout="stacked">
                <ModelSelector
                  provider={settings.llm_provider}
                  modelValue={settings.llm_model}
                  models={LLM_MODELS}
                  onChange={v => update('llm_model', v)}
                />
              </SettingItem>
            </>
          )}

          {modelType === 'embed' && (
            <>
              <ProviderField
                label={t('settings.embedProvider')}
                description={t('settings.embedProviderDesc')}
                provider={settings.embed_provider}
                onProviderChange={v => update('embed_provider', v)}
                baseUrl={settings.embed_base_url}
                onBaseUrlChange={v => update('embed_base_url', v)}
                apiKey={settings.embed_api_key}
                onApiKeyChange={v => update('embed_api_key', v)}
                providerOptions={providerOptions(EMBED_MODELS)}
                needsKey={getProviderMeta(settings.embed_provider).needsKey}
                baseUrlPlaceholder={getProviderMeta(settings.embed_provider).defaultUrl}
                showBaseUrl={settings.embed_provider === 'openai'}
              />
              <SettingItem title={t('settings.model')} layout="stacked">
                <ModelSelector
                  provider={settings.embed_provider}
                  modelValue={settings.embed_model}
                  models={EMBED_MODELS}
                  onChange={v => update('embed_model', v)}
                />
              </SettingItem>
              <SettingItem title={t('settings.instruction')} layout="stacked">
                <input
                  className="settings-input"
                  type="text"
                  value={settings.embed_instruction}
                  onChange={e => update('embed_instruction', e.target.value)}
                  placeholder={t('settings.instructionPlaceholder')}
                  style={{ width: '100%' }}
                />
              </SettingItem>
            </>
          )}

          {modelType === 'rerank' && (
            <>
              <ProviderField
                label={t('settings.rerankProvider')}
                description={t('settings.rerankProviderDesc')}
                provider={settings.rerank_provider}
                onProviderChange={v => update('rerank_provider', v)}
                baseUrl=""
                onBaseUrlChange={() => {}}
                apiKey=""
                onApiKeyChange={() => {}}
                providerOptions={providerOptions(RERANK_MODELS)}
                needsKey={false}
                showBaseUrl={false}
              />
              <SettingItem title={t('settings.model')} layout="stacked">
                <ModelSelector
                  provider={settings.rerank_provider}
                  modelValue={settings.rerank_model}
                  models={RERANK_MODELS}
                  onChange={v => update('rerank_model', v)}
                />
              </SettingItem>
            </>
          )}

          {modelType === 'vlm' && (
            <>
              <ProviderField
                label={t('settings.vlmProvider')}
                description={t('settings.vlmProviderDesc')}
                provider={settings.vlm_provider}
                onProviderChange={v => update('vlm_provider', v)}
                baseUrl={settings.vlm_base_url}
                onBaseUrlChange={v => update('vlm_base_url', v)}
                apiKey={settings.vlm_api_key}
                onApiKeyChange={v => update('vlm_api_key', v)}
                providerOptions={providerOptions(VLM_MODELS)}
                needsKey={getProviderMeta(settings.vlm_provider).needsKey}
                baseUrlPlaceholder={getProviderMeta(settings.vlm_provider).defaultUrl}
              />
              <SettingItem title={t('settings.model')} layout="stacked">
                <ModelSelector
                  provider={settings.vlm_provider}
                  modelValue={settings.vlm_model}
                  models={VLM_MODELS}
                  onChange={v => update('vlm_model', v)}
                />
              </SettingItem>
            </>
          )}

          {modelType === 'ocr' && (
            <>
              <ProviderField
                label={t('settings.ocrProvider')}
                description={t('settings.ocrProviderDesc')}
                provider={settings.ocr_provider}
                onProviderChange={v => update('ocr_provider', v)}
                baseUrl={settings.ocr_base_url}
                onBaseUrlChange={v => update('ocr_base_url', v)}
                apiKey={settings.ocr_api_key}
                onApiKeyChange={v => update('ocr_api_key', v)}
                providerOptions={providerOptions(OCR_MODELS)}
                needsKey={getProviderMeta(settings.ocr_provider).needsKey}
                baseUrlPlaceholder={getProviderMeta(settings.ocr_provider).defaultUrl}
              />
              <SettingItem title={t('settings.model')} layout="stacked">
                <ModelSelector
                  provider={settings.ocr_provider}
                  modelValue={settings.ocr_model}
                  models={OCR_MODELS}
                  onChange={v => update('ocr_model', v)}
                />
              </SettingItem>
            </>
          )}
        </SettingGroup>

        {modelType === 'llm' && (
          <SettingGroup title={t('settings.llmSampling')}>
            <NumberField
              label={t('settings.maxTokens')}
              description={t('settings.maxTokensDesc')}
              value={settings.llm_max_tokens}
              onChange={v => update('llm_max_tokens', v)}
              min={1}
              max={65536}
              step={128}
              width={120}
            />
            <NumberField
              label={t('settings.temperature')}
              description={t('settings.temperatureDesc')}
              value={settings.llm_temperature}
              onChange={v => update('llm_temperature', v)}
              min={0}
              max={2}
              step={0.1}
              width={100}
            />
            <NumberField
              label={t('settings.topP')}
              description={t('settings.topPDesc')}
              value={settings.llm_top_p}
              onChange={v => update('llm_top_p', v)}
              min={0}
              max={1}
              step={0.05}
              width={100}
            />
            <NumberField
              label={t('settings.requestTimeout')}
              description={t('settings.requestTimeoutDesc')}
              value={settings.llm_request_timeout}
              onChange={v => update('llm_request_timeout', v)}
              min={1}
              max={600}
              step={10}
              width={120}
            />
          </SettingGroup>
        )}

        {modelType === 'embed' && (
          <SettingGroup title={t('settings.embedRuntime')}>
            <ProviderField
              label={t('settings.device')}
              description={t('settings.deviceDesc')}
              provider={settings.embed_device}
              onProviderChange={v => update('embed_device', v as SettingsState['embed_device'])}
              baseUrl=""
              onBaseUrlChange={() => {}}
              apiKey=""
              onApiKeyChange={() => {}}
              providerOptions={[
                { value: 'cpu', label: 'CPU' },
                { value: 'cuda', label: 'CUDA' },
                { value: 'auto', label: 'Auto' },
              ]}
              needsKey={false}
              showBaseUrl={false}
            />
            <NumberField
              label={t('settings.mrlDim')}
              description={t('settings.mrlDimDesc')}
              value={settings.embed_mrl_dim}
              onChange={v => update('embed_mrl_dim', v)}
              min={0}
              max={4096}
              step={64}
              width={100}
              placeholder="0"
            />
          </SettingGroup>
        )}

        {modelType === 'rerank' && (
          <SettingGroup title={t('settings.rerankRuntime')}>
            <ProviderField
              label={t('settings.device')}
              description={t('settings.deviceDesc')}
              provider={settings.rerank_device}
              onProviderChange={v => update('rerank_device', v as SettingsState['rerank_device'])}
              baseUrl=""
              onBaseUrlChange={() => {}}
              apiKey=""
              onApiKeyChange={() => {}}
              providerOptions={[
                { value: 'cpu', label: 'CPU' },
                { value: 'cuda', label: 'CUDA' },
                { value: 'auto', label: 'Auto' },
              ]}
              needsKey={false}
              showBaseUrl={false}
            />
            <NumberField
              label={t('settings.maxLength')}
              description={t('settings.maxLengthDesc')}
              value={settings.rerank_max_length}
              onChange={v => update('rerank_max_length', v)}
              min={128}
              max={32768}
              step={256}
              width={120}
              placeholder="8192"
            />
          </SettingGroup>
        )}

        {modelType === 'ocr' && (
          <>
            <SettingGroup title={t('settings.ocrFlags')}>
              <ToggleField
                label={t('settings.useHfMirror')}
                description={t('settings.useHfMirrorDesc')}
                value={settings.ocr_use_hf_mirror}
                onChange={v => update('ocr_use_hf_mirror', v)}
              />
              <ToggleField
                label={t('settings.usePdfInspector')}
                description={t('settings.usePdfInspectorDesc')}
                value={settings.ocr_use_pdf_inspector}
                onChange={v => update('ocr_use_pdf_inspector', v)}
              />
            </SettingGroup>
            <OcrBackendKeys settings={settings} setSettings={setSettings} />
          </>
        )}
      </SettingSection>

      {testStatus?.error && (
        <div style={errorStyle}>{testStatus.error}</div>
      )}
    </div>
  )
}

function OcrBackendKeys({ settings, setSettings }: { settings: SettingsState; setSettings: React.Dispatch<React.SetStateAction<SettingsState>> }) {
  const { t } = useTranslation()
  const update = <K extends keyof SettingsState>(key: K, value: SettingsState[K]) => {
    setSettings(s => ({ ...s, [key]: value }))
  }

  return (
    <SettingGroup title={t('ocr.backendSection.title')}>
      <p style={{ margin: '0 0 12px', fontSize: 12, color: 'var(--text-muted)' }}>
        {t('ocr.backendSection.desc')}
      </p>
      <BackendKeyRow
        label={t('ocr.config.mineru')}
        placeholder="eyJ0eXBlIjoiSldU..."
        value={settings.ocr_mineru_api_key}
        onChange={v => update('ocr_mineru_api_key', v)}
      />
      <BackendKeyRow
        label={t('ocr.config.uniparser')}
        placeholder="up_..."
        value={settings.ocr_uniparser_api_key}
        onChange={v => update('ocr_uniparser_api_key', v)}
      />
      <BackendKeyRow
        label={t('ocr.config.paddleocr')}
        placeholder="bearer token"
        value={settings.ocr_paddleocr_api_key}
        onChange={v => update('ocr_paddleocr_api_key', v)}
        extra={[
          {
            label: t('ocr.config.paddleocrHost'),
            value: settings.ocr_paddleocr_host,
            onChange: v => update('ocr_paddleocr_host', v),
            placeholder: 'https://paddleocr.aistudio-app.com',
          },
          {
            label: t('ocr.config.paddleocrModel'),
            value: settings.ocr_paddleocr_model,
            onChange: v => update('ocr_paddleocr_model', v),
            placeholder: 'PaddleOCR-VL-1.6',
          },
        ]}
      />
    </SettingGroup>
  )
}

interface BackendKeyRowProps {
  label: string
  placeholder: string
  value: string
  onChange: (v: string) => void
  extra?: Array<{
    label: string
    value: string
    onChange: (v: string) => void
    placeholder: string
  }>
}

function BackendKeyRow({ label, placeholder, value, onChange, extra }: BackendKeyRowProps) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--text-primary)' }}>
        {label}
      </label>
      <ApiKeyInput value={value} onChange={onChange} placeholder={placeholder} />
      {extra && extra.length > 0 && (
        <div style={{ marginTop: 8, display: 'grid', gap: 6 }}>
          {extra.map(e => (
            <div key={e.label} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <label style={{ fontSize: 11, color: 'var(--text-muted)', minWidth: 80 }}>{e.label}</label>
              <input
                type="text"
                value={e.value}
                onChange={ev => e.onChange(ev.target.value)}
                placeholder={e.placeholder}
                style={{
                  flex: 1,
                  padding: '6px 8px',
                  fontSize: 12,
                  border: '1px solid var(--border)',
                  borderRadius: 4,
                  background: 'var(--bg-base)',
                  color: 'var(--text-primary)',
                  fontFamily: 'var(--font-mono, monospace)',
                }}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const cardStyle: React.CSSProperties = {
  padding: 20,
  border: '1px solid var(--border)',
  borderRadius: 12,
  background: 'var(--bg-surface)',
  boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
}

const errorStyle: React.CSSProperties = {
  marginTop: 12,
  padding: 10,
  background: 'rgba(239, 68, 68, 0.08)',
  border: '1px solid rgba(239, 68, 68, 0.3)',
  borderRadius: 6,
  color: '#ef4444',
  fontSize: 12,
  fontFamily: 'monospace',
  wordBreak: 'break-all',
}
```

### Step 3.2: Add card CSS (optional)

Append to `frontend/src/styles/settings.css` if the file exists and contains card utilities:

```css
.model-config-card {
  /* cardStyle inline handles the look; keep this class for future theming */
}
```

If `settings.css` is not the right place, skip this step.

### Step 3.3: Verify TypeScript

Run:

```bash
cd /c/Users/10954/Desktop/MBForge/frontend
npx tsc --noEmit
```

Expected: no errors from the new file.

### Step 3.4: Commit

```bash
cd /c/Users/10954/Desktop/MBForge
git add frontend/src/components/settings/ModelConfigCard.tsx
git commit -m "feat(settings): add reusable ModelConfigCard component"
```

---

## Task 4: Frontend — refactor AIModelsSection

**Files:**
- Modify: `frontend/src/components/settings/sections/AIModelsSection.tsx`
- Delete: `frontend/src/components/settings/LlmStatusCard.tsx`

### Step 4.1: Replace AIModelsSection body

Replace the entire content of `AIModelsSection.tsx` with:

```tsx
// AI Models 栏目 — LLM / Embedding / Reranker / VLM / OCR 五个 tab。
// 所有子页共享 ModelConfigCard，风格统一且全部可编辑。

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Tabs, { TabPanel } from '../../ui/Tabs'
import ModelConfigCard from '../ModelConfigCard'
import type { SettingsState } from '../types'

type Tab = 'llm' | 'embed' | 'rerank' | 'vlm' | 'ocr'

interface Props {
  settings: SettingsState
  setSettings: React.Dispatch<React.SetStateAction<SettingsState>>
}

const TAB_CONFIG: Record<Tab, { titleKey: string; descKey?: string; showTest?: boolean }> = {
  llm: { titleKey: 'settings.tabLlm', descKey: 'settings.tabLlmDesc', showTest: true },
  embed: { titleKey: 'settings.tabEmbed', descKey: 'settings.tabEmbedDesc' },
  rerank: { titleKey: 'settings.tabRerank', descKey: 'settings.tabRerankDesc' },
  vlm: { titleKey: 'settings.tabVlm', descKey: 'settings.tabVlmDesc' },
  ocr: { titleKey: 'settings.tabOcr', descKey: 'settings.tabOcrDesc' },
}

export default function AIModelsSection({ settings, setSettings }: Props) {
  const { t } = useTranslation()
  const [tab, setTab] = useState<Tab>('llm')

  return (
    <>
      <Tabs
        items={[
          { key: 'llm', label: t('settings.tabLlm') },
          { key: 'embed', label: t('settings.tabEmbed') },
          { key: 'rerank', label: t('settings.tabRerank') },
          { key: 'vlm', label: t('settings.tabVlm') },
          { key: 'ocr', label: t('settings.tabOcr') },
        ]}
        activeKey={tab}
        onChange={k => setTab(k as Tab)}
        variant="underline"
        size="sm"
      />

      <TabPanel activeKey={tab} tabKey="llm">
        <ModelConfigCard
          modelType="llm"
          title={t(TAB_CONFIG.llm.titleKey)}
          description={TAB_CONFIG.llm.descKey ? t(TAB_CONFIG.llm.descKey) : undefined}
          settings={settings}
          setSettings={setSettings}
          showTest={TAB_CONFIG.llm.showTest}
        />
      </TabPanel>

      <TabPanel activeKey={tab} tabKey="embed">
        <ModelConfigCard
          modelType="embed"
          title={t(TAB_CONFIG.embed.titleKey)}
          description={TAB_CONFIG.embed.descKey ? t(TAB_CONFIG.embed.descKey) : undefined}
          settings={settings}
          setSettings={setSettings}
        />
      </TabPanel>

      <TabPanel activeKey={tab} tabKey="rerank">
        <ModelConfigCard
          modelType="rerank"
          title={t(TAB_CONFIG.rerank.titleKey)}
          description={TAB_CONFIG.rerank.descKey ? t(TAB_CONFIG.rerank.descKey) : undefined}
          settings={settings}
          setSettings={setSettings}
        />
      </TabPanel>

      <TabPanel activeKey={tab} tabKey="vlm">
        <ModelConfigCard
          modelType="vlm"
          title={t(TAB_CONFIG.vlm.titleKey)}
          description={TAB_CONFIG.vlm.descKey ? t(TAB_CONFIG.vlm.descKey) : undefined}
          settings={settings}
          setSettings={setSettings}
        />
      </TabPanel>

      <TabPanel activeKey={tab} tabKey="ocr">
        <ModelConfigCard
          modelType="ocr"
          title={t(TAB_CONFIG.ocr.titleKey)}
          description={TAB_CONFIG.ocr.descKey ? t(TAB_CONFIG.ocr.descKey) : undefined}
          settings={settings}
          setSettings={setSettings}
        />
      </TabPanel>
    </>
  )
}
```

### Step 4.2: Delete LlmStatusCard

```bash
rm /c/Users/10954/Desktop/MBForge/frontend/src/components/settings/LlmStatusCard.tsx
```

### Step 4.3: Verify TypeScript

Run:

```bash
cd /c/Users/10954/Desktop/MBForge/frontend
npx tsc --noEmit
```

Expected: no errors.

### Step 4.4: Commit

```bash
cd /c/Users/10954/Desktop/MBForge
git add frontend/src/components/settings/sections/AIModelsSection.tsx
git rm frontend/src/components/settings/LlmStatusCard.tsx
git commit -m "feat(settings): unify AI model tabs with ModelConfigCard"
```

---

## Task 5: Frontend — add i18n keys

**Files:**
- Modify: `frontend/src/i18n/locales/en.json`
- Modify: `frontend/src/i18n/locales/zh-CN.json`

### Step 5.1: Add English keys

Insert after `"settings.llmSampling": "LLM Sampling",` in `en.json`:

```json
  "settings.llmProvider": "Provider",
  "settings.llmProviderDesc": "LLM provider (OpenAI-compatible, Anthropic, Ollama, etc.)",
  "settings.llmBaseUrl": "Base URL",
  "settings.llmBaseUrlDesc": "Provider endpoint URL",
  "settings.llmApiKey": "API Key",
  "settings.llmApiKeyDesc": "API key for the selected provider",
  "settings.llmModel": "Model",
  "settings.llmModelDesc": "Model identifier to use",
  "settings.maxTokens": "Max Tokens",
  "settings.maxTokensDesc": "Maximum tokens per completion",
  "settings.temperature": "Temperature",
  "settings.connectionGroup": "Connection",
  "settings.advancedGroup": "Advanced",
  "settings.tabLlmDesc": "Large language model used for chat and agent reasoning.",
  "settings.tabEmbedDesc": "Text embedding model used for semantic search.",
  "settings.tabRerankDesc": "Cross-encoder reranker for retrieval result ordering.",
  "settings.tabVlmDesc": "Vision-language model for molecule image understanding.",
  "settings.tabOcrDesc": "Document text recognition provider and backend keys.",
  "settings.llmStatus.not_configured": "Not configured",
  "settings.llmStatus.ok": "Online",
  "settings.llmStatus.unreachable": "Unreachable",
  "settings.llmStatus.http_error": "HTTP error",
  "settings.llmStatus.auth_error": "Auth failed",
```

### Step 5.2: Add Chinese keys

Insert after `"settings.llmSampling": "LLM 采样",` in `zh-CN.json`:

```json
  "settings.llmProvider": "提供方",
  "settings.llmProviderDesc": "LLM 提供方（OpenAI 兼容、Anthropic、Ollama 等）",
  "settings.llmBaseUrl": "Base URL",
  "settings.llmBaseUrlDesc": "提供方接口地址",
  "settings.llmApiKey": "API Key",
  "settings.llmApiKeyDesc": "所选提供方的 API 密钥",
  "settings.llmModel": "模型",
  "settings.llmModelDesc": "要使用的模型标识",
  "settings.maxTokens": "最大 Token 数",
  "settings.maxTokensDesc": "每次完成的最大 token 数",
  "settings.temperature": "温度",
  "settings.connectionGroup": "连接信息",
  "settings.advancedGroup": "高级参数",
  "settings.tabLlmDesc": "用于对话和 Agent 推理的大语言模型。",
  "settings.tabEmbedDesc": "用于语义搜索的文本嵌入模型。",
  "settings.tabRerankDesc": "用于检索结果排序的交叉编码重排序模型。",
  "settings.tabVlmDesc": "用于分子图像理解的视觉-语言模型。",
  "settings.tabOcrDesc": "文档文字识别提供方及各后端密钥。",
  "settings.llmStatus.not_configured": "未配置",
  "settings.llmStatus.ok": "在线",
  "settings.llmStatus.unreachable": "无法连接",
  "settings.llmStatus.http_error": "HTTP 错误",
  "settings.llmStatus.auth_error": "认证失败",
```

### Step 5.3: Verify JSON validity

Run:

```bash
cd /c/Users/10954/Desktop/MBForge/frontend
node -e "JSON.parse(require('fs').readFileSync('./src/i18n/locales/en.json')); console.log('en OK')"
node -e "JSON.parse(require('fs').readFileSync('./src/i18n/locales/zh-CN.json')); console.log('zh-CN OK')"
```

Expected:

```
en OK
zh-CN OK
```

### Step 5.4: Commit

```bash
cd /c/Users/10954/Desktop/MBForge
git add frontend/src/i18n/locales/en.json frontend/src/i18n/locales/zh-CN.json
git commit -m "i18n(settings): add editable LLM field keys"
```

---

## Task 6: Frontend — build and run tests

**Files:**
- None (verification task)

### Step 6.1: TypeScript check

Run:

```bash
cd /c/Users/10954/Desktop/MBForge/frontend
npx tsc --noEmit
```

Expected: no errors.

### Step 6.2: Production build

Run:

```bash
cd /c/Users/10954/Desktop/MBForge/frontend
npm run build
```

Expected: build succeeds.

### Step 6.3: Run tests (allow known failures)

Run:

```bash
cd /c/Users/10954/Desktop/MBForge/frontend
npm test -- --run
```

Expected: `ProcessingQueue.logs.test.tsx` failures are pre-existing and acceptable. Any new failures in settings-related tests must be fixed before proceeding.

### Step 6.4: Commit

```bash
cd /c/Users/10954/Desktop/MBForge
git commit --allow-empty -m "chore(settings): verify frontend build and tests"
```

---

## Task 7: Backend — final cargo check

**Files:**
- None (verification task)

### Step 7.1: Check Rust

Run:

```bash
cd /c/Users/10954/Desktop/MBForge/src-tauri
cargo check
```

Expected: no errors.

### Step 7.2: Run Rust tests

Run:

```bash
cd /c/Users/10954/Desktop/MBForge/src-tauri
cargo test --lib
```

Expected: existing tests pass.

### Step 7.3: Commit

```bash
cd /c/Users/10954/Desktop/MBForge
git commit --allow-empty -m "chore(settings): verify backend build and tests"
```

---

## Self-Review Checklist

1. **Spec coverage**
   - [x] Card-based unified style for all 5 tabs → Task 3 + Task 4
   - [x] LLM editable (provider, base URL, API key, model, sampling params) → Task 3
   - [x] Env-first + config.json fallback → Task 1
   - [x] Test button retained for LLM → Task 3
   - [x] i18n updates → Task 5
   - [x] Build/test verification → Tasks 6 + 7

2. **Placeholder scan**
   - [x] No "TBD", "TODO", "implement later"
   - [x] No vague "add error handling" without code
   - [x] All code steps include actual code

3. **Type consistency**
   - [x] `MbforgeProviderConfig::from_app_config()` keeps zero-argument signature used by all callers
   - [x] `LlmEnvStatus::from_active_config()` replaces `from_env` consistently
   - [x] `ModelConfigCard` uses the same `SettingsState` keys defined in `types.ts`
   - [x] `toBackendPayload` already emits `llm` node; no change needed

4. **Risks**
   - [x] Backward compatibility: env still wins
   - [x] Caller churn avoided by not changing `from_app_config` signature
   - [x] OCR backend keys preserved in dedicated sub-component
