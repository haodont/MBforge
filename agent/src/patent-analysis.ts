/**
 * Evidence-constrained Patent-analysis runtime.
 *
 * The Python Patent stage opens one bound attempt per document and hands over a
 * bounded gap worklist: one unit of work per rule refusal, each carrying its own
 * excerpt. This side runs a Pi session whose only job is to answer those gaps —
 * it cannot pick its own work, its own excerpt or another document. The task
 * credential is captured here and is never a tool parameter, so the model cannot
 * choose a scope, a path or another document — the backend resolves all of that
 * from the credential.
 */

import { readFileSync } from 'node:fs'
import type { IncomingMessage, ServerResponse } from 'node:http'

import { defineTool } from '@earendil-works/pi-coding-agent'
import { Type } from '@earendil-works/pi-ai'

import { sendJson, startSse, writeSse } from './http.js'
import {
  asRecord,
  loadPersistedLlmConfig,
  readConfig,
  sanitizeError,
  stringValue,
} from './llm.js'
import { createSessionForSpec, type SessionSpec } from './session.js'
import { postTool } from './tool.js'

/** Bumped whenever the patent prompt changes, so results stay attributable. */
export const PATENT_PROMPT_VERSION = 'patent-gap-v4.4'
export const PATENT_PROTOCOL_VERSION = '2'

const TOOLS = {
  getGap: '/api/v1/patent-analysis/tools/get-gap',
  requestExcerpt: '/api/v1/patent-analysis/tools/request-excerpt',
  listMolecules: '/api/v1/patent-analysis/tools/list-molecules',
  submitGapAnswer: '/api/v1/patent-analysis/tools/submit-gap-answer',
} as const

/** The tool surface of a Patent run (never the chat tools). */
export const PATENT_TOOL_NAMES = [
  'get_gap',
  'request_excerpt',
  'list_molecules',
  'submit_gap_answer',
] as const

/**
 * How many structure lookups one gap may make.
 *
 * One call used to be the whole allowance, which left a session blind to the rest
 * of a 130–355 candidate catalogue when the page it got did not carry the label it
 * was asked about — a live run answered two lookups, then died on its gap budget.
 * A label lookup is one call and answers the question, so three is a bound rather
 * than a ration.
 */
const MAX_MOLECULE_LOOKUPS = 3

/**
 * Association gaps: the rule already read the passage, only its *owner* is unknown.
 *
 * Keyed by issue code, not by gap kind, because the work here is not to read a
 * value — it is to say which already-recognized structure a printed designation
 * belongs to. Every form below is a real corpus string.
 */
const ASSOCIATION_FORMS: Record<string, string> = {
  characterization_attribution: [
    'This gap is printed spectra or elemental data whose owner the rules could not',
    'name. The text itself is already recorded verbatim — do not retype or convert it.',
    'Forms: 化合物77：1H NMR (400 MHz, CDCl3) δ 7.42 (s, 1H); MS (ESI) m/z: 456.2 [M+H]+;',
    'LCMS: m/z 329.0 [M+H]+; 元素分析 calcd for C22H24N4O: C 70.19, H 6.43.',
    'Answer by linking the designation this passage belongs to: return',
    'status "answered" with links (label_raw as printed, mol_id of a recognized',
    'structure, the evidence id you read it from). If the passage names two',
    'designations or none, answer "unanswerable" with reason "no_attribution".',
  ].join('\n'),
  compound_name_unresolved: [
    'This gap is a printed chemical name whose designation the rules could not bind.',
    'Form: 实施例1：N-(5-(3,5-二氟苄基)噻唑-2-基)-2-甲基丙硫酰胺 — the name is already',
    'recorded; link it to the designation that owns it (links[].mol_id must be a',
    'structure this document recognized). A name may not be turned into a structure.',
  ].join('\n'),
  synthesis_route_unresolved: [
    'This gap is a preparation route whose product designation the rules could not',
    'resolve. Form: 参考实施例1方法，制得化合物36.8mg，收率16.5%。 (a mass, not',
    'compound 36) and "The following compounds were synthesized using a similar',
    'method to that of Example 1." Link the route to the designation whose compound',
    'it prepares; if the route names no product, answer "unanswerable" with',
    'reason "no_attribution". Do not restate the steps: they are already recorded.',
  ].join('\n'),
  molecule_label_unresolved: [
    'This gap is a designation printed in the document that no recognized structure',
    'claims. Forms: 化合物44, 実施例7, E020, IGP-20024-01, and OCR variants that',
    'differ only in case or spacing.',
    'Answer with links: label_raw as printed, mol_id of the structure you judge',
    'belongs to it (rule_context.structures lists the candidates the excerpt',
    'prints, with their mol_ids), plus the evidence id you read that from.',
    'When the gap lists no candidate for that label, call list_molecules with',
    'label set to the designation as printed: one call returns every structure that',
    'carries it, so do not page through the catalogue.',
    'Choose only a structure this document recognized; never author a SMILES.',
  ].join('\n'),
  molecule_candidate_ambiguous: [
    'This gap is a designation that more than one recognized structure could claim.',
    'Decide from the excerpt alone: a designation printed beside a structure on the',
    'same page, a shared number with a different suffix (77 vs 77-A), or a section',
    'that prepares exactly one compound.',
    'If the gap lists none of them, list_molecules with that label returns the whole',
    'set of structures carrying it — compare their pages and labels against the',
    'excerpt rather than guessing.',
    'Answer with one link per designation, citing the evidence that settles it. If the',
    'excerpt does not settle it, answer "unanswerable" with reason "no_attribution" —',
    'guessing which structure is worse than reporting the ambiguity.',
  ].join('\n'),
}

/**
 * Per-form guidance, appended to the gap the model just fetched.
 *
 * Every line below was read out of the analysed corpus (see
 * docs/wiki/patent-extraction-forms.md), and the closing sentence is the point:
 * an answer that says "there is no fact here" is a correct answer.
 */
const FORM_BLOCKS: Record<string, string> = {
  table: [
    'This gap is one activity table the rules refused to read.',
    'Forms you may see, all real:',
    '- a metric header spanning sibling columns, with a target row under it',
    "  (| 化合物编号 | IC50(nM) | then | MRGPRX1 | MRGPRX2 |);",
    "- a qualitative bin cell, sometimes OCR'd as 十 instead of + (十 counts as",
    '  one step of the same scale as +);',
    '- one row repeating (designation, value) pairs under repeated headers',
    '  (| 实施例编号 | IC50 (nM) | 实施例编号 | IC50 (nM) |);',
    '- a structure column carrying OCR noise (H3C, N. HN S) that is not a',
    '  designation: a value beside it has no owner. Report that with',
    '  unanswerable_reason "no_attribution" instead of attaching it to a compound.',
    'A line that defines a scale (A: IC50 < 500 nM, 注："+":IC50>1μM) is a',
    'definition, never a reading: it is not an item.',
    'When the gap lists rule_context.structures, name the structure each row',
    'belongs to with molecule_ref only when the mapping is explicit. Keep the',
    'printed designation and leave molecule_ref empty when unresolved.',
    'This task extracts readings; list_molecules is unavailable. Use only the',
    'supplied structure mapping and submit readings even without a structure.',
    'The evidence packet distinguishes work (data rows) from context (methods,',
    'captions and legends). Read context to determine the metric/unit and assay',
    'scope; proximity alone does not establish scope. Each item must include',
    'source_quote copied as one complete data row and cite that work evidence.',
    'For pipe tables also supply source_column: the zero-based value column,',
    'counting designation and structure columns. Copy value.raw_text from that',
    'exact cell; row_label_raw must copy its own designation cell. Never borrow',
    'a value from a sibling (designation, value) pair or invent a missing label.',
    'Keep explicitly printed control labels such as 阳参化合物 and leave their',
    'structure unresolved unless the supplied mapping proves it.',
    'Also cite the context evidence used for metric/unit/bins. Keep all assay',
    'columns separate; skip ND/NA/NT. Return every supported cell in this chunk.',
  ].join('\n'),
  prose_measurement: [
    'This gap is prose that names a metric without a value the rules could read.',
    'Forms you may see, all real:',
    '- one sentence listing several examples and one shared reading',
    '  ("Examples 4, 25, 28 and 30 exhibited a pIC50 ≥ 8.0.") — that is one item',
    '  per example, each keeping the printed operator and the listing as printed;',
    '- glyph damage ("ρIC50", "ICs0", full-width digits, "5.5 >ρIC5 0> 4.5") —',
    '  report "glyph_damaged" when the printed reading cannot be trusted;',
    '- a term definition ("术语"IC50"是指…", "the term ... refers to") or a',
    '  Markush list ("-CF3，-CH2-CF3…"): report "not_a_fact".',
  ].join('\n'),
  assay_attribution: [
    'This gap is a reading whose assay is unknown to the rules. The reading itself is',
    'already recorded (rule_context.related_fact_id names it) and is not your job to',
    'restate: returning it again only risks rewriting a value that is already verbatim.',
    'Name the assay that owns it: return one assay method with its own evidence',
    '(target, system, endpoint, conditions as printed, the verbatim raw_text). A',
    'caption, a section heading or a table title is evidence for the assay. Return',
    'items only if you are reporting a reading the rules missed — then point them at',
    'the method with assay_local_key; if you report none, Python binds the recorded',
    'reading to your method. If nothing in the excerpt states which assay produced the',
    'readings, answer "unanswerable" with reason "no_attribution" — never guess one.',
  ].join('\n'),
  assay_method: [
    'This gap is an assay description whose heading the rules did not recognize.',
    'Return one assay method: target, system (species, as printed), endpoint,',
    'conditions as printed, and the verbatim raw_text you based it on.',
  ].join('\n'),
}


export interface PatentBudget {
  max_model_turns: number
  wall_clock_seconds: number
  max_total_tokens: number
  digest_char_budget: number
  /** Per provider request timeout; never the chat's short exchange budget. */
  request_timeout_seconds: number
}

export interface PatentGapInput {
  gap_id: string
  gap_kind: string
  code: string
  message?: string
  page_start?: number | null
  page_end?: number | null
  evidence_ids: string[]
  excerpt: string
  rule_context?: Record<string, unknown>
}

export interface PatentRunRequest {
  doc_id: string
  run_id: string
  attempt_id: string
  evidence_signature: string
  credential: string
  budget: PatentBudget
  gaps: PatentGapInput[]
}

export type PatentStatus = 'succeeded' | 'failed' | 'cancelled'

export interface PatentOutcome {
  ok: boolean
  status: PatentStatus
  /** ``false`` when the run stopped early: submitted facts are still valid. */
  complete: boolean
  turns: number
  tool_calls: number
  /** ``null`` when the provider reported no usage: unknown, never 0. */
  tokens: number | null
  duration_ms: number
  model: string
  prompt_version: string
  error_code?: string
  error?: string
}

interface UsageLike {
  input?: number
  output?: number
  totalTokens?: number
}

export interface PatentBudgetGuard {
  noteTurn(): void
  noteToolCall(): void
  noteUsage(usage: UsageLike | undefined): number | null
  exceeded(): string | null
  stats(): { turns: number; tool_calls: number; tokens: number | null; duration_ms: number }
}

/** Pure budget accounting; ``now`` is injectable so tests need no clock. */
export function createBudgetGuard(
  budget: PatentBudget,
  now: () => number = Date.now,
): PatentBudgetGuard {
  const startedAt = now()
  let turns = 0
  let toolCalls = 0
  let tokens: number | null = null

  return {
    noteTurn() {
      turns += 1
    },
    noteToolCall() {
      toolCalls += 1
    },
    noteUsage(usage) {
      const total =
        typeof usage?.totalTokens === 'number'
          ? usage.totalTokens
          : typeof usage?.input === 'number' || typeof usage?.output === 'number'
            ? (usage?.input ?? 0) + (usage?.output ?? 0)
            : null
      if (total !== null && Number.isFinite(total)) tokens = (tokens ?? 0) + total
      return tokens
    },
    exceeded() {
      if (turns > budget.max_model_turns) return 'model turn budget exceeded'
      if (now() - startedAt > budget.wall_clock_seconds * 1000) {
        return 'wall clock budget exceeded'
      }
      if (tokens !== null && tokens > budget.max_total_tokens) {
        return 'token budget exceeded'
      }
      return null
    },
    stats() {
      return {
        turns,
        tool_calls: toolCalls,
        tokens,
        duration_ms: Math.max(0, now() - startedAt),
      }
    },
  }
}

type StopKind = 'none' | 'user' | 'disconnect' | 'budget'

const attempts = new Map<string, () => Promise<void>>()

/** Register the abort hook for one in-flight attempt. */
export function registerAttempt(attemptId: string, abort: () => Promise<void>): void {
  attempts.set(attemptId, abort)
}

/** Cancel one in-flight attempt; ``false`` when it already finished. */
export function cancelAttempt(attemptId: string): boolean {
  const abort = attempts.get(attemptId)
  if (!abort) return false
  void abort()
  return true
}

export function unregisterAttempt(attemptId: string): void {
  attempts.delete(attemptId)
}

export function activeAttemptIds(): string[] {
  return [...attempts.keys()].sort()
}

export interface PatentToolHooks {
  /** Host-assigned work: a session cannot fetch or submit a different gap. */
  gap?: PatentGapInput
  isActive?: () => boolean
  /** Called on every submission so the run can stream it and settle. */
  onSubmit(accepted: boolean, payload: Record<string, unknown>): void
  /**
   * The attempt's identity triple, injected into every answer.
   *
   * The binding is the caller's, not the model's: supplying it here removes a
   * whole failure mode (a stale or mistyped attempt) from the prompt.
   */
  identity?: {
    doc_id: string
    attempt_id: string
    evidence_signature: string
  }
}

function textResult(name: string, payload: unknown, details: Record<string, unknown>) {
  return {
    content: [{ type: 'text' as const, text: JSON.stringify(payload) }],
    details: { tool: name, ...details },
  }
}

/** The structures a gap already identified, for reuse without a lookup. */
function readStructures(
  gap: Record<string, unknown>,
): Array<{ label: string; mol_id: string }> {
  const context = asRecord(gap.rule_context)
  const raw = Array.isArray(context.structures) ? context.structures : []
  const found: Array<{ label: string; mol_id: string }> = []
  for (const entry of raw.slice(0, 20)) {
    const item = asRecord(entry)
    const label = stringValue(item.label, '', 128)
    const molId = stringValue(item.mol_id, '', 512)
    if (label && molId) {
      found.push({ label, mol_id: molId })
    }
  }
  return found
}

/** Build the run's tools; the credential stays captured in this closure. */
export function createPatentTools(credential: string, hooks: PatentToolHooks) {
  /**
   * The structures the current gap already identified, as ``label -> mol_id``.
   *
   * They travel with the gap precisely so no lookup is needed; a session that
   * looks them up again pays for the same answer twice and (measured on
   * CN120329282A) still submitted an empty molecule_ref. Non-table gaps retain
   * bounded lookups; table readings do not depend on a resolved structure.
   */
  let currentStructures = hooks.gap ? readStructures({ ...hooks.gap }) : []

  /**
   * The gap the model holds but has not answered.
   *
   * A live run fetched gap after gap and submitted nothing (24 tool calls, all
   * ``get_gap``) until its budget ran out. The work is one gap at a time, so a
   * second fetch while one is open is refused with the next step spelled out —
   * the model can still re-read the gap it holds, and can still submit it.
   */
  let openGap: string | null = hooks.gap?.gap_id ?? null
  let moleculeLookups = 0

  const getGap = defineTool({
    name: 'get_gap',
    label: 'Get the next gap',
    description:
      'Return one bounded gap: what the rules refused to read, where it is, and the verbatim excerpt an answer is judged against. Call it with no gap_id for the next unanswered gap. The reply also carries the forms this kind of gap takes.',
    promptSnippet: 'fetch the next gap to answer',
    promptGuidelines: [
      'Work one gap at a time: fetch it, answer it, submit it, then fetch the next.',
      'Answer only from the excerpt you were given; cite its evidence ids.',
    ],
    parameters: Type.Object({
      gap_id: Type.Optional(
        Type.String({ maxLength: 128, description: 'Omit for the next unanswered gap.' }),
      ),
    }),
    async execute(_toolCallId, params, signal) {
      const requested = params.gap_id ?? ''
      if (openGap && requested !== openGap) {
        return {
          content: [
            {
              type: 'text' as const,
              text:
                `Gap ${openGap} is still unanswered, so there is no next gap yet. ` +
                'Answer it with submit_gap_answer first — if its excerpt does not ' +
                'settle it, submit status "unanswerable" with the matching reason. ' +
                'Fetching another gap before that answers nothing.',
            },
          ],
          details: {
            tool: 'get_gap',
            gap_kind: '',
            payload: {},
            refused: 'open_gap_unsubmitted',
          },
        }
      }
      const payload = await postTool<Record<string, unknown>>(
        TOOLS.getGap,
        { credential, gap_id: requested },
        signal,
      )
      const gap = asRecord(payload.gap)
      if (payload.success === false) {
        // The model only sees this as a failed tool call and retries; without this
        // line a whole run can burn its budget with nothing in any log to explain it.
        console.error('[mbforge] get_gap refused:', JSON.stringify(payload).slice(0, 600))
      }
      const kind = stringValue(gap.gap_kind, '', 64)
      currentStructures = readStructures(gap)
      openGap = stringValue(gap.gap_id, '', 128) || null
      // Association gaps are keyed by issue code: their work is not to read a value
      // but to name the owner of a passage the rules already read.
      const code = stringValue(gap.code, '', 64)
      const block = ASSOCIATION_FORMS[code] ?? FORM_BLOCKS[kind] ?? ''
      const parts = [JSON.stringify(payload)]
      if (block) {
        parts.push(`Forms for this gap (${kind}):\n${block}`)
      }
      if (currentStructures.length) {
        parts.push(
          'Structures this gap already identified — copy the mol_id into ' +
            'molecule_ref, and do not call list_molecules:\n' +
            currentStructures
              .map((item) => `  ${item.label} -> ${item.mol_id}`)
              .join('\n'),
        )
      }
      if (openGap) {
        // The last thing the model reads before it decides what to do next.
        parts.push(
          'Answer this gap now: submit it with submit_gap_answer, then fetch the next.',
        )
      }
      return {
        content: [{ type: 'text' as const, text: parts.join('\n\n') }],
        details: { tool: 'get_gap', gap_kind: kind, payload, refused: '' },
      }
    },
  })

  const requestExcerpt = defineTool({
    name: 'request_excerpt',
    label: 'Ask for one more excerpt',
    description:
      "Fetch the one bounded follow-up excerpt a gap may ask for (at most 20 pages, 200 rows, or 50 evidence ids). Use it only when the gap's own excerpt is missing the header, caption or legend the answer needs; a gap may ask once.",
    promptSnippet: 'fetch one bounded follow-up excerpt for the current gap',
    promptGuidelines: [
      'One follow-up excerpt per gap; after it, answer with what you have.',
    ],
    parameters: Type.Object({
      gap_id: Type.String({ minLength: 1, maxLength: 128 }),
      evidence_ids: Type.Optional(
        Type.Array(Type.String({ maxLength: 64 }), { maxItems: 50 }),
      ),
      page_from: Type.Optional(Type.Number({ minimum: 1 })),
      page_to: Type.Optional(Type.Number({ minimum: 1 })),
    }),
    async execute(_toolCallId, params, signal) {
      if (hooks.isActive && !hooks.isActive()) throw new Error('gap session has ended')
      if (hooks.gap && params.gap_id !== hooks.gap.gap_id) {
        return textResult('request_excerpt', { success: false, error: 'use the assigned gap_id' }, {})
      }
      const payload = await postTool<Record<string, unknown>>(
        TOOLS.requestExcerpt,
        {
          credential,
          gap_id: params.gap_id,
          evidence_ids: params.evidence_ids ?? [],
          page_from: params.page_from,
          page_to: params.page_to,
        },
        signal,
      )
      return textResult('request_excerpt', payload, { payload })
    },
  })

  const listMolecules = defineTool({
    name: 'list_molecules',
    label: 'List bound structures',
    description:
      'List the structures already recognized in the bound document as a compact identity list (mol_id, name, labels, structure_role, page). Never invents a structure: a molecule_ref must be one of these. Pass label (the printed designation, e.g. 化合物77 or 实施例7) to get exactly the structures that carry it — that is the way to settle an ambiguous or unclaimed designation. Without a label it pages through the whole catalogue.',
    promptSnippet: 'list the recognized structures carrying a printed label',
    promptGuidelines: [
      'Look a designation up by label instead of paging through the catalogue.',
      'At most three lookups per gap; a label lookup answers the question in one call.',
    ],
    parameters: Type.Object({
      label: Type.Optional(
        Type.String({
          maxLength: 200,
          description:
            'A printed designation to look up. Omit to page the whole catalogue.',
        }),
      ),
      page: Type.Optional(Type.Number({ minimum: 1 })),
      page_size: Type.Optional(Type.Number({ minimum: 1, maximum: 50 })),
    }),
    async execute(_toolCallId, params, signal) {
      if (hooks.isActive && !hooks.isActive()) throw new Error('gap session has ended')
      if (moleculeLookups >= MAX_MOLECULE_LOOKUPS) {
        return textResult('list_molecules', {
          success: false,
          error: `at most ${MAX_MOLECULE_LOOKUPS} structure lookups per gap; answer with what you have`,
        }, {})
      }
      moleculeLookups += 1
      const payload = await postTool<Record<string, unknown>>(
        TOOLS.listMolecules,
        {
          credential,
          label: params.label ?? '',
          page: params.page ?? 1,
          page_size: params.page_size ?? 20,
        },
        signal,
      )
      return textResult('list_molecules', payload, { payload })
    },
  })

  const submitGapAnswer = defineTool({
    name: 'submit_gap_answer',
    label: 'Submit one gap answer',
    description:
      'Submit your answer for one gap. The document/attempt binding, the gap identity and evidence membership (the answer may only cite the gap\'s own excerpt, plus the one follow-up you fetched) are checked server-side; a rejected answer returns the reasons so you can fix it and submit again. An accepted answer is kept even if the run stops early.',
    promptSnippet: 'submit the answer for the current gap',
    promptGuidelines: [
      'Every item must cite evidence ids from this gap\'s excerpt.',
      'If there is no fact here, answer "unanswerable" with a reason — that is a real answer.',
      'If a submission is rejected, fix the reported reasons and submit again.',
    ],
    parameters: Type.Object({
      answer: Type.Unsafe<Record<string, unknown>>(gapAnswerSchema(Boolean(hooks.gap && hooks.identity))),
    }),
    async execute(_toolCallId, params, signal) {
      if (hooks.isActive && !hooks.isActive()) throw new Error('gap session has ended')
      const payload = await postTool<Record<string, unknown>>(
        TOOLS.submitGapAnswer,
        {
          credential,
          answer: {
            ...params.answer,
            ...(hooks.identity ?? {}),
            ...(hooks.gap ? { gap_id: hooks.gap.gap_id, gap_kind: hooks.gap.gap_kind } : {}),
          },
        },
        signal,
      )
      const accepted = payload.success === true
      if (accepted) openGap = null
      hooks.onSubmit(accepted, payload)
      return {
        content: [{ type: 'text' as const, text: JSON.stringify(payload) }],
        details: { tool: 'submit_gap_answer', payload },
        // A host-assigned session ends here; the host schedules the next gap.
        terminate: Boolean(hooks.gap && accepted && payload.status !== 'needs_excerpt'),
      }
    },
  })

  return [getGap, requestExcerpt, listMolecules, submitGapAnswer]
    .filter(tool => hooks.gap?.gap_kind !== 'table' || tool.name !== 'list_molecules')
}

/** The gap-answer contract, read from the exported bundle (no second copy here). */
function gapAnswerSchema(bindIdentity = true): Record<string, unknown> {
  const url = new URL('../schemas/patent-gap.v2.json', import.meta.url)
  const bundle = JSON.parse(readFileSync(url, 'utf8')) as {
    models?: Record<string, Record<string, unknown>>
  }
  const answer = bundle.models?.PatentGapAnswer
  if (!answer) throw new Error('patent gap schema unavailable')
  const defs = asRecord(answer.$defs)
  const expand = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(expand)
    if (value === null || typeof value !== 'object') return value
    const node = asRecord(value)
    if (typeof node.$ref === 'string') {
      const key = node.$ref.split('/').pop() ?? ''
      if (!defs[key]) throw new Error(`missing patent schema definition: ${key}`)
      return expand(defs[key])
    }
    return Object.fromEntries(Object.entries(node)
      .filter(([key]) => key !== '$defs')
      .map(([key, item]) => [key, expand(item)]))
  }
  // Identity is assigned by the host, never asked of the model.
  const schema = asRecord(expand(answer))
  if (!bindIdentity) return schema
  const properties = { ...asRecord(schema.properties) }
  const bound = ['doc_id', 'attempt_id', 'evidence_signature', 'gap_id', 'gap_kind']
  for (const key of bound) delete properties[key]
  return { ...schema, properties,
    required: (schema.required as string[]).filter(key => !bound.includes(key)) }
}

/**
 * One worked answer in the exact shape the contract accepts.
 *
 * The schema alone left the session without a submit-ready object — the first
 * live run spent its whole budget and submitted nothing — so the prompt carries
 * an example instance as well. It is the CN selectivity row read out of the
 * corpus, minus the identity triple (the sidecar fills that in), because a
 * worked example is what makes the first submission cheap.
 */
const EXAMPLE_ANSWER = JSON.stringify(
  {
    status: 'answered',
    items: [
      {
        local_key: 'item-1',
        metric: 'IC50',
        value: { raw_text: '++', qualitative: '++' },
        source_quote: '| 实施例1 | ++ |',
        source_column: 1,
        compound_label_raw: '实施例1',
        row_label_raw: '实施例1',
        compound_label_key: '1',
        page: 21,
        evidence_ids: ['<an evidence id from this gap>'],
      },
    ],
    evidence_ids: ['<an evidence id from this gap>'],
  },
  null,
  2,
)

/**
 * The numeric shape, from ``| 化合物77 | 26.3 |`` in CN120329282A p113.
 *
 * The qualitative instance above was not enough: a run submitted four correct
 * readings and had them rejected twice, because the number's key inside the
 * value object (``value.value``) was never shown.
 */
const EXAMPLE_NUMERIC_ANSWER = JSON.stringify(
  {
    status: 'answered',
    items: [
      {
        local_key: 'item-1',
        metric: 'CYP3A4抑制率',
        value: { raw_text: '26.3', operator: '=', value: 26.3, unit: '%' },
        source_quote: '| 化合物77 | 26.3 |',
        source_column: 1,
        compound_label_raw: '化合物77',
        row_label_raw: '化合物77',
        compound_label_key: '77',
        molecule_ref: '<the mol_id of that structure from this gap>',
        target: 'CYP3A4',
        page: 113,
        evidence_ids: ['<an evidence id from this gap>'],
      },
    ],
    evidence_ids: ['<an evidence id from this gap>'],
  },
  null,
  2,
)

const EXAMPLE_UNANSWERABLE = JSON.stringify(
  {
    status: 'unanswerable',
    unanswerable_reason: 'glyph_damaged',
    evidence_ids: [],
  },
  null,
  2,
)

/**
 * A link-only answer: the association shape the contract accepts.
 *
 * The label is sent exactly as printed (``label_key`` is derived by the backend),
 * and the structure must be one this document already recognized. A link states no
 * value, so it can never fabricate a reading.
 */
const EXAMPLE_LINK_ANSWER = JSON.stringify(
  {
    status: 'answered',
    links: [
      {
        label_raw: '化合物77-A',
        label_key: '',
        mol_id: '<the mol_id of a structure this document recognized>',
        evidence_ids: ['<an evidence id from this gap>'],
        rationale: '该段只制备此化合物，标签与结构同页相邻。',
      },
    ],
    evidence_ids: ['<an evidence id from this gap>'],
  },
  null,
  2,
)

function hardRules(): string {
  return (
    'Rules:\n' +
    '- The host assigns one gap. Answer it with submit_gap_answer and stop. ' +
    'If it cannot be answered, submit "unanswerable" with the matching reason.\n' +
    '- Answer from the gap\'s excerpt only, and cite its evidence ids. Never cite ' +
    'an id from elsewhere; the backend rejects an answer that does.\n' +
    '- Never invent a number, a unit or a structure. Never rewrite the printed ' +
    'operator: "< 100 nM" is not "100 nM". Missing stays missing.\n' +
    '- A line that defines a scale or a term is not a fact ("A: IC50 < 500 nM", ' +
    '注："+":IC50>1μM, 术语"IC50"是指…). Say so with status "unanswerable" and ' +
    'reason "not_a_fact".\n' +
    '- Never author or edit a SMILES. Preserve the printed designation even when ' +
    'its structure is unresolved. A designation is document-local: Example 7 is ' +
    'not automatically Compound 7, and 77, 77-A and 77-B are distinct. ' +
    'Never choose between structures sharing a label without evidence. ' +
    'When the gap lists structures under rule_context.structures, set ' +
    'molecule_ref only when the printed designation unambiguously identifies it. ' +
    'Leave molecule_ref empty if unresolved; the reading still belongs to its ' +
    'printed document-local label. A candidate list is not an answer key.\n' +
    '- Preserve qualitative bins as value.qualitative and keep any stated bounds ' +
    'in conditions. Never turn ++++ or an interval into a point IC50. Keep the ' +
    'row label exactly as printed and each target/substrate column separate.\n' +
    '- Inside a reading\'s value object the digits belong to the key named ' +
    '"value" (value.value = 26.3). "number" is not a key and is rejected.\n' +
    '- An association is not a reading. When the gap\'s work is "which structure ' +
    'does this passage belong to", answer with links (label_raw exactly as ' +
    'printed, mol_id of a recognized structure, the evidence you read it from) ' +
    'and do not restate values that are already recorded.\n' +
    '- Do not merge a human target with its mouse ortholog: record target and ' +
    'system (species) as printed.\n' +
    '- If the excerpt genuinely does not settle the gap, say "unanswerable" with ' +
    'the matching reason. A give-up with a reason is a real answer; a guess is not.\n' +
    '- You may ask for exactly one follow-up excerpt per gap with ' +
    'request_excerpt, and only when the header, caption or legend you need is ' +
    'missing. After it, answer.\n'
  )
}

/** System prompt for a Patent run: bounded gaps, evidence-constrained answers. */
export function patentSystemPrompt(gap?: PatentGapInput): string {
  return (
    'You are the MBForge patent-analysis worker. You analyze exactly one bound ' +
    'patent document by answering a bounded list of gaps: each gap is one thing ' +
    'the deterministic rules refused to read, with its own excerpt. The document ' +
    'id, the library and the evidence set are bound by the caller; you cannot ' +
    'change them, and no tool call takes a path or a document id.\n' +
    hardRules() +
    '\nThe submit_gap_answer tool parameters define the answer contract.\n' +
    '\nThe host supplies the gap and injects the document/attempt identity.\n' +
    'Example answer for a qualitative table row, as the answer argument of ' +
    'submit_gap_answer:\n' +
    (gap && ASSOCIATION_FORMS[gap.code] ? EXAMPLE_LINK_ANSWER : EXAMPLE_ANSWER) +
    (gap ? '' : '\nExample answer for a numeric table row:\n' + EXAMPLE_NUMERIC_ANSWER) +
    '\nExample answer when the excerpt holds no fact:\n' +
    EXAMPLE_UNANSWERABLE
  )
}

function initialPrompt(gap: PatentGapInput): string {
  const guidance = ASSOCIATION_FORMS[gap.code] ?? FORM_BLOCKS[gap.gap_kind] ?? ''
  return `Answer this assigned gap and submit once.\n${JSON.stringify(gap)}\n${guidance}`
}

function boundedInt(value: unknown, fallback: number, min: number, max: number): number {
  const parsed =
    typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : fallback
  return Math.min(Math.max(parsed, min), max)
}

function parseBudget(input: unknown): PatentBudget {
  const raw = asRecord(input)
  return {
    max_model_turns: boundedInt(raw.max_model_turns, 24, 1, 200),
    wall_clock_seconds: boundedInt(raw.wall_clock_seconds, 600, 5, 7200),
    max_total_tokens: boundedInt(raw.max_total_tokens, 80_000, 1000, 4_000_000),
    digest_char_budget: boundedInt(raw.digest_char_budget, 60_000, 1000, 500_000),
    request_timeout_seconds: boundedInt(raw.request_timeout_seconds, 240, 10, 7200),
  }
}

export function parsePatentRequest(
  body: unknown,
): { ok: true; value: PatentRunRequest } | { ok: false; error: string } {
  const input = asRecord(body)
  if (stringValue(input.protocol_version, '', 16) !== PATENT_PROTOCOL_VERSION) {
    return { ok: false, error: 'unsupported protocol_version' }
  }
  const docId = stringValue(input.doc_id, '', 128)
  const runId = stringValue(input.run_id, '', 128)
  const attemptId = stringValue(input.attempt_id, '', 128)
  const evidenceSignature = stringValue(input.evidence_signature, '', 128)
  const credential = stringValue(input.credential, '', 128)
  if (!docId || !runId || !attemptId || !evidenceSignature) {
    return {
      ok: false,
      error: 'doc_id, run_id, attempt_id and evidence_signature are required',
    }
  }
  if (credential.length < 8) {
    return { ok: false, error: 'credential is required' }
  }
  const gaps = Array.isArray(input.gaps)
    ? input.gaps.filter((item): item is Record<string, unknown> => Boolean(asRecord(item)))
    : []
  return {
    ok: true,
    value: {
      doc_id: docId,
      run_id: runId,
      attempt_id: attemptId,
      evidence_signature: evidenceSignature,
      credential,
      budget: parseBudget(input.budget),
      gaps: gaps
        .map((gap) => ({
          gap_id: stringValue(gap.gap_id, '', 128),
          gap_kind: stringValue(gap.gap_kind, '', 64),
          code: stringValue(gap.code, '', 64),
          message: stringValue(gap.message, '', 2000),
          page_start: typeof gap.page_start === 'number' ? gap.page_start : null,
          page_end: typeof gap.page_end === 'number' ? gap.page_end : null,
          evidence_ids: Array.isArray(gap.evidence_ids)
            ? gap.evidence_ids.map((id) => stringValue(id, '', 128)).filter(Boolean)
            : [],
          excerpt: stringValue(gap.excerpt, '', 20_000),
          rule_context: asRecord(gap.rule_context),
        }))
        .filter((gap) => gap.gap_id.length > 0),
    },
  }
}

export async function handlePatentAnalysis(
  request: IncomingMessage,
  response: ServerResponse,
  body: unknown,
): Promise<void> {
  const parsed = parsePatentRequest(body)
  if (!parsed.ok) {
    sendJson(request, response, 422, { error: parsed.error })
    return
  }
  const run = parsed.value

  const config = readConfig(undefined, await loadPersistedLlmConfig())
  const guard = createBudgetGuard(run.budget)
  let submitted = false
  let fatal: string | null = null

  if (run.gaps.length === 0) {
    // No work: the caller must not have opened an attempt at all, so refuse to
    // spend a provider call on it.
    sendJson(request, response, 200, {
      ok: false,
      status: 'failed',
      complete: true,
      turns: 0,
      tool_calls: 0,
      tokens: null,
      duration_ms: 0,
      model: config.model,
      prompt_version: PATENT_PROMPT_VERSION,
      error_code: 'no_gaps',
      error: 'the request carried no gap worklist',
    })
    return
  }
  // Mutated from the abort closure, so it is read through an object: TypeScript
  // would otherwise narrow a plain local to its initial value.
  const stop: { kind: StopKind; reason: string | null } = {
    kind: 'none',
    reason: null,
  }

  const answered = new Set<string>()
  let session: Awaited<ReturnType<typeof createSessionForSpec>> | undefined
  let settled = false
  const startedAt = Date.now()
  const abort = async (kind: StopKind, reason: string) => {
    stop.kind = stop.kind === 'none' ? kind : stop.kind
    stop.reason ??= reason
    try { await session?.abort() } catch { /* best-effort abort */ }
  }
  startSse(request, response)
  writeSse(response, 'progress', {
    kind: 'progress', phase: 'bind',
    message: `bound to document ${run.doc_id} (attempt ${run.attempt_id})`,
  })
  const wallClock = setTimeout(
    () => void abort('budget', 'wall clock budget exceeded'),
    run.budget.wall_clock_seconds * 1000,
  )
  const onClose = () => {
    if (!settled) void abort('disconnect', 'client disconnected')
  }
  response.once('close', onClose)
  registerAttempt(run.attempt_id, () => abort('user', 'cancelled by the caller'))

  try {
    for (const gap of run.gaps) {
      if (stop.kind !== 'none') break
      const breached = guard.exceeded()
      if (breached) { await abort('budget', breached); break }
      let active = true
      let gapTurns = 0
      let unsubscribe: (() => void) | undefined
      let timer: ReturnType<typeof setTimeout> | undefined
      let rejectGap: (reason: Error) => void = () => {}
      const gapStopped = new Promise<never>((_resolve, reject) => { rejectGap = reject })
      try {
        const tools = createPatentTools(run.credential, {
          gap,
          identity: { doc_id: run.doc_id, attempt_id: run.attempt_id,
            evidence_signature: run.evidence_signature },
          isActive: () => active && stop.kind === 'none',
          onSubmit: (accepted, payload) => {
            if (accepted && payload.status !== 'needs_excerpt') {
              submitted = true
              answered.add(gap.gap_id)
            }
            writeSse(response, 'gap', { kind: 'gap', ok: accepted,
              message: accepted ? 'gap answer accepted' : 'gap answer rejected',
              data: { ...payload, gap_id: gap.gap_id } })
          },
        }).filter(tool => tool.name !== 'get_gap')
        const spec: SessionSpec = {
          systemPrompt: patentSystemPrompt(gap),
          toolNames: tools.map(tool => tool.name), customTools: tools,
        }
        session = await createSessionForSpec(
          { ...config, requestTimeoutMs: run.budget.request_timeout_seconds * 1000 }, spec,
        )
        const current = session
        const endGap = (reason: string) => {
          active = false
          rejectGap(new Error(reason))
          void current.abort().catch(() => {})
        }
        // Bound the entire gap, including provider streams that keep headers open.
        const remaining = run.budget.wall_clock_seconds * 1000 - (Date.now() - startedAt)
        timer = setTimeout(() => endGap('gap time budget exceeded'),
          Math.max(1, Math.min(run.budget.request_timeout_seconds * 1000, remaining)))
        writeSse(response, 'progress', { kind: 'progress', phase: 'gap',
          message: `assigned gap ${gap.gap_id}` })
        unsubscribe = current.subscribe(event => {
          if (!active) return
          if (event.type === 'turn_start') {
            guard.noteTurn()
            gapTurns += 1
            writeSse(response, 'progress', { kind: 'progress', phase: 'turn',
              turn: guard.stats().turns, message: `model turn ${guard.stats().turns}` })
            if (gapTurns > 4) endGap('per-gap turn limit exceeded')
          } else if (event.type === 'message_end') {
            guard.noteUsage((event.message as { usage?: UsageLike }).usage)
          } else if (event.type === 'tool_execution_start') {
            guard.noteToolCall()
            writeSse(response, 'tool', { kind: 'tool', tool: event.toolName, ok: null })
          } else if (event.type === 'tool_execution_end') {
            const content = asRecord(event.result).content
            const detail = event.isError && Array.isArray(content)
              ? content.map(part => asRecord(part).text).filter(text => typeof text === 'string').join('\n') : ''
            const error = detail
              ? sanitizeError(detail.split(run.credential).join('***'), config.apiKey) : null
            writeSse(response, 'tool', { kind: 'tool', tool: event.toolName,
              ok: !event.isError, error, message: error ?? '' })
          }
          const limit = guard.exceeded()
          if (limit) { void abort('budget', limit); endGap(limit) }
        })
        await Promise.race([current.prompt(initialPrompt(gap), {
          expandPromptTemplates: false, source: 'rpc',
        }), gapStopped])
        const providerError = current.agent.state.errorMessage
        if (providerError) throw new Error(providerError)
        if (!answered.has(gap.gap_id)) throw new Error('gap ended without a final submission')
      } catch (error) {
        fatal = sanitizeError(error, run.credential)
        writeSse(response, 'progress', { kind: 'progress', phase: 'gap_failed',
          message: `gap ${gap.gap_id}: ${fatal}` })
      } finally {
        active = false
        clearTimeout(timer)
        unsubscribe?.()
        session?.dispose()
        session = undefined
      }
    }
  } finally {
    settled = true
    clearTimeout(wallClock)
    response.removeListener('close', onClose)
    unregisterAttempt(run.attempt_id)
    const stats = guard.stats()
    const cancelled = stop.kind === 'user' || stop.kind === 'disconnect'
    const status: PatentStatus = cancelled ? 'cancelled' : submitted ? 'succeeded' : 'failed'
    const complete = answered.size === run.gaps.length && stop.kind === 'none'
    const errorCode = complete ? undefined : stop.kind === 'budget' ? 'budget_exceeded'
      : cancelled ? 'cancelled' : fatal ? 'gap_failed' : 'no_submission'
    const outcome: PatentOutcome = {
      ok: status === 'succeeded', status, complete,
      turns: stats.turns, tool_calls: stats.tool_calls, tokens: stats.tokens,
      duration_ms: stats.duration_ms, model: config.model, prompt_version: PATENT_PROMPT_VERSION,
      ...(errorCode ? { error_code: errorCode } : {}),
      ...(!complete ? { error: stop.reason ?? fatal ?? 'not all gaps were answered' } : {}),
    }
    writeSse(response, 'done', outcome)
    if (!response.writableEnded) response.end()
  }
}

/** Cancel one in-flight attempt; a late submission is refused by the backend. */
export async function handlePatentAnalysisCancel(
  request: IncomingMessage,
  response: ServerResponse,
  body: unknown,
): Promise<void> {
  const input = asRecord(body)
  const attemptId = stringValue(input.attempt_id, '', 128)
  if (!attemptId) {
    sendJson(request, response, 422, { error: 'attempt_id is required' })
    return
  }
  sendJson(request, response, 200, {
    success: true,
    cancelled: cancelAttempt(attemptId),
  })
}
