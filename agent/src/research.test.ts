// @tested-functions buildResearchArgs, runResearch, runResearchWorkers, registerResearchChild
import assert from 'node:assert/strict'
import test from 'node:test'

import type { ExtensionAPI } from '@earendil-works/pi-coding-agent'

import {
  buildResearchArgs,
  registerResearchChild,
  runResearch,
  runResearchWorkers,
  type ResearchRunnerInput,
} from './research.js'

test('research child loads the extension read-only, inherits the model, and keeps the question off argv', () => {
  const args = buildResearchArgs({
    cwd: 'C:/repo',
    question: 'Compare X',
    systemPrompt: 'sys',
    model: 'custom/gpt-x',
    tools: ['search_library', 'get_patent_result'],
  })
  const extensionIndex = args.indexOf('-e')
  assert.ok(extensionIndex >= 0, 'the child must load the MBForge extension')
  assert.match(args[extensionIndex + 1], /extension\.js$/)
  const toolsIndex = args.indexOf('--tools')
  assert.equal(args[toolsIndex + 1], 'search_library,get_patent_result')
  const modelIndex = args.indexOf('--model')
  assert.equal(args[modelIndex + 1], 'custom/gpt-x')
  assert.ok(args.includes('--append-system-prompt'))
  assert.equal(
    args.includes('Compare X'),
    false,
    'the question travels over stdin, not argv',
  )

  const bare = buildResearchArgs({
    cwd: 'C:/repo',
    question: 'q',
    systemPrompt: 'sys',
  })
  assert.equal(bare.includes('--model'), false)
  assert.equal(bare.includes('--tools'), false)
})

test('runResearch appends focus and returns the trimmed finding', async () => {
  let captured: ResearchRunnerInput | undefined
  const answer = await runResearch(
    {
      cwd: 'C:/repo',
      question: 'Compare X',
      focus: 'doc A',
      model: 'custom/gpt-x',
      tools: ['search_library'],
    },
    async (input) => {
      captured = input
      return '  finding  '
    },
  )
  assert.equal(answer, 'finding')
  assert.match(captured?.question ?? '', /Compare X\n\nFocus: doc A/)
  assert.equal(captured?.model, 'custom/gpt-x')
  assert.deepEqual(captured?.tools, ['search_library'])
  assert.match(
    captured?.systemPrompt ?? '',
    /read-only library research subagent/,
  )
})

test('research fans out sub-questions to bounded concurrent workers, preserving order and tolerating a failed worker', async () => {
  let active = 0
  let peak = 0
  const runner = async (input: ResearchRunnerInput) => {
    active += 1
    peak = Math.max(peak, active)
    await new Promise((resolve) => setTimeout(resolve, 5))
    active -= 1
    if (input.question.includes('boom')) throw new Error('worker exploded')
    return `  finding for ${input.question}  `
  }

  const findings = await runResearchWorkers(
    {
      cwd: 'C:/repo',
      tasks: [
        { question: 'q1' },
        { question: 'q2 boom' },
        { question: 'q3', focus: 'doc A' },
        { question: 'q4' },
        { question: 'q5' },
      ],
      tools: ['search_library'],
      concurrency: 2,
    },
    runner,
  )

  assert.deepEqual(
    findings.map((finding) => finding.question),
    ['q1', 'q2 boom', 'q3', 'q4', 'q5'],
    'task order preserved',
  )
  assert.equal(findings[0].answer, 'finding for q1', 'finding trimmed')
  assert.match(
    findings[1].error ?? '',
    /worker exploded/,
    'failed worker surfaced, not thrown',
  )
  assert.equal(findings[1].answer, undefined)
  assert.equal(findings[2].focus, 'doc A', 'focus carried through')
  assert.equal(peak, 2, 'concurrency bounded to the cap and actually parallel')
})

test('the research child registers and activates only read-only capabilities', async (t) => {
  const original = globalThis.fetch
  t.after(() => {
    globalThis.fetch = original
  })
  globalThis.fetch = (async () =>
    new Response(
      JSON.stringify({
        success: true,
        token_path: './unused',
        capabilities: [
          {
            name: 'search_library',
            description: 'read',
            mutating: false,
            input_schema: {
              type: 'object',
              properties: { query: { type: 'string' } },
            },
          },
          {
            name: 'update_record',
            description: 'write',
            mutating: true,
            input_schema: {
              type: 'object',
              properties: { id: { type: 'string' } },
            },
          },
        ],
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    )) as typeof fetch

  const registered: string[] = []
  let active: string[] = []
  let handler:
    | ((event: { systemPrompt: string }) => Promise<{ systemPrompt: string }>)
    | undefined
  const pi = {
    registerTool: (tool: { name: string }) => {
      registered.push(tool.name)
    },
    setActiveTools: (names: string[]) => {
      active = names
    },
    on: (name: string, next: typeof handler) => {
      if (name === 'before_agent_start') handler = next
    },
  } as unknown as ExtensionAPI

  await registerResearchChild(pi)
  assert.deepEqual(
    registered,
    ['search_library'],
    'the mutating capability is never registered',
  )
  assert.deepEqual(active, ['search_library'])
  assert.ok(handler)
  const result = await handler({ systemPrompt: 'base' })
  assert.match(
    result.systemPrompt,
    /Read-only library capabilities \(1\): search_library/,
  )
  assert.match(result.systemPrompt, /do not write or spawn subagents/)
})
