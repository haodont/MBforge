import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FileTextIcon } from './icons'
import GroupsPanel from './GroupsPanel'
import Button from '@/components/ui/Button'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import { useAppContext } from '@/context/AppContext'
import {
  useLibraryStatus,
  useCollections,
  useCreateCollection,
  useRenameCollection,
  useDeleteCollection,
} from '@/api/query/hooks'
import { showToast } from '@/hooks/useToast'
import { getUserFacingError } from '@/utils/errors'

export default function LibraryPanel() {
  const { t } = useTranslation()
  const { activeCollectionId, setActiveCollectionId } = useAppContext()
  const statusQuery = useLibraryStatus()
  const collectionsQuery = useCollections()
  const createMutation = useCreateCollection()
  const renameMutation = useRenameCollection()
  const deleteMutation = useDeleteCollection()

  const collections = collectionsQuery.data?.collections ?? []
  const docCount = statusQuery.data?.doc_count ?? 0

  const handleCreateGroup = async (name: string): Promise<string | undefined> => {
    try {
      const resp = await createMutation.mutateAsync({ name })
      if (resp.success && resp.collection) {
        return resp.collection.collection_id
      } else {
        showToast(resp.error || 'Failed to create group', 'error')
        return undefined
      }
    } catch (e) {
      showToast(getUserFacingError(e, t('library.configureLibrary')), 'error')
      return undefined
    }
  }

  const handleRenameGroup = useCallback(
    async (id: string, newName: string) => {
      if (!newName.trim()) {
        showToast(t('group.renameEmpty'), 'warning')
        return
      }
      try {
        await renameMutation.mutateAsync({ collectionId: id, name: newName.trim() })
        showToast(t('group.renameSuccess', { name: newName.trim() }), 'success')
      } catch (e) {
        showToast(
          getUserFacingError(e, t('group.renameError', { error: '' })),
          'error',
        )
      }
    },
    [renameMutation, t],
  )

  const [pendingDelete, setPendingDelete] = useState<{ id: string; name: string } | null>(null)

  const handleDeleteGroup = useCallback(
    (id: string, name: string) => {
      setPendingDelete({ id, name })
    },
    [],
  )

  const runDeleteGroup = useCallback(
    async (id: string, name: string) => {
      setPendingDelete(null)
      try {
        await deleteMutation.mutateAsync(id)
        if (activeCollectionId === id) setActiveCollectionId(null)
        showToast(t('group.deleteSuccess', { name }), 'success')
      } catch (e) {
        showToast(
          getUserFacingError(e, t('group.deleteError', { error: '' })),
          'error',
        )
      }
    },
    [activeCollectionId, deleteMutation, setActiveCollectionId, t],
  )

  return (
    <div className="library-panel">
      <GroupsPanel
        collections={collections}
        activeId={activeCollectionId}
        onSelect={setActiveCollectionId}
        onCreateGroup={handleCreateGroup}
        onRenameGroup={handleRenameGroup}
        onDeleteGroup={handleDeleteGroup}
      />

      <div className="library-panel-section library-panel-section--all-documents">
        <Button
          variant="ghost"
          size="sm"
          ariaPressed={activeCollectionId === null}
          className={`library-panel-item ${activeCollectionId === null ? 'library-panel-item--active' : ''}`}
          onClick={() => setActiveCollectionId(null)}
        >
          <FileTextIcon size={14} />
          <span className="library-panel-item-label">{t('library.allDocuments')}</span>
          <span className="library-panel-item-count">{docCount}</span>
        </Button>
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        title={t('group.delete')}
        message={pendingDelete ? t('group.deleteConfirm', { name: pendingDelete.name }) : ''}
        confirmLabel={t('group.delete')}
        onConfirm={() => { if (pendingDelete) void runDeleteGroup(pendingDelete.id, pendingDelete.name) }}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  )
}
