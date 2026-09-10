import RelationPanel from '../analytics/RelationPanel'
import type { MoleculeRecord } from '@/types'

export interface RelationsTabProps {
  molecules: MoleculeRecord[]
}

export default function RelationsTab({ molecules }: RelationsTabProps) {
  return <RelationPanel molecules={molecules} />
}
