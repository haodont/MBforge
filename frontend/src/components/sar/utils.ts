import type { MoleculeRecord } from '@/types'
import type { SARSession } from '@/types'

export function moleculesToSession(molecules: MoleculeRecord[]): SARSession {
  return {
    id: 'session_current',
    name: '当前项目分子',
    target: undefined,
    coreSmiles: undefined,
    createdAt: new Date().toISOString(),
    sourceDocs: [],
    compounds: molecules.map(m => ({
      id: m.mol_id,
      name: m.name || m.mol_id,
      esmiles: m.esmiles,
      rGroups: {},
      activity: m.activity ?? undefined,
      activityType: m.activity_type || undefined,
      units: m.units || undefined,
      notes: m.notes || undefined,
    })),
  }
}
