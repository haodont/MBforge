import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { existsSync } from 'node:fs'
import { readFile, unlink } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { extname, join, resolve } from 'node:path'

import {
  defineTool,
  getAgentDir,
  type ExtensionAPI,
} from '@earendil-works/pi-coding-agent'
import { Type } from 'typebox'

import { atomicWrite, createSerializer, readJsonFile } from './localStore.js'
import { errorMessage } from './text.js'
import { toolRenderers } from './toolRender.js'

/**
 * Code drafts as reviewable artifacts, not executable snippets.
 *
 * The agent naturally writes Python as a draft. This tool gives that habit a
 * proper home: the code is saved, checked statically (Python AST + Ruff), and
 * returned with diagnostics. It never executes model-authored code. A draft can
 * be inspected with `read`, then written with the normal edit/write tools only
 * after its checks pass and the user agrees.
 */

export const DRAFT_TOOL_NAME = 'draft'
export const DRAFT_TOOL_NAMES = [DRAFT_TOOL_NAME] as const

const REPO_ROOT = fileURLToPath(new URL('../..', import.meta.url))
const MAX_CODE_CHARS = 64_000
const MAX_DRAFTS = 40
const MAX_DIAGNOSTICS = 20

const EXTENSIONS: Readonly<Record<string, string>> = {
  python: 'py',
  py: 'py',
  typescript: 'ts',
  ts: 'ts',
  tsx: 'tsx',
  javascript: 'js',
  js: 'js',
  jsx: 'jsx',
  json: 'json',
  sql: 'sql',
  yaml: 'yaml',
  yml: 'yaml',
  toml: 'toml',
  markdown: 'md',
  md: 'md',
  shell: 'sh',
  sh: 'sh',
  bash: 'sh',
  text: 'txt',
  txt: 'txt',
}

export interface DraftDiagnostic {
  code: string
  message: string
  line: number
  column: number
  severity: string
}

export interface DraftCheck {
  name: string
  status: 'ok' | 'error' | 'unavailable'
  message: string
  diagnostics: DraftDiagnostic[]
}

export interface DraftCall {
  line: number
  name: string
  keywords: string[]
}

export interface DraftAnalysis {
  checks: DraftCheck[]
  calls: DraftCall[]
  definitions: Array<{ line: number; name: string }>
}

export interface DraftRecord {
  id: string
  language: string
  file: string
  target_path?: string
  summary?: string
  lines: number
  chars: number
  created_at: string
  checks: DraftCheck[]
}

export interface DraftRead {
  record: DraftRecord
  code: string
}

interface DraftStore {
  version: 1
  items: DraftRecord[]
}

interface ProcessResult {
  code: number | null
  stdout: string
  stderr: string
  timedOut: boolean
  error?: string
}

function cap(value: string, max = 200_000): string {
  return value.length > max ? `${value.slice(0, max)}\n…` : value
}

/** Run a child process with bounded output and a hard timeout. */
function runProcess(
  command: string,
  args: string[],
  input: string,
  timeoutMs = 10_000,
): Promise<ProcessResult> {
  const { promise, resolve } = Promise.withResolvers<ProcessResult>()
  let child
  try {
    child = spawn(command, args, {
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
    })
  } catch (error) {
    resolve({
      code: null,
      stdout: '',
      stderr: '',
      timedOut: false,
      error: errorMessage(error),
    })
    return promise
  }

  let stdout = ''
  let stderr = ''
  let settled = false
  const finish = (result: ProcessResult): void => {
    if (settled) return
    settled = true
    clearTimeout(timer)
    resolve(result)
  }
  const timer = setTimeout(() => {
    child.kill()
    finish({ code: null, stdout, stderr, timedOut: true })
  }, timeoutMs)
  timer.unref()

  child.stdout?.setEncoding('utf8')
  child.stdout?.on('data', (chunk: string) => {
    stdout = cap(stdout + chunk)
  })
  child.stderr?.setEncoding('utf8')
  child.stderr?.on('data', (chunk: string) => {
    stderr = cap(stderr + chunk)
  })
  child.on('error', (error) => {
    finish({
      code: null,
      stdout,
      stderr,
      timedOut: false,
      error: error.message,
    })
  })
  child.on('close', (code) => {
    finish({ code, stdout, stderr, timedOut: false })
  })
  child.stdin?.end(input)
  return promise
}

/** Resolve a repo venv tool, an explicit env override, or the PATH fallback. */
function toolCommand(
  envName: string,
  executable: string,
  fallback: string,
): { command: string; args: string[] } {
  const explicit = process.env[envName]?.trim()
  if (explicit) return { command: explicit, args: [] }
  const venv = join(
    REPO_ROOT,
    '.venv',
    process.platform === 'win32' ? 'Scripts' : 'bin',
    executable,
  )
  if (existsSync(venv)) return { command: venv, args: [] }
  return { command: fallback, args: [] }
}

const PYTHON = toolCommand(
  'MBFORGE_PYTHON',
  process.platform === 'win32' ? 'python.exe' : 'python',
  process.platform === 'win32' ? 'python' : 'python3',
)
const RUFF = toolCommand(
  'MBFORGE_RUFF',
  process.platform === 'win32' ? 'ruff.exe' : 'ruff',
  'ruff',
)

const PYTHON_PARSE = String.raw`
import ast, json, sys

source = sys.stdin.read()
try:
    tree = ast.parse(source)
except SyntaxError as error:
    print(json.dumps({
        "ok": False,
        "errors": [{
            "line": error.lineno or 0,
            "column": error.offset or 0,
            "message": error.msg or "syntax error",
        }],
    }))
else:
    def name(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        return "<expression>"

    calls = []
    definitions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            calls.append({
                "line": node.lineno,
                "name": name(node.func),
                "keywords": [keyword.arg for keyword in node.keywords if keyword.arg],
            })
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions.append({"line": node.lineno, "name": node.name})
    print(json.dumps({
        "ok": True,
        "calls": calls[:20],
        "definitions": definitions[:20],
    }))
`

async function checkPython(code: string): Promise<DraftAnalysis> {
  const parsed = await runProcess(
    PYTHON.command,
    [...PYTHON.args, '-c', PYTHON_PARSE],
    code,
  )
  if (parsed.error) {
    return {
      checks: [
        {
          name: 'syntax',
          status: 'unavailable',
          message: `Python is unavailable: ${parsed.error}`,
          diagnostics: [],
        },
      ],
      calls: [],
      definitions: [],
    }
  }
  if (parsed.timedOut) {
    return {
      checks: [
        {
          name: 'syntax',
          status: 'error',
          message: 'Python syntax check timed out',
          diagnostics: [],
        },
      ],
      calls: [],
      definitions: [],
    }
  }
  let payload: {
    ok?: boolean
    errors?: Array<{ line?: number; column?: number; message?: string }>
    calls?: Array<{ line?: number; name?: string; keywords?: string[] }>
    definitions?: Array<{ line?: number; name?: string }>
  }
  try {
    payload = JSON.parse(parsed.stdout) as typeof payload
  } catch {
    return {
      checks: [
        {
          name: 'syntax',
          status: 'error',
          message: `Python returned invalid output${parsed.stderr ? `: ${parsed.stderr.trim()}` : ''}`,
          diagnostics: [],
        },
      ],
      calls: [],
      definitions: [],
    }
  }
  const diagnostics = (payload.errors ?? [])
    .slice(0, MAX_DIAGNOSTICS)
    .map((error) => ({
      code: 'syntax',
      message: error.message ?? 'syntax error',
      line: error.line ?? 0,
      column: error.column ?? 0,
      severity: 'error',
    }))
  return {
    checks: [
      {
        name: 'syntax',
        status: payload.ok ? 'ok' : 'error',
        message: payload.ok ? 'Python parsed' : 'Python syntax error',
        diagnostics,
      },
    ],
    calls: (payload.calls ?? []).map((call) => ({
      line: call.line ?? 0,
      name: call.name ?? '<expression>',
      keywords: call.keywords ?? [],
    })),
    definitions: (payload.definitions ?? []).map((definition) => ({
      line: definition.line ?? 0,
      name: definition.name ?? '<anonymous>',
    })),
  }
}

async function checkRuff(code: string): Promise<DraftCheck> {
  const result = await runProcess(
    RUFF.command,
    [
      ...RUFF.args,
      'check',
      '--stdin-filename',
      'draft.py',
      '--output-format',
      'json',
      '-',
    ],
    code,
  )
  if (result.error) {
    return {
      name: 'ruff',
      status: 'unavailable',
      message: `Ruff is unavailable: ${result.error}`,
      diagnostics: [],
    }
  }
  if (result.timedOut) {
    return {
      name: 'ruff',
      status: 'error',
      message: 'Ruff timed out',
      diagnostics: [],
    }
  }
  let rows: Array<{
    code?: string
    message?: string
    severity?: string
    location?: { row?: number; column?: number }
  }>
  try {
    rows = JSON.parse(result.stdout) as typeof rows
  } catch {
    return {
      name: 'ruff',
      status: 'error',
      message: `Ruff returned invalid output${result.stderr ? `: ${result.stderr.trim()}` : ''}`,
      diagnostics: [],
    }
  }
  if (!Array.isArray(rows)) {
    return {
      name: 'ruff',
      status: 'error',
      message: 'Ruff returned a non-array report',
      diagnostics: [],
    }
  }
  const diagnostics = rows.slice(0, MAX_DIAGNOSTICS).map((row) => ({
    code: row.code ?? 'ruff',
    message: row.message ?? 'lint error',
    line: row.location?.row ?? 0,
    column: row.location?.column ?? 0,
    severity: row.severity ?? 'error',
  }))
  return {
    name: 'ruff',
    status: diagnostics.length === 0 ? 'ok' : 'error',
    message:
      diagnostics.length === 0
        ? 'Ruff clean'
        : `${diagnostics.length} Ruff diagnostic(s)`,
    diagnostics,
  }
}

function scriptFilename(language: string): string {
  if (language === 'tsx') return 'draft.tsx'
  if (language === 'jsx') return 'draft.jsx'
  if (language === 'js' || language === 'javascript') return 'draft.js'
  return 'draft.ts'
}

function scriptCheckName(language: string): string {
  return language === 'typescript' || language === 'ts' || language === 'tsx'
    ? 'typescript'
    : 'javascript'
}

async function checkScript(
  code: string,
  language: string,
): Promise<DraftCheck> {
  // Optional dev dependency: loading the TypeScript compiler eagerly would add
  // ~17 MB to every session, including sessions that never draft TS.
  const ts = await import('typescript').catch(() => undefined)
  if (!ts) {
    return {
      name: scriptCheckName(language),
      status: 'unavailable',
      message:
        'TypeScript is not installed; draft was saved without a syntax check.',
      diagnostics: [],
    }
  }
  const filename = scriptFilename(language)
  try {
    const kind =
      language === 'tsx'
        ? ts.ScriptKind.TSX
        : language === 'jsx'
          ? ts.ScriptKind.JSX
          : language === 'js' || language === 'javascript'
            ? ts.ScriptKind.JS
            : ts.ScriptKind.TS
    const sourceFile = ts.createSourceFile(
      filename,
      code,
      ts.ScriptTarget.Latest,
      true,
      kind,
    )
    const result = ts.transpileModule(code, {
      fileName: filename,
      reportDiagnostics: true,
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.ESNext,
        jsx: ts.JsxEmit.ReactJSX,
        allowJs: true,
        checkJs: false,
      },
    })
    const diagnostics = (result.diagnostics ?? [])
      .filter(
        (diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error,
      )
      .slice(0, MAX_DIAGNOSTICS)
      .map((diagnostic) => {
        const position =
          diagnostic.start === undefined
            ? { line: 0, character: 0 }
            : ts.getLineAndCharacterOfPosition(sourceFile, diagnostic.start)
        return {
          code: `TS${diagnostic.code}`,
          message: ts.flattenDiagnosticMessageText(diagnostic.messageText, ' '),
          line: position.line + 1,
          column: position.character + 1,
          severity: 'error',
        }
      })
    return {
      name: scriptCheckName(language),
      status: diagnostics.length === 0 ? 'ok' : 'error',
      message:
        diagnostics.length === 0
          ? 'Syntax clean (parse only; no type check)'
          : `${diagnostics.length} syntax error(s)`,
      diagnostics,
    }
  } catch (error) {
    return {
      name: scriptCheckName(language),
      status: 'error',
      message: errorMessage(error),
      diagnostics: [],
    }
  }
}

function checkJson(code: string): DraftAnalysis {
  try {
    JSON.parse(code)
    return {
      checks: [
        { name: 'json', status: 'ok', message: 'JSON parsed', diagnostics: [] },
      ],
      calls: [],
      definitions: [],
    }
  } catch (error) {
    const message = errorMessage(error)
    const match = /position (\d+)/i.exec(message)
    let line = 0
    let column = 0
    if (match) {
      const position = Number(match[1])
      const before = code.slice(0, position)
      line = before.split('\n').length
      column = position - before.lastIndexOf('\n')
    }
    return {
      checks: [
        {
          name: 'json',
          status: 'error',
          message: 'JSON parse error',
          diagnostics: [
            { code: 'json', message, line, column, severity: 'error' },
          ],
        },
      ],
      calls: [],
      definitions: [],
    }
  }
}

/** Static checks only; this never executes the supplied code. */
export async function checkDraft(
  code: string,
  language = 'python',
): Promise<DraftAnalysis> {
  const normalized = language.trim().toLowerCase() || 'python'
  if (normalized === 'python' || normalized === 'py') {
    const syntax = await checkPython(code)
    const ruff = await checkRuff(code)
    return { ...syntax, checks: [...syntax.checks, ruff] }
  }
  if (
    normalized === 'typescript' ||
    normalized === 'ts' ||
    normalized === 'tsx' ||
    normalized === 'javascript' ||
    normalized === 'js' ||
    normalized === 'jsx'
  ) {
    const check = await checkScript(code, normalized)
    return { checks: [check], calls: [], definitions: [] }
  }
  if (normalized === 'json') return checkJson(code)
  return {
    checks: [
      {
        name: 'syntax',
        status: 'unavailable',
        message: `Formal checks cover Python, TypeScript/JavaScript and JSON; ${normalized} was saved without a static check.`,
        diagnostics: [],
      },
    ],
    calls: [],
    definitions: [],
  }
}

export function draftRoot(): string {
  const override = process.env.MBFORGE_DRAFT_DIR?.trim()
  return override ? resolve(override) : join(getAgentDir(), 'DRAFTS')
}

function indexFile(): string {
  return join(draftRoot(), 'index.json')
}

async function readStore(): Promise<DraftStore> {
  const raw = await readJsonFile(indexFile())
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    return { version: 1, items: [] }
  }
  const record = raw as Record<string, unknown>
  const items = Array.isArray(record.items)
    ? record.items.filter(
        (item): item is DraftRecord =>
          typeof item === 'object' &&
          item !== null &&
          typeof (item as DraftRecord).id === 'string' &&
          typeof (item as DraftRecord).file === 'string',
      )
    : []
  return { version: 1, items }
}

const serialize = createSerializer()

export interface SaveDraftInput {
  code: string
  language?: string
  target_path?: string
  summary?: string
}

function extensionFor(language: string): string {
  return EXTENSIONS[language] ?? (extname(language).replace('.', '') || 'txt')
}

/** Save a draft and its static diagnostics; never executes the code. */
export async function saveDraft(input: SaveDraftInput): Promise<DraftRecord> {
  const code = input.code.replace(/\r\n?/g, '\n').replace(/\s+$/, '')
  if (code.trim() === '') throw new Error('draft code must not be empty')
  if (code.length > MAX_CODE_CHARS) {
    throw new Error(`draft is larger than ${MAX_CODE_CHARS} characters`)
  }
  const language = input.language?.trim().toLowerCase() || 'python'
  const analysis = await checkDraft(code, language)
  const id = `draft-${randomUUID().slice(0, 8)}`
  const file = join(draftRoot(), `${id}.${extensionFor(language)}`)
  await atomicWrite(file, `${code}\n`)
  const record: DraftRecord = {
    id,
    language,
    file,
    target_path: input.target_path?.trim() || undefined,
    summary: input.summary?.trim() || undefined,
    lines: code.split('\n').length,
    chars: code.length,
    created_at: new Date().toISOString(),
    checks: analysis.checks,
  }

  return serialize(async () => {
    const store = await readStore()
    const all = [record, ...store.items]
    const next: DraftStore = { version: 1, items: all.slice(0, MAX_DRAFTS) }
    await atomicWrite(indexFile(), `${JSON.stringify(next, null, 2)}\n`)
    for (const removed of all.slice(MAX_DRAFTS)) {
      try {
        await unlink(removed.file)
      } catch {
        // A draft file may already be gone; the index remains authoritative.
      }
    }
    return record
  })
}

/** Draft metadata, newest first. */
export async function listDrafts(): Promise<DraftRecord[]> {
  return (await readStore()).items
}

/** Read one saved draft's code; the id is validated before touching disk. */
export async function readDraft(id: string): Promise<DraftRead> {
  const normalized = id.trim()
  if (!/^draft-[0-9a-f]{8}$/.test(normalized)) {
    throw new Error(`invalid draft id: ${id}`)
  }
  const record = (await readStore()).items.find(
    (item) => item.id === normalized,
  )
  if (!record) throw new Error(`draft not found: ${normalized}`)
  const code = await readFile(record.file, 'utf8')
  return { record, code }
}

const draftParameters = Type.Object({
  action: Type.Union(
    [
      Type.Literal('check'),
      Type.Literal('save'),
      Type.Literal('list'),
      Type.Literal('read'),
    ],
    {
      description:
        'check: validate code without saving; save: store the draft and return its path; list: recent drafts; read: one draft by id.',
    },
  ),
  code: Type.Optional(
    Type.String({
      description: 'Draft source code (required for check/save).',
      maxLength: MAX_CODE_CHARS,
    }),
  ),
  language: Type.Optional(
    Type.String({
      description:
        'Language for syntax checks; Python currently gets AST + Ruff.',
      maxLength: 32,
    }),
  ),
  target_path: Type.Optional(
    Type.String({
      description:
        'Intended repository file, used when the user applies the draft.',
      maxLength: 500,
    }),
  ),
  summary: Type.Optional(
    Type.String({
      description: 'One-line purpose of this draft.',
      maxLength: 500,
    }),
  ),
  id: Type.Optional(
    Type.String({
      description: 'Draft id for action=read.',
      pattern: '^draft-[0-9a-f]{8}$',
    }),
  ),
})

function toolResult(details: Record<string, unknown>) {
  return {
    content: [{ type: 'text' as const, text: JSON.stringify(details) }],
    details,
  }
}

/** Register the `draft` tool. */
export function registerDraftTool(pi: ExtensionAPI): void {
  pi.registerTool(
    defineTool({
      name: DRAFT_TOOL_NAME,
      label: 'Draft code',
      description:
        'Save or statically check a code draft instead of pasting a fenced block. Python gets AST + Ruff; TypeScript/JavaScript gets syntax diagnostics; JSON is parsed; other languages are saved and marked unchecked. The code is never executed. Use check before writing code with edit/write, or save to hand a draft to the user. Use list/read to revisit saved drafts.',
      promptGuidelines: [
        'When code is the deliverable, call draft action="check" with the exact code and target_path; fix every diagnostic, then write it with the normal edit/write tools. Use action="save" when the user should review a file first.',
        'Python drafts are checked with AST + Ruff; TypeScript/JavaScript drafts get syntax diagnostics only (no type check); JSON is parsed. Other languages are saved with status unavailable rather than silently accepted.',
        'Never paste a fenced code block as a substitute for editing a file. A draft is static code; it is not executed. SourceEvidence.create and other backend constructors are not capabilities.',
        'Do not put credentials, tokens, or library evidence text into a draft. Drafts live under the agent home, not the library.',
      ],
      parameters: draftParameters,
      ...toolRenderers(DRAFT_TOOL_NAME),
      async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
        if (params.action === 'check') {
          if (!params.code)
            throw new Error('draft action "check" requires code')
          const language = params.language?.trim().toLowerCase() || 'python'
          const analysis = await checkDraft(params.code, language)
          return toolResult({
            action: 'check',
            language,
            lines: params.code.split('\n').length,
            target_path: params.target_path?.trim() || undefined,
            summary: params.summary?.trim() || undefined,
            ...analysis,
          })
        }
        if (params.action === 'save') {
          if (!params.code) throw new Error('draft action "save" requires code')
          const record = await saveDraft({
            code: params.code,
            language: params.language,
            target_path: params.target_path,
            summary: params.summary,
          })
          return toolResult({ action: 'save', ...record })
        }
        if (params.action === 'list') {
          return toolResult({ action: 'list', items: await listDrafts() })
        }
        if (!params.id) throw new Error('draft action "read" requires id')
        const draft = await readDraft(params.id)
        return toolResult({ action: 'read', ...draft.record, code: draft.code })
      },
    }),
  )
}
