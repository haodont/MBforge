import { useState, useMemo, type ReactNode } from 'react'
import Pagination from './Pagination'

export interface DataTableColumn<T> {
  /** 唯一 key，对应 row[key] */
  key: keyof T | string
  /** 列标题 */
  title: ReactNode
  /** 自定义渲染 */
  render?: (row: T, index: number) => ReactNode
  /** 是否可排序 */
  sortable?: boolean
  /** 排序函数（默认按 value 字典序）*/
  sorter?: (a: T, b: T) => number
  /** 列宽度 */
  width?: number | string
  /** 对齐方式 */
  align?: 'left' | 'center' | 'right'
  /** 固定列（不滚动） */
  fixed?: 'left' | 'right'
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[]
  data: T[]
  /** 行 key（默认用 row.key 字段）*/
  rowKey?: keyof T | ((row: T) => string)
  /** 是否加载中 */
  loading?: boolean
  /** 空状态文案 */
  emptyText?: string
  /** 行点击回调 */
  onRowClick?: (row: T, index: number) => void
  /** 行 hover 高亮 */
  hoverable?: boolean
  /** 斑马纹 */
  striped?: boolean
  /** 边框 */
  bordered?: boolean
  /** 紧凑模式 */
  size?: 'sm' | 'md' | 'lg'
  /** 是否启用分页 */
  pagination?: {
    pageSize: number
    showQuickJumper?: boolean
    showTotal?: boolean
  }
  /** 表格标题栏 */
  title?: ReactNode
  /** 表格右上角操作区 */
  extra?: ReactNode
  style?: React.CSSProperties
  className?: string
}

const sizeMap = {
  sm: { cellPadding: '6px 10px', fontSize: 12, headerSize: 11 },
  md: { cellPadding: '10px 12px', fontSize: 13, headerSize: 12 },
  lg: { cellPadding: '14px 16px', fontSize: 14, headerSize: 13 },
}

type SortState = { key: string; direction: 'asc' | 'desc' } | null

/**
 * DataTable 通用数据表格。
 *
 * 支持排序、分页、行点击、自定义渲染。
 * 不可用于超大数据集（>1000 行），那种场景应使用 react-virtual 等虚拟滚动。
 */
export default function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  rowKey = 'key',
  loading = false,
  emptyText = '暂无数据',
  onRowClick,
  hoverable = true,
  striped = false,
  bordered = true,
  size = 'md',
  pagination,
  title,
  extra,
  style,
  className,
}: DataTableProps<T>) {
  const [sort, setSort] = useState<SortState>(null)
  const [page, setPage] = useState(1)

  const sizeStyle = sizeMap[size]

  const processedData = useMemo(() => {
    const result = [...data]
    if (sort) {
      const col = columns.find(c => c.key === sort.key)
      const sorter = col?.sorter ?? ((a: T, b: T) => {
        const av = a[col?.key as keyof T]
        const bv = b[col?.key as keyof T]
        if (av == null) return 1
        if (bv == null) return -1
        if (typeof av === 'number' && typeof bv === 'number') return av - bv
        return String(av).localeCompare(String(bv))
      })
      result.sort((a, b) => {
        const r = sorter(a, b)
        return sort.direction === 'asc' ? r : -r
      })
    }
    return result
  }, [data, sort, columns])

  const pagedData = useMemo(() => {
    if (!pagination) return processedData
    const start = (page - 1) * pagination.pageSize
    return processedData.slice(start, start + pagination.pageSize)
  }, [processedData, page, pagination])

  const getRowKey = (row: T, index: number): string => {
    if (typeof rowKey === 'function') return rowKey(row)
    return String(row[rowKey] ?? index)
  }

  const handleSort = (col: DataTableColumn<T>) => {
    if (!col.sortable) return
    if (sort?.key === col.key) {
      setSort(s => s?.direction === 'asc' ? { key: col.key as string, direction: 'desc' } : null)
    } else {
      setSort({ key: col.key as string, direction: 'asc' })
    }
  }

  const totalPages = pagination ? Math.ceil(processedData.length / pagination.pageSize) : 1

  return (
    <div
      className={className}
      style={{
        background: 'var(--bg-surface)',
        border: bordered ? '1px solid var(--border)' : 'none',
        borderRadius: 12,
        overflow: 'hidden',
        ...style,
      }}
    >
      {(title || extra) && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '14px 16px',
          borderBottom: '1px solid var(--border)',
        }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
            {title}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>{extra}</div>
        </div>
      )}

      <div style={{ overflowX: 'auto' }}>
        <table style={{
          width: '100%',
          borderCollapse: 'collapse',
          fontSize: sizeStyle.fontSize,
        }}>
          <thead>
            <tr style={{ background: 'var(--bg-base)' }}>
              {columns.map(col => (
                <th
                  key={col.key as string}
                  style={{
                    padding: sizeStyle.cellPadding,
                    textAlign: col.align ?? 'left',
                    fontSize: sizeStyle.headerSize,
                    fontWeight: 600,
                    color: 'var(--text-muted)',
                    textTransform: 'uppercase',
                    letterSpacing: 0.5,
                    width: col.width,
                    cursor: col.sortable ? 'pointer' : 'default',
                    userSelect: 'none',
                    whiteSpace: 'nowrap',
                    borderBottom: '1px solid var(--border)',
                    position: col.fixed ? 'sticky' : undefined,
                    left: col.fixed === 'left' ? 0 : undefined,
                    right: col.fixed === 'right' ? 0 : undefined,
                    background: 'var(--bg-base)',
                    zIndex: col.fixed ? 1 : undefined,
                  }}
                  onClick={() => handleSort(col)}
                >
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    {col.title}
                    {col.sortable && (
                      <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>
                        {sort?.key === col.key
                          ? (sort.direction === 'asc' ? '▲' : '▼')
                          : '⇅'}
                      </span>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={columns.length} style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>
                  加载中...
                </td>
              </tr>
            ) : pagedData.length === 0 ? (
              <tr>
                <td colSpan={columns.length} style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>
                  {emptyText}
                </td>
              </tr>
            ) : (
              pagedData.map((row, i) => (
                <tr
                  key={getRowKey(row, i)}
                  onClick={onRowClick ? () => onRowClick(row, i) : undefined}
                  style={{
                    background: striped && i % 2 === 1 ? 'var(--bg-base)' : 'transparent',
                    cursor: onRowClick ? 'pointer' : 'default',
                    transition: 'background 0.1s',
                  }}
                  onMouseEnter={e => {
                    if (hoverable) e.currentTarget.style.background = 'var(--bg-hover)'
                  }}
                  onMouseLeave={e => {
                    if (hoverable) e.currentTarget.style.background =
                      striped && i % 2 === 1 ? 'var(--bg-base)' : 'transparent'
                  }}
                >
                  {columns.map(col => (
                    <td
                      key={col.key as string}
                      style={{
                        padding: sizeStyle.cellPadding,
                        textAlign: col.align ?? 'left',
                        color: 'var(--text-primary)',
                        borderBottom: '1px solid var(--border)',
                      }}
                    >
                      {col.render ? col.render(row, i) : (row[col.key as keyof T] as ReactNode)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {pagination && totalPages > 1 && (
        <div style={{
          padding: '12px 16px',
          borderTop: '1px solid var(--border)',
          display: 'flex',
          justifyContent: 'flex-end',
        }}>
          <Pagination
            current={page}
            total={totalPages}
            pageSize={pagination.pageSize}
            totalItems={processedData.length}
            onChange={setPage}
            showQuickJumper={pagination.showQuickJumper}
            showTotal={pagination.showTotal}
            size={size === 'lg' ? 'md' : 'sm'}
          />
        </div>
      )}
    </div>
  )
}
