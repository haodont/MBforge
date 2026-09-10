import { httpPost, httpGet, invokeWithError } from './_utils'
import { ErrorCode } from '@/utils/errors'

// ---- ocr test (cloud backend auth probe) ----

export interface OcrTestResult {
  ok: boolean
  status: number | null
  message: string
}

export async function testOcrPaddleocr(
  host: string | null,
  apiKey: string,
  model: string | null,
): Promise<OcrTestResult> {
  return httpPost<OcrTestResult>('/api/v1/ocr/test-paddleocr', { host, apiKey, model })
}

export interface OcrChainStatus {
  backends: string[]
  priority: string[]
}

/** Which OCR backends the chain would try under current settings. */
export async function getOcrChainStatus(): Promise<OcrChainStatus> {
  return invokeWithError(
    () => httpGet<OcrChainStatus>('/api/v1/ocr/chain-status'),
    ErrorCode.ApiError,
  )
}
