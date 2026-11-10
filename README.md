# MBForge

MBForge is a local AI workbench for turning molecular-science PDFs into a
searchable knowledge base. It extracts molecules and activities, keeps source
artifacts for review, and exposes search workflows through a React UI and
FastAPI backend.

## Current scope

- The default UI is a research conversation with a side-by-side resource and
  evidence workspace. Documents can be selected as chat references, source
  citations open the existing PDF viewer, and background tasks use the existing
  queue. Visible research history is stored in per-library SQL, with durable Pi
  conversation files and an automatic import of legacy browser history. Explicit
  analysis actions create idempotent task references; result cards retain their
  original revision while showing the current published facts. The evidence
  workspace includes assay-aware measurements, source navigation and conflict
  decisions. Evidence-tool coverage is a read record, not semantic verification.
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
  auto-enqueue is disabled), settling at 已提取, 就绪 or 失败; documents can be
  selected, queued, or deleted in bulk.

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

# Development mode (backend reload + Vite HMR + frontend Pi Agent)
npm --prefix frontend run dev:all
```

Open <http://127.0.0.1:5173>. `dev:all` starts the backend with source reload,
starts Vite with HMR, waits in one terminal, and stops the paired process if
either service exits with an error. Its default backend and frontend ports are
`18792`, `5173`, and `18800`; all fail clearly if already in use. The LLM
runtime is the separate Node process under `agent/`; Python only exposes the
FastAPI tool endpoints it needs.

The sidecar uses Pi `@earendil-works/pi-coding-agent@1.5.0` (the previous
`@mariozechner` packages are deprecated). Research chat searches extracted SQL
evidence across documents with `search_library`, then reads source evidence and
accepted activities. When local information is insufficient, optional Tavily
tools search the public web and fetch relevant pages through the official
[`@tavily/pi-extension@0.1.2`](https://www.npmjs.com/package/@tavily/pi-extension).
Enable **Settings → AI models → LLM → Web research**, enter a Tavily API key,
and save; it applies to the next message. Web research is disabled by default.
Search keywords and selected URLs are sent to Tavily and consume its credits.
Each user turn allows up to four searches and three fetch calls (three URLs per
fetch). Patent extraction continues to use only its document's evidence.

`npm --prefix frontend run dev` starts Vite only. Run `dev:all` for a complete
local stack, or start the backend and Node agent separately; Vite does not own
or stop the agent process. Chat requests use the same-origin `/agent-api` proxy
when Vite is running.

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
edit mode. Patent extraction is asynchronous: `submit_extraction` returns a
`run_id`, then poll `get_run` and read `get_patent_result`.

### Agent CLI

`npm --prefix agent run cli` opens pi's normal interactive CLI with the MBForge
capability tools registered. Use `/login` to choose a provider (OAuth or API
key), `/model` to pick a model, `/mbforge` to inspect the active capability
mode, and then ask in natural language. Read-only is the default; set
`MBFORGE_AGENT_MODE=edit` (PowerShell: `$env:MBFORGE_AGENT_MODE='edit'`) before
launching to expose mutating capabilities. The FastAPI backend must be running
on port 18792.

The CLI is a pi extension (`agent/src/extension.ts`), not a custom REPL:
built-in coding tools are disabled with `--no-builtin-tools`, while pi's
provider login, model switching, sessions, and themes remain available. The
web research workspace keeps using the Node sidecar under `agent/`; the CLI and
the sidecar share the same `settings.json` and capability API.

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
