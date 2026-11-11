import type { ExtensionAPI, ExtensionContext } from '@earendil-works/pi-coding-agent'
import { createHash } from 'node:crypto'
import { setTimeout as sleep } from 'node:timers/promises'

import {
  backendLabel,
  brandHeader,
  brandStatus,
  brandThemePaths,
  brandWorkingFrames,
  type BrandState,
} from './brand.js'
import {
  backendBaseUrl,
  loadCapabilityToolset,
  type CapabilityTool,
  type CapabilityToolset,
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
import { registerEndpointCommand } from './endpoint.js'
import {
  ensureMemoryFile,
  MEMORY_TOOL_NAMES,
  memorySystemPrompt,
  registerMemoryCommand,
  registerMemoryTools,
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
import {
  goalArtifactRoot,
  pruneAllGoalArtifacts,
  writeGoalArtifact,
} from './goalArtifacts.js'
import { createRunNotifier, createRunWatcher } from './runs.js'
import { DEV_MODE_TOOL_NAMES, registerDevModeTool } from './devMode.js'

// Bound worst-case startup: a few short attempts tolerate a backend that is
// still coming up, then degrade to zero tools so pi opens promptly.
const MANIFEST_ATTEMPTS = 3
const MANIFEST_RETRY_DELAY_MS = 400
const BUILTIN_TOOL_NAMES = [
  'read',
  'bash',
  'edit',
  'write',
  'grep',
  'find',
  'ls',
] as const

async function loadCapabilityToolsetWithRetry(
  onRunEnqueued?: (runId: string) => void,
): Promise<CapabilityToolset> {
  let lastError: unknown
  for (let attempt = 1; attempt <= MANIFEST_ATTEMPTS; attempt += 1) {
    try {
      return await loadCapabilityToolset(onRunEnqueued)
    } catch (error) {
      lastError = error
      if (attempt < MANIFEST_ATTEMPTS) {
        await sleep(MANIFEST_RETRY_DELAY_MS)
      }
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError))
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
      'manifest; report the backend status and its log location instead.'
    )
  }
  const mutating = new Set(mutatingNames)
  const readNames = tools.filter((tool) => !mutating.has(tool.name)).map((tool) => tool.name)
  const writeNames = tools.filter((tool) => mutating.has(tool.name)).map((tool) => tool.name)
  const localNote =
    localTools.length > 0
      ? ` Local tools (${localTools.join(', ')}) only touch local agent state, not library data.`
      : ''
  const scope =
    mode === 'auto'
      ? 'Mode auto exposes every registered MBForge capability; mutating calls need the capability token and return 403 without it. Repository tools are inactive.'
      : 'Mode dev exposes every registered MBForge capability plus built-in repository tools; mutating calls need the capability token.'
  return [
    `MBForge session mode (${mode}).`,
    `Read capabilities (${readNames.length}): ${readNames.length > 0 ? readNames.join(', ') : 'none'}.`,
    `Mutating capabilities (${writeNames.length}): ${writeNames.length > 0 ? writeNames.join(', ') : 'none'}.`,
    `${scope}${localNote}`,
    'The active tool list is authoritative. Do not query /api/v1/capabilities, do not print a curl command to discover capabilities, and do not guess that an inactive tool exists. If an action has no active tool, say it is unavailable in this session.',
    'Document-scoped capabilities accept a document reference, not only the full doc_id: the exact title, the exact file name, a doc_id prefix of 8 hex characters or more, or the 12-character short_id. Prefer the title or the short_id returned by resolve_document when quoting a document.',
    'Do not infer HTTP route prefixes, request field formats, or stored file names; check get_api_surface or get_document before using them.',
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
export default async function mbforgeExtension(pi: ExtensionAPI): Promise<void> {
  let sessionMode = resolveSessionMode()
  let memoryError: string | undefined
  try {
    await ensureMemoryFile()
  } catch (error) {
    memoryError = error instanceof Error ? error.message : String(error)
  }

  let tools: CapabilityTool[] = []
  let mutatingNames: string[] = []
  let loadError: string | undefined
  const runNotifier = createRunNotifier(pi)
  const runWatcher = createRunWatcher((completion) =>
    runNotifier.notify(completion),
  )
  try {
    const toolset = await loadCapabilityToolsetWithRetry((runId) =>
      runWatcher.watch(runId),
    )
    tools = toolset.tools
    mutatingNames = toolset.mutatingNames
  } catch (error) {
    loadError = error instanceof Error ? error.message : String(error)
  }

  let activeGoal: string | undefined
  let reviewRunning = false
  const pendingTools = new Map<
    string,
    { goalId: string; toolName: string; input: string }
  >()

  const state: BrandState = {
    mode: sessionMode,
    backend: backendLabel(backendBaseUrl()),
    online: loadError === undefined,
    toolCount: tools.length,
  }

  for (const tool of tools) {
    pi.registerTool(tool)
  }
  registerMemoryTools(pi)
  registerImprovementTools(pi)
  registerReviewTools(pi)
  registerGoalTool(pi, {
    enqueueReview: (job) => enqueueReviewJob(job),
    getActiveGoal: () => activeGoal,
    setActiveGoal: (id) => {
      activeGoal = id
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
    const capability = tools.map((tool) => tool.name)
    const next = new Set([
      ...capability,
      ...(memoryError ? [] : [...MEMORY_TOOL_NAMES]),
      ...IMPROVEMENT_TOOL_NAMES,
      ...REVIEW_TOOL_NAMES,
      ...GOAL_TOOL_NAMES,
      ...DEV_MODE_TOOL_NAMES,
      ...(usesBuiltinTools(sessionMode) ? [...BUILTIN_TOOL_NAMES] : []),
    ])
    pi.setActiveTools([...next])
    state.toolCount = capability.length
  }

  function formatReviewNotice(job: GoalReviewJob, result: Awaited<ReturnType<typeof runReview>>): string {
    const suggestions = result.improvements
      .map((item) => `- ${item.title}`)
      .join('\n')
    return [
      `Goal review · ${job.goalId}`,
      result.summary || '(no summary)',
      `Memory lessons: ${result.memories.length}`,
      suggestions ? `Suggestions:\n${suggestions}` : 'Suggestions: none',
      result.warnings.length > 0
        ? `Warnings:\n${result.warnings.map((item) => `- ${item}`).join('\n')}`
        : '',
    ]
      .filter((line) => line !== '')
      .join('\n')
  }

  async function drainReviewQueue(ctx: ExtensionContext): Promise<void> {
    if (reviewRunning) return
    reviewRunning = true
    try {
      for (;;) {
        const job = await claimNextReview()
        if (!job) break
        try {
          const result = await runReview({
            cwd: job.cwd,
            transcript: job.transcript,
          })
          await finishReviewJob(job.id)
          pi.sendMessage(
            {
              customType: 'mbforge-goal-review',
              content: formatReviewNotice(job, result),
              display: true,
              details: { goalId: job.goalId, ...result },
            },
            { triggerTurn: false },
          )
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error)
          await failReviewJob(job.id, message)
          pi.sendMessage(
            {
              customType: 'mbforge-goal-review',
              content: `Goal review failed · ${job.goalId}\n${message}`,
              display: true,
              details: { goalId: job.goalId, error: message },
            },
            { triggerTurn: false },
          )
          ctx.ui.notify(`Goal review failed: ${message}`, 'warning')
        }
      }
    } finally {
      reviewRunning = false
    }
  }

  function refreshBrand(ctx: ExtensionContext): void {
    ctx.ui.setHeader((_tui, theme) => brandHeader(theme, state))
    ctx.ui.setStatus('mbforge', brandStatus(state))
  }

  // Display-only: turn the model's [[ev:id]] citation markers and [[ui:...]]
  // workbench markers into clickable frontend links. The session and model
  // context keep the original text.
  pi.registerMarkdownTransformer((markdown, context) => {
    if (context.isStreaming || context.messageType !== 'assistant') return markdown
    return linkifyUiLinks(linkifyCitations(markdown))
  })

  // Contribute the palette during resource discovery as well, so direct
  // `pi -e ./dist/extension.js` launches find the themes without the npm
  // script's `--theme` flag.
  pi.on('resources_discover', () => ({ themePaths: brandThemePaths() }))

  pi.on('before_agent_start', async (event) => {
    let memory = ''
    if (!memoryError) {
      try {
        memory = await memorySystemPrompt()
      } catch {
        // A memory read failure must not block the agent.
      }
    }
    const sections = [
      event.systemPrompt,
      capabilityContext(
        sessionMode,
        tools,
        mutatingNames,
        loadError,
        [
          ...(memoryError ? [] : MEMORY_TOOL_NAMES),
          ...IMPROVEMENT_TOOL_NAMES,
          ...REVIEW_TOOL_NAMES,
          ...GOAL_TOOL_NAMES,
          ...DEV_MODE_TOOL_NAMES,
        ],
      ),
      memory,
    ].filter((section) => section.length > 0)
    return { systemPrompt: sections.join('\n\n') }
  })

  const skippedArtifactTools = new Set([
    GOAL_TOOL_NAME,
    REVIEW_TOOL_NAME,
    'memory',
    'memory_ephemeral',
    'suggest_improvement',
  ])

  pi.on('tool_execution_start', (event) => {
    if (!activeGoal || skippedArtifactTools.has(event.toolName)) return
    pendingTools.set(event.toolCallId, {
      goalId: activeGoal,
      toolName: event.toolName,
      input: JSON.stringify(event.args ?? {}).slice(0, 2_000),
    })
  })

  pi.on('tool_execution_end', async (event, ctx) => {
    const pending = pendingTools.get(event.toolCallId)
    pendingTools.delete(event.toolCallId)
    const goalId = pending?.goalId ?? activeGoal
    if (!goalId || skippedArtifactTools.has(event.toolName)) return

    const serializedInput = pending?.input ?? '{}'
    const inputDigest = createHash('sha256')
      .update(serializedInput)
      .digest('hex')
      .slice(0, 16)
    const result = event.result as
      | { content?: Array<{ type?: string; text?: string }> }
      | undefined
    const parts = Array.isArray(result?.content)
      ? result.content.map((part) =>
          part.type === 'text' && typeof part.text === 'string'
            ? part.text
            : `[${part.type ?? 'result'}]`,
        )
      : []
    const body =
      parts.join('\n') ||
      (event.isError ? 'tool execution failed without a text result' : '')
    let artifact = ''
    try {
      if (body) {
        artifact = await writeGoalArtifact({
          sessionId: ctx.sessionManager.getSessionId() ?? 'session',
          goalId,
          toolName: event.toolName,
          content: body,
        })
      }
    } catch {
      // Artifact capture is best-effort; the session transcript still has the result.
    }
    pi.appendEntry(GOAL_ENTRY_TYPE, {
      action: 'tool',
      goal_id: goalId,
      tool: event.toolName,
      input: serializedInput,
      input_digest: inputDigest,
      status: event.isError ? 'error' : 'ok',
      artifact,
      at: new Date().toISOString(),
    })
  })

  pi.on('session_start', async (_event, ctx) => {
    reconstructEvidence(ctx)
    activeGoal = activeGoalFromBranch(ctx.sessionManager.getBranch())
    applyActiveTools()
    void drainReviewQueue(ctx).catch((error) => {
      const message = error instanceof Error ? error.message : String(error)
      ctx.ui.notify(`Goal review queue failed: ${message}`, 'error')
    })
    refreshBrand(ctx)
    ctx.ui.setWorkingIndicator({
      frames: brandWorkingFrames(ctx.ui.theme),
      intervalMs: 160,
    })
    ctx.ui.setWorkingMessage('MBForge · working')
    if (loadError) {
      ctx.ui.notify(
        `MBForge backend unavailable: ${loadError}. Start the backend and relaunch.`,
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
  })

  pi.on('agent_start', () => {
    runNotifier.markBusy()
  })

  pi.on('session_shutdown', () => {
    runWatcher.stopAll()
    runNotifier.stop()
  })

  pi.on('agent_settled', async (event, ctx) => {
    runNotifier.markIdle()
    if (event.aborted && activeGoal) {
      const id = activeGoal
      pi.appendEntry(GOAL_ENTRY_TYPE, {
        action: 'cancel',
        goal_id: id,
        reason: 'run aborted',
        at: new Date().toISOString(),
      })
      activeGoal = undefined
    }
    void drainReviewQueue(ctx).catch((error) => {
      const message = error instanceof Error ? error.message : String(error)
      ctx.ui.notify(`Goal review queue failed: ${message}`, 'error')
    })
  })

  pi.registerCommand('mbforge', {
    description: 'Show or switch MBForge mode (auto|dev)',
    handler: async (args, ctx) => {
      const [action, value] = args.trim().split(/\s+/)
      if (action === 'mode') {
        const next = parseSessionMode(value ?? '')
        if (next === undefined) {
          ctx.ui.notify('Usage: /mbforge mode auto|dev', 'warning')
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
      if (action) {
        ctx.ui.notify('Usage: /mbforge mode auto|dev', 'warning')
        return
      }
      if (loadError) {
        ctx.ui.notify(
          `MBForge backend unavailable: ${loadError}. Start the backend and relaunch.`,
          'warning',
        )
        return
      }
      const mutating = new Set(mutatingNames)
      const readNames = tools.filter((tool) => !mutating.has(tool.name)).map((tool) => tool.name)
      const writeNames = tools.filter((tool) => mutating.has(tool.name)).map((tool) => tool.name)
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
          `local    ${[...MEMORY_TOOL_NAMES, ...IMPROVEMENT_TOOL_NAMES, ...REVIEW_TOOL_NAMES, ...GOAL_TOOL_NAMES].join(', ')} (${memoryError ? 'memory unavailable' : 'memory layers + IMPROVEMENTS.json'})`,
        ].join('\n'),
        'info',
      )
    },
  })

  pi.registerCommand('goal-reviews', {
    description: 'Show or retry background goal reviews',
    handler: async (args, ctx) => {
      const [action, id] = args.trim().split(/\s+/)
      try {
        if (action === 'retry') {
          if (!id) {
            ctx.ui.notify('Usage: /goal-reviews retry <review-id>', 'warning')
            return
          }
          const ok = await retryReviewJob(id)
          ctx.ui.notify(
            ok ? `Review ${id} requeued` : `No failed review with id ${id}`,
            ok ? 'info' : 'warning',
          )
          if (ok) {
            void drainReviewQueue(ctx).catch((error) => {
              const message = error instanceof Error ? error.message : String(error)
              ctx.ui.notify(`Goal review queue failed: ${message}`, 'error')
            })
          }
          return
        }
        if (action === 'prune') {
          const removed = await pruneAllGoalArtifacts()
          ctx.ui.notify(`Pruned ${removed} goal artifact file(s)`, 'info')
          return
        }
        if (action) {
          ctx.ui.notify(
            'Usage: /goal-reviews | /goal-reviews retry <id> | /goal-reviews prune',
            'warning',
          )
          return
        }
        const jobs = await listReviewJobs()
        if (jobs.length === 0) {
          ctx.ui.notify(`No goal reviews queued. Artifacts: ${goalArtifactRoot()}`, 'info')
          return
        }
        const lines = jobs.slice(0, 12).map((job) => {
          const suffix = job.error ? ` · ${job.error.slice(0, 80)}` : ''
          return `${job.status} ${job.id} ${job.goalId}${suffix}`
        })
        ctx.ui.notify(
          [
            `Goal reviews (${jobs.length}) · artifacts: ${goalArtifactRoot()}`,
            ...lines,
          ].join('\n'),
          'info',
        )
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        ctx.ui.notify(`Goal review queue unavailable: ${message}`, 'error')
      }
    },
  })

  registerEndpointCommand(pi)
  registerMemoryCommand(pi)
}
