import { stdin as input, stdout as output } from 'node:process'
import { createInterface, type Interface } from 'node:readline/promises'

import type { AgentSession } from '@mariozechner/pi-coding-agent'

import type { AgentMode } from './capabilities.js'
import { createSession, readPersistedConfig } from './runtime.js'

interface CliArgs {
  mode: AgentMode
  prompt?: string
  tokenFile?: string
}

function usage(): string {
  return [
    'Usage: mbforge-agent [--mode readonly|edit] [--prompt <text>] [--token-file <path>]',
    '',
    '  --mode        readonly (default) or edit; edit enables mutating capabilities',
    '  --prompt, -p  run one prompt and exit',
    '  --token-file  capability token path (default: manifest token_path)',
  ].join('\n')
}

function parseArgs(argv: string[]): CliArgs {
  let mode: AgentMode =
    process.env.MBFORGE_AGENT_MODE === 'edit' ? 'edit' : 'readonly'
  let prompt: string | undefined
  let tokenFile = process.env.MBFORGE_CAPABILITY_TOKEN_FILE

  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index]
    if (argument === '--mode') {
      const value = argv[++index]
      if (value !== 'readonly' && value !== 'edit') {
        throw new Error('--mode must be readonly or edit')
      }
      mode = value
    } else if (argument === '--prompt' || argument === '-p') {
      prompt = argv[++index]
    } else if (argument === '--token-file') {
      tokenFile = argv[++index]
    } else if (argument === '--help' || argument === '-h') {
      console.log(usage())
      process.exit(0)
    } else {
      throw new Error(`unknown argument: ${argument}`)
    }
  }

  if (tokenFile) process.env.MBFORGE_CAPABILITY_TOKEN_FILE = tokenFile
  return { mode, prompt, tokenFile }
}

async function promptOnce(session: AgentSession, message: string): Promise<void> {
  const unsubscribe = session.subscribe((event) => {
    if (event.type === 'message_update' && event.assistantMessageEvent.type === 'text_delta') {
      process.stdout.write(event.assistantMessageEvent.delta)
    } else if (event.type === 'tool_execution_start') {
      process.stderr.write(`\n[tool] ${event.toolName} start\n`)
    } else if (event.type === 'tool_execution_end') {
      process.stderr.write(`[tool] ${event.toolName} ${event.isError ? 'error' : 'done'}\n`)
    }
  })
  try {
    await session.prompt(message, { expandPromptTemplates: false })
  } finally {
    unsubscribe()
    process.stdout.write('\n')
  }
  const error = session.agent.state.errorMessage
  if (error) throw new Error(error)
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2))
  const config = await readPersistedConfig({})
  const session = await createSession(config, args.mode)
  let readline: Interface | undefined

  process.on('SIGINT', () => {
    if (session.isStreaming) {
      void session.abort()
      return
    }
    session.dispose()
    process.exit(0)
  })

  try {
    if (args.prompt) {
      await promptOnce(session, args.prompt)
      return
    }

    readline = createInterface({ input, output })
    console.log(`MBForge agent (${args.mode}). /exit to quit.`)
    for (;;) {
      const line = (await readline.question('mbforge> ')).trim()
      if (!line) continue
      if (line === '/exit' || line === '/quit') break
      if (line === '/mode') {
        console.log(args.mode)
        continue
      }
      try {
        await promptOnce(session, line)
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error)
        console.error(`error: ${detail}`)
      }
    }
  } finally {
    readline?.close()
    session.dispose()
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error))
  process.exitCode = 1
})
