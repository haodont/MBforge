// Model config constants — grouped by provider.
//
// These are only "suggested values" for the UI dropdowns; users can type any
// model name (see the free-text `ModelSelector`). This lists each
// provider's mainstream default models for quick selection.

export interface ModelOption {
  value: string
  label: string
}

export type ModelMap = Record<string, ModelOption[]>

export const LLM_MODELS: ModelMap = {
  openai_compatible: [
    { value: 'gpt-4o', label: 'GPT-4o' },
    { value: 'gpt-4o-mini', label: 'GPT-4o mini' },
    { value: 'deepseek-chat', label: 'DeepSeek Chat' },
    { value: 'Qwen/Qwen2.5-7B-Instruct-GGUF', label: 'Qwen2.5-7B-Instruct (GGUF)' },
  ],
  anthropic: [
    { value: 'claude-sonnet-4-5', label: 'Claude Sonnet 4.5' },
    { value: 'claude-opus-4-1', label: 'Claude Opus 4.1' },
    { value: 'claude-haiku-4-5', label: 'Claude Haiku 4.5' },
  ],
  ollama: [
    { value: 'qwen2.5:7b', label: 'Qwen2.5 7B' },
    { value: 'llama3.1:8b', label: 'Llama 3.1 8B' },
    { value: 'gemma2:9b', label: 'Gemma 2 9B' },
  ],
}

export const VLM_MODELS: ModelMap = {
  openai_compatible: [
    { value: 'gpt-4o', label: 'GPT-4o' },
    { value: 'gpt-4o-mini', label: 'GPT-4o mini' },
  ],
  anthropic: [{ value: 'claude-sonnet-4-5', label: 'Claude Sonnet 4.5' }],
  qwen_vl: [
    { value: 'Qwen/Qwen2-VL-7B-Instruct', label: 'Qwen2-VL-7B-Instruct' },
    { value: 'Qwen/Qwen2-VL-72B-Instruct', label: 'Qwen2-VL-72B-Instruct' },
  ],
}


/** Human-readable provider label + default placeholder URL (for guidance). */
export const PROVIDER_META: Record<string, { label: string; defaultUrl: string; needsKey: boolean }> = {
  // LLM
  openai_compatible: { label: 'OpenAI Compatible', defaultUrl: 'https://api.openai.com/v1', needsKey: true },
  anthropic: { label: 'Anthropic', defaultUrl: 'https://api.anthropic.com', needsKey: true },
  ollama: { label: 'Ollama (local)', defaultUrl: 'http://localhost:11434', needsKey: false },
  // VLM
  qwen_vl: { label: 'Qwen-VL (local)', defaultUrl: '', needsKey: false },
}