import type { DesignationUnboundCandidate, ReviewBbox } from '@/api/http/review'
import { cropImageUrl } from '@/api/http/library'
import { useSmilesToRdkitSvg } from '@/api/query/hooks'
import Button from '@/components/ui/Button'
import Card from '@/components/ui/Card'

const imageStyle: React.CSSProperties = {
  display: 'block',
  width: '100%',
  height: 200,
  objectFit: 'contain',
  border: '1px solid var(--border)',
  borderRadius: 6,
  background: '#fff',
}

const unavailableStyle: React.CSSProperties = {
  ...imageStyle,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  boxSizing: 'border-box',
  padding: 12,
  color: 'var(--text-muted)',
  fontSize: 13,
  textAlign: 'center',
}

const hintStyle: React.CSSProperties = {
  marginBottom: 6,
  fontSize: 12,
  color: 'var(--text-secondary)',
}

interface ReviewCandidateCardProps {
  docId: string
  libraryRoot: string | null
  candidate: DesignationUnboundCandidate
  selected: boolean
  onChoose: (molId: string) => void
  onOpenPdf: (page: number | null, bbox: ReviewBbox | null) => void
}

/**
 * One structure a reviewer can bind a printed reading to.
 *
 * The crop is the printed drawing itself — the evidence a human needs — beside
 * the RDKit rendering of the same SMILES, so a wrong recognition is visible
 * instead of trusted.
 */
export default function ReviewCandidateCard({
  docId,
  libraryRoot,
  candidate,
  selected,
  onChoose,
  onOpenPdf,
}: ReviewCandidateCardProps) {
  const svgQuery = useSmilesToRdkitSvg(candidate.smiles)
  const rdkitSvg = svgQuery.data ?? null
  const cropUrl = candidate.crop_relpath
    ? cropImageUrl(docId, candidate.crop_relpath, libraryRoot ?? '')
    : null

  return (
    <Card padding={12}>
      <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
        <input
          type="radio"
          name={`unbound-${docId}`}
          checked={selected}
          onChange={() => onChoose(candidate.mol_id)}
        />
        <strong>{candidate.name || candidate.mol_id}</strong>
        {candidate.page != null && (
          <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
            第 {candidate.page} 页
          </span>
        )}
      </label>
      <div style={{ display: 'flex', gap: 12, marginTop: 10 }}>
        <div style={{ flex: 1 }}>
          <div style={hintStyle}>来源结构图</div>
          {cropUrl ? (
            <img src={cropUrl} alt="来源结构图" style={imageStyle} loading="lazy" />
          ) : (
            <div style={unavailableStyle}>暂无来源结构图</div>
          )}
        </div>
        <div style={{ flex: 1 }}>
          <div style={hintStyle}>RDKit 2D</div>
          {rdkitSvg ? (
            <img
              src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(rdkitSvg)}`}
              alt="RDKit 2D 结构图"
              style={imageStyle}
            />
          ) : (
            <div style={unavailableStyle}>暂无 SMILES，无法生成 RDKit 2D 结构图</div>
          )}
        </div>
      </div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          marginTop: 10,
        }}
      >
        <code style={{ overflowWrap: 'anywhere', color: 'var(--text-secondary)', fontSize: 12 }}>
          {candidate.smiles}
        </code>
        <Button size="sm" variant="ghost" onClick={() => onOpenPdf(candidate.page, candidate.bbox)}>
          打开原文
        </Button>
      </div>
    </Card>
  )
}
