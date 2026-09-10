import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/hooks/useToast', () => ({ showToast: vi.fn() }))

vi.mock('@/api/http/molecule', () => ({
  molListClusters: vi.fn(),
  molGetClusterMembers: vi.fn(),
  molAssignCluster: vi.fn(),
  molRemoveFromCluster: vi.fn(),
}))

import { molAssignCluster, molListClusters } from '@/api/http/molecule'
import ClusterPanel from '../ClusterPanel'

const molecules = [{ mol_id: 'm1', esmiles: 'CCO', name: 'ethanol' }] as never[]

describe('ClusterPanel destructive confirmation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(molListClusters as ReturnType<typeof vi.fn>).mockResolvedValue([])
  })

  it('does not assign when the dialog is cancelled', () => {
    render(<ClusterPanel molecules={molecules} />)
    fireEvent.click(screen.getByRole('button', { name: 'analytics.clusters.assign' }))
    fireEvent.click(screen.getByRole('button', { name: /取消/ }))
    expect(molAssignCluster).not.toHaveBeenCalled()
  })

  it('assigns only after confirming the dialog', async () => {
    ;(molAssignCluster as ReturnType<typeof vi.fn>).mockResolvedValue(undefined)

    render(<ClusterPanel molecules={molecules} />)

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'm1' } })
    fireEvent.change(
      screen.getByPlaceholderText('analytics.clusters.clusterPlaceholder'),
      { target: { value: 'C-1' } },
    )
    fireEvent.click(screen.getByRole('button', { name: 'analytics.clusters.assign' }))
    // The dialog confirm shares the label; click the last match (in the modal).
    const confirmButtons = screen.getAllByRole('button', { name: 'analytics.clusters.assign' })
    fireEvent.click(confirmButtons[confirmButtons.length - 1])

    await waitFor(() =>
      expect(molAssignCluster).toHaveBeenCalledWith('m1', 'C-1'),
    )
  })
})
