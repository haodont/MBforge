/**
 * 笔记实体.
 *
 * Field shape matches the Pydantic `Note` schema in `src/mbforge/models/`.
 */
export interface Note {
  id: string
  title: string
  content: string
  tags: string[]
  /** 关联的实体 */
  links: NoteLink[]
  createdAt: string
  updatedAt: string
}

export interface NoteLink {
  type: 'molecule' | 'document' | 'session' | 'note'
  refId: string
  refTitle: string
}
