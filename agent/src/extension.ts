import type {
  ExtensionAPI,
  ExtensionContext,
} from '@earendil-works/pi-coding-agent'
import { createHash } from 'node:crypto'
import { stat } from 'node:fs/promises'

import { BACKEND_TOOL_NAMES, registerBackendTool } from './backendTool.js'
import {
  backendLabel,
  brandHeader,
  brandThemePaths,
  brandWorkingFrames,
  type BrandState,
} from './brand.js'
import { brandFooter } from './footer.js'
import {
  GOAL_REVIEW_MESSAGE_TYPE,
  RUN_MESSAGE_TYPE,
  goalReviewRenderer,
  runNoticeRenderer,
} from './messages.js'
import { builtinToolRenderers } from './toolRender.js'
import {
  backendBaseUrl,
  createCapabilityToolsetManager,
  type CapabilityTool,
} from './capabilities.js'
import {
  parseSessionMode,
  resolveSessionMode,
  usesBuiltinTools,
  type SessionMode,
} from './modes.js'
import {
  clearEvidence,
  linkifyCitations,
  rememberEvidence,
  type EvidenceLocation,
} from './citations.js'
import { linkifyUiLinks } from './uiLinks.js'
import { errorMessage } from './text.js'
import { registerEndpointCommand } from './endpointCommand.js'
import {
  ensureMemoryFile,
  MEMORY_TOOL_NAMES,
  memoryColdPath,
  memoryFilePath,
  memorySystemPrompt,
  registerMemoryCommand,
  registerMemoryTools,
  setMemoryRuntime,
} from './memory.js'
import {
  IMPROVEMENT_TOOL_NAMES,
  registerImprovementTools,
} from './improvements.js'
import {
  REVIEW_TOOL_NAME,
  REVIEW_TOOL_NAMES,
  registerReviewTools,
  runReview,
} from './review.js'
import {
  activeGoalFromBranch,
  GOAL_ENTRY_TYPE,
  GOAL_TOOL_NAMES,
  GOAL_TOOL_NAME,
  goalContractPrompt,
  goalStateFromBranch,
  registerGoalTool,
  type GoalReviewJob,
} from './goal.js'
import {
  claimNextReview,
  enqueueReviewJob,
  failReviewJob,
  finishReviewJob,
  listReviewJobs,
  retryReviewJob,
} from './reviewQueue.js'
import { ReviewNoticeQueue, type ReviewNotice } from './reviewNotices.js'
import { createRunNotifier, createRunWatcher } from './runs.js'
import { DEV_MODE_TOOL_NAMES, registerDevModeTool } from './devMode.js'
import { ASK_TOOL_NAME, ASK_TOOL_NAMES, registerAskTool } from './ask.js'
import {
  DRAFT_TOOL_NAME,
  DRAFT_TOOL_NAMES,
  registerDraftTool,
} from './draft.js'
import {
  RESEARCH_TOOL_NAME,
  RESEARCH_TOOL_NAMES,
  registerResearchChild,
  registerResearchTools,
} from './research.js'
import { goalWidget } from './goalWidget.js'
import {
  addWorkThread,
  readWorkState,
  registerWorkStateTools,
  WORK_STATE_TOOL_NAMES,
  workStateFilePath,
  workStateSystemPrompt,
} from './workState.js'
import { detectNoProgress } from './behaviorEval.js'
import { exportGoalFixture, sweepFixtures } from './evalFixtures.js'
import {
  learnedMethodsPrompt,
  pruneSkeleton,
  readSkills,
  recordSuccess,
  refreshSkills,
  skillStorePath,
} from './skillInduction.js'
import { trajectoryFromBranch, type TrajectoryStep } from './trajectory.js'

const BUILTIN_TOOL_NAMES = [
  'read',
  'bash',
  'edit',
  'write',
  'grep',
  'find',
  'ls',
] as const

/** Cheap change-detector for a store file: mtime+size, or 'absent'. */
async function fileSignature(path: string): Promise<string> {
  try {
    const info = await stat(path)
    return `${info.mtimeMs}:${info.size}`
  } catch {
    return 'absent'
  }
}

/**
 * Close the eval loop: behavioral regressions found by the fixture sweep become
 * deduped work_state follow-ups so they re-enter the agent's resume context
 * instead of only failing `npm test`. Best-effort and bounded.
 */
async function surfaceBehavioralRegressions(): Promise<void> {
  const failures = await sweepFixtures()
  if (failures.length === 0) return
  const state = await readWorkState()
  const openTitles = new Set(
    state.threads
      .filter((thread) => thread.status === 'open')
      .map((thread) => thread.title),
  )
  for (const failure of failures.slice(0, 5)) {
    const title = `behavioral regression: ${failure.file}`
    if (openTitles.has(title)) continue
    openTitles.add(title)
    await addWorkThread({
      kind: 'follow_up',
      title,
      detail: failure.violations.map((violation) => violation.rule).join(', '),
    })
  }
}

/**
 * Pi throws from every ctx accessor once the session is replaced (`newSession`,
 * `fork`, `switchSession`) or reloaded. Background work can outlive that, so it
 * must ask before touching a captured ctx: an uncaught throw here takes pi down.
 */
function isLive(ctx: ExtensionContext): boolean {
  try {
    void ctx.ui
    return true
  } catch {
    return false
  }
}

/** `ctx.ui.notify` for work that may be holding a ctx pi already invalidated. */
function notifyLive(
  ctx: ExtensionContext,
  message: string,
  type: 'info' | 'warning' | 'error',
): void {
  if (isLive(ctx)) ctx.ui.notify(message, type)
}

/** Rebuild the citation cache from the active branch so resumed sessions linkify. */
function reconstructEvidence(ctx: ExtensionContext): void {
  clearEvidence()
  for (const entry of ctx.sessionManager.getBranch()) {
    if (entry.type !== 'message') continue
    const message = entry.message as { role?: string; details?: unknown }
    if (message.role !== 'toolResult') continue
    const index = (
      message.details as { evidenceIndex?: EvidenceLocation[] } | undefined
    )?.evidenceIndex
    if (!Array.isArray(index)) continue
    for (const location of index) rememberEvidence(location)
  }
}

/**
 * Tell the model what this session can actually call. Pi already renders the
 * registered tool definitions, but the explicit mode/availability summary
 * stops it from probing the manifest with curl when the user asks what is
 * possible.
 */
function capabilityContext(
  mode: SessionMode,
  tools: CapabilityTool[],
  mutatingNames: string[],
  loadError: string | undefined,
  localTools: string[] = [],
): string {
  if (loadError) {
    const localNote =
      localTools.length > 0
        ? ` Local tools (${localTools.join(', ')}) remain available for local agent state.`
        : ''
    return (
      'MBForge backend capabilities are unavailable because the backend could ' +
      `not be reached: ${loadError}.${localNote} Do not query the capability ` +
      'manifest; report the backend status and its log location instead. ' +
      'backend_control can start the backend; capabilities reload automatically ' +
      'after a successful start, and /mbforge reload refreshes them on demand.'
    )
  }
  const mutating = new Set(mutatingNames)
  const readNames = tools
    .filter((tool) => !mutating.has(tool.name))
    .map((tool) => tool.name)
  const writeNames = tools
    .filter((tool) => mutating.has(tool.name))
    .map((tool) => tool.name)
  const localNote =
    localTools.length > 0
      ? ` Local tools (${localTools.join(', ')}) manage agent-local state, not library data; work_state action=check additionally reads linked run/review/document status read-only to reconcile follow-ups.`
      : ''
  const scope =
    mode === 'auto'
      ? 'Mode auto exposes every registered MBForge capability; mutating calls need the capability token and return 403 without it. Repository/code tools are inactive: when a task needs them, call request_dev_mode and let the user approve or decline. Do not answer that the user must request dev mode themselves, and do not print commands for them to run instead.'
      : 'Mode dev exposes every registered MBForge capability plus built-in repository tools; mutating calls need the capability token.'
  return [
    `MBForge session mode (${mode}).`,
    `Read capabilities (${readNames.length}): ${readNames.length > 0 ? readNames.join(', ') : 'none'}.`,
    `Mutating capabilities (${writeNames.length}): ${writeNames.length > 0 ? writeNames.join(', ') : 'none'}.`,
    `${scope}${localNote}`,
    'The active tool list is authoritative. Do not query /api/v1/capabilities, do not print a curl command to discover capabilities, and do not guess that an inactive tool exists. If no active tool can perform the action, call a local escalation tool when one exists (request_dev_mode for repository work); otherwise say it is unavailable in this session.',
    'Document-scoped capabilities accept a document reference, not only the full doc_id: the exact title, the exact file name, a doc_id prefix of 8 hex characters or more, or the 12-character short_id. Prefer the title or the short_id returned by resolve_document when quoting a document.',
    'Do not infer HTTP route prefixes, request field formats, or stored file names; check get_api_surface or document_read before using them.',
  ].join(' ')
}

/**
 * Pi extension entry point.
 *
 * `pi [-e ./dist/extension.js]` opens pi's normal interactive CLI (including
 * `/login`, `/model`, sessions, themes) with the MBForge capability tools
 * registered. The launcher registers built-in code tools only when the session
 * mode is `dev`. Provider login is intentionally left to pi.
 *
 * The extension also applies the MBForge identity: it contributes the shipped
 * `themes/` directory, replaces the startup header with the workbench banner,
 * and turns the footer status and working indicator into MBForge furniture.
 *
 * If the MBForge backend is not running, capability registration degrades to
 * zero tools so pi still opens for provider login; the header reports the
 * offline state.
 */
export default async function mbforgeExtension(
  pi: ExtensionAPI,
): Promise<void> {
  if (process.env.MBFORGE_RESEARCH_CHILD === '1') {
    await registerResearchChild(pi)
    return
  }
  let sessionMode = resolveSessionMode()
  let memoryError: string | undefined
  try {
    await ensureMemoryFile()
  } catch (error) {
    memoryError = errorMessage(error)
  }

  const runNotifier = createRunNotifier(pi)
  const runWatcher = createRunWatcher((completion) =>
    runNotifier.notify(completion),
  )
  const capabilityToolset = createCapabilityToolsetManager(
    (tool) => pi.registerTool(tool),
    (runId) => runWatcher.watch(runId),
  )
  await capabilityToolset.load()

  let activeGoal: string | undefined
  let reviewRunning = false
  const reviewNotices = new ReviewNoticeQueue()
  let activeToolCalls = 0
  let tpsStart: number | undefined
  let tpsChars = 0
  const pendingTools = new Map<
    string,
    { goalId: string | undefined; toolName: string; input: string }
  >()
  const WORKING_MESSAGE = 'MBForge · working'

  // Lightweight no-progress guard: a tight run of identical calls is surfaced
  // once as a hint, never hard-blocked. Detection reuses the offline grader.
  const LOOP_WINDOW = 12
  const LOOP_THRESHOLD = 3
  let loopTail: TrajectoryStep[] = []
  let loopNotifiedKey = ''
  const trackLoop = (
    tool: string,
    inputDigest: string,
    isError: boolean,
    ctx: ExtensionContext,
  ): void => {
    loopTail.push({
      tool,
      inputDigest,
      status: isError ? 'error' : 'ok',
      at: '',
    })
    if (loopTail.length > LOOP_WINDOW) loopTail = loopTail.slice(-LOOP_WINDOW)
    const loop = detectNoProgress(loopTail, LOOP_THRESHOLD)
    if (!loop) {
      loopNotifiedKey = ''
      return
    }
    const key = `${loop.tool}:${loop.inputDigest}`
    if (loopNotifiedKey === key) return
    loopNotifiedKey = key
    ctx.ui.notify(
      `MBForge: ${loop.tool} repeated ${loop.count} identical calls without progress; change approach or stop.`,
      'warning',
    )
  }

  const state: BrandState = {
    mode: sessionMode,
    backend: backendLabel(backendBaseUrl()),
    online: capabilityToolset.loadError === undefined,
    toolCount: capabilityToolset.tools.length,
    localToolCount: usesBuiltinTools(sessionMode)
      ? BUILTIN_TOOL_NAMES.length
      : 0,
  }

  pi.registerMessageRenderer(GOAL_REVIEW_MESSAGE_TYPE, goalReviewRenderer)
  pi.registerMessageRenderer(RUN_MESSAGE_TYPE, runNoticeRenderer)
  registerAskTool(pi)
  registerDraftTool(pi)
  registerResearchTools(pi, {
    getReadTools: () => {
      const mutating = new Set(capabilityToolset.mutatingNames)
      return capabilityToolset.tools
        .filter((tool) => !mutating.has(tool.name))
        .map((tool) => tool.name)
    },
  })
  const builtinRenderNames = new Set<string>(BUILTIN_TOOL_NAMES)
  pi.registerToolRenderer((name, next) => {
    const base = next()
    if (!base || !builtinRenderNames.has(name)) return base
    return builtinToolRenderers(name, base)
  })
  registerMemoryTools(pi)
  registerImprovementTools(pi)
  registerWorkStateTools(pi)
  registerBackendTool(pi, {
    onBackendRunning: (ctx) => reloadCapabilities(ctx),
  })
  registerReviewTools(pi)
  registerGoalTool(pi, {
    enqueueReview: (job) => enqueueReviewJob(job),
    getActiveGoal: () => activeGoal,
    setActiveGoal: (id, ctx) => {
      activeGoal = id
      refreshGoalWidget(ctx)
    },
    archiveTrajectory: (goalId, branch) => {
      void (async () => {
        await exportGoalFixture(goalId, branch, sessionMode)
        await refreshSkills()
        const trajectory = trajectoryFromBranch(branch, goalId)
        if (trajectory) await recordSuccess(pruneSkeleton(trajectory.steps))
      })().catch(() => {
        // Learning is best-effort; never block goal completion.
      })
    },
  })
  registerDevModeTool(pi, {
    getMode: () => sessionMode,
    enableDevMode: (ctx) => {
      enterMode('dev', ctx)
      ctx.ui.notify('MBForge mode: dev (repository + capabilities)', 'info')
    },
  })

  function enterMode(next: SessionMode, ctx: ExtensionContext): void {
    sessionMode = next
    state.mode = next
    applyActiveTools()
    refreshBrand(ctx)
  }

  function applyActiveTools(): void {
    const capability = capabilityToolset.tools.map((tool) => tool.name)
    const next = new Set([
      ...capability,
      ...(memoryError ? [] : [...MEMORY_TOOL_NAMES]),
      ...IMPROVEMENT_TOOL_NAMES,
      ...WORK_STATE_TOOL_NAMES,
      ...REVIEW_TOOL_NAMES,
      ...GOAL_TOOL_NAMES,
      ...BACKEND_TOOL_NAMES,
      ...DEV_MODE_TOOL_NAMES,
      ...ASK_TOOL_NAMES,
      ...DRAFT_TOOL_NAMES,
      ...RESEARCH_TOOL_NAMES,
      ...(usesBuiltinTools(sessionMode) ? [...BUILTIN_TOOL_NAMES] : []),
    ])
    pi.setActiveTools([...next])
    state.toolCount = capability.length
    state.online = capabilityToolset.loadError === undefined
    state.localToolCount = usesBuiltinTools(sessionMode)
      ? BUILTIN_TOOL_NAMES.length
      : 0
    if (!state.online) state.queue = undefined
  }

  /** Re-fetch the capability manifest and re-apply the active tool set. */
  async function reloadCapabilities(ctx: ExtensionContext): Promise<void> {
    const result = await capabilityToolset.reload()
    if (!isLive(ctx)) return
    applyActiveTools()
    refreshBrand(ctx)
    if (result.ok) {
      notifyLive(
        ctx,
        `MBForge capabilities reloaded (${result.count} tools)`,
        'info',
      )
    } else {
      notifyLive(
        ctx,
        `MBForge capability reload failed: ${result.error}`,
        'warning',
      )
    }
  }

  function formatReviewNotice(
    job: GoalReviewJob,
    result: Awaited<ReturnType<typeof runReview>>,
  ): string {
    const suggestions = result.improvements
      .map((item) => `- ${item.title}`)
      .join('\n')
    const followUps = result.follow_ups
      .map((item) => `- ${item.title}`)
      .join('\n')
    return [
      `Goal review · ${job.goalId}`,
      result.summary || '(no summary)',
      `Memory lessons: ${result.memories.length}`,
      suggestions ? `Suggestions:\n${suggestions}` : 'Suggestions: none',
      followUps ? `Follow-ups queued:\n${followUps}` : '',
      result.warnings.length > 0
        ? `Warnings:\n${result.warnings.map((item) => `- ${item}`).join('\n')}`
        : '',
    ]
      .filter((line) => line !== '')
      .join('\n')
  }

  function deliverReviewNotice(
    notice: ReviewNotice,
    ctx: ExtensionContext,
  ): void {
    pi.sendMessage(
      {
        customType: GOAL_REVIEW_MESSAGE_TYPE,
        content: notice.content,
        display: true,
        details: notice.details,
      },
      { triggerTurn: false },
    )
    if (notice.warning) ctx.ui.notify(notice.warning, 'warning')
  }

  function publishReviewNotice(
    notice: ReviewNotice,
    ctx: ExtensionContext,
  ): void {
    // A review outlives its turn: when the session behind `ctx` was replaced or
    // reloaded, hold the notice for the next settled point instead of writing to
    // a dead ctx.
    if (activeGoal !== undefined || !isLive(ctx)) {
      reviewNotices.enqueue(notice)
      return
    }
    deliverReviewNotice(notice, ctx)
  }

  function flushReviewNotices(ctx: ExtensionContext): void {
    for (const notice of reviewNotices.drain(activeGoal !== undefined)) {
      deliverReviewNotice(notice, ctx)
    }
  }

  async function drainReviewQueue(ctx: ExtensionContext): Promise<void> {
    if (reviewRunning) return
    reviewRunning = true
    // Read the model off the ctx once, before the first await: a review runs for
    // minutes and its ctx is stale by the time the next job is claimed.
    const model = ctx.model
    const modelRegistry = ctx.modelRegistry
    try {
      for (;;) {
        const job = await claimNextReview()
        if (!job) break
        try {
          setMemoryRuntime(model, modelRegistry)
          const result = await runReview({
            cwd: job.cwd,
            transcript: job.transcript,
            model: model ? `${model.provider}/${model.id}` : undefined,
          })
          await finishReviewJob(job.id)
          publishReviewNotice(
            {
              reviewId: job.id,
              content: formatReviewNotice(job, result),
              details: { reviewId: job.id, goalId: job.goalId, ...result },
            },
            ctx,
          )
        } catch (error) {
          const message = errorMessage(error)
          await failReviewJob(job.id, message)
          publishReviewNotice(
            {
              reviewId: job.id,
              content: `Goal review failed · ${job.id} (${job.goalId})\n${message}`,
              details: {
                reviewId: job.id,
                goalId: job.goalId,
                error: message,
              },
              warning: `Goal review failed (${job.id}): ${message}`,
            },
            ctx,
          )
        }
      }
    } finally {
      reviewRunning = false
    }
  }

  function refreshBrand(ctx: ExtensionContext): void {
    ctx.ui.setHeader((_tui, theme) => brandHeader(theme, state))
    ctx.ui.setFooter((_tui, theme, footerData) =>
      brandFooter(theme, state, ctx, footerData),
    )
    ctx.ui.setTitle(`MBForge · ${state.mode}`)
    refreshGoalWidget(ctx)
  }

  /**
   * Show the active goal below the editor, at the bottom of the screen. The
   * widget is removed rather than left stale when the goal is completed,
   * cancelled, or the branch changes. `ctx` must be the caller's live context;
   * caching one here would outlive the session it belongs to.
   */
  function refreshGoalWidget(ctx: ExtensionContext): void {
    if (!isLive(ctx) || typeof ctx.ui.setWidget !== 'function') return
    const id = activeGoal
    ctx.ui.setWidget(
      'mbforge-goal',
      id ? (_tui, theme) => goalWidget(theme, ctx, id) : undefined,
      { placement: 'belowEditor' },
    )
  }

  // Display-only: turn the model's [[ev:id]] citation markers and [[ui:...]]
  // workbench markers into clickable frontend links. The session and model
  // context keep the original text.
  pi.registerMarkdownTransformer((markdown, context) => {
    if (context.isStreaming || context.messageType !== 'assistant')
      return markdown
    return linkifyUiLinks(linkifyCitations(markdown))
  })

  // Contribute the palette during resource discovery as well, so direct
  // `pi -e ./dist/extension.js` launches find the themes without the npm
  // script's `--theme` flag.
  pi.on('resources_discover', () => ({ themePaths: brandThemePaths() }))

  // Memoized injected context: rebuild only when a source actually changes, so
  // unchanged turns return a byte-identical system prompt (provider prefix-cache
  // friendly) and skip re-reading the stores.
  let injectedContextCache: { key: string; value: string } | undefined

  pi.on('before_agent_start', async (event, ctx) => {
    const branch = ctx.sessionManager.getBranch()
    let goalEntryCount = 0
    for (const entry of branch) {
      if (
        typeof entry === 'object' &&
        entry !== null &&
        (entry as { customType?: string }).customType === GOAL_ENTRY_TYPE
      ) {
        goalEntryCount += 1
      }
    }
    const key = JSON.stringify([
      event.systemPrompt,
      sessionMode,
      capabilityToolset.loadError ?? '',
      capabilityToolset.tools.map((tool) => tool.name).join(','),
      memoryError ?? '',
      await fileSignature(memoryFilePath()),
      await fileSignature(memoryColdPath()),
      await fileSignature(workStateFilePath()),
      await fileSignature(skillStorePath()),
      activeGoal ?? '',
      goalEntryCount,
    ])
    if (injectedContextCache && injectedContextCache.key === key) {
      return { systemPrompt: injectedContextCache.value }
    }
    let memory = ''
    if (!memoryError) {
      try {
        memory = await memorySystemPrompt()
      } catch {
        // A memory read failure must not block the agent.
      }
    }
    let workState = ''
    try {
      workState = await workStateSystemPrompt()
    } catch {
      // The work ledger is best-effort context; never block the agent on it.
    }
    let goalContract = ''
    try {
      const id = activeGoalFromBranch(branch)
      const state = id ? goalStateFromBranch(branch, id) : undefined
      if (state) goalContract = goalContractPrompt(state.goal)
    } catch {
      // The goal contract is best-effort context; never block the agent on it.
    }
    let learned = ''
    try {
      learned = learnedMethodsPrompt(await readSkills())
    } catch {
      // Learned methods are best-effort context; never block the agent on them.
    }
    const sections = [
      event.systemPrompt,
      capabilityContext(
        sessionMode,
        capabilityToolset.tools,
        capabilityToolset.mutatingNames,
        capabilityToolset.loadError,
        [
          ...(memoryError ? [] : MEMORY_TOOL_NAMES),
          ...IMPROVEMENT_TOOL_NAMES,
          ...WORK_STATE_TOOL_NAMES,
          ...REVIEW_TOOL_NAMES,
          ...GOAL_TOOL_NAMES,
          ...BACKEND_TOOL_NAMES,
          ...DEV_MODE_TOOL_NAMES,
          ...ASK_TOOL_NAMES,
          ...DRAFT_TOOL_NAMES,
          ...RESEARCH_TOOL_NAMES,
        ],
      ),
      memory,
      workState,
      goalContract,
      learned,
    ].filter((section) => section.length > 0)
    const value = sections.join('\n\n')
    injectedContextCache = { key, value }
    return { systemPrompt: value }
  })

  const skippedTrajectoryTools = new Set([
    GOAL_TOOL_NAME,
    REVIEW_TOOL_NAME,
    ASK_TOOL_NAME,
    DRAFT_TOOL_NAME,
    RESEARCH_TOOL_NAME,
    'memory',
    'work_state',
    'suggest_improvement',
  ])

  pi.on('tool_execution_start', (event, ctx) => {
    activeToolCalls += 1
    ctx.ui.setWorkingMessage(`MBForge · ${event.toolName.replaceAll('_', ' ')}`)
    pendingTools.set(event.toolCallId, {
      goalId: activeGoal,
      toolName: event.toolName,
      input: JSON.stringify(event.args ?? {}).slice(0, 2_000),
    })
  })

  pi.on('tool_execution_end', async (event, ctx) => {
    activeToolCalls = Math.max(0, activeToolCalls - 1)
    if (activeToolCalls === 0) ctx.ui.setWorkingMessage(WORKING_MESSAGE)
    if (event.toolName === 'get_worker_status' && !event.isError) {
      const result = event.result as
        { details?: { data?: unknown } } | undefined
      const data = result?.details?.data
      if (typeof data === 'object' && data !== null) {
        const record = data as Record<string, unknown>
        if (
          typeof record.status === 'string' &&
          typeof record.active === 'number' &&
          typeof record.backlog === 'number'
        ) {
          state.queue = {
            status: record.status,
            active: record.active,
            backlog: record.backlog,
          }
        }
      }
    }
    const pending = pendingTools.get(event.toolCallId)
    pendingTools.delete(event.toolCallId)
    const serializedInput = pending?.input ?? '{}'
    const inputDigest = createHash('sha256')
      .update(serializedInput)
      .digest('hex')
      .slice(0, 16)
    trackLoop(event.toolName, inputDigest, Boolean(event.isError), ctx)
    const goalId = pending?.goalId ?? activeGoal
    if (!goalId || skippedTrajectoryTools.has(event.toolName)) return

    pi.appendEntry(GOAL_ENTRY_TYPE, {
      action: 'tool',
      goal_id: goalId,
      tool: event.toolName,
      input: serializedInput,
      input_digest: inputDigest,
      status: event.isError ? 'error' : 'ok',
      at: new Date().toISOString(),
    })
  })

  pi.on('session_start', async (_event, ctx) => {
    reconstructEvidence(ctx)
    loopTail = []
    loopNotifiedKey = ''
    activeGoal = activeGoalFromBranch(ctx.sessionManager.getBranch())
    state.tps = undefined
    state.tpsLive = false
    tpsStart = undefined
    tpsChars = 0
    applyActiveTools()
    void surfaceBehavioralRegressions().catch(() => {
      // Eval feedback is best-effort; never block session start.
    })
    flushReviewNotices(ctx)
    void drainReviewQueue(ctx).catch((error) => {
      const message = errorMessage(error)
      notifyLive(ctx, `Goal review queue failed: ${message}`, 'error')
    })
    refreshBrand(ctx)
    ctx.ui.setWorkingIndicator({
      frames: brandWorkingFrames(ctx.ui.theme),
      intervalMs: 160,
    })
    ctx.ui.setWorkingMessage(WORKING_MESSAGE)
    if (capabilityToolset.loadError) {
      ctx.ui.notify(
        `MBForge backend unavailable: ${capabilityToolset.loadError}. Use backend_control to start it, then /mbforge reload.`,
        'warning',
      )
    }
    if (memoryError) {
      ctx.ui.notify(`MBForge memory unavailable: ${memoryError}`, 'warning')
    }
  })

  pi.on('session_tree', async (_event, ctx) => {
    reconstructEvidence(ctx)
    activeGoal = activeGoalFromBranch(ctx.sessionManager.getBranch())
    state.tps = undefined
    state.tpsLive = false
    tpsStart = undefined
    tpsChars = 0
    refreshGoalWidget(ctx)
    flushReviewNotices(ctx)
  })

  pi.on('message_start', (event) => {
    if (event.message.role !== 'assistant') return
    tpsStart =
      typeof event.message.timestamp === 'number'
        ? event.message.timestamp
        : Date.now()
    tpsChars = 0
    state.tpsLive = true
  })

  pi.on('message_update', (event) => {
    if (event.message.role !== 'assistant') return
    const update = event.assistantMessageEvent
    if (
      update.type !== 'text_delta' &&
      update.type !== 'thinking_delta' &&
      update.type !== 'toolcall_delta'
    ) {
      return
    }
    tpsChars += update.delta.length
    const start = tpsStart ?? Date.now()
    const seconds = (Date.now() - start) / 1000
    if (seconds >= 0.25) {
      state.tps = tpsChars / 4 / seconds
      state.tpsLive = true
    }
  })

  pi.on('message_end', (event) => {
    if (event.message.role !== 'assistant') return
    const output = event.message.usage?.output ?? 0
    const duration = event.message.durationMs
    if (typeof duration === 'number' && duration > 0 && output > 0) {
      state.tps = output / (duration / 1000)
    } else if (tpsStart !== undefined && tpsChars > 0) {
      const seconds = (Date.now() - tpsStart) / 1000
      if (seconds > 0) state.tps = tpsChars / 4 / seconds
    }
    state.tpsLive = false
    tpsStart = undefined
    tpsChars = 0
  })

  pi.on('agent_start', () => {
    runNotifier.markBusy()
  })

  pi.on('session_shutdown', () => {
    runWatcher.stopAll()
    runNotifier.stop()
  })

  pi.on('agent_settled', async (event, ctx) => {
    activeToolCalls = 0
    state.tpsLive = false
    ctx.ui.setWorkingMessage(WORKING_MESSAGE)
    runNotifier.markIdle()
    if (event.aborted && activeGoal) {
      const id = activeGoal
      const state = goalStateFromBranch(ctx.sessionManager.getBranch(), id)
      if (state && state.goal.status !== 'paused') {
        pi.appendEntry(GOAL_ENTRY_TYPE, {
          action: 'update',
          goal_id: id,
          goal: { ...state.goal, status: 'paused' },
          reason: 'run aborted',
          at: new Date().toISOString(),
        })
      }
      refreshGoalWidget(ctx)
    }
    void drainReviewQueue(ctx).catch((error) => {
      const message = errorMessage(error)
      notifyLive(ctx, `Goal review queue failed: ${message}`, 'error')
    })
    flushReviewNotices(ctx)
  })

  pi.registerCommand('mbforge', {
    description:
      'Show or switch MBForge mode (auto|dev), or reload capabilities',
    handler: async (args, ctx) => {
      const [action, value] = args.trim().split(/\s+/)
      if (action === 'mode') {
        const next = parseSessionMode(value ?? '')
        if (next === undefined) {
          ctx.ui.notify(
            'Usage: /mbforge mode auto|dev | /mbforge reload',
            'warning',
          )
          return
        }
        enterMode(next, ctx)
        ctx.ui.notify(
          `MBForge mode: ${next} (${
            next === 'dev' ? 'repository + capabilities' : 'capabilities only'
          })`,
          'info',
        )
        return
      }
      if (action === 'reload') {
        await reloadCapabilities(ctx)
        return
      }
      if (action) {
        ctx.ui.notify(
          'Usage: /mbforge mode auto|dev | /mbforge reload',
          'warning',
        )
        return
      }
      if (capabilityToolset.loadError) {
        ctx.ui.notify(
          `MBForge backend unavailable: ${capabilityToolset.loadError}. Use backend_control to start it, then /mbforge reload.`,
          'warning',
        )
        return
      }
      const mutating = new Set(capabilityToolset.mutatingNames)
      const readNames = capabilityToolset.tools
        .filter((tool) => !mutating.has(tool.name))
        .map((tool) => tool.name)
      const writeNames = capabilityToolset.tools
        .filter((tool) => mutating.has(tool.name))
        .map((tool) => tool.name)
      ctx.ui.notify(
        [
          `⬡ MBForge · mode: ${sessionMode}`,
          `scope    ${
            usesBuiltinTools(sessionMode)
              ? 'mbforge capabilities + repository tools'
              : 'mbforge capabilities only'
          }`,
          `read     ${readNames.length}: ${readNames.join(', ')}`,
          `mutating ${writeNames.length}: ${writeNames.join(', ')} (token-gated)`,
          `backend  ${state.backend}`,
          `local    ${[...MEMORY_TOOL_NAMES, ...IMPROVEMENT_TOOL_NAMES, ...WORK_STATE_TOOL_NAMES, ...REVIEW_TOOL_NAMES, ...GOAL_TOOL_NAMES, ...BACKEND_TOOL_NAMES].join(', ')} (${memoryError ? 'memory unavailable' : 'memory layers + IMPROVEMENTS.json'})`,
        ].join('\n'),
        'info',
      )
    },
  })

  pi.registerCommand('goal-reviews', {
    description: 'Show, retry, or drain background goal reviews',
    handler: async (args, ctx) => {
      const [action, id] = args.trim().split(/\s+/)
      try {
        if (action === 'retry') {
          if (!id) {
            ctx.ui.notify(
              'Usage: /goal-reviews retry <review-id|goal-id>',
              'warning',
            )
            return
          }
          let review = await retryReviewJob(id)
          if (!review) {
            const existing = (await listReviewJobs()).find(
              (job) => job.id === id || job.goalId === id,
            )
            if (!existing) {
              ctx.ui.notify(
                `No goal review with review id or goal id ${id}`,
                'warning',
              )
              return
            }
            review = existing
            ctx.ui.notify(
              `Review ${review.id} (${review.goalId}) is already queued; the queue will run it`,
              'info',
            )
          } else {
            reviewNotices.remove(review.id)
            ctx.ui.notify(
              `Review ${review.id} (${review.goalId}) requeued`,
              'info',
            )
          }
          void drainReviewQueue(ctx).catch((error) => {
            const message = errorMessage(error)
            notifyLive(ctx, `Goal review queue failed: ${message}`, 'error')
          })
          return
        }
        if (action) {
          ctx.ui.notify(
            'Usage: /goal-reviews | /goal-reviews retry <review-id|goal-id>',
            'warning',
          )
          return
        }
        const jobs = await listReviewJobs()
        const held = reviewNotices.size
        const heldLabel =
          held > 0 ? `${held} held until the active goal ends` : ''
        if (jobs.length === 0) {
          ctx.ui.notify(
            `No goal reviews queued.${heldLabel ? ` ${heldLabel}.` : ''}`,
            'info',
          )
          return
        }
        const lines = jobs.slice(0, 12).map((job) => {
          const suffix = job.error ? ` · ${job.error.slice(0, 80)}` : ''
          return `${job.status} ${job.id} ${job.goalId}${suffix}`
        })
        ctx.ui.notify(
          [
            `Goal reviews (${jobs.length})${heldLabel ? ` · ${heldLabel}` : ''}`,
            ...lines,
          ].join('\n'),
          'info',
        )
      } catch (error) {
        const message = errorMessage(error)
        ctx.ui.notify(`Goal review queue unavailable: ${message}`, 'error')
      }
    },
  })

  registerEndpointCommand(pi)
  registerMemoryCommand(pi)
}
