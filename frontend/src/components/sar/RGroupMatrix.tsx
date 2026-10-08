import { useState, useMemo } from 'react'
import { Card, EmptyState, Spinner } from '../ui'
import type { SARCompound } from '@/types'
import type {
  RGroupMatrix as RGroupMatrixData,
  ActivityHeatmapEntry,
} from '@/api/http/sar'
import { useSarBuildMatrix, useSarHeatmap } from '@/api/query/hooks'
import CoreScaffoldCard from './rgroup/CoreScaffoldCard'
import MatrixTable from './rgroup/MatrixTable'
import HeatmapPanel from './rgroup/HeatmapPanel'

// ============================================================================
// Types
// ============================================================================

export interface RGroupMatrixProps {
  /** 化合物列表（带 SMILES + 活性数据） */
  compounds: SARCompound[]
  /** 预定义共同骨架（不传则自动提取） */
  coreSmiles?: string
  /** IC50 默认 "lower is better"，%inhibition 等设 false */
  lowerIsBetter?: boolean
  /** 矩阵行点击回调（用于跳转分子详情） */
  onCompoundClick?: (compound: SARCompound) => void
}

// ============================================================================
// Main orchestrator
// ============================================================================

/**
 * R-Group 矩阵视图.
 *
 * 数据流 (FastAPI 后端,通过 /api/v1/sar/* 路由):
 * 1. `sar_build_matrix` → 共同骨架 + 矩阵数据
 * 2. `sar_heatmap`     → 聚合热力图
 *
 * 子组件：
 * - <CoreScaffoldCard>  共同骨架展示
 * - <MatrixTable>       化合物 × R 位置 矩阵
 * - <HeatmapPanel>      活性热力图
 */
export default function RGroupMatrixView({
  compounds,
  coreSmiles,
  lowerIsBetter = true,
  onCompoundClick,
}: RGroupMatrixProps) {
  const [showHeatmap, setShowHeatmap] = useState(true)

  // 后端 matrix 调用 (POST /api/v1/sar/build-matrix)
  const matrixQuery = useSarBuildMatrix(
    compounds.map(c => ({
      id: c.id,
      name: c.name,
      smiles: c.esmiles,
      activity: c.activity ?? undefined,
      activity_type: c.activityType ?? undefined,
      units: c.units ?? undefined,
    })),
    coreSmiles,
  )
  const matrixResult = matrixQuery.data
  // Backend may fail-closed with success:false while still returning shape.
  const matrix: RGroupMatrixData | null =
    matrixResult && matrixResult.success !== false && matrixResult.core_smiles
      ? matrixResult
      : null
  const loading = matrixQuery.isFetching
  const error = matrixQuery.isError
    ? '请求失败（SAR 可能尚未实现）'
    : matrixResult && matrixResult.success === false
      ? matrixResult.error ?? 'SAR 分析尚未实现（实验性功能）'
      : matrixResult && !matrixResult.core_smiles
        ? '未找到共同骨架'
        : null

  // heatmap 调用 (POST /api/v1/sar/heatmap)
  const heatmapQuery = useSarHeatmap(matrix, lowerIsBetter)
  const heatmaps = useMemo<ActivityHeatmapEntry[]>(
    () => heatmapQuery.data ?? [],
    [heatmapQuery.data],
  )

  // 热力图 pAct 范围（用于图例）
  const heatmapStats = useMemo(() => {
    const allPActs: number[] = []
    for (const h of heatmaps) {
      for (const cell of h.cells) {
        if (cell.avg_activity > 0) {
          const pAct = 9 - Math.log10(cell.avg_activity)
          if (Number.isFinite(pAct)) allPActs.push(pAct)
        }
      }
    }
    if (allPActs.length === 0) return null
    return {
      min: Math.min(...allPActs),
      max: Math.max(...allPActs),
    }
  }, [heatmaps])

  // ----- Render states -----

  if (loading) {
    return (
      <Card padding="40px" style={{ display: 'flex', justifyContent: 'center' }}>
        <Spinner />
        <span style={{ marginLeft: 12, color: 'var(--text-muted)', fontSize: 13 }}>
          正在提取共同骨架并构建 R-group 矩阵…
        </span>
      </Card>
    )
  }

  if (error) {
    return <EmptyState message={`R-Group 分析失败：${error}`} error />
  }

  if (!matrix) {
    return <EmptyState message="至少需要 2 个化合物才能进行 R-Group 分析" />
  }

  if (matrix.r_labels.length === 0 || matrix.rows.length === 0) {
    return (
      <EmptyState
        message={`未找到跨越所有化合物的共同骨架（${matrix.unmatched_count} 个化合物不匹配）`}
      />
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <CoreScaffoldCard
        coreSmiles={matrix.core_smiles}
        compoundCount={matrix.compounds.length}
        unmatched={matrix.unmatched_count}
      />

      {/* 工具栏：切换热力图 */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button
          onClick={() => setShowHeatmap(v => !v)}
          style={{
            padding: '6px 12px',
            fontSize: 12,
            background: 'var(--bg-surface)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            cursor: 'pointer',
          }}
        >
          {showHeatmap ? '隐藏' : '显示'} 活性热力图
        </button>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          IC50 数据：数值越低活性越高（{lowerIsBetter ? 'lower is better' : 'higher is better'}）
        </span>
      </div>

      {/* 矩阵表格 + 热力图 */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: showHeatmap ? 'minmax(0, 1.4fr) minmax(0, 1fr)' : '1fr',
          gap: 16,
          alignItems: 'start',
        }}
      >
        <MatrixTable matrix={matrix} onCompoundClick={onCompoundClick} />
        {showHeatmap && (
          <HeatmapPanel heatmaps={heatmaps} stats={heatmapStats} lowerIsBetter={lowerIsBetter} />
        )}
      </div>
    </div>
  )
}
