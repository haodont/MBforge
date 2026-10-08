/** Queue task list — animated rows, virtualized for genuinely long queues. */

import { useRef } from 'react'
import { AnimatePresence } from 'framer-motion'
import { useVirtualizer } from '@tanstack/react-virtual'
import { TaskRow } from './TaskRow'
import type { IngestLogEvent, IngestTask } from '@/api/http/ingest_queue'

// Stable identity so memoized rows without logs skip re-renders.
const EMPTY_LOGS: IngestLogEvent[] = []

export interface QueueTaskListProps {
  tasks: IngestTask[]
  now: number
  expandedLogDocs: Set<string>
  logMap: Map<string, IngestLogEvent[]>
  actionId: string | null
  onToggleLogs: (docId: string) => void
  onCancel: (task: IngestTask) => void
  onRetry: (task: IngestTask, resumeFromStage?: string) => void
  onDelete: (task: IngestTask) => void
  onTogglePin: (task: IngestTask) => void
}

/** Keep the common queue small and animated; virtualize only genuinely long queues. */
export function QueueTaskList({
  tasks,
  now,
  expandedLogDocs,
  logMap,
  actionId,
  onToggleLogs,
  onCancel,
  onRetry,
  onDelete,
  onTogglePin,
}: QueueTaskListProps) {
  const parentRef = useRef<HTMLDivElement>(null)
  const shouldVirtualize = tasks.length > 80
  // TanStack Virtual exposes mutable functions that React Compiler cannot memoize.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: shouldVirtualize ? tasks.length : 0,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 116,
    measureElement: (element) => element.getBoundingClientRect().height,
    overscan: 6,
  })

  const renderTask = (task: IngestTask) => (
    <TaskRow
      key={task.id}
      task={task}
      // Terminal rows never display elapsed/ETA — freeze `now` so the 1s
      // tick re-renders only rows that actually show a live clock.
      now={task.status === 'done' || task.status === 'cancelled' ? 0 : now}
      isLogsExpanded={expandedLogDocs.has(task.doc_id)}
      logs={logMap.get(task.doc_id) ?? EMPTY_LOGS}
      isActioning={actionId === task.id}
      onToggleLogs={onToggleLogs}
      onCancel={onCancel}
      onRetry={onRetry}
      onDelete={onDelete}
      onTogglePin={onTogglePin}
    />
  )

  if (!shouldVirtualize) {
    return (
      <div className="queue-list">
        <AnimatePresence initial={false}>
          {tasks.map(renderTask)}
        </AnimatePresence>
      </div>
    )
  }

  return (
    <div ref={parentRef} className="queue-list queue-list-virtual">
      <div
        className="queue-list-virtual-inner"
        style={{ height: `${virtualizer.getTotalSize()}px` }}
      >
        {virtualizer.getVirtualItems().map((virtualItem) => (
          <div
            key={tasks[virtualItem.index].id}
            ref={virtualizer.measureElement}
            data-index={virtualItem.index}
            className="queue-list-virtual-item"
            style={{ transform: `translateY(${virtualItem.start}px)` }}
          >
            {renderTask(tasks[virtualItem.index])}
          </div>
        ))}
      </div>
    </div>
  )
}
