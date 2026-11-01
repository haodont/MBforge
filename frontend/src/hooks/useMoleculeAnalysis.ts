import { useMemo, useState } from 'react'
import type { MoleculeRecord } from '@/types'

export type AnalysisTab = 'analytics' | 'relations'

export interface UseMoleculeAnalysisResult {
  activeTab: AnalysisTab
  setActiveTab: React.Dispatch<React.SetStateAction<AnalysisTab>>
  selectedMolecules: MoleculeRecord[]
  analysisInput: MoleculeRecord[]
  hasSelection: boolean
}

export function useMoleculeAnalysis(
  molecules: MoleculeRecord[],
  selectedIds: Set<string>,
): UseMoleculeAnalysisResult {
  const [activeTab, setActiveTab] = useState<AnalysisTab>('analytics')

  const selectedMolecules = useMemo(
    () => molecules.filter((m) => selectedIds.has(m.mol_id)),
    [molecules, selectedIds],
  )

  const hasSelection = useMemo(() => selectedMolecules.length > 0, [selectedMolecules])

  const analysisInput = useMemo(
    () => (hasSelection ? selectedMolecules : molecules),
    [hasSelection, selectedMolecules, molecules],
  )

  return {
    activeTab,
    setActiveTab,
    selectedMolecules,
    analysisInput,
    hasSelection,
  }
}
