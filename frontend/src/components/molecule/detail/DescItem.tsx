interface DescItemProps {
  label: string
  value: string
  unit?: string
}

export default function DescItem({ label, value, unit }: DescItemProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        minHeight: 82,
        justifyContent: 'space-between',
        gap: 8,
        padding: '12px 14px',
        background: 'var(--bg-base)',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border)',
        boxShadow: 'var(--shadow-sm)',
      }}
    >
      <div style={{ fontSize: 12, color: 'var(--text-muted)', fontWeight: 600 }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, minWidth: 0 }}>
        <span
          style={{
            color: 'var(--text-primary)',
            fontFamily: 'monospace',
            fontSize: 19,
            fontWeight: 600,
            fontVariantNumeric: 'tabular-nums',
            overflowWrap: 'anywhere',
          }}
        >
          {value}
        </span>
        {unit && (
          <span style={{ flexShrink: 0, color: 'var(--text-muted)', fontSize: 12 }}>{unit}</span>
        )}
      </div>
    </div>
  )
}