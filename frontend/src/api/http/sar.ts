/** SAR 分析 — HTTP backend */

import { httpPost, invokeWithError, ErrorCode } from './_utils'

export interface CompoundInput {
  id: string
  name: string
  smiles: string
  activity?: number
  activity_type?: string
  units?: string
}

export interface CompoundMatch extends CompoundInput {
  matches: boolean
}

export interface RGroupMatrix {
  core_smiles: string
  r_labels: string[]
  rows: string[][]
  compounds: CompoundMatch[]
  unmatched_count: number
}

export interface HeatmapCell {
  substituent_smiles: string
  avg_activity: number
  count: number
  min: number
  max: number
}

export interface ActivityHeatmap {
  r_label: string
  cells: HeatmapCell[]
}

/** 构建 R-group 矩阵（后端未实现时会 fail-closed） */
export async function sarBuildMatrix(
  compounds: CompoundInput[],
  coreSmiles?: string,
): Promise<RGroupMatrix & { success?: boolean; error?: string }> {
  return invokeWithError(
    () => httpPost<RGroupMatrix & { success?: boolean; error?: string }>(
      '/api/v1/sar/build-matrix',
      { compounds, coreSmiles: coreSmiles ?? null },
    ),
    ErrorCode.ApiError,
  )
}

/** 兼容旧名 — client.ts 迁移 */
export type ActivityHeatmapEntry = ActivityHeatmap
export type ActivityHeatmapCell = HeatmapCell

/** 构建活性热力图 */
export async function sarHeatmap(
  matrix: RGroupMatrix,
  lowerIsBetter: boolean = true,
): Promise<ActivityHeatmap[]> {
  return invokeWithError(
    () => httpPost<ActivityHeatmap[]>('/api/v1/sar/heatmap', { matrix, lowerIsBetter }),
    ErrorCode.ApiError,
  )
}
