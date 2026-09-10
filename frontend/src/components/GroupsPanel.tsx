import { useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronRightIcon, ChevronDownIcon, FolderIcon, PlusIcon, EditIcon, TrashIcon } from './icons'
import Menu, { type MenuItem } from '@/components/ui/Menu'
import IconButton from '@/components/ui/IconButton'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import type { CollectionNode } from '@/api/http/library'

interface ContextMenuState {
  collectionId: string
  name: string
}

interface Props {
  collections: CollectionNode[]
  activeId: string | null
  onSelect: (id: string | null) => void
  onCreateGroup: (name: string) => Promise<string | undefined>
  onRenameGroup: (id: string, newName: string) => Promise<void> | void
  onDeleteGroup: (id: string, name: string) => Promise<void> | void
}

export default function GroupsPanel({
  collections,
  activeId,
  onSelect,
  onCreateGroup,
  onRenameGroup,
  onDeleteGroup,
}: Props) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null)

  const toggleExpand = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleCreate = async () => {
    if (!newName.trim()) return
    const createdId = await onCreateGroup(newName.trim())
    setNewName('')
    setShowCreate(false)
    if (createdId) {
      const findParent = (nodes: CollectionNode[], target: string): string | null => {
        for (const n of nodes) {
          if (n.children.some(c => c.collection_id === target)) return n.collection_id
          const found = findParent(n.children, target)
          if (found) return found
        }
        return null
      }
      const parentId = findParent(collections, createdId)
      if (parentId) setExpanded(prev => new Set(prev).add(parentId))
    }
  }

  const closeContextMenu = useCallback(() => setContextMenu(null), [])

  const handleContextMenu = (
    e: React.MouseEvent<HTMLButtonElement>,
    node: CollectionNode,
  ) => {
    e.preventDefault()
    e.stopPropagation()
    setContextMenu({ collectionId: node.collection_id, name: node.name })
  }

  const handleRename = async (id: string, currentName: string) => {
    closeContextMenu()
    const next = window.prompt(t('group.renamePrompt', { name: currentName }), currentName)
    if (next === null) return
    await onRenameGroup(id, next)
  }

  const handleDelete = async (id: string, name: string) => {
    closeContextMenu()
    await onDeleteGroup(id, name)
  }

  const contextItems: MenuItem[] = contextMenu
    ? [
        {
          key: 'rename',
          label: t('group.rename'),
          icon: <EditIcon size={14} />,
          onClick: () => void handleRename(contextMenu.collectionId, contextMenu.name),
        },
        {
          key: 'delete',
          label: t('group.delete'),
          icon: <TrashIcon size={14} />,
          danger: true,
          onClick: () => void handleDelete(contextMenu.collectionId, contextMenu.name),
        },
      ]
    : []

  const renderNode = (node: CollectionNode, depth: number) => {
    const isExpanded = expanded.has(node.collection_id)
    const isActive = activeId === node.collection_id
    const hasChildren = node.children.length > 0

    return (
      <div key={node.collection_id}>
        <Button
          variant="ghost"
          size="sm"
          className={`library-tree-node ${isActive ? 'library-tree-node--active' : ''}`}
          onContextMenu={(e) => handleContextMenu(e, node)}
          onClick={() => onSelect(node.collection_id)}
          style={{ paddingLeft: `${12 + depth * 16}px`, width: '100%', justifyContent: 'flex-start' }}
        >
          {hasChildren ? (
            <span
              className="library-tree-chevron"
              onClick={(e) => { e.stopPropagation(); toggleExpand(node.collection_id) }}
            >
              {isExpanded ? <ChevronDownIcon size={12} /> : <ChevronRightIcon size={12} />}
            </span>
          ) : (
            <span className="library-tree-chevron library-tree-chevron--spacer" />
          )}
          <FolderIcon size={14} />
          <span className="library-tree-label">{node.name}</span>
          <span className="library-tree-count">{node.doc_count}</span>
        </Button>
        {hasChildren && isExpanded && (
          <div>{node.children.map(c => renderNode(c, depth + 1))}</div>
        )}
      </div>
    )
  }

  return (
    <div className="library-groups-panel">
      <div className="library-groups-header">
        <span className="library-groups-title">{t('library.collections') || 'Groups'}</span>
        <IconButton
          size={32}
          title={t('library.newCollection') || 'New Group'}
          onClick={() => setShowCreate(!showCreate)}
        >
          <PlusIcon size={12} />
        </IconButton>
      </div>

      {showCreate && (
        <div className="library-groups-create">
          <Input
            type="text"
            className="library-groups-create-input"
            placeholder={t('library.newCollection') || 'Group name...'}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void handleCreate(); if (e.key === 'Escape') { setShowCreate(false); setNewName('') } }}
            autoFocus
          />
          <Button size="sm" className="library-groups-create-btn" onClick={handleCreate}>
            {t('common.add')}
          </Button>
        </div>
      )}

      <div className="library-tree">
        {collections.length === 0 ? (
          <div className="library-tree-empty">{t('library.noCollections') || 'No groups yet'}</div>
        ) : (
          collections.map(c => renderNode(c, 0))
        )}
      </div>

      <Menu
        open={contextMenu !== null}
        onOpenChange={(next) => { if (!next) setContextMenu(null) }}
        items={contextItems}
      />
    </div>
  )
}
