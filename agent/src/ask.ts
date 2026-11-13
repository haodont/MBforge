import {
  getKeybindings,
  Input,
  truncateToWidth,
  visibleWidth,
  type Component,
} from '@earendil-works/pi-tui'
import {
  defineTool,
  keyHint,
  keyText,
  type ExtensionAPI,
  type ExtensionContext,
  type Theme,
} from '@earendil-works/pi-coding-agent'
import { Type } from 'typebox'

import { toolRenderers } from './toolRender.js'
import { renderSegments, wrapText, type Segment } from './uiText.js'

/**
 * One question dialog for every user-facing decision.
 *
 * The tool surface is generic (`kind` + title/message/options), while the
 * dialog is the same card for `ask`, `request_dev_mode`, and
 * `suggest_improvement`: `⬡ MBForge`, the question in bold, context in muted
 * text, one option per row, and a bottom key-hint bar. The answer is a plain
 * object so the model can branch without parsing prose.
 */

export type AskKind = 'confirm' | 'select' | 'multi_select' | 'text'

export interface AskOption {
  value: string
  label?: string
  description?: string
}

export interface AskQuestion {
  kind: AskKind
  title: string
  message?: string
  options?: AskOption[]
  placeholder?: string
  default_value?: string
  confirm_label?: string
  cancel_label?: string
}

export interface AskAnswer {
  kind: AskKind
  title: string
  answer: string | null
  answer_label: string | null
  confirmed: boolean | null
  selected: string[]
  cancelled: boolean
}

export const ASK_TOOL_NAME = 'ask'
export const ASK_TOOL_NAMES = [ASK_TOOL_NAME] as const

const KIND_LABELS: Readonly<Record<AskKind, string>> = {
  confirm: 'confirm',
  select: 'choose',
  multi_select: 'choose multiple',
  text: 'answer',
}

const OPTION_WINDOW = 8

/** Build the browser-safe question: validate shape and fill confirm options. */
function normalizeQuestion(question: AskQuestion): AskQuestion {
  const title = question.title.trim()
  if (title === '') throw new Error('ask requires a non-empty title')
  const message = question.message?.trim() || undefined
  if (question.kind === 'text') {
    return {
      ...question,
      title,
      message,
      options: [],
      placeholder: question.placeholder?.trim() || undefined,
      default_value: question.default_value?.trim() || undefined,
    }
  }

  const options =
    question.kind === 'confirm'
      ? [
          { value: 'yes', label: question.confirm_label?.trim() || 'Yes' },
          { value: 'no', label: question.cancel_label?.trim() || 'No' },
        ]
      : (question.options ?? []).map((option) => ({
          value: option.value.trim(),
          label: option.label?.trim() || undefined,
          description: option.description?.trim() || undefined,
        }))
  if (options.length === 0) {
    throw new Error(`ask kind "${question.kind}" requires at least one option`)
  }
  const seen = new Set<string>()
  for (const option of options) {
    if (option.value === '')
      throw new Error('ask options need a non-empty value')
    if (seen.has(option.value))
      throw new Error(`ask option "${option.value}" is duplicated`)
    seen.add(option.value)
  }
  return {
    ...question,
    title,
    message,
    options,
    placeholder: undefined,
    default_value: undefined,
    confirm_label: undefined,
    cancel_label: undefined,
  }
}

function cancelledAnswer(question: AskQuestion): AskAnswer {
  return {
    kind: question.kind,
    title: question.title,
    answer: null,
    answer_label: null,
    confirmed: null,
    selected: [],
    cancelled: true,
  }
}

/** One question card, rendered in the editor slot by `ctx.ui.custom`. */
class AskDialog implements Component {
  private readonly input: Input
  private selectedIndex = 0
  private readonly selected = new Set<string>()
  private _focused = false

  constructor(
    private readonly question: AskQuestion,
    private readonly theme: Theme,
    private readonly done: (answer: AskAnswer) => void,
  ) {
    this.input = new Input({
      prompt: '',
      placeholder: question.placeholder ?? '',
      placeholderStyle: (text) => this.theme.fg('dim', text),
    })
    this.input.setValue(question.default_value ?? '')
    this.input.onSubmit = (value) => this.finishText(value)
    this.input.onEscape = () => this.finishCancelled()
    this.input.focused = true
  }

  get focused(): boolean {
    return this._focused
  }

  set focused(value: boolean) {
    this._focused = value
    this.input.focused = value
  }

  invalidate(): void {}

  dispose(): void {}

  handleInput(data: string): void {
    const kb = getKeybindings()
    if (this.question.kind === 'text') {
      this.input.handleInput(data)
      return
    }
    if (kb.matches(data, 'tui.select.cancel')) {
      this.finishCancelled()
      return
    }
    if (this.question.kind === 'multi_select' && data === ' ') {
      this.toggle()
      return
    }
    if (kb.matches(data, 'tui.select.up') || data === 'k') {
      this.move(-1)
      return
    }
    if (kb.matches(data, 'tui.select.down') || data === 'j') {
      this.move(1)
      return
    }
    if (kb.matches(data, 'tui.select.confirm') || data === '\n') {
      this.submit()
    }
  }

  render(width: number): string[] {
    const total = Math.max(16, Math.min(width - 2, 78))
    const contentWidth = Math.max(8, total - 4)
    const rows: string[] = []
    const kindLabel = KIND_LABELS[this.question.kind]

    rows.push(
      renderSegments([
        { text: '⬡ ', style: (text) => this.theme.fg('accent', text) },
        {
          text: 'MBForge',
          style: (text) => this.theme.bold(this.theme.fg('accent', text)),
        },
        { text: ' · ', style: (text) => this.theme.fg('dim', text) },
        { text: kindLabel, style: (text) => this.theme.fg('muted', text) },
      ]),
    )
    rows.push('')
    for (const line of wrapText(this.question.title, contentWidth)) {
      rows.push(
        renderSegments([
          {
            text: line,
            style: (text) => this.theme.bold(this.theme.fg('text', text)),
          },
        ]),
      )
    }
    const message = this.question.message?.trim()
    if (message) {
      rows.push('')
      for (const line of wrapText(message, contentWidth)) {
        rows.push(
          line === ''
            ? ''
            : renderSegments([
                { text: line, style: (text) => this.theme.fg('muted', text) },
              ]),
        )
      }
    }

    rows.push('')
    if (this.question.kind === 'text') {
      const inputWidth = Math.max(8, contentWidth - 2)
      for (const line of this.input.render(inputWidth)) {
        rows.push(
          `${renderSegments([{ text: '> ', style: (text) => this.theme.fg('accent', text) }])}${line}`,
        )
      }
    } else {
      const options = this.question.options ?? []
      const start = Math.max(
        0,
        Math.min(
          this.selectedIndex - Math.floor(OPTION_WINDOW / 2),
          Math.max(0, options.length - OPTION_WINDOW),
        ),
      )
      const end = Math.min(options.length, start + OPTION_WINDOW)
      if (start > 0) {
        rows.push(
          renderSegments([
            {
              text: `… ${start} above`,
              style: (text) => this.theme.fg('dim', text),
            },
          ]),
        )
      }
      for (let index = start; index < end; index += 1) {
        rows.push(this.renderOption(index, options[index]))
      }
      if (end < options.length) {
        rows.push(
          renderSegments([
            {
              text: `… ${options.length - end} below`,
              style: (text) => this.theme.fg('dim', text),
            },
          ]),
        )
      }
    }

    rows.push('')
    rows.push(
      renderSegments([
        { text: this.hint(), style: (text) => this.theme.fg('dim', text) },
      ]),
    )
    return this.frame(total, contentWidth, rows)
  }

  private renderOption(index: number, option: AskOption | undefined): string {
    const active = index === this.selectedIndex
    const label = option?.label ?? option?.value ?? ''
    const checked = option ? this.selected.has(option.value) : false
    const segments: Segment[] = []
    if (this.question.kind === 'multi_select') {
      segments.push({
        text: checked ? '[x] ' : '[ ] ',
        style: (text) => this.theme.fg(active ? 'accent' : 'dim', text),
      })
    } else {
      segments.push({
        text: active ? '❯ ' : '  ',
        style: (text) => this.theme.fg(active ? 'accent' : 'dim', text),
      })
    }
    segments.push({
      text: label,
      style: (text) =>
        active
          ? this.theme.bold(this.theme.fg('accent', text))
          : this.theme.fg(checked ? 'accent' : 'text', text),
    })
    if (option?.description) {
      segments.push({
        text: ` · ${option.description}`,
        style: (text) => this.theme.fg('dim', text),
      })
    }
    return renderSegments(segments)
  }

  private hint(): string {
    const up = keyText('tui.select.up')
    const down = keyText('tui.select.down')
    if (this.question.kind === 'text') {
      return `${keyHint('tui.select.confirm', 'submit')} · ${keyHint('tui.select.cancel', 'cancel')}`
    }
    if (this.question.kind === 'multi_select') {
      return `${up}/${down} move · space toggle · ${keyHint('tui.select.confirm', 'submit')} · ${keyHint('tui.select.cancel', 'cancel')}`
    }
    return `${up}/${down} move · ${keyHint('tui.select.confirm', this.question.kind === 'confirm' ? 'choose' : 'select')} · ${keyHint('tui.select.cancel', 'cancel')}`
  }

  private frame(total: number, contentWidth: number, rows: string[]): string[] {
    const border = (text: string) => this.theme.fg('borderMuted', text)
    const top = border(`╭${'─'.repeat(total - 2)}╮`)
    const bottom = border(`╰${'─'.repeat(total - 2)}╯`)
    const body = rows.map((row) => {
      const clipped = truncateToWidth(row, contentWidth, '…')
      const padding = ' '.repeat(
        Math.max(0, contentWidth - visibleWidth(clipped)),
      )
      return `${border('│')} ${clipped}${padding} ${border('│')}`
    })
    return [top, ...body, bottom]
  }

  private base(): AskAnswer {
    return {
      kind: this.question.kind,
      title: this.question.title,
      answer: null,
      answer_label: null,
      confirmed: null,
      selected: [],
      cancelled: false,
    }
  }

  private move(delta: number): void {
    const count = this.question.options?.length ?? 0
    if (count === 0) return
    this.selectedIndex = Math.min(
      count - 1,
      Math.max(0, this.selectedIndex + delta),
    )
  }

  private toggle(): void {
    const option = this.question.options?.[this.selectedIndex]
    if (!option) return
    if (this.selected.has(option.value)) this.selected.delete(option.value)
    else this.selected.add(option.value)
  }

  private submit(): void {
    if (this.question.kind === 'multi_select') {
      this.done({ ...this.base(), selected: [...this.selected] })
      return
    }
    const option = this.question.options?.[this.selectedIndex]
    if (!option) return
    this.done({
      ...this.base(),
      answer: option.value,
      answer_label: option.label ?? option.value,
      confirmed:
        this.question.kind === 'confirm' ? this.selectedIndex === 0 : null,
    })
  }

  private finishText(value: string): void {
    const answer = value.trim()
    this.done({ ...this.base(), answer, answer_label: answer || null })
  }

  private finishCancelled(): void {
    this.done({ ...this.base(), cancelled: true })
  }
}

/** Fallback for RPC/headless sessions and tests without the custom dialog. */
async function fallbackAsk(
  ctx: ExtensionContext,
  question: AskQuestion,
): Promise<AskAnswer> {
  if (question.kind === 'confirm') {
    const approved = await ctx.ui.confirm(
      question.title,
      question.message ?? '',
    )
    return {
      kind: 'confirm',
      title: question.title,
      answer: approved ? 'yes' : 'no',
      answer_label: approved
        ? (question.options?.[0]?.label ?? 'Yes')
        : (question.options?.[1]?.label ?? 'No'),
      confirmed: approved,
      selected: [],
      cancelled: false,
    }
  }
  const prompt = question.message
    ? `${question.title}\n${question.message}`
    : question.title
  if (question.kind === 'select') {
    const options = question.options ?? []
    const labels = options.map((option) => option.label ?? option.value)
    const picked = await ctx.ui.select(prompt, labels)
    if (picked === undefined) return cancelledAnswer(question)
    const option = options[labels.indexOf(picked)] ?? options[0]
    if (!option) return cancelledAnswer(question)
    return {
      kind: 'select',
      title: question.title,
      answer: option.value,
      answer_label: option.label ?? option.value,
      confirmed: null,
      selected: [],
      cancelled: false,
    }
  }
  if (question.kind === 'text') {
    const value = await ctx.ui.input(prompt, question.placeholder)
    if (value === undefined) return cancelledAnswer(question)
    const answer = value.trim()
    return {
      kind: 'text',
      title: question.title,
      answer,
      answer_label: answer || null,
      confirmed: null,
      selected: [],
      cancelled: false,
    }
  }
  throw new Error('multi-select needs the interactive TUI')
}

/**
 * Ask the user one question and resolve with the answer. In the TUI the
 * branded card is used; RPC and headless sessions fall back to pi's selector,
 * confirm, or input dialog so the call still works.
 */
export async function askUser(
  ctx: ExtensionContext,
  question: AskQuestion,
): Promise<AskAnswer> {
  if (!ctx.hasUI) {
    throw new Error(
      'ask needs an interactive session; no question dialog is available',
    )
  }
  const normalized = normalizeQuestion(question)
  if (ctx.mode === 'tui' && typeof ctx.ui.custom === 'function') {
    return ctx.ui.custom<AskAnswer>(
      (_tui, theme, _keybindings, done) =>
        new AskDialog(normalized, theme, done),
      { blocked: { kind: 'question', message: normalized.title } },
    )
  }
  return fallbackAsk(ctx, normalized)
}

const askOptionParameters = Type.Object({
  value: Type.String({
    description: 'Stable value returned to the model; keep it short.',
    maxLength: 200,
  }),
  label: Type.Optional(
    Type.String({
      description: 'Short label shown to the user; defaults to value.',
      maxLength: 200,
    }),
  ),
  description: Type.Optional(
    Type.String({
      description: 'Optional one-line explanation shown after the label.',
      maxLength: 400,
    }),
  ),
})

const askParameters = Type.Object({
  kind: Type.Union(
    [
      Type.Literal('confirm'),
      Type.Literal('select'),
      Type.Literal('multi_select'),
      Type.Literal('text'),
    ],
    {
      description:
        'confirm: yes/no; select: one option; multi_select: several options; text: a short free-form answer.',
    },
  ),
  title: Type.String({
    description: 'The question itself, one short sentence.',
    maxLength: 200,
  }),
  message: Type.Optional(
    Type.String({
      description:
        'Context shown under the question: why it matters, a short list, or the consequence of each choice.',
      maxLength: 4000,
    }),
  ),
  options: Type.Optional(
    Type.Array(askOptionParameters, {
      description:
        'Required for select and multi_select; ignored for confirm and text.',
      maxItems: OPTION_WINDOW,
    }),
  ),
  placeholder: Type.Optional(
    Type.String({
      description:
        'For text: grey placeholder, such as a file name or a format example.',
      maxLength: 160,
    }),
  ),
  default_value: Type.Optional(
    Type.String({
      description: 'For text: initial value in the input.',
      maxLength: 200,
    }),
  ),
  confirm_label: Type.Optional(
    Type.String({
      description: 'For confirm: label of the positive choice.',
      maxLength: 40,
    }),
  ),
  cancel_label: Type.Optional(
    Type.String({
      description: 'For confirm: label of the negative choice.',
      maxLength: 40,
    }),
  ),
})

/** Register the generic `ask` tool. */
export function registerAskTool(pi: ExtensionAPI): void {
  pi.registerTool(
    defineTool({
      name: ASK_TOOL_NAME,
      label: 'Ask the user',
      description:
        'Ask the user one blocking question and wait for the answer. Use confirm for yes/no, select for one choice, multi_select for several choices, or text for a short free-form answer. Put context in message and choices in options; do not use it to ask for facts you can read or to confirm a tool call.',
      promptGuidelines: [
        'Ask at most one question per turn. Provide 2–5 options with a stable value and a short label; put the consequence of each choice in description or message.',
        'The answer is the user’s decision, not library evidence. Do not cite it as a source; cite library identifiers separately.',
        'If the user cancels, do not repeat the same question. Proceed with the safe default or ask a different question.',
        'Do not use ask to request permission for dev mode or an improvement proposal; request_dev_mode and suggest_improvement have their own approval dialogs.',
      ],
      parameters: askParameters,
      ...toolRenderers(ASK_TOOL_NAME),
      async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
        const answer = await askUser(ctx, params as AskQuestion)
        return {
          content: [{ type: 'text', text: JSON.stringify(answer) }],
          details: answer,
        }
      },
    }),
  )
}
