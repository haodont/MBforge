import { useMemo, useState } from 'react'
import { moleculesToSession } from '../components/sar/utils'
import type { MoleculeRecord, SARSession } from '@/types'

export type AnalysisTab = 'overview' | 'rgroup' | 'cliffs' | 'analytics' | 'relations'

export interface UseMoleculeAnalysisResult {
  activeTab: AnalysisTab
  setActiveTab: React.Dispatch<React.SetStateAction<AnalysisTab>>
  selectedMolecules: MoleculeRecord[]
  analysisInput: MoleculeRecord[]
  sarSession: SARSession | null
  hasSelection: boolean
}

export function useMoleculeAnalysis(
  molecules: MoleculeRecord[],
  selectedIds: Set<string>,
): UseMoleculeAnalysisResult {
  const [activeTab, setActiveTab] = useState<AnalysisTab>('overview')

  const selectedMolecules = useMemo(
    () => molecules.filter((m) => selectedIds.has(m.mol_id)),
    [molecules, selectedIds],
  )

  const hasSelection = useMemo(() => selectedMolecules.length > 0, [selectedMolecules])

  const analysisInput = useMemo(
    () => (hasSelection ? selectedMolecules : molecules),
    [hasSelection, selectedMolecules, molecules],
  )

  const sarSession = useMemo(
    () => (analysisInput.length > 0 ? moleculesToSession(analysisInput) : null),
    [analysisInput],
  )

  return {
    activeTab,
    setActiveTab,
    selectedMolecules,
    analysisInput,
    sarSession,
    hasSelection,
  }
}
