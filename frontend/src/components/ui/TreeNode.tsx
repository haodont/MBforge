import { motion, AnimatePresence } from 'framer-motion'
import { FolderIcon, FileTextIcon, ChevronRightIcon } from '../icons'

interface FileNode {
  name: string
  path: string
  is_dir: boolean
  children: FileNode[]
}

export interface TreeNodeProps {
  node: FileNode
  depth?: number
  expanded?: boolean
  onToggle?: () => void
  onClick?: () => void
}

export default function TreeNode({ node, depth = 0, expanded = false, onToggle, onClick }: TreeNodeProps) {
  const paddingLeft = `${8 + depth * 16}px`

  if (node.is_dir) {
    return (
      <div>
        <div
          onClick={onToggle}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            padding: '4px 8px',
            paddingLeft,
            cursor: 'pointer',
            fontSize: '13px',
            color: 'var(--text-primary)',
            borderRadius: '4px',
            transition: 'background 0.1s',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-hover)' }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
        >
          <span style={{
            display: 'inline-flex',
            transition: 'transform 0.15s',
            transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)',
          }}>
            <ChevronRightIcon size={12} />
          </span>
          <FolderIcon size={14} />
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {node.name}
          </span>
        </div>
        <AnimatePresence>
          {expanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2, ease: 'easeInOut' }}
              style={{ overflow: 'hidden' }}
            >
              {node.children.map((child) => (
                <TreeNode
                  key={child.path}
                  node={child}
                  depth={depth + 1}
                  onClick={() => onClick?.()}
                />
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    )
  }

  return (
    <div
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '4px',
        padding: '4px 8px',
        paddingLeft,
        cursor: 'pointer',
        fontSize: '13px',
        color: 'var(--text-secondary)',
        borderRadius: '4px',
        transition: 'background 0.1s, color 0.1s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'var(--bg-hover)'
        e.currentTarget.style.color = 'var(--text-primary)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'transparent'
        e.currentTarget.style.color = 'var(--text-secondary)'
      }}
    >
      <FileTextIcon size={14} />
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {node.name}
      </span>
    </div>
  )
}
