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
  /** Advanced: text-only molecule fallback via one cloud tool-call pass. */
  llm_molecule_tool_enabled: boolean
  /** Advanced: max source chars sent to the molecule registration tool. */
  llm_molecule_tool_max_chars: number

  // —— VLM ——
  vlm_provider: string
  vlm_base_url: string
  vlm_api_key: string
  vlm_model: string

  // —— Local layout producer (text + regions) ——
  /** Detector confidence threshold for layout regions. */
  layout_conf_threshold: number
  /** Read region text locally; without it text regions carry no content. */
  layout_read_text: boolean
  /** Run MolDet on the same render so a figure region can be typed as one molecule. */
  layout_cross_model: boolean

  // —— Model Service ——
  server_host: string
  server_port: number
  server_auto_start: boolean
  server_startup_timeout: number
  server_health_check_interval: number

  // —— Models ——
  model_cache_dir: string

  // —— PDF parsing ——
  pdf_chunk_size: number
  pdf_chunk_overlap: number

  // —— MoldDet ——
  auto_moldet_on_import: boolean
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
  llm_molecule_tool_enabled: false,
  llm_molecule_tool_max_chars: 16000,

  vlm_provider: 'none',
  vlm_base_url: '',
  vlm_api_key: '',
  vlm_model: '',

  layout_conf_threshold: 0.4,
  layout_read_text: true,
  layout_cross_model: true,

  server_host: '127.0.0.1',
  server_port: 18792,
  server_auto_start: true,
  server_startup_timeout: 120,
  server_health_check_interval: 5,

  model_cache_dir: '',

  pdf_chunk_size: 512,
  pdf_chunk_overlap: 50,

  auto_moldet_on_import: true,
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
 * Note: auto_* booleans (auto_moldet_on_import / auto_enqueue_on_import)
 * default to True (matching backend `IngestConfig` / `MoldetConfig` defaults),
 * expressed as `!== false` rather than `=== true`.
 */
export function flattenSettings(raw: AppSettings | null | undefined): SettingsState {
  const s: AppSettings = raw ?? {}
  const llm = s.llm ?? {}
  const vlm = s.vlm ?? {}
  const layout = s.layout ?? {}
  const ms = s.model_server ?? {}
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
    llm_molecule_tool_enabled: llm.molecule_tool_enabled === true,
    llm_molecule_tool_max_chars:
      typeof llm.molecule_tool_max_chars === 'number'
        ? llm.molecule_tool_max_chars
        : DEFAULT_SETTINGS.llm_molecule_tool_max_chars,

    vlm_provider: vlm.provider || DEFAULT_SETTINGS.vlm_provider,
    vlm_base_url: vlm.base_url || DEFAULT_SETTINGS.vlm_base_url,
    vlm_api_key: vlm.api_key || DEFAULT_SETTINGS.vlm_api_key,
    vlm_model: vlm.model || DEFAULT_SETTINGS.vlm_model,

    layout_conf_threshold:
      typeof layout.conf_threshold === 'number'
        ? layout.conf_threshold
        : DEFAULT_SETTINGS.layout_conf_threshold,
    layout_read_text: layout.read_text !== false,
    layout_cross_model: layout.cross_model !== false,

    server_host: ms.host || DEFAULT_SETTINGS.server_host,
    server_port: ms.port || DEFAULT_SETTINGS.server_port,
    server_auto_start: ms.auto_start !== false,
    server_startup_timeout: ms.startup_timeout || DEFAULT_SETTINGS.server_startup_timeout,
    server_health_check_interval:
      ms.health_check_interval || DEFAULT_SETTINGS.server_health_check_interval,

    model_cache_dir: s.model_cache_dir || DEFAULT_SETTINGS.model_cache_dir,

    pdf_chunk_size: s.pdf_parse?.chunk_size || DEFAULT_SETTINGS.pdf_chunk_size,
    pdf_chunk_overlap: s.pdf_parse?.chunk_overlap || DEFAULT_SETTINGS.pdf_chunk_overlap,

    auto_moldet_on_import: s.moldet?.auto_moldet_on_import !== false,
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
      molecule_tool_enabled: s.llm_molecule_tool_enabled,
      molecule_tool_max_chars: s.llm_molecule_tool_max_chars,
    },
    vlm: {
      provider: s.vlm_provider,
      base_url: s.vlm_base_url,
      api_key: s.vlm_api_key,
      model: s.vlm_model,
    },
    layout: {
      conf_threshold: s.layout_conf_threshold,
      read_text: s.layout_read_text,
      cross_model: s.layout_cross_model,
    },
    model_server: {
      host: s.server_host,
      port: s.server_port,
      auto_start: s.server_auto_start,
      startup_timeout: s.server_startup_timeout,
      health_check_interval: s.server_health_check_interval,
    },
    model_cache_dir: s.model_cache_dir,
    pdf_parse: {
      chunk_size: s.pdf_chunk_size,
      chunk_overlap: s.pdf_chunk_overlap,
    },
    moldet: {
      auto_moldet_on_import: s.auto_moldet_on_import,
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
