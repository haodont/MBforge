# MBForge

MBForge is a local AI workbench for turning molecular-science PDFs into a
searchable knowledge base. It extracts molecules and activities, keeps source
artifacts for review, and exposes search workflows through a React UI and
FastAPI backend.

## Current scope

- PDF pipeline: Extract → Join → Markdown → Patent. Extract is the single producer: one render drives the local layout/text/table producer and a second drives the molecule pass (MolDet + MolParser), and both feed one raw branch artifact. Join validates it into SQL `SourceEvidence`; Patent reads those rows, publishes one facts artifact, and performs deterministic document-local associations. Link has been removed from the active path; Persist remains unregistered for a later redesign.
- Molecule detection and recognition with MolDetv2-YOLO26, MolParser-Mobile
  (E-SMILES), RDKit, and MoleCode; page layout and text recognition run entirely
  locally (Hiro-Layout + RapidOCR) — no cloud OCR service is called.
- Local storage per library: SQLite business data and document artifacts; no
  third-party knowledge-index runtime is required.
- Knowledge-base search, molecule search, evidence review, and activity data.
- Workspace document import accepts multiple PDFs at once, rejects duplicate
  filenames, and reports partial failures; documents can be selected, queued, or
  deleted in bulk.

The project is a research baseline. Recognition and extracted data require
human review; model loading can take several seconds on the first request.
Mobile, multi-user collaboration, and rich export formats are currently out of
scope. Track active work in [TODO/INDEX.md](TODO/INDEX.md).

## Requirements

Python 3.12, [uv](https://github.com/astral-sh/uv), Node.js 24.14.1+ and npm.
GPU is optional, but required by local MolDet/MolParser inference. Business
settings are stored in `~/MBForge/settings.json`; the default library root is
`~/MBForge`.

Dependencies are split into a core install plus the `local-models` and `gpu`
extras (heavy AI/GPU inference). `uv sync` installs the full stack through the
`dev` group. For a constrained, core-only install use `uv sync --no-dev`; add
inference support with `pip install "mbforge[gpu,local-models]"`. Startup logs
a capability summary of which optional modules and CUDA are available.

## Model weights

Heavy models are downloaded at runtime by `ResourceManager` (ModelScope) into
`~/MBForge/models/`; none are stored in git except the one exception below.

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
  `cp assets/models/moldetv2_structure_ft.pt ~/MBForge/models/MolDetv2/moldet_v2_yolo26n_960_doc.pt`
  (or point `DEFAULT_SUBPATH` in `src/mbforge/adapters/inference/moldet_v2_ft.py`
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

A standalone `npm --prefix frontend run dev` (Vite alone) also brings up the
LLM agent automatically and serves its `/v1/chat` API through Vite's
same-origin `/agent-api` proxy, so the Agent page works without running
`dev:all`. When an agent is already listening on `18800` (for example under
`dev:all`), the frontend keeps talking to it directly.

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

The Extract branch writes one raw branch file under the document staging
directory (`.staging/extract.json`), carrying page text, typed layout regions,
recognized table content and the molecule pass' SMILES/E-SMILES; the Join
validates it and indexes the joined `SourceEvidence` rows in SQLite, which is
the only runtime evidence store. After Join, text spans in the readable
`extract.json` branch also carry their final `evidence_id`.

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
field. The canonical layout is:

```text
{library_root}/
├── .mbforge/library.db       # unified SQLite database
├── .mbforge/wiki/            # native Wiki artifacts
├── storage/{doc_id}/         # source, pages, crops, reports
└── notes/                    # user notes
```

Use `LibraryLayout` for library paths and `ArtifactResolver` for document
artifacts. Do not construct these paths inline.

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

MBForge 是面向分子科学与药物发现的本地 AI 工作台：将 PDF 文献提取为分子、活性数据和可检索知识库，并提供证据复核、分子检索和知识库查询。当前为研究基线，自动识别结果需要人工核验。

安装与启动命令见上文；开发约束、架构、任务和历史文档见[文档索引](docs/README.md)。
