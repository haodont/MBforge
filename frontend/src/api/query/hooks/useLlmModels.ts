/** React Query hook for the provider LLM model-list probe. */

import { useMutation } from '@tanstack/react-query'
import {
  fetchLlmModels,
  type FetchLlmModelsBody,
  type FetchLlmModelsResponse,
} from '@/api/http/settings'

/** Query the configured provider for its available models (dropdown probe). */
export function useLlmModels() {
  return useMutation<FetchLlmModelsResponse, Error, FetchLlmModelsBody>({
    mutationFn: (body) => fetchLlmModels(body),
  })
}
