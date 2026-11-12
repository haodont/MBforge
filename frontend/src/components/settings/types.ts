// Settings panel — shared types and defaults.
//
// Single source of truth: every section reads and writes the same
// `SettingsState` so saving never drops or misroutes a field.
// `DEFAULT_SETTINGS` stays aligned with the backend `AppConfig` Pydantic
// schema (see `src/mbforge/foundation/config.py`).

import type { AppSettings } from '../../api/http/settings'

/** Flat state while editing. Fields are carried as strings/numbers/booleans. */
export interface SettingsState {
  // —— General ——
  theme: 'dark' | 'light' | 'system'
  language: 'zh' | 'en'

  // —— LLM ——
  llm_provider: string
  llm_base_url: string
  llm_api_key: string
  llm_model: string
  llm_max_tokens: number
  llm_temperature: number
  llm_top_p: number
  llm_request_timeout: number
  /** Advanced: language passed to provider (default 'en'). */
  llm_language: string

  // —— Local layout producer (text + regions) ——
  /** Detector confidence threshold for layout regions. */
  layout_conf_threshold: number
  /** Run MolDet on the same render so a figure region can be typed as one molecule. */
  layout_cross_model: boolean

  // —— Models ——
  model_cache_dir: string

  // —— MoldDet ——
  detection_batch_size: number
  /** Advanced: 'auto' lets MBForge pick (default); 'cpu' / 'cuda' override. */
  moldet_device: string
  /** Advanced: explicit MolParser-Mobile checkpoint dir (empty = use default). */
  moldet_molparser_dir: string
  /** Advanced: PDF render DPI for detection (higher = slower + sharper). */
  moldet_detection_dpi: number
  /** Advanced: MolParser crops per inference batch (clamped to 1-64). */
  moldet_molparser_batch_size: number
  /** Advanced: page char threshold for selecting text-only vs detection. */
  moldet_text_page_char_threshold: number
  /** Advanced: per-doc page cap; 0 = unlimited. */
  moldet_max_pages_per_doc: number

  // —— Ingest ——
  auto_enqueue_on_import: boolean
  /** Advanced: default queue priority for newly-imported PDFs. */
  ingest_default_priority: number


  // —— Cache sizes (read-only, reported by backend) ——
  cache_size_semantic_mb: number
  cache_size_detection_mb: number
  cache_size_molecules_mb: number
}

export const DEFAULT_SETTINGS: SettingsState = {
  theme: 'dark',
  language: 'zh',

  llm_provider: 'openai_compatible',
  llm_base_url: '',
  llm_api_key: '',
  llm_model: '',
  llm_max_tokens: 4096,
  llm_temperature: 0.7,
  llm_top_p: 1.0,
  llm_request_timeout: 60,
  llm_language: 'en',

  layout_conf_threshold: 0.4,
  layout_cross_model: true,

  model_cache_dir: '',

  detection_batch_size: 0,
  moldet_device: 'auto',
  moldet_molparser_dir: '',
  moldet_detection_dpi: 200,
  moldet_molparser_batch_size: 16,
  moldet_text_page_char_threshold: 500,
  moldet_max_pages_per_doc: 0,

  auto_enqueue_on_import: true,
  ingest_default_priority: 0,


  cache_size_semantic_mb: 0,
  cache_size_detection_mb: 0,
  cache_size_molecules_mb: 0,
}


/**
 * Flatten the backend JSON into SettingsState. Missing fields fall back to
 * defaults.
 *
 * Note: backend `AppConfig` fields are snake_case, matching our
 * SettingsState snake_case; the explicit mapping is safer than relying on
 * serde rename.
 *
 * Note: the auto_enqueue_on_import boolean defaults to True (matching the
 * backend `IngestConfig` default), expressed as `!== false` rather than
 * `=== true`.
 */
export function flattenSettings(raw: AppSettings | null | undefined): SettingsState {
  const s: AppSettings = raw ?? {}
  const llm = s.llm ?? {}
  const layout = s.layout ?? {}
  return {
    theme: (s.theme as SettingsState['theme'] | undefined) || DEFAULT_SETTINGS.theme,
    // Backend used to default to "zh-CN"; the frontend/i18n only speaks "zh"/"en".
    language:
      (s.language === 'zh-CN' ? 'zh' : (s.language as SettingsState['language'] | undefined)) ||
      DEFAULT_SETTINGS.language,

    llm_provider: llm.provider || DEFAULT_SETTINGS.llm_provider,
    llm_base_url: llm.base_url || DEFAULT_SETTINGS.llm_base_url,
    llm_api_key: llm.api_key || DEFAULT_SETTINGS.llm_api_key,
    llm_model: llm.model || DEFAULT_SETTINGS.llm_model,
    llm_max_tokens: llm.max_tokens || DEFAULT_SETTINGS.llm_max_tokens,
    llm_temperature:
      typeof llm.temperature === 'number' ? llm.temperature : DEFAULT_SETTINGS.llm_temperature,
    llm_top_p: typeof llm.top_p === 'number' ? llm.top_p : DEFAULT_SETTINGS.llm_top_p,
    llm_request_timeout: llm.request_timeout || DEFAULT_SETTINGS.llm_request_timeout,
    llm_language: llm.language || DEFAULT_SETTINGS.llm_language,

    layout_conf_threshold:
      typeof layout.conf_threshold === 'number'
        ? layout.conf_threshold
        : DEFAULT_SETTINGS.layout_conf_threshold,
    layout_cross_model: layout.cross_model !== false,

    model_cache_dir: s.model_cache_dir || DEFAULT_SETTINGS.model_cache_dir,

    detection_batch_size:
      typeof s.moldet?.detection_batch_size === 'number'
        ? s.moldet.detection_batch_size
        : DEFAULT_SETTINGS.detection_batch_size,
    moldet_device: s.moldet?.device || DEFAULT_SETTINGS.moldet_device,
    moldet_molparser_dir: s.moldet?.molparser_dir || DEFAULT_SETTINGS.moldet_molparser_dir,
    moldet_detection_dpi:
      typeof s.moldet?.detection_dpi === 'number'
        ? s.moldet.detection_dpi
        : DEFAULT_SETTINGS.moldet_detection_dpi,
    moldet_text_page_char_threshold:
      typeof s.moldet?.text_page_char_threshold === 'number'
        ? s.moldet.text_page_char_threshold
        : DEFAULT_SETTINGS.moldet_text_page_char_threshold,
    moldet_molparser_batch_size:
      typeof s.moldet?.molparser_batch_size === 'number'
        ? s.moldet.molparser_batch_size
        : DEFAULT_SETTINGS.moldet_molparser_batch_size,
    moldet_max_pages_per_doc:
      typeof s.moldet?.max_pages_per_doc === 'number'
        ? s.moldet.max_pages_per_doc
        : DEFAULT_SETTINGS.moldet_max_pages_per_doc,

    auto_enqueue_on_import: s.ingest?.auto_enqueue_on_import !== false,
    ingest_default_priority:
      typeof s.ingest?.default_priority === 'number'
        ? s.ingest.default_priority
        : DEFAULT_SETTINGS.ingest_default_priority,


    cache_size_semantic_mb: 0, // populated by backend refresh at startup
    cache_size_detection_mb: 0,
    cache_size_molecules_mb: 0,
  }
}

/**
 * Flatten SettingsState into the nested JSON expected by the backend
 * `save_settings`. Key invariant: keep every node (even empty strings)
 * so the backend merge can clear fields correctly.
 */
export function toBackendPayload(s: SettingsState): Record<string, unknown> {
  return {
    theme: s.theme,
    language: s.language,
    llm: {
      provider: s.llm_provider,
      base_url: s.llm_base_url,
      api_key: s.llm_api_key,
      model: s.llm_model,
      max_tokens: s.llm_max_tokens,
      temperature: s.llm_temperature,
      top_p: s.llm_top_p,
      request_timeout: s.llm_request_timeout,
      language: s.llm_language,
    },
    layout: {
      conf_threshold: s.layout_conf_threshold,
      cross_model: s.layout_cross_model,
    },
    model_cache_dir: s.model_cache_dir,
    moldet: {
      detection_batch_size: s.detection_batch_size,
      molparser_batch_size: s.moldet_molparser_batch_size,
      device: s.moldet_device,
      molparser_dir: s.moldet_molparser_dir,
      detection_dpi: s.moldet_detection_dpi,
      text_page_char_threshold: s.moldet_text_page_char_threshold,
      max_pages_per_doc: s.moldet_max_pages_per_doc > 0 ? s.moldet_max_pages_per_doc : null,
    },
    ingest: {
      auto_enqueue_on_import: s.auto_enqueue_on_import,
      default_priority: s.ingest_default_priority,
    },
  }
}

/** Shallow compare — JSON.stringify would false-positive on key order. */
export function isSettingsEqual(a: SettingsState, b: SettingsState): boolean {
  const keys = Object.keys(a) as (keyof SettingsState)[]
  for (const k of keys) {
    if (a[k] !== b[k]) return false
  }
  return true
}
