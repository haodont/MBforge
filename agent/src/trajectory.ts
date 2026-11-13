import { GOAL_ENTRY_TYPE } from './goal.js'
import { atomicWrite } from './localStore.js'

export interface TrajectoryStep {
  tool: string
  inputDigest: string
  status: 'ok' | 'error'
  at: string
}

export interface Trajectory {
  goalId: string
  title: string
  steps: TrajectoryStep[]
  /** Session mode at completion; lets the baseline forbid capability bypass in auto. */
  mode?: string
}

function goalData(entry: unknown): Record<string, unknown> | undefined {
  if (typeof entry !== 'object' || entry === null || Array.isArray(entry)) {
    return undefined
  }
  const record = entry as Record<string, unknown>
  if (record.type !== 'custom' || record.customType !== GOAL_ENTRY_TYPE) {
    return undefined
  }
  if (
    typeof record.data !== 'object' ||
    record.data === null ||
    Array.isArray(record.data)
  ) {
    return undefined
  }
  return record.data as Record<string, unknown>
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/**
 * Extract a goal's ordered tool-call trajectory from a session branch. Real
 * runs recorded by the goal artifact hook become frozen eval fixtures through
 * {@link exportTrajectoryFile}; the grader never needs the model or network.
 */
export function trajectoryFromBranch(
  branch: readonly unknown[],
  goalId?: string,
): Trajectory | undefined {
  let id = goalId ?? ''
  let title = ''
  const steps: TrajectoryStep[] = []
  for (const entry of branch) {
    const data = goalData(entry)
    if (!data) continue
    const action = str(data.action)
    if (action === 'begin' || action === 'update') {
      const goal = data.goal
      if (typeof goal === 'object' && goal !== null && !Array.isArray(goal)) {
        const definition = goal as Record<string, unknown>
        const gid = str(definition.id)
        if (!id && gid) id = gid
        if (gid && gid === id) title = str(definition.title) || title
      }
      continue
    }
    if (action !== 'tool') continue
    const gid = str(data.goal_id)
    if (!id && gid) id = gid
    if (id && gid && gid !== id) continue
    const tool = str(data.tool)
    if (!tool) continue
    steps.push({
      tool,
      inputDigest: str(data.input_digest),
      status: str(data.status) === 'error' ? 'error' : 'ok',
      at: str(data.at),
    })
  }
  if (!id || steps.length === 0) return undefined
  return { goalId: id, title, steps }
}

/** Freeze a trajectory as a JSON eval fixture. */
export async function exportTrajectoryFile(
  path: string,
  trajectory: Trajectory,
): Promise<void> {
  await atomicWrite(path, `${JSON.stringify(trajectory, null, 2)}\n`)
}
