import type { Trajectory, TrajectoryStep } from './trajectory.js'

export interface BehaviorExpectations {
  requiredTools?: string[]
  forbiddenTools?: string[]
  maxSteps?: number
  maxConsecutiveRepeats?: number
}

export type BehaviorRule =
  'required_tool' | 'forbidden_tool' | 'step_budget' | 'no_progress'

export interface BehaviorViolation {
  rule: BehaviorRule
  message: string
}

export interface BehaviorReport {
  passed: boolean
  stepCount: number
  violations: BehaviorViolation[]
}

export const DEFAULT_REPEAT_THRESHOLD = 3

/**
 * Find a run of consecutive identical calls (same tool and input digest). An
 * empty digest is never matched, so distinct no-arg calls are not conflated.
 * Shared by the offline grader and the runtime loop guard.
 */
export function detectNoProgress(
  steps: readonly TrajectoryStep[],
  threshold = DEFAULT_REPEAT_THRESHOLD,
): { tool: string; inputDigest: string; count: number } | undefined {
  let run = 1
  for (let index = 1; index <= steps.length; index += 1) {
    const previous = steps[index - 1]
    const current = steps[index]
    const identical =
      current !== undefined &&
      previous !== undefined &&
      current.tool === previous.tool &&
      current.inputDigest === previous.inputDigest &&
      current.inputDigest !== ''
    if (identical) {
      run += 1
      continue
    }
    if (previous && run >= threshold) {
      return {
        tool: previous.tool,
        inputDigest: previous.inputDigest,
        count: run,
      }
    }
    run = 1
  }
  return undefined
}

/** Deterministic behavioral gate over a frozen trajectory; no model involved. */
export function gradeTrajectory(
  trajectory: Trajectory,
  expectations: BehaviorExpectations,
): BehaviorReport {
  const steps = trajectory.steps
  const called = new Set(steps.map((step) => step.tool))
  const violations: BehaviorViolation[] = []

  for (const tool of expectations.requiredTools ?? []) {
    if (!called.has(tool)) {
      violations.push({
        rule: 'required_tool',
        message: `required tool ${tool} was never called`,
      })
    }
  }
  for (const tool of expectations.forbiddenTools ?? []) {
    if (called.has(tool)) {
      violations.push({
        rule: 'forbidden_tool',
        message: `forbidden tool ${tool} was called`,
      })
    }
  }
  if (
    expectations.maxSteps !== undefined &&
    steps.length > expectations.maxSteps
  ) {
    violations.push({
      rule: 'step_budget',
      message: `${steps.length} steps exceeds the budget of ${expectations.maxSteps}`,
    })
  }
  const loop = detectNoProgress(
    steps,
    expectations.maxConsecutiveRepeats ?? DEFAULT_REPEAT_THRESHOLD,
  )
  if (loop) {
    violations.push({
      rule: 'no_progress',
      message: `${loop.tool} repeated ${loop.count} identical consecutive calls without progress`,
    })
  }
  return {
    passed: violations.length === 0,
    stepCount: steps.length,
    violations,
  }
}

/** Repository mutation tools that bypass the capability contract in auto mode. */
export const AUTO_FORBIDDEN_TOOLS = ['bash', 'edit', 'write']

/**
 * Expectations derived automatically from a trajectory, so the regression gate
 * needs no hand-written rules: a no-progress loop is always a violation, and in
 * auto mode the built-in mutation tools must never appear (capabilities are the
 * only write path). Task-specific required tools stay a manual addition.
 */
export function baselineExpectations(
  trajectory: Trajectory,
): BehaviorExpectations {
  return {
    maxConsecutiveRepeats: DEFAULT_REPEAT_THRESHOLD,
    forbiddenTools: trajectory.mode === 'auto' ? [...AUTO_FORBIDDEN_TOOLS] : [],
  }
}
