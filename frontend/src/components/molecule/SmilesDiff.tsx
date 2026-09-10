interface SmilesDiffProps {
  before: string
  after: string
}

export default function SmilesDiff({ before, after }: SmilesDiffProps) {
  if (before === after) return null
  let i = 0
  while (i < before.length && i < after.length && before[i] === after[i]) i++

  return (
    <div className="mol-smiles-diff">
      <div>
        <span className="mol-diff-label">原：</span>
        <span className="mol-diff-same">{before.slice(0, i)}</span>
        <span className="mol-diff-removed">{before.slice(i)}</span>
      </div>
      <div>
        <span className="mol-diff-label">新：</span>
        <span className="mol-diff-same">{after.slice(0, i)}</span>
        <span className="mol-diff-added">{after.slice(i)}</span>
      </div>
    </div>
  )
}
