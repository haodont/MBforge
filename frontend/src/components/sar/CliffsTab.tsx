import { useState, useMemo, useEffect, useCallback } from 'react'
import { SectionTitle, Card, EmptyState, AlertBanner, Button } from '../ui'
import { molFindActivityCliffs, molScaffoldProfile } from '@/api/http/molecule'
import type { ActivityCliff, ScaffoldProfile } from '@/api/http/molecule'
import type { SARSession } from '@/types'
import { getUserFacingError } from '@/utils/errors'

const DEFAULT_MIN_SIMILARITY = 0.7
const DEFAULT_MIN_RATIO = 5

interface CliffsTabProps {
  session: SARSession
  libraryRoot: string | null
}

export default function CliffsTab({ session, libraryRoot }: CliffsTabProps) {
  const [minSim, setMinSim] = useState(DEFAULT_MIN_SIMILARITY)
  const [minRatio, setMinRatio] = useState(DEFAULT_MIN_RATIO)
  const [cliffs, setCliffs] = useState<ActivityCliff[] | null>(null)
  const [profile, setProfile] = useState<ScaffoldProfile | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const inferredScaffold = useMemo(() => {
    const smilesList = session.compounds.map(c => c.esmiles).filter(Boolean)
    if (smilesList.length < 2) return null
    const counts = new Map<string, number>()
    for (const smi of smilesList) {
      for (let len = 8; len >= 4; len--) {
        for (let i = 0; i + len <= smi.length; i++) {
          const sub = smi.substring(i, i + len)
          if (/[=#@]/.test(sub)) continue
          counts.set(sub, (counts.get(sub) ?? 0) + 1)
        }
      }
    }
    const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1])
    const best = sorted.find(([, n]) => n >= 2)
    return best ? best[0] : null
  }, [session.compounds])

  const run = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      if (!libraryRoot) {
        setError('项目未打开')
        return
      }
      const cliffResults = await molFindActivityCliffs(libraryRoot, minSim, minRatio)
      setCliffs(cliffResults)
      if (inferredScaffold) {
        try {
          const p = await molScaffoldProfile(libraryRoot, inferredScaffold)
          setProfile(p)
        } catch {
          setProfile(null)
        }
      } else {
        setProfile(null)
      }
    } catch (e) {
      setError(getUserFacingError(e, '加载 activity cliffs 失败'))
    } finally {
      setLoading(false)
    }
  }, [minSim, minRatio, inferredScaffold, libraryRoot])

  useEffect(() => {
    void run()
  }, [run])

  return (
    <div>
      <AlertBanner
        variant="info"
        message="活性悬崖 = 结构相似但活性差异显著的分子对，是 SAR 分析的核心。调整下方阈值可过滤严格度。"
      />

      <div className="sar-cliffs-controls">
        <ParamInput
          label="最小相似度"
          value={minSim}
          step={0.05}
          min={0.5}
          max={0.99}
          onChange={setMinSim}
        />
        <ParamInput
          label="最小活性比"
          value={minRatio}
          step={1}
          min={2}
          max={100}
          onChange={setMinRatio}
        />
        <Button variant="secondary" size="sm" onClick={run} loading={loading}>
          重新计算
        </Button>
      </div>

      {error && <AlertBanner variant="error" message={`计算失败: ${error}`} />}

      {profile && (
        <div className="sar-profile-section">
          <SectionTitle>
            骨架 Profile: <code className="sar-profile-code">{profile.scaffold_esmiles}</code>
          </SectionTitle>
          <div className="sar-profile-grid">
            <Stat label="匹配分子数" value={profile.molecule_count} />
            <Stat label="有活性" value={profile.activity_summary.count_with_activity} />
            <Stat label="无活性" value={profile.activity_summary.count_without_activity} />
            <Stat
              label="活性范围"
              value={
                profile.activity_summary.min_activity != null && profile.activity_summary.max_activity != null
                  ? `${profile.activity_summary.min_activity.toFixed(1)} – ${profile.activity_summary.max_activity.toFixed(1)}`
                  : '—'
              }
            />
            <Stat
              label="平均活性"
              value={profile.activity_summary.mean_activity != null ? profile.activity_summary.mean_activity.toFixed(2) : '—'}
            />
          </div>
        </div>
      )}

      <SectionTitle>活性悬崖</SectionTitle>
      {cliffs == null ? (
        <EmptyState message="加载中…" />
      ) : cliffs.length === 0 ? (
        <EmptyState message={`在 minSim=${minSim}、minRatio=${minRatio} 下没有找到活性悬崖`} />
      ) : (
        <div className="sar-cliffs-list">
          {cliffs.map((c, i) => (
            <CliffRow key={`${c.mol_a_id}-${c.mol_b_id}-${i}`} cliff={c} />
          ))}
        </div>
      )}
    </div>
  )
}

interface ParamInputProps {
  label: string
  value: number
  step: number
  min: number
  max: number
  onChange: (n: number) => void
}

function ParamInput({ label, value, step, min, max, onChange }: ParamInputProps) {
  return (
    <label className="sar-param-input">
      {label}
      <input
        type="number"
        value={value}
        step={step}
        min={min}
        max={max}
        onChange={e => onChange(Number(e.target.value))}
      />
    </label>
  )
}

interface StatProps {
  label: string
  value: string | number
}

function Stat({ label, value }: StatProps) {
  return (
    <div className="sar-stat-card">
      <div className="sar-stat-card-label">{label}</div>
      <div className="sar-stat-card-value">{value}</div>
    </div>
  )
}

interface CliffRowProps {
  cliff: ActivityCliff
}

function CliffRow({ cliff }: CliffRowProps) {
  return (
    <Card padding="12px 16px">
      <div className="sar-cliff-row">
        <div className="sar-cliff-mol">
          <div className="sar-cliff-mol-name">{cliff.mol_a_name}</div>
          <code className="sar-cliff-mol-smiles">{cliff.mol_a_esmiles}</code>
          <div className="sar-cliff-mol-activity">
            IC50: {cliff.activity_a ?? '—'} {cliff.activity_type}
          </div>
        </div>
        <div className="sar-cliff-metric">
          <div className="sar-cliff-metric-label">相似度</div>
          <div className="sar-cliff-metric-value">{(cliff.similarity_score * 100).toFixed(1)}%</div>
        </div>
        <div className="sar-cliff-metric">
          <div className="sar-cliff-metric-label">活性比</div>
          <div className="sar-cliff-metric-value sar-cliff-metric-value--warn">
            {cliff.activity_ratio != null ? `${cliff.activity_ratio.toFixed(1)}×` : '—'}
          </div>
        </div>
        <div className="sar-cliff-mol">
          <div className="sar-cliff-mol-name">{cliff.mol_b_name}</div>
          <code className="sar-cliff-mol-smiles">{cliff.mol_b_esmiles}</code>
          <div className="sar-cliff-mol-activity">
            IC50: {cliff.activity_b ?? '—'} {cliff.activity_type}
          </div>
        </div>
      </div>
    </Card>
  )
}
