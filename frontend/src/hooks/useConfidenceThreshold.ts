/**
 * 置信度阈值 hook — OCR 矫正流程的"自动确认门槛"。
 *
 * 矫正面板（CorrectionPanel）使用此阈值：
 *   - 高于此阈值的 OCR 结果视为可信，可在 `handleFinish` 自动确认
 *   - 低于此阈值的需要人工复核（默认与 `chem_tanimoto_batch_filter` 默认 0.5 一致）
 *
 * 数据来源：
 *   - `ExtractionResult.moldet_conf`（检测阶段，0-1）
 *   - `Molecule.ocrConfidence`（矫正面板接收，0-1）
 *
 * 持久化：localStorage key `mbforge_confidence_threshold`。
 */

import { useState, useCallback } from 'react'

const THRESHOLD_KEY = 'mbforge_confidence_threshold'

/** 默认值：与 `api/tauri/molecule.ts::chemTanimotoBatchFilter` 默认 0.5 一致 */
export const DEFAULT_CONFIDENCE_THRESHOLD = 0.5

/** 取值范围 */
export const MIN_THRESHOLD = 0
export const MAX_THRESHOLD = 1
export const STEP = 0.05

function loadThreshold(): number {
  try {
    const stored = localStorage.getItem(THRESHOLD_KEY)
    if (stored === null) return DEFAULT_CONFIDENCE_THRESHOLD
    const parsed = Number(stored)
    if (Number.isFinite(parsed) && parsed >= MIN_THRESHOLD && parsed <= MAX_THRESHOLD) {
      return parsed
    }
  } catch {
    // localStorage 不可用（隐私模式、SSR 等）— 用默认值
  }
  return DEFAULT_CONFIDENCE_THRESHOLD
}

export function useConfidenceThreshold(): readonly [number, (next: number) => void] {
  const [threshold, setThresholdState] = useState<number>(loadThreshold)

  const setThreshold = useCallback((next: number) => {
    const clamped = Math.min(MAX_THRESHOLD, Math.max(MIN_THRESHOLD, next))
    setThresholdState(clamped)
    try {
      localStorage.setItem(THRESHOLD_KEY, String(clamped))
    } catch {
      // 持久化失败不影响 in-memory 状态
    }
  }, [])

  return [threshold, setThreshold] as const
}
