import Chip from '../ui/Chip'

interface TagPillProps {
  label: string
  active: boolean
  onClick: () => void
}

export default function TagPill({ label, active, onClick }: TagPillProps) {
  return <Chip label={`#${label}`} active={active} onClick={onClick} />
}
