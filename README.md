# MBForge

MBForge is a local AI workbench for turning molecular-science PDFs into a
searchable knowledge base. It extracts molecules and activities, keeps source
artifacts for review, and exposes search workflows through a React UI and
FastAPI backend.

## Current scope

- The agent surface is the pi CLI: `npm --prefix agent run cli` opens pi's
  interactive session with MBForge's capabilities registered as tools. The same
  capabilities are exposed over HTTP at `/api/v1/capabilities`; read-only calls
  need no credential and mutating calls require `X-MBForge-Token`. There is no
  web chat surface and no Node agent server.
- PDF pipeline: Extract → Markdown → Patent. Extract is the single producer: one render drives the local layout/text/table producer and a second drives the molecule pass (MolDet + MolParser), and it mints and persists the canonical SQL `SourceEvidence` rows itself. Markdown assembles the readable document from that evidence; Patent reads it, publishes one facts artifact, and performs deterministic document-local associations. SQL is the only evidence store — there is no branch artifact. Link and Persist have been removed from the active path.
- Molecule detection and recognition with MolDetv2-YOLO26 and MolParser-Mobile
  (E-SMILES) plus RDKit; page layout, text and table-structure recognition run
  entirely locally (Hiro-Layout + RapidOCR + SLANet-1M) — no cloud OCR service is
  called.
- Local storage per library: SQLite business data and document artifacts; no
  third-party knowledge-index runtime is required.
- Knowledge-base search, molecule search, activity data, and a unified review
  center covering molecule, Markush and evidence items — Markush structures are
  classified during Extract and reviewed in that center.
- Workspace document import accepts multiple PDFs at once, rejects duplicate
  filenames, and reports partial failures; each imported document is registered
  and listed right away as 待处理 and starts processing immediately (unless
  auto-enqueue is disabled), settling at 已提取, 就绪 or 失败. Documents can be
  selected, exported, or deleted in bulk. Pipeline execution controls (Extract,
  Patent, cancel, retry) live in the CLI; the queue page is read-only.
- Removed with the CLI-only cutover: the web research/chat workspace, the
  review center's automatic AI-assist suggestion generation, the provider
  model-list and connectivity-probe settings, and the optional LLM-led Patent
  analysis. The deterministic Patent pipeline and its facts are unchanged; the
  research SQL tables, `review_assists` storage and the research queue hook are
  gone. The CLI may file review proposals through `propose_review`; a human
  still confirms or rejects every proposal.

The project is a research baseline. Recognition and extracted data require
human review; model loading can take several seconds on the first request.
Mobile, multi-user collaboration, and rich export formats are currently out of
scope. Track active work in [TODO/INDEX.md](TODO/INDEX.md).

## Requirements

Python 3.12, [uv](https://github.com/astral-sh/uv), Node.js 24.14.1+ and npm.
GPU is optional, but required by local MolDet/MolParser inference. The project
is distributed as its source folder and keeps all
runtime state inside it: settings, logs, model weights and the default library
root all live under `library/` next to `src/`. Copying the folder copies the
whole installation.

Dependencies are split into a core install plus three extras: `local-models`
and `gpu` (heavy AI/GPU inference) and `onnx` (CPU fallback for crop-label OCR;
mutually exclusive with `gpu` — both provide the `onnxruntime` module). `uv
sync` installs the full stack through the `dev` group. For a constrained,
core-only install use `uv sync --no-dev`; add inference support with
`pip install "mbforge[gpu,local-models]"`. Startup logs a capability summary of
which optional modules and CUDA are available.

`uv` resolves packages from the Tsinghua TUNA mirror by default (declared as the
default index in `pyproject.toml`, with `pytorch-cu128` kept as an explicit
index for `torch`/`torchvision`). A plain `pip install` is unaffected and still
uses the environment's own index configuration.

## Model weights

Heavy models are downloaded at runtime by `ResourceManager` (ModelScope) into
`library/models/`; none are stored in git except the one exception below.

- **`assets/models/moldetv2_structure_ft.pt`** — MolDetv2 structure-detection
  weights **fine-tuned on patent pages**. Source: the
  [Moldetv2 project](https://modelscope.cn/models/UniParser/MolDetv2-YOLO26)
  (`UniParser/MolDetv2-YOLO26` `960_doc` base, single-class `structure`
  detection; fine-tune continued run `moldetv2_structure_ft_cont/weights/best.pt`,
  trained on 1426 patent pages). **License: upstream `cc-by-nc-sa-4.0`** —
  academic/non-commercial use only; redistribution must keep attribution and
  share-alike. This file is the only model weight committed to the
  repository, so a fresh clone has a working patent-aware detector out of
  the box. To use it as the active detector, copy it over the runtime model:
  `cp assets/models/moldetv2_structure_ft.pt library/models/MolDetv2/moldet_v2_yolo26n_960_doc.pt`
  (or point `DEFAULT_SUBPATH` in `src/mbforge/foundation/inference/moldet_v2_ft.py`
  at it).

## Quick start

```bash
uv sync
npm --prefix frontend install
npm --prefix agent install

# Optional: expose the agent CLI as `mbforge` (one time)
npm --prefix agent run link

# Optional: pre-download fd/ripgrep for the offline agent CLI
npm --prefix agent run prefetch:bin

# Development mode (backend reload + Vite HMR)
npm --prefix frontend run dev:all

# Agent CLI (separate terminal; starts the backend if needed)
npm --prefix agent run cli
```

`npm --prefix agent run link` installs a global `mbforge` shim, so `mbforge`
from any directory launches the same CLI. Remove it with
`npm unlink -g mbforge-agent`.

Open <http://127.0.0.1:5173>. `dev:all` starts the backend with source reload,
starts Vite with HMR, waits in one terminal, and stops the paired process if
either service exits with an error. Its default ports are `18792` (backend) and
`5173` (frontend); both fail clearly if already in use. `dev:all` does not start
the agent: the pi CLI is a separate foreground process under `agent/`, and
quitting it leaves the dev stack running.

`npm --prefix frontend run dev` starts Vite only. Run `dev:all` for backend plus
Vite, or start the backend separately; Vite does not own or stop it. HTTP calls
use the same-origin `/api` proxy when Vite is running.

To use isolated ports (for example, a second worktree), set all values before
starting. The launcher passes the backend address to the Vite proxy, direct
frontend URLs, and backend CORS configuration:

```powershell
$env:MBFORGE_DEV_PORT = '28792'
$env:MBFORGE_DEV_FRONTEND_PORT = '25173'
npm --prefix frontend run dev:all
```

`MBFORGE_DEV_HOST` defaults to `127.0.0.1`. To run the services separately,
use `uv run python -m mbforge --host 127.0.0.1 --port 18792` and `cd frontend
&& npm run dev`. To build the frontend, run `cd frontend && npm run build`;
FastAPI serves `frontend/dist/` when it exists.

### Pipeline evidence contract

Extract mints the canonical `SourceEvidence` rows from page text, typed layout
regions, recognized table content and the molecule pass' SMILES/E-SMILES, and
persists them directly into SQLite (`{library_root}/library.db`) — SQL
is the only runtime evidence store and there is no intermediate branch artifact.
Text spans and downstream artifacts carry the resulting `evidence_id` rather
than duplicating the evidence payload.

## Capability API

MBForge exposes agent-callable capabilities under `/api/v1/capabilities`.
`GET /api/v1/capabilities` returns the manifest; `GET /api/v1/capabilities/guide`
returns a Markdown guide with input schemas. Read-only calls need no credential.
Mutating calls require `X-MBForge-Token`; the token is created at
`{library_root}/.mbforge/capability-token` and is read by the harness only in
capability-write modes (`auto` / `dev`). Patent facts are produced by a
separate opt-in run:
`submit_patent_analysis` queues the Patent stage and returns `run_ids`; poll
`get_run`, then read `get_patent_result`. `submit_extraction` runs Extract +
Markdown. `search_evidence` searches extracted text across documents,
`ocr_page_region` reads layout-guided text from one page or PDF region.
`query_activities` is the canonical reading-level activity dataset for one
document: it returns every stored reading, including unattributed ones, with
assay, value, page, evidence ids and attributed molecule identities. It applies
no activity threshold; follow `next_offset` before claiming completeness.
`inspect_visual` consolidates the visual actions: `page_image` renders a stored
page or PDF-point region, `page_molecules` runs MolDet + MolParser on a stored
page/region (no base64), `molecule_image` renders a SMILES (concrete or
Markush), and `recognize_structure` recognizes caller-supplied base64 image
bytes with MolParser. Image actions return an image attachment; the TUI
previews it inline on Kitty/iTerm2 terminals and shows an image fallback label
otherwise.
`propose_review` files an AI review proposal for a human decision; it never
applies the proposed value and refuses a target a human already decided.
`list_review_queue` returns the unified review queue (pending by default) with
each item's `kind` + `item_id`, document, page and bbox — the same identity the
review center addresses as `/review?kind=&id=`, so an agent can link the exact
decision instead of describing it.

### Agent CLI

`npm --prefix agent run cli` (or `mbforge` after the one-time link) opens pi's
normal interactive CLI with the MBForge capability tools registered. The
launcher pins pi's agent directory to
`agent/.pi-agent/` through `PI_CODING_AGENT_DIR`, so settings, packages,
extensions, skills, prompts, themes, and system-prompt files from `~/.pi/agent`
never load into this project; only `agent/APPEND_SYSTEM.md`, the MBForge
extension, and project skills under `agent/skills/` apply. That directory is
git-ignored and starts without provider
credentials: run `/login` once to store built-in provider credentials, then
`/model` to pick a model and
`/mbforge` to inspect the active capability mode. For a custom
OpenAI/Anthropic-compatible endpoint, run `/endpoint`; it prompts for the base
URL, protocol, and API key, reads `/models` to let you pick a model (with a
manual fallback), then reads `/models/{model}` for context/output limits the
list omitted before pre-filling the context window and max output tokens from
the returned metadata so you can override them. It writes the endpoint and
model metadata to `agent/.pi-agent/models.json`, and writes the key only to
`agent/.pi-agent/auth.json` (a literal or `$ENV_VAR` reference). Context sizes
accept plain tokens or `k`/`m` suffixes, for example `128000`, `128k`, or `1m`.
Run `/model` afterward to select the new model.

Project skills live under `agent/skills/` and are loaded by the launcher.
`patent-active-molecules` is the SOP for extracting every stored activity
reading and its molecules from one patent; invoke it directly with
`/skill:patent-active-molecules`.

The CLI also creates `agent/.pi-agent/MEMORY.md` for durable local notes. The
model calls one `memory` tool: `add` stores a short preference or workspace
fact under `user`, `feedback`, `project`, or `reference`, `list` reports the
stored notes with their ids, and `delete` removes a stale entry by id. The
matching `/memory` command shows the file (`/memory list`),
`/memory add [type] <text>` appends, and `/memory delete <id>` deletes. The
agent also adds notes on its own when a reply states a durable preference or
workspace fact. The file
is injected into each turn as context (never as source evidence), capped at
16 KiB, and stays out of git. Override its path with `MBFORGE_MEMORY_FILE` if
needed. Delete `agent/.pi-agent/` to reset the project agent (including memory and suggestion history).

The agent can also propose scoped improvements to the pipeline, capability
tools, prompt, UI, or docs with the local `suggest_improvement` tool. A
suggestion is stored in `agent/.pi-agent/IMPROVEMENTS.json` only after the user
approves or declines it in a terminal dialog. On approval in `dev` mode, the
agent implements exactly the proposed change and marks the record completed;
outside `dev` mode approval is recorded but implementation waits for a mode
switch. `/improvements` lists the log. Override its path with
`MBFORGE_IMPROVEMENTS_FILE` if needed.

The agent registers a goal with the local `goal` tool before non-trivial
work: 1-5 verifiable requirements, acceptance evidence, constraints, and
non-goals. It updates the goal when scope changes and cancels it when the user
stops or replaces the task. `goal complete` requires a summary, verification,
and residual risks, then queues a background review instead of blocking the
answer. An aborted run cancels the active goal.

The background review spawns a read-only child Pi session over the goal-scoped
transcript, lets it read referenced source files, writes durable lessons through
the local memory tool, and returns scoped improvement proposals. The reviewer
is told not to alter code, not to call itself, and not to review trivia.
Suggestions remain advice until the user files one with `suggest_improvement`.
The manual `review_task` tool remains for explicit ad-hoc reviews.

Review jobs are persisted in `agent/.pi-agent/GOAL_REVIEW_QUEUE.json`; a job left
running by a crash is retried up to three times, and a permanently failed job
stays visible instead of disappearing. Full tool text is captured under
`agent/.pi-agent/GOAL_ARTIFACTS/<session>/<goal>/`; the review transcript carries
the tool name, compact input, status, and artifact path, so the reviewer can
read the full output on demand. Override the queue path with
`MBFORGE_REVIEW_QUEUE_FILE` for tests or custom layouts.

`/goal-reviews` lists queued, running, and failed reviews; `/goal-reviews retry
<id>` requeues a failed one; `/goal-reviews prune` applies the artifact
retention pass. Artifacts keep at most 200 files and 50 MiB per goal, and each
captured output is capped at 200,000 characters. Override the artifact root
with `MBFORGE_GOAL_ARTIFACT_DIR`. Failed, blocked, and aborted tool calls are
captured from `tool_execution_end`, so a call that never produces a normal
`tool_result` still leaves an `error` entry in the goal index.

Session mode controls the agent's depth with one setting:
`MBFORGE_AGENT_MODE=auto|dev` (PowerShell:
`$env:MBFORGE_AGENT_MODE='dev'`).

| Mode | Capability tools | Built-in repository tools |
|---|---|---|
| `auto` (default) | all 18, mutating calls token-gated | off |
| `dev` | all 18, mutating calls token-gated | `read`, `bash`, `edit`, `write`, `grep`, `find`, `ls` |

In `auto`, only MBForge capability tools are exposed (plus the local tools); no
repository or built-in code tools are active. A mutating capability without the
capability token is answered with 403. `dev`
adds the seven built-ins on top of the same capability set.

The mode can be changed in-session without restarting:

```text
/mbforge mode auto
/mbforge mode dev
```

The change is session-local; a restart returns to the environment default.
`edit` is accepted as an alias for `auto`, and
`MBFORGE_AGENT_DEV=1` is still accepted as the legacy default for `dev`.
Built-in tools run with the user's OS permissions and are intended only for
repository/source work, never for changing library data, database files,
artifacts, or capability tokens. The launcher
starts the FastAPI backend at the configured backend address (default port
18792) when nothing is listening, waits for `/api/v1/capabilities`, and stops
the backend it started when pi exits. A backend that was already running is
reused and left alone. Set `MBFORGE_AGENT_START_BACKEND=0` to require a
separately managed backend; the auto-started backend logs to
`agent/.pi-agent/logs/backend.log`. Edit `agent/APPEND_SYSTEM.md` to change the
agent's domain instructions; it is appended to pi's base system prompt on
every launch.

Skill discovery is disabled with `--no-skills`. The launcher explicitly loads
`agent/skills/` only when that directory exists, so `~/.agents/skills`,
`~/.pi/agent/skills`, package skills, and project `.pi/skills` are never
scanned. Put project skills under `agent/skills/<name>/SKILL.md`;
`/skill:<name>` works in every mode, and dev mode's built-in `read` tool also
lists the loaded skills in the prompt.

Pi manages `fd` and `rg` under `agent/.pi-agent/bin`. The launcher runs
`--offline`, so Pi never downloads them at startup; run
`npm --prefix agent run prefetch:bin` online once to populate that directory
and remove the offline warnings. The command is idempotent.

The CLI is a pi extension (`agent/src/extension.ts`), not a custom REPL.
Built-in pi tools stay off outside `dev` mode; `/mbforge mode dev` enables
`read`, `bash`, `edit`, `write`, `grep`, `find`, and `ls`, with `grep`/`find`
using the managed `rg`/`fd` binaries. Pi's provider login, model switching,
sessions, and themes remain available. It is the only agent surface: the
backend serves the capability API and never starts an agent process, and there
is no HTTP agent server to configure.

## Verification

```bash
uv run pytest tests/ -q
uv run ruff check src/ tests/
uv run ruff format src/ tests/ --check

cd frontend
npm run lint
npx tsc --noEmit
npm run test
npm run build
```

## Storage contract

`library_root` is the Python field and `libraryRoot` is the TypeScript/wire
field. It defaults to the source folder's `library/` directory, which is where
settings, logs and model weights also live, so the whole installation travels
with the folder. Document records live in the `documents` table of
`library.db`, keyed by the SHA-256 of the file's bytes — identical content is
one document, and `file_name` is unique. The canonical layout is:

```text
{library_root}/
├── library.db                          # unified SQLite database
├── queue.lock                          # ingest-worker ownership lock
├── procs/                              # runtime process registry
├── backups/                            # pre-mutation document snapshots
└── storage/{doc_id}/                   # document artifacts
    ├── {file_name}                     # the imported PDF, under its original name
    ├── document.md
    ├── report.json
    ├── patent_facts.json
    └── crops/{filename}                # molecule crop images
```

`source.pdf` is read only as a legacy fallback (tracked in
[TODO/INDEX.md](TODO/INDEX.md)). Use `LibraryLayout` for library and document
paths. Do not construct these paths inline.

## Documentation

Start with the [documentation index](docs/README.md).

| Need | Document |
|---|---|
| Install and product overview | [README.md](README.md) |
| AI coding rules | [AGENTS.md](AGENTS.md) |
| Architecture and code standards | [docs/wiki/architecture.md](docs/wiki/architecture.md) |
| Pipeline reference | [docs/wiki/pipeline.md](docs/wiki/pipeline.md) |
| HTTP API | [docs/api/README.md](docs/api/README.md) |
| Work priorities | [TODO/INDEX.md](TODO/INDEX.md) |
| Releases and branches | [docs/wiki/workflow.md](docs/wiki/workflow.md) |

Historical analysis, reviews, and implementation plans are kept for context;
they are not current API documentation. When documentation conflicts with the
code, verify the code and update the relevant living document.

## License

[CC BY-NC-SA 4.0](LICENSE). Non-commercial use only.

---

## 中文简介

MBForge 是面向分子科学与药物发现的本地 AI 工作台：将 PDF 文献提取为分子、活性数据和可检索知识库，并提供证据复核、分子检索与知识库笔记。当前为研究基线，自动识别结果需要人工核验。

安装与启动命令见上文；开发约束、架构、任务和历史文档见[文档索引](docs/README.md)。
