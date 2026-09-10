interface Props {
  texts: string[]
}

export default function RelatedTextPanel({ texts }: Props) {
  return (
    <section>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 4 }}>
        相关文本
      </div>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
          padding: '8px 10px',
          border: '1px solid var(--border)',
          borderRadius: 6,
          background: 'var(--bg-base)',
        }}
      >
        {texts.map((text) => (
          <p
            key={text}
            style={{
              margin: 0,
              color: 'var(--text-secondary)',
              fontSize: 11,
              lineHeight: 1.5,
              whiteSpace: 'pre-wrap',
              overflowWrap: 'anywhere',
            }}
          >
            {text}
          </p>
        ))}
      </div>
    </section>
  )
}