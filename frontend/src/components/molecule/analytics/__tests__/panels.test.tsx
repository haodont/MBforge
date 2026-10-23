// Usage tests for the molecule analytics panels (AnalogSearchPanel,
// ClusterPanel, DedupPanel, RelationPanel, SubstructureSearchPanel): each
// panel is exercised end to end, asserting that a blank/invalid submission is
// ignored, that a cancelled confirmation dialog never reaches the backend, and
// that the confirmed call carries the exact parameters the panel collected.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  fireEvent,
  render,
  screen,
  waitFor,
  waitForElementToBeRemoved,
} from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from '@/api/query/client'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/hooks/useToast', () => ({ showToast: vi.fn() }))

vi.mock('@/api/http/molecule_chem', () => ({
  molFindAnalogsWithActivity: vi.fn(),
  molListClusters: vi.fn(),
  molGetClusterMembers: vi.fn(),
  molAssignCluster: vi.fn(),
  molRemoveFromCluster: vi.fn(),
  molDedupBatch: vi.fn(),
  molSearchSubstructure: vi.fn(),
  molGetStats: vi.fn(),
  molFindByMolecule: vi.fn(),
  molAddRelation: vi.fn(),
  molDeleteRelation: vi.fn(),
}))

import {
  molAddRelation,
  molAssignCluster,
  molDedupBatch,
  molFindAnalogsWithActivity,
  molListClusters,
  molSearchSubstructure,
} from '@/api/http/molecule_chem'
import AnalogSearchPanel from '../AnalogSearchPanel'
import ClusterPanel from '../ClusterPanel'
import DedupPanel from '../DedupPanel'
import RelationPanel from '../RelationPanel'
import SubstructureSearchPanel from '../SubstructureSearchPanel'

const molecules = [{ mol_id: 'm1', esmiles: 'CCO', name: 'ethanol' }] as never[]

function renderWithQuery(ui: React.ReactElement) {
  const client = createQueryClient()
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('molecule analytics panels', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(molListClusters).mockResolvedValue([])
  })

  it('submits the selected reference molecule to the analog search', async () => {
    vi.mocked(molFindAnalogsWithActivity).mockResolvedValue([] as never)
    renderWithQuery(<AnalogSearchPanel molecules={molecules} />)

    // No reference molecule selected: the search must not fire.
    fireEvent.click(screen.getByRole('button', { name: 'analytics.analogs.find' }))
    expect(molFindAnalogsWithActivity).not.toHaveBeenCalled()

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'm1' } })
    fireEvent.click(screen.getByRole('button', { name: 'analytics.analogs.find' }))

    await waitFor(() =>
      expect(molFindAnalogsWithActivity).toHaveBeenCalledWith('m1', expect.any(Number)),
    )
  })

  it('assigns a cluster only after confirming the dialog', async () => {
    vi.mocked(molAssignCluster).mockResolvedValue(1)
    renderWithQuery(<ClusterPanel molecules={molecules} />)

    fireEvent.click(screen.getByRole('button', { name: 'analytics.clusters.assign' }))
    fireEvent.click(screen.getByRole('button', { name: /取消/ }))
    expect(molAssignCluster).not.toHaveBeenCalled()
    // The modal keeps its exit animation mounted; wait for it to leave before
    // re-opening the dialog.
    await waitForElementToBeRemoved(() => screen.queryByRole('button', { name: /取消/ }))

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'm1' } })
    fireEvent.change(
      screen.getByPlaceholderText('analytics.clusters.clusterPlaceholder'),
      { target: { value: 'C-1' } },
    )
    fireEvent.click(screen.getByRole('button', { name: 'analytics.clusters.assign' }))
    // The dialog confirm shares the label; click the last match (in the modal).
    const confirmButtons = screen.getAllByRole('button', { name: 'analytics.clusters.assign' })
    fireEvent.click(confirmButtons[confirmButtons.length - 1])

    await waitFor(() => expect(molAssignCluster).toHaveBeenCalledWith('m1', 'C-1'))
  })

  it('deduplicates only after confirming the dialog', async () => {
    vi.mocked(molDedupBatch).mockResolvedValue({
      duplicates: [],
      new_mols: [],
      relations_added: 0,
    })
    renderWithQuery(<DedupPanel molecules={molecules} onComplete={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'analytics.dedup.run' }))
    fireEvent.click(screen.getByRole('button', { name: /取消/ }))
    expect(molDedupBatch).not.toHaveBeenCalled()
    await waitForElementToBeRemoved(() => screen.queryByRole('button', { name: /取消/ }))

    fireEvent.click(screen.getByRole('button', { name: 'analytics.dedup.run' }))
    // The dialog confirm shares the label; click the last match (in the modal).
    const confirmButtons = screen.getAllByRole('button', { name: 'analytics.dedup.run' })
    fireEvent.click(confirmButtons[confirmButtons.length - 1])

    await waitFor(() => expect(molDedupBatch).toHaveBeenCalledWith([['m1', 'CCO']], 0.95))
  })

  it('adds a relation only after confirming the dialog', async () => {
    vi.mocked(molAddRelation).mockResolvedValue({ id: 1 } as never)
    renderWithQuery(
      <RelationPanel
        molecules={
          [
            { mol_id: 'm1', esmiles: 'CCO', name: 'ethanol' },
            { mol_id: 'm2', esmiles: 'CCN', name: 'ethylamine' },
          ] as never[]
        }
      />,
    )

    const addButton = () => screen.getAllByRole('button', { name: 'common.add' })

    fireEvent.click(addButton()[0])
    fireEvent.click(screen.getByRole('button', { name: /取消/ }))
    expect(molAddRelation).not.toHaveBeenCalled()
    await waitForElementToBeRemoved(() => screen.queryByRole('button', { name: /取消/ }))

    const selects = screen.getAllByRole('combobox')
    fireEvent.change(selects[0], { target: { value: 'm1' } })
    fireEvent.change(selects[1], { target: { value: 'm2' } })
    fireEvent.click(addButton()[0])
    // The dialog confirm shares the label; click the last match (in the modal).
    fireEvent.click(addButton()[addButton().length - 1])

    await waitFor(() =>
      expect(molAddRelation).toHaveBeenCalledWith('m1', 'm2', 'similar', undefined),
    )
  })

  it('submits the trimmed substructure query to the search', async () => {
    vi.mocked(molSearchSubstructure).mockResolvedValue([] as never)
    renderWithQuery(<SubstructureSearchPanel />)

    // Blank query: the search must not fire.
    fireEvent.click(screen.getByRole('button', { name: 'common.search' }))
    expect(molSearchSubstructure).not.toHaveBeenCalled()

    fireEvent.change(screen.getByPlaceholderText('analytics.substructure.placeholder'), {
      target: { value: '  c1ccccc1  ' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'common.search' }))

    await waitFor(() =>
      expect(molSearchSubstructure).toHaveBeenCalledWith('c1ccccc1', expect.any(Number)),
    )
  })
})
