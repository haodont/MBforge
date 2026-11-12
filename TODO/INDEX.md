# MBForge TODO index

This directory records active architecture and implementation plans.

## Code drafts get a typed home and static checks (2026-11-12)

The model often writes Python helper functions as fenced blocks, like drafting
`SourceEvidence.create(...)` instead of editing a file. Executing those blocks
would bypass capability validation and evidence provenance, so the answer is a
draft artifact plus static checks, not an executor.

- `agent/src/draft.ts` registers the local `draft` tool with `check`, `save`,
  `list`, and `read`. `check` returns diagnostics without touching disk;
  `save` writes `{agent_home}/DRAFTS/<id>.<ext>` plus an index and returns the
  path, target file, line count, and checks.
- Checkers are language-specific: Python uses an AST parse plus Ruff; TypeScript
  and JavaScript use the TypeScript parser's syntax diagnostics (no type check);
  JSON uses `JSON.parse`. SQL, YAML, TOML, Markdown and text are saved but
  explicitly reported `unavailable`, never silently accepted.
- No checker executes the supplied code. Python's AST parse and Ruff, and the
  TypeScript `transpileModule` parser, are static. The no-execution behavior is
  tested with a draft that writes a marker file; the marker stays absent.
- The tool is active in both modes, is listed in the agent's local-tool context,
  and is skipped from goal artifacts. The prompt now tells the model to call
  `draft action="check"` before `edit`/`write`, or `action="save"` when the user
  should review a file, and never to paste a fenced block as a substitute.
- Tool rows summarize the verdict (`syntax ✓ · ruff ✗`), show diagnostics only
  when expanded, and keep the code out of the call row.

Verified with `npm --prefix agent run check` and the full `npm --prefix agent
test` suite (62 passed, including `draft.test.ts` for Python/TS/JS/JSON checks,
unavailable languages, no execution, and save/list/read).

## Goal review streams events and only fails on silence (2026-11-12)

Automatic goal review and `review_task` first failed on Windows with
`spawn ENAMETOOLONG`: `spawnReviewer` placed the entire goal transcript — the
goal definition, a 40-row tool index, and the conversation — into the final CLI
argument. Windows caps a process command line at roughly 32k UTF-16 characters,
so `CreateProcess` rejected the spawn before pi started. The next run then hit
the old three-minute wall-clock limit while the reviewer was still working.

- `buildReviewerArgs` returns only flags, the system prompt, and the inherited
  model. The prompt travels on stdin; `pi --mode json` reads piped stdin.
- Reviews use JSON event mode, so the parent sees `message_update`,
  `tool_execution_*`, and `message_end` events while the child runs. The final
  assistant `message_end` text is the report; error, aborted, length, and
  tool-use-without-answer messages fail explicitly.
- `spawnPiText` no longer requires a wall-clock deadline. It supports
  `idleTimeoutMs`, which resets on stdout or stderr activity; review sets five
  minutes of total silence. A slow but progressing review is no longer killed.
  `research` keeps its absolute timeout because it is a foreground call.
- The duplicated `projectCwd`/`piInvocation` definitions in `review.ts` are
  removed in favor of `agent/src/piChild.ts`.
- Failure notices show both the review id (`review-…`) and goal id (`goal-…`),
  and `/goal-reviews retry` accepts either one; using the goal id shown in the
  notice no longer dead-ends with "No failed review".
- A review that finishes while a foreground goal is active is held in
  `ReviewNoticeQueue` instead of being injected into the session. The queue is
  released by `agent_settled`, `session_start`, or `session_tree` only after
  `activeGoal` is empty; `/goal-reviews` reports how many notices are held.
  Held failures also defer their warning toast. Retrying a failed review drops
  its stale held notice before the new attempt. Held notices live only in the
  session; a CLI exit before the foreground goal ends drops them.

Verified with `npm --prefix agent run check` and `npm --prefix agent test`
(70 passed; review tests cover 40k prompts staying off argv, extraction of
the final assistant message from JSON events, retry by goal id, and holding
notices until the foreground goal ends).

## The active goal is pinned below the editor (2026-11-12)

A `goal` begin was only visible as a tool row that scrolled away. The active
goal now has a persistent checklist at the bottom of the screen
(pi's `setWidget(..., {placement: "belowEditor"})`):

- `agent/src/goalWidget.ts` reads `goalStateFromBranch` and renders
  `⬡ GOAL “<title>”` with the goal id, then the objective, then todo-style
  `Requirements` and `Acceptance` checkboxes and compact `Constraints` /
  `Not in scope` rows. Requirements show all five; acceptance is capped at five,
  constraints/non-goals at three, each with a `… N more` row.
- The branch scan is cached by branch length + goal id, so an update or a
  resumed session shows the latest definition and a frame does not rescan
  hundreds of entries.
- `agent/src/extension.ts` installs/removes the widget from `refreshBrand`,
  `session_start`, `session_tree`, `agent_settled` (aborted goal), and the goal
  tool's `setActiveGoal` callback. `goal` action `update` now calls
  `setActiveGoal(id)` after appending the update so the checklist refreshes
  without changing the active id.
- A completed or cancelled goal removes the widget instead of leaving a stale
  line. If the session has no active goal at startup, the widget is cleared.

## TPS is shown in the footer (2026-11-12)

- Final response speed uses `AssistantMessage.usage.output /
  AssistantMessage.durationMs`, both supplied by pi-ai, so it is exact for the
  completed message. `agent/src/footer.ts` also derives it from the latest
  assistant entry when a session is resumed.
- While streaming, `message_update` deltas accumulate and are approximated as
  `chars / 4` over elapsed time; the footer marks this estimate with `~`.
  Live TPS is accent-coloured, the final value is muted.
- Display: full footer `23.4 tps` / `~18.2 tps`, compact footer `23 tps`.
  `session_start` and `session_tree` reset the live estimate; `agent_settled`
  clears the live flag without dropping the final value.

Verified with `npm --prefix agent run check` and the full `npm --prefix agent
test` suite (58 passed, including `goalWidget.test.ts` and `footer.test.ts`).

## Paper-and-ink palette replaces the indigo-on-blue scheme (2026-11-12)

The frontend tokens and the two pi themes were cool indigo/violet on blue-gray
surfaces. They were coherent but generic, and some foreground values sat below
4.5:1 on their tinted backgrounds. The palette is now derived from Flexoki
(MIT, Steph Ango), with Radix's 12-step use-case discipline and Catppuccin's
"never colour alone" rule:

- **Neutrals** use Flexoki's warm paper/ink ramp: light `paper #FFFCF0` →
  `base-50 #F2F0E5` → `base-100 #E6E4D9` → `base-150 #DAD8CE`, ink text
  `#100F0F`; dark `black #100F0F` → `base-950 #1C1B1A` → `base-900 #282726`
  → `base-850 #343331`, text `#CECDC3`. The old cool blue-gray cast is gone.
- **One primary accent**: Flexoki blue-600 `#205EA6` in light, blue-300
  `#66A0C8` in dark. Dark solid buttons pair it with `--text-on-accent
  #100F0F`; light buttons use paper text. Cyan is reserved for links, active
  states and the `text` overlay; green success, orange warning, red error,
  purple/magenta for code and thinking.
- **Frontend** `styles/theme.css` and `styles/tokens.ts` carry the same values;
  `MoleculeOverlay`, `OcrOverlay` and the brand SVG now use tokens or the
  matching accent values instead of their own blue/green/amber literals.
- **CLI** `agent/themes/mbforge-{dark,light}.json` mirror the same roles:
  dark bg `#100F0F`, text `#CECDC3`, accent `#66A0C8`, border `#343331`;
  light bg `#FFFCF0`, text `#100F0F`, accent `#205EA6`, border `#CECDC3`.
  Code/thinking colours use the extended Flexoki ramp, not ad-hoc hexes.
- Measured WCAG contrast (normal text target 4.5:1): light text/paper 18.6,
  secondary 7.1, muted 5.0, accent 6.4, warning 5.7, danger 6.2; dark
  text/ink 12.0, secondary 9.3, muted 5.2, accent 6.8, success 6.1, info 6.7.
  Light success/info use the 700 steps for small text (`#536907`, `#1C6C66`)
  so status text stays above the target on paper and on tinted chips.

References: Flexoki `https://stephango.com/flexoki`, Radix Colors
`understanding-the-scale`, Catppuccin style guide, and the WCAG contrast
formula. Verified with `npm --prefix frontend run build`,
`npm --prefix agent run check`, and `npm --prefix agent test`.

## One question dialog for ask, dev mode, and improvements (2026-11-12)

The agent could only ask through two bespoke paths: `request_dev_mode` called
`ctx.ui.confirm`, and `suggest_improvement` passed a `confirm` callback into the
store layer. There was no way to ask a normal multiple-choice question, and the
two approvals did not share a presentation.

- `agent/src/ask.ts` adds the local `ask` tool with four kinds: `confirm`,
  `select`, `multi_select`, and `text`. The model supplies a title, optional
  context (`message`), and options with a stable `value` plus short `label`/
  `description`; the answer object is `{kind,title,answer,answer_label,
  confirmed,selected,cancelled}`.
- The TUI presentation is one card: `⬡ MBForge · <kind>` header, bold question,
  muted context, one option per row with `❯` (or `[x]`), and a bottom key-hint
  bar. It is width-adaptive (bordered up to 78 columns), windows more than eight
  options with `… N above/below`, supports `j/k` and arrow navigation, space to
  toggle multi-select, number-free selection, and Esc/Ctrl+C cancel. Text uses
  the same card with a focused input line.
- `askUser` uses `ctx.ui.custom` in the TUI, and falls back to
  `ctx.ui.confirm`/`select`/`input` in RPC or headless sessions so the same
  contract still works; multi-select is explicitly TUI-only.
- `request_dev_mode` and `suggest_improvement` now pass their question through
  `askUser` with their own labels (`Enable dev mode` / `Stay in auto`,
  `Apply improvement` / `Decline`). Their results still mean the same thing:
  `confirmed` false is a decline, `cancelled` is a dismissed dialog, and the
  improvement store records the decision exactly as before.
- `ask` is active in both session modes and is skipped from goal artifacts; the
  tool-result row summarizes the chosen label or `cancelled` instead of dumping
  JSON. `APPEND_SYSTEM.md` tells the model to ask one question at a time, to
  prefer 2–5 options, and not to duplicate the dedicated approvals.

Verified with `npm --prefix agent run check` and the full `npm --prefix agent
test` suite (including the answer-mapping/fallback tests in `ask.test.ts`); the
dialog variants (select, confirm, multi-select, text, cancel) were rendered at
80 and 48 columns with a captured `ctx.ui.custom` factory.

## CLI chrome follows the agent-TUI grammar (2026-11-11)

The pi TUI worked but looked loose: a five-line wordmark, a one-token status
line, raw `tool_name {json}` rows, and pi's purple `[mbforge-goal-review]` box.
The chrome now uses the conventions the agent CLIs converged on: a bordered
welcome only, a borderless transcript, `✓`/`✗` status glyphs, a `└` result
connector, `·`-separated metadata, bold/default/muted tiers, and a statusline
whose right column is reserved for model and usage.

- `agent/src/brand.ts`: rounded startup banner (max 78 columns) with identity
  left and backend health right; below 46 columns it stacks unframed. An
  offline state adds one remedy row (`backend_control` or `/mbforge reload`).
  The six-frame, one-cell, 100 ms molecule pulse replaces the four-frame glyph.
  The banner is the only framed surface.
- `agent/src/footer.ts`: replaces pi's built-in footer with two dense rows —
  brand, mode, capability count, repo-tool count and backend health, with the
  model right-aligned; then path, branch and session name on the left with token
  totals and context usage on the right. Below 80 columns the model and
  cache/cost drop, the host degrades to `online`, and the path clips before the
  usage numbers. Usage totals are cached by leaf id, entry count and model.
- `agent/src/toolRender.ts`: read capability calls use `⬡`, mutating calls `⬢`
  in warning colour; results hang under `  └ ` with `✓`/`✗`, a `·` duration and
  `more at offset N` pointer; expanded items indent six columns. Running calls
  show a whole-second elapsed badge instead of a bare ellipsis, errors wrap to
  three lines so the validation tail survives, and built-in repository tools
  (`read`, `bash`, `edit`, `write`, `grep`, `find`, `ls`) keep pi's result
  renderers but use the same one-line call grammar. The `suggest_improvement`
  rows use the same grammar, and a non-executable approval puts
  `dev mode required` on its own warning line instead of letting the head row
  clip it.
- `agent/src/footer.ts`: a `get_worker_status` result caches
  `queue active/backlog` for the status line (dropped when the backend goes
  offline).
- `agent/src/messages.ts`: `mbforge-goal-review` renders as a card (goal id,
  outcome, wrapped summary, counts, expandable suggestions and warnings), and
  `mbforge.run` completion notices rebuild their header from `details.runs`
  (run id, status, document) instead of showing the generic custom-message box.
- `agent/src/uiText.ts` is the single place where rows are clipped, styled and
  right-aligned by visible columns. `agent/src/extension.ts` installs the
  header, footer and terminal title, registers both message renderers, and makes
  the working row name the tool that is currently running.

Verified with `npm --prefix agent run check`, `npm --prefix agent test` (45
passed), a live CLI launch at 100 columns, and harness renders at 100/80/60/40/
32 columns plus offline and dev states. Design references: clig.dev, GitHub
TUIKit `docs/foundations.md`, the `tui-patterns` Claude Code and design-language
analyses, and Jens Römer's TUI design notes.

## The agent drives the queue, so the queue reports to the agent (2026-11-11)

With the pi session as the scheduler, the failure modes moved from the UI to
the session: a failed run told the model to "inspect the failed stage" while
`get_run` omitted the stage error; a run paused by the model gate looked
identical to a run that had just been queued; and a resumed session had no way
to find a run whose completion notice died with the previous CLI.

- `get_run` nodes now carry `updated_at` and the truncated `error`.
- New read capability `list_runs` groups queue rows by run, newest first, and
  defaults to runs that have not reached a terminal outcome, so a new or
  resumed session can discover in-flight work. `status=all` adds history.
- New read capability `get_worker_status` returns worker online/offline, lock
  state, active/backlog/total counts and the model gate reason. It is the
  agent-facing counterpart of `GET /api/v1/pipeline/worker/status` without the
  process-registry and orphan detail the agent cannot act on.
- `ensure_queue_worker` now sets a per-root `asyncio.Event`, and `_drain_loop`
  waits on it instead of sleeping out `_CLAIM_POLL_S`, so an enqueue starts the
  first stage immediately. Its cleanup uses
  `asyncio.gather(waiter, return_exceptions=True)`: suppressing the waiter's
  `CancelledError` also swallowed `asyncio.run`'s shutdown cancellation and
  hung the worker test.
- The CLI completion message includes each failed stage's error, so the model
  can act from the wake message instead of calling `get_run` first.

## The capability surface is consolidated into fewer tools (2026-11-11)

24 capabilities asked the model to choose between near-duplicates. Merged, in
pairs that share a noun and a mutability class:

| now | absorbed | why |
| --- | --- | --- |
| `document_read(part=info\|markdown)` | `get_document`, `get_document_markdown` | both take only `doc_id` |
| `runs(action=get\|list)` | `get_run`, `list_runs` | one run vs the run list; `get` requires `run_id`, so a missing id is a schema error |
| `run_control(action=cancel\|retry)` | `cancel_run`, `retry_run` | identical `{run_id}` payload, one queue-row action |
| `inspect_visual(action=page_text)` | `ocr_page_region` | the text branch of the same "look at this page" tool |
| `memory(action=ephemeral)` | `memory_ephemeral` | same store; the inspector took no parameters |

Capabilities 24 → 20, CLI-local tools 7 → 6. Nothing was merged across mutability: `Capability.mutating` is static
and `registry.invoke` rejects mutating calls outside edit mode, so a read/write
union would either block reads in auto mode or need per-action gating.

Deliberately not merged: `list_evidence` + `search_evidence` (different required
fields; optional-parameter unions invite calls that supply neither),
`list_review_queue` + `propose_review` (read vs write), the doc-scoped data
views (`get_patent_result`, `query_activities`, `verify_structures` — no shared
fields beyond `doc_id`), and `resolve_document` (the discovery entry point).

Agent-side follow-ups in the same change: the run watcher polls `runs` with
`action=get`, `DOC_LINK_TOOLS` keys on `document_read`, the goal artifact skip
list no longer names `memory_ephemeral`, and the prompt text in
`APPEND_SYSTEM.md` names the new tools. Verified on a fresh backend instance on
port 18799: the manifest lists 20 capabilities, none of the old names, and
`runs(action=list)` answers over HTTP; `tests/unit` 435 passed, agent suite 42
passed.

## The agent can start, stop, and restart the backend (2026-11-11)

The launcher starts the FastAPI backend before pi and stops it on exit, but
`agent/.pi-agent/MEMORY.md` records the consequence: without `--reload` a Python
change stays invisible until someone restarts the process by hand. The agent now
has `backend_control` (`agent/src/backendTool.ts`) with `action=start|stop|restart`.

Ownership is the design problem: pi runs in a child process of the launcher, so
the extension never sees the launcher's `ChildProcess`. Both sides therefore use
`agent/src/backendControl.ts` (moved out of `scripts/backend.mjs`, which is
deleted), and a start records `{pid, host, port, baseUrl, log, startedAt}` in
`{agent_home}/backend.json`. `stop` kills only that pid's tree; with no record it
refuses and leaves the listener running, which is what protects a backend
started by `npm --prefix frontend run dev:all`. A stale record (nothing answers)
is discarded, a record for another address is discarded rather than applied, and
a spawn whose child exited before the probe turned ready is reported as a failure
instead of recording a pid that never served.

Verified against the real app: start on port 18799 took 9.5 s to `ready`, stop
took 0.25 s to `offline` and removed the record; a stub listener on another port
keeps serving after `stop`/`restart` refuse it. The launcher and the tool each
stop what they started (launcher: its child; tool: its child on process exit, and
the recorded pid otherwise).

## Capability images render inline in the CLI on Windows Terminal (2026-11-11)

`inspect_visual` (`page_image`, `molecule_image`) already attached its PNG to the
model as image content, but the CLI only ever showed pi's placeholder
`[Image: [image/png] 1190x1684]`: pi-tui 1.5 speaks Kitty and iTerm2 only and
maps `WT_SESSION` to `images: null`. omp renders the same images in the same
terminal because it bundles a fork (`@oh-my-pi/pi-tui`) with a sixel encoder and
a runtime `CSI ? 2 ; 1 ; 0 S` probe; Windows Terminal 1.22+ answers it.

Decision: encode sixel in our own renderer instead of taking the fork.
`agent/src/terminalImage.ts` decodes the PNG (all five row filters, colour types
0/2/3/4/6, alpha composited over white), box-downscales into the 72x24 cell box,
median-cut quantises to 256 colours and emits one DECSIXEL sequence.
`toolRender.ts` uses it when `sixelSupported()` accepts the terminal and falls
back to pi's `Image` otherwise, so Kitty/iTerm2 users see no change.

Two pi-tui constraints drive the output shape, both verified against the
installed package rather than assumed:
- `visibleWidth` strips CSI/OSC/APC but not DCS, so a raw sixel line measures
  thousands of columns and `tui-alt-screen` slices it to the terminal width.
  Every image line therefore starts with a no-op Kitty APC
  (`\x1b_Gq=2\x1b\\`), which `isImageLine` matches; image lines are exempt from
  slicing, search highlight and selection repaint. `terminalImage.test.ts`
  asserts this against pi's own `isImageLine`/`visibleWidth`.
- a sixel image moves the cursor by its own height while pi counts rows from the
  component's lines, so the block writes `rows - 1` blank lines, moves the cursor
  back up and draws over them.

Measured on `CN119504738A` p122 (1190x1684 render): 34x24 cells, 30 KB of escape
bytes, 76 ms to encode, cached per image hash and cell box. A region crop (the
usual `page_image` call) is proportionally sharper. Not done: echoing the
*input* image of `recognize_structure` (the model authored it) and any overlay
for `page_molecules`, which returns molecule data and no image.

## Table masking runs before cell OCR, unconditionally (2026-11-11)

Evidence row `b1603718dc46dd6e241fca4082e01530` (doc `31fc2846…`, p122 of
`CN119504738A`) published a table whose 结构 column held drawing glyphs —
`CF3 N NH HN N NH O CF3 N` — although the mask → cell-OCR → label-backfill path
existed. It was behind `layout.mask_table_molecules` (default **off**), so the
Extract branch never entered it and cell OCR read every atom label and bond
glyph into the evidence text.

Decision: masking is part of table recognition, not an option. MolDet now always
runs on the layout render (before it ran only for the R3/R4 merge, so a page
read with `cross_model=False` had no boxes to mask); `cross_model` gates only
those merge rules. A table crop hands every molecule box it holds to the cell
recognizer, which blanks it and writes `[MOL:n]` into that cell, numbered in
table order, and `mint_evidence` folds in the label the molecule pass read
(`artifacts/table_molecule_cells.py`) — the one place the two producers meet. A
drawing whose own label was never read keeps its token instead of an invented
number. The config field, the flag and `scripts/table_mask_ab.py` are gone; the
page-read surface (`page_text`) masks too.

Masking alone did not make that table readable, and the same evidence row shows
the second defect: **SLANet's per-cell boxes are not cell geometry.** Its box
for each cell hugs the text line it saw, so on a row made tall by a drawing the
box is one line high (命名 cell 61 px against a ~240 px row) and can drift into
the neighbouring row (实施例 cell predicted 625–675 while `实施例 42` prints at
561–585). Cell OCR read inside those boxes, so 实施例编号 was empty and only the
last row's 526.2/504.2/499.2 were lost (490.1 happened to fall inside its box).
`table_slanet._ruled_cells` now recovers the cell geometry from the rules the
table itself draws: when the detected rule count matches the structure model's
rows × columns, the drawn grid is used for cell OCR (3 px inset, so the rule is
not read as text); a borderless or merged-cell table keeps the model's boxes.

Measured on that page (no library write, before → after): 实施例编号 empty → 40,
41, 42, 43; LC-MS only 490.1 → 526.2, 504.2, 499.2, 490.1; 命名 one line → the
whole 3-line name; 结构 `CF3 N NH HN N NH O CF3 N` → `[MOL:0]`…`[MOL:3]`. The
page prints no compound number beside those drawings (the row's designation is
the 实施例 number in column 1), so the four tokens stay — the documented case.
The recorded mask A/B (265 → 3, 15 → 3, 12 → 0 chemistry-looking cells) is why
the mask is now mandatory. Re-ingesting `CN119504738A` replaces the stale
evidence row; no migration is needed because the stage mints it.

## Agent links into the workbench (2026-11-11)

The CLI answers in the terminal, but a citation is only checkable where the
page is drawn and a review item is only decidable in the review center. The
agent therefore never writes a URL: it writes an opaque marker and the CLI
renders a markdown link to the workbench route, which pi draws as a clickable
OSC 8 hyperlink. `agent/src/uiLinks.ts` owns the routes and encoding;
`[[ui:review]]`, `[[ui:review:<kind>:<item_id>]]`,
`[[ui:doc:<doc_id>[:<page>]]]`, `[[ui:queue]]`, `[[ui:molecules]]` and
`[[ui:workspace]]` are the whole vocabulary. ``[[ui:doc:…]]`` requires the full
64-hex doc id, because the document view resolves the stored PDF from it; an
unknown surface, an unknown review kind, a missing item id or page 0 stays
literal instead of linking a route that would land on a different item.

- The review item route already existed (`/review?kind=&id=` seeds the filter
  and selection) but the agent had no way to learn an item's identity. The new
  read capability `list_review_queue`
  (`service/capabilities/read_review.py`) publishes the unified queue: pending
  by default, with `kind`, `item_id`, document/short id, page, bbox, name,
  SMILES, confidence, reasons and per-kind counts. The kind vocabulary is
  `ReviewKind` in `service/dto/review.py`, which now also declares
  `designation_unbound` — the queue already produced that kind and the review
  center already listed it, so the DTO was the stale copy.
- Evidence citations keep the separate `[[ev:<evidence_id>]]` marker: the
  citation cache knows the doc/page/bbox and links `/open?doc=&page=&evidence=`,
  while `[[ui:doc:…]]` opens the document without an evidence highlight.
- Frontend base URL: `MBFORGE_FRONTEND_URL` wins (single-port deployments that
  serve the SPA from the API); otherwise `MBFORGE_DEV_HOST` /
  `MBFORGE_DEV_FRONTEND_PORT` follow the same variables `dev:all` binds Vite to.
- Prompt wiring: `APPEND_SYSTEM.md` states when to offer a link and forbids
  model-authored URLs; `uiGuidelines` adds per-tool markers for
  `list_review_queue`, document reads, run producers and molecule search.
- Tests: `agent/src/uiLinks.test.ts` protects marker → route rendering and the
  literal fallbacks; `test_capability_http.py` protects the queue row identity,
  counts and unknown-kind rejection.

Open: the review center has no route for "all items of one document"; a link
that filters by `doc_id` would need a `doc` query parameter on `/review`.

## Review items show the structure they ask about (2026-11-11)

A `designation_unbound` item asked a human to pick a structure but showed only
`candidate.name || candidate.mol_id`: the item's own `crop_relpath`, `bbox` and
`smiles` are null because they describe the *reading*, not a candidate, so
`ReviewEvidenceComparison` rendered “暂无来源结构图 / 暂无 SMILES” and there was
nothing to confirm against.

- The candidate payload now carries `page`, `bbox` and `crop_relpath`, taken
  from the candidate's first detection. `page` is 1-based to match the item's
  own `page`; `bbox` is PDF points, bottom-left origin; `crop_relpath` uses the
  same library-relative form as the item-level field.
- The review center renders one `ReviewCandidateCard` per candidate: the printed
  crop beside the RDKit rendering of the same SMILES, the radio that selects it,
  and an “打开原文” that opens that candidate's own page and bbox. The item-level
  comparison is hidden for this kind because it is empty by construction.
- Re-running the Patent stage is what refreshes the items: the item id is
  `stable_id("unbound", doc_id, measurement_id)`, so the publish upserts instead
  of duplicating, and `insert_review_item`'s conflict update does not touch
  `status` — a human decision survives the re-run.

## Dev-mode HTTP bypass is a trust boundary, not a sandbox (2026-11-11)

Only `/api/v1/capabilities/*` derives a mode from the capability token
(`api/http/capabilities.py::_context`). The frontend routes are unauthenticated:
review decisions, document delete, library configure, settings and resource
installs all accept a plain `POST`, and any local process can call them. That is
not an oversight to patch with a token on those routes — the Vite UI runs as the
same OS user and a browser cannot hold a secret the agent cannot read, so a
second credential would be readable by the same process that is supposed to lack
it. `foundation/capability_token.py` already says as much: the token is a local
intent guard, not a security boundary.

What is enforceable is the tool surface:

- `auto` registers only capability tools plus local-state tools (`memory`,
  `goal`, `review_task`, `suggest_improvement`, `request_dev_mode`). The
  reviewer subagent is spawned with `--tools read,grep,find,ls`, so no
  registered path reaches HTTP or SQLite.
- `dev` adds `read`, `bash`, `edit`, `write`, `grep`, `find`, `ls`. Those can
  call every route listed above and open `library.db` directly, bypassing
  capability validation and the token. Shell pattern matching is not a fix:
  PowerShell, `node -e`, `python -c` or a small script reach the same data, and
  the model may call none of them.

Decision: the capability contract is the only *sanctioned* path, and the prompt
states it (`dev` built-in tools never call `/api/v1` or the database); no
command filter is added, because it would be theater. Real prevention needs OS
isolation — the CLI as a separate account/container with the repository mounted
and no route to the backend or library. If visibility is wanted instead, log
mutating requests that are not capability invocations; that detects, it does not
prevent.

The boundary also assumes the default `127.0.0.1` bind: setting
`MBFORGE_HOST=0.0.0.0` publishes those unauthenticated mutations to the
network, and nothing currently warns about that.

## One-call agent import and run-completion wake (2026-11-10)

`import_pdf` is now the agent's one import call: it registers the file and,
unless `ingest.auto_enqueue_on_import` is off, enqueues Extract -> Markdown and
returns `run_id`. The browser upload route and the capability share
`ingest.auto_enqueue_on_import`, so both surfaces behave alike; a disabled or
failing enqueue still leaves the stored document `pending` instead of failing
the import.

The pi extension watches every run id a capability result carries
(`submit_extraction`, `reingest_document`, `submit_patent_analysis` and
`import_pdf`) by polling the read-only `runs` capability, and reports each
run once. Delivery never uses pi's `deliverAs` queues, whose queued follow-up
messages were re-delivered when a session was resumed: a completion that
arrives while the session is busy is held in process memory and flushed as one
message at `agent_settled`, and an idle delivery uses `triggerTurn` alone.
Held completions die with the process, so a resumed session cannot wake for
work it already missed. Timers are unref'd and stopped on `session_shutdown`;
a closed CLI has no watcher.

## Naming a drawing from the page's own text (2026-11-10)

The molecule pass reads a compound number off the crop around a drawing (a
15%-expanded window). That window misses a number printed in the margin, and a
US application prints exactly that: `US20210128561A1` lists its compounds as
`[drawing][A-5]`, the number in the gutter beside the drawing. The layout
producer has already read that number — it is a text region of its own, with a
position — so the number that names a drawing can come from the page's text.

`service/pipeline/detection/text_label_assignment.py` does that, and the
Extract stage runs it before the evidence is minted
(`_name_drawings_from_page_text`):

- **Only a bare token is a read.** A phrase that merely mentions a compound
  (`目标化合物11的制备`) names no drawing; a token without a letter in it
  (`[0331]`, `1`) is a paragraph marker or a step, not a compound. So the CN
  corpus, whose numbers are printed inside phrases, is untouched.
- **The page is matched as a whole.** The gutter is narrow: on p7 a number sits
  54 pt from its own drawing and 58 pt from the next column's, so number by
  number the wrong column wins. Matching one number to one drawing and one
  drawing to one number keeps every number with the drawing of its own column.
- **A number keeps its own column.** The drawings of a list are printed in
  columns and the numbers in the gutter *after* their own column's drawings,
  so the candidate drawings of a number are the ones of that column. Without
  it a number can reach across a narrow gutter to the next column's drawing
  (p63: 33 pt away against its own column's 102 pt).

Measured on `US20210128561A1` (67 pages): the compound list prints **88
compounds twice** (pp.6–19 and pp.54–67), **290 printed numbers**, and the
assignment names **285 of them** — the five it cannot settle are reported, not
guessed. The document's activity table now reads **47 of 64** readings with a
structure, against **0** before. `CN119504738A` is unchanged: 14 readings, 7
attributed, the same issue counts.

Still open on that document: a molecule row keeps the first name written for its
SMILES, so a drawing the crop pass mis-read steals the name of the compound
that shares its structure (10 readings); and the first four compounds of the
list were recognized as fragments of their drawings, so no candidate survives
for them at all. Both are recognition questions, not table questions.

The last four readings (A-26, B-49 ×2, B-50) need a *human* — they are
printed more than once and the printings disagree — so they went to the review
queue as `propose_review` proposals against the measurement ids, each naming
the structure the printings agree on, with the drawing evidence ids attached.
A proposal never applies a value; it hands the decision over.

### Still open on this path

1. **The PK table.** `Cmax (ng/mL)` and `AUC0-t (h*ng/mL)` are printed on p125
   of the same document (compounds 13 and 25) and no metric family accepts
   them, so the two rows are not readings.
2. **`patent_stage.py:150` writes `review_candidates=[]`** — a vestige of the
   removed LLM-gap path. The AI proposals live in `review_items` (the review
   queue the UI reads); the artifact field is simply never filled.

### The pair path does not need an example heading

The published pair path joined a reading to the structure its *example
heading* declares (`entries._declared_structure_activity`), so a US
application — which prints the compound number in the activity table instead —
published **0 pairs** although 60 of its 64 readings own a structure. The
declaration is needed only to map an *example* reference and to check a
printed product mass; a reading that names a compound is joined by that name,
so the early "no examples, no pairs" return is gone. Measured on
`US20210128561A1`: **0 → 59 pairs** (the four disputed designations stay
unpaired), and the pairs say `verified_by_mass: false` because the document
prints no product mass for those compounds — the flag reports mass
consistency, it is not identity verification. `CN119504738A` is unchanged:
7 pairs, all seven mass-verified, 7 of 14 readings attributed.

**The molecule keeps every designation it answers to.** One structure is drawn
more than once in a patent — as a compound in the list and as an intermediate
in the scheme — so the `molecules` row must keep all the names, not the first
one written. Two changes: `molecules.labels` (the column the schema already had
and `document_label_numbers` already read) is written with every designation
the molecule's drawings carry; and the molecule's primary name is chosen by
`select_molecule_name` with a **source tier** — a designation the page's own
text printed outranks the same designation read off a crop window, whatever its
detection confidence. Without the tier, `A-2` lost to the scheme label `2`
because the scheme drawing scored higher (0.951 vs 0.943). The read surface now
reports the gap it actually sees: the four unbound US readings are
`structure_detected_unmatched` (the structure *is* drawn) instead of
`label_not_read`.

**A structure the page names stays concrete.** A compound list prints the
number beside the drawing, and the crop's OCR context on such a page is the
document's own prose — often the generic formula's R-group list ("R1 means
-H, -CH3 …"). The context signals (`context_numbered_r_group`,
`context_optional_substitution`) read that text as Markush wording, so the
compound was classified `review_required` and dropped at persist: `A-1` and
`A-4` had no row in `molecules` at all. A designation the **page's own text**
prints (`label_source = "page_text"`, recorded per detection in
`name_candidates`) is the document's own statement about that drawing, so such a
structure is classified `complete` and the neighbouring prose is not evidence
against it. A crop-window designation (a scheme label) still triggers the
review, unchanged. Measured on `US20210128561A1`: readings that own a
structure 54 → **60 of 64**; `CN119504738A` unchanged (14 readings, 7
attributed) — its numbers are printed inside phrases, so no designation comes
from the page text and the rule cannot fire.

**A structure answers to the designation its drawings agree on.** The same
compound is printed twice, and the two printings are not always recognized the
same way, so one structure can arrive carrying two designations (the minority
one being a misreading of a neighbouring compound's drawing). The per-drawing
record (`properties.detection_designations`) lets the association count them: a
structure owns the designation most of its drawings carry, and the minority
candidate drops out of the competition instead of making the designation
ambiguous; a structure whose designations tie owns neither. Measured on
`US20210128561A1`: entries carrying a structure 36 → 42, ambiguous designations
9 → 3, readings that own a structure 47 → **54 of 64**. `CN119504738A` is
unchanged (14 readings, 7 attributed, compound 1 still unbound — its candidates
tie), which is the case the rule must not break.

## Run-completion notifications repeat (2026-11-10)

A finished run wakes the agent again and again: the same `run_id` was
delivered three times in one session (`20261110142332`, `...42523`,
`...42931`), every one of them a run that had been done for hours. The
mechanism is **not** the watcher's seeding — the watcher only watches the runs
a capability returned in this session (`agent/src/capabilities.ts:152`
`onRunEnqueued?.(runId)` → `extension.ts:191-194`), and the per-instance
`active`/`forget` sets dedupe *within* one watcher. The repeated delivery
comes from the **follow-up delivery** itself: `agent/src/runs.ts:143` sends the
finished run as `pi.sendMessage({customType: 'mbforge.run'}, {triggerTurn:
true, deliverAs: 'followUp'})`, and a queued follow-up is replayed when the
session resumes — so one finished run wakes the agent once per resume.

Two ways out: deliver the notice without the follow-up queue (`triggerTurn`
alone, so it is not replayed), or mark the run as already-notified where the
session can see it (session dir / a small state file) so a resumed session
stays quiet. Either way the notification must not wake the agent for work
that finished before it looked.

## US-style activity tables (2026-11-10)

`US20210128561A1` printed its SAR table the way a US application does, and the
pipeline read **zero** of its ~87 printed activity rows: the table was refused
as `complex_activity_table`. Four separate gaps added up:

1. **The metric was printed under a spanning title row.** The header printed
   ``β-arrestin assay (CHO β-arrestin human MrgX4`` on one line and
   ``L83S) IC50 ± [μM]a (% inhibition ± SEM)c`` on the next; the layout looked
   for the metric in the first row only. The metric is now looked up in the
   header row, in the rows under it, and in the rows above it, and the assay
   name is assembled from the spanning title (the same header cells still span
   their empty siblings, so a CN table with ``化合物编号 | IC50(nM) | | |`` keeps
   its four columns).
2. **The compound numbers came from a letter series.** ``A-1``, ``B-40``,
   ``C-67`` are compound keys of their own now (`compound_label_key`), not
   unreadable cells.
3. **The values carried three shapes.** ``11.6 ± 3.7`` is one reading with its
   error term, ``>100 (4%)`` is one censored reading, and ``>100 (40%) >100
   (45%)`` is two readings the layout merged into one cell — the last one names
   no single compound, so it is left out and reported.
4. **A cell that names no compound no longer withholds the whole table.** The
   completeness contract now means "every cell that names a compound and
   prints one value was read"; cells that name no compound and cells that hold
   two merged readings are counted and published as the issue
   `activity_cells_unattributed`. A cell that *does* name a compound but whose
   value cannot be read still discards the table, because that reading exists
   and is unknown.

Measured on `US20210128561A1` (67 pages): **0 → 64 readings**, 51 distinct
compound labels, and 51 compound entries that the Patent stage now mints from
the document's own prose (they were missing before, because nothing in the
document had been read). `CN119504738A` is unchanged: 14 readings, 7 attributed,
the same issue counts. The structures are still unbound on both documents — the
printed numbers are not attached to the drawings (see the structure verification
section below), which is a separate problem from reading the table.

## Document references in capabilities (2026-11-10)

`doc_id` is the SHA-256 of the stored bytes, so it is a 64-character hex string
nobody can hold in their head. Every document-scoped capability therefore
accepts a document *reference* and resolves it once, in the registry
(`service/capabilities/registry.py`), before the handler runs
(`service/use_cases/documents/document_refs.py`):

- the full 64-hex `doc_id`;
- a unique `doc_id` prefix of 8 hex characters or more;
- the exact file name;
- the exact title.

Matching is exact — no substring or fuzzy guessing — and an ambiguous
reference is rejected (`ValidationError` with the candidate list) instead of
picking one. A reference that matches nothing is passed through unchanged, so
the handler still reports the document as missing. `resolve_document` returns
the quotable `short_id` (first 8 hex characters) next to the full id, and the
input schemas publish the accepted forms so the agent does not have to guess.

The HTTP document endpoints are unchanged: the alias is an agent-facing
convenience, and the frontend keeps using full ids.

## Structure verification surface (2026-11-10)

The recognizer cannot be trusted by its detection score: `moldet_conf` is
MolDet's confidence that a structure was *found*, not that the SMILES is right,
and MolParser's own confidence is not exposed. Checking a structure therefore
needs signals that are independent of the model — the drawn structure, the
printed name, and the printed mass.

`verify_structures` (read-only capability) closes the automatable part of that
loop on the canonical SQL evidence and the committed Patent snapshot. It
returns one row per recognized structure: `formula`, `molar_mass`,
`exact_mass` (monoisotopic, salt-stripped parent), `main_formula`,
`structure_kind` (`concrete`/`markush`), the printed designation the structure
carries, the compound entry that owns it, and the printed MS line that
designation owns with `printed_mz`/`expected_mz`/`delta` and a verdict at the
patent's own 0.6 Da tolerance (`match` / `mismatch` / `not_comparable`). The
summary counts the coverage: structures, matches, mismatches, structures with
no printed mass, printed MS lines, and lines no structure claims.

- Service: `service/use_cases/documents/structure_verification.py`
  (`verify_structures`). Capability: `verify_structures`
  (`service/capabilities/read_structures.py`). Nothing is written; a delta is evidence for
  a human, never a correction.
- The chemistry rules are the pipeline's own, not a second copy: the mass
  helpers `exact_mass` / `largest_fragment_mol`
  (`pipeline/detection/label_recovery.py`) and the printed-mass parser
  `printed_ms_mz` / `adduct_mass_delta`
  (`pipeline/patent/rules/characterization.py`) were promoted from private to
  shared so the read surface and the Patent stage cannot disagree about one
  printed line.
- Two findings from the first run on `CN119504738A` (447 structures):
  1. **A printed mass scraped out of a structure row is not a printed mass.**
     The crop's OCR context quotes the neighbouring prose, so 17 of 47 MS
     lines in the snapshot came from molecule rows and carried another
     compound's mass. The capability excludes them and counts them
     (`printed_ms_from_structure_rows`); the Patent stage still pairs them, so
     its own `smiles_mass_mismatch` set is polluted the same way.
  2. **A Markush scaffold has no compound mass.** Its dummy atoms carry no
     weight, so a delta against a printed m/z means nothing: those rows are
     `not_comparable`, not `mismatch`.
  Measured: 4 concrete structures match their printed mass (|delta| ≤ 0.5 Da),
  2 concrete mismatches, 3 Markush rows not comparable, 438 of 447 structures
  have no printed mass at all (the document prints MS for few compounds), and
  22 printed lines no structure claims.

Open: the two mismatches that remain are printed *intermediate* masses bound
to the product's designation (pp.67, 75) — separating an intermediate's mass
from its product is an attribution rule, not a read-side fix.

## Agent molecule-recognition tool (2026-11-09)

A whole-document comparison on `CN120118069A` measured what the chat model can
do on its own: given page images it found the activity pages (98–102) and read
all 69 values exactly, but it could **not** emit a single SMILES from a drawn
structure (one structure page burned its full 24k-token budget on reasoning and
returned empty content). Structure reading therefore belongs to the local
detectors, exposed to the model as a tool instead of an expectation.

`inspect_visual` action `page_molecules` now runs MolDetv2 + MolParser over one page of a stored
document and returns, per structure: SMILES, E-SMILES, pixel box, PDF-point box
(bottom-left origin, the overlay contract), detection score and OCR-read printed
labels. It is read-only and never persists anything.

- Service: `service/use_cases/molecule/recognition.py` (`recognize_page_molecules`).
  It takes `(library_root, doc_id)` and an absolute PDF path, so path policy
  stays with the caller.
- Capability: `inspect_visual` action `page_molecules` (read-only, `service/capabilities/read_visual.py`)
  resolves the stored PDF and returns the same result; it never persists.
- Agent wiring: the pi CLI receives it from the capability manifest; no
  sidecar-only tool remains.
- Tests: `tests/unit/services/test_molecule_recognition.py` protects the PDF-point
  box contract, the region filter and truncation visibility.

Pending: decide whether the model may cite a label→SMILES match as evidence
(currently it reports tool output, not a new fact).

## Table-embedded molecules (2026-11-06)

Structures drawn *inside* a table cell were being read as cell text: the table
producer runs SLANet-1M on the whole crop and recognizes every detected line
whose centre falls in a cell, so atom labels and bond glyphs became cell
content. Measured on the 13-document development corpus: up to **260
chemistry-looking cells in one document** (`0 HN. NH 0 CF3 N`, `N HN S CH3 O`),
and table-embedded molecules are the norm there (68/68 tables, 104/105, 56/64 in
the worst three; 409 molecules in one document).

`layout.mask_table_molecules` (default **off**) now makes the table read as
text: molecule boxes from the layout producer's own MolDet pass are blanked in a
copy of the table crop **for cell-text recognition only** (structure inference
still sees the original crop), and a `[MOL:n]` token is written into the cell
that holds the drawing, preserving its row/column position. The token → molecule
mapping (PDF points) rides on the region (`molecule_cells`), and evidence
minting replaces a token with the printed label the molecule pass read from the
crop (`name`, else `ocr_labels[0]`); an unlabelled molecule keeps its token
rather than an invented number. Non-table text evidence is unchanged, and a
table without embedded molecules behaves exactly as before.

**2026-11-11: enforcement, see “Table masking runs before cell OCR” above.**
The switch and the A/B script are gone; the mask is unconditional. Measured
off → on (table pages only, chemistry-looking cells): CN121270515A 0 → 0
(8 tables, no table molecules — control), KR20250121245A 12 → 0 (26 tables /
126 molecules masked), WO2025002360A1 15 → 3 (20/218), WO2025223036A1 265 → 3
(56/317), CN119504738A 10 → 0 (3/11, rows and cells unchanged). Table structure
counts were stable apart from model run-to-run nondeterminism (one row on two
documents). The 400-page JP document was never compared; its table pages are the
remaining blind spot.

## Activity pair truth (2026-11-06)

Two deterministic defects are fixed on `CN119504738A` (the only document in the
local library): no model call, no re-extract, both covered by unit tests.

1. **A page-split activity table is read under its own page's header.** Table 1
   prints 14 IC50 readings across pp.124-125. Page 125 resumes with a data row and
   no header, so the Markdown converter promoted that row to the header and the
   parser dropped all 7 rows with **0 readings, 0 issues and no LLM gap** —
   invisible in every surface. `service/pipeline/activity/table_scan.py` now owns
   one table evidence row: direct parse, then cross-page header inheritance
   (adjacent page only, same column count, first cell a designation, no header
   band), then a refusal that is always reported. Inherited readings stay
   auditable through `table_header_inherited`, which cites both evidence rows.
   Measured: **7 → 14 readings, 3 → 7 structure links, 0 silent drops**.
2. **A disputed designation never becomes a published pair.** One structure is
   detected with labels `1` and `22` (p.91 prepares `21`), so the association
   refuses both and the reading keeps no attribution — but the declared-example
   join published `化合物1 IC50 64.6` beside that structure, so the artifact's
   `structure_activity` contradicted `measurement_attribution` and the export.
   The ambiguity issue now carries its `label_key` and
   `_declared_structure_activity` withholds that designation. Measured: the
   declared pairs equal the SQL attribution set (2, 4, 10, 24, 27, 30, 1A) and
   the compound-1 pair is gone. `candidate_label_keys` moved to
   `patent/candidate_labels.py` (three importers shared a private helper).

3. **The assay is declared in the body, not in the title.** `[0891]测试例1:MRGPRX2体外
   钙流测定试验` sits inside an example section, and the assay rule read section
   titles only, so all 14 readings carried `assay_method_unresolved` and no
   target. `rules/assay.py` now reads body assay blocks (`测试例` / `试验例` /
   `Test Example`); each block owns the evidence after it up to the next heading,
   and the association picks the method whose block cites the reading's own row
   when a section prints several assays. The receptor token also needed ASCII
   boundaries — `\b` does not fire between `MRGPRX2` and the CJK text after it.
   Measured: **14/14 readings carry `assay_method_id` and `target="MRGPRX2"`**,
   and `assay_method_unresolved` is gone. `assay_description` stays empty: no
   printed description flows into the method yet.
4. **A declaration without parentheses is still a declaration.** `(目标化合物11)`
   and `实施例17：目标化合物17的制备` both state the product; requiring a bare
   `(化合物N)` dropped them. Declared examples on this document: **21 → 39**, now
   covering every designation Table 1 prints. A molecule detection payload may no
   longer mint a declaration — it repeats nearby headings verbatim, which put a
   second copy of the same example on the detection's page.
Still open on the same document, measured: **24 of 450 recognised structures
print a designation** (11%), so 11/14/17/23/32/33 stay unowned even though the
document now declares an example for each of them; `assay_description` stays
empty because no printed description reaches the method; `review_items = 0`
because both mint inputs are empty (`review_candidates` needed the removed LLM
merge, and every `smiles_mass_mismatch` issue carries `mol_id = ""`).

## Unbound readings, honest coverage, read surface (2026-11-07)

Three ordered follow-ups are implemented and measured on the live library
(`CN119504738A`: 14 readings, 7 attributed).

1. **A reading with no structure is now a review item.** Publishing mints one
   `designation_unbound` item per unattributed reading whose designation's own
   example section drew structures (the scope is the section page range plus the
   reading page; a document that drew nothing there is a source fact, not a
   question). Each item carries the page candidates; confirming it with
   `choice=<candidate mol_id>` writes `measurement_attribution` with
   `method="human"` and marks the reading accepted. A choice outside the
   candidates is refused. Measured: **7 items** for the
   seven unowned readings (1, 11, 14, 17, 23, 32, 33), 4-8 candidates each, and
   the live queue carries these 7 unbound items (Markush review items were since removed).
2. **Coverage no longer calls recoverable work undrawn.** `dataset_stats` now
   reads whether the document drew structures whose designation was never read
   and reports `label_not_read` instead of `designation_without_structure`.
   Measured on the same document: `{structure_detected_unmatched: 1,
   label_not_read: 6}` — five of which are the recovery targets, and the one
   `unmatched` is compound 1, whose structure carries a disputed label.
3. **The read surface answers dataset questions.** `query_activities` accepts an
   empty `doc_id` (library scope), `metric`, `min_value` and `max_value`, and each
   row carries its `reasons` classification instead of `[]`. The `activity_stats`
   route reports printed vs attributed plus the reason split, so a caller can
   check coverage before claiming there is no data.
   The activity HTTP route gained the same filters.

Still open from this pass: the export CSV does not carry the attribution
method/confidence, `query_activities` has no `has_more` cursor, and the
`measurements.review_status` flag still has no queue semantics of its own.
Tests: 434 unit tests pass (3 pre-existing recorrection environment errors), and
the new service/router tests cover minting, binding, candidate refusal, the
`label_not_read` classification and the value filter.

## AI review proposals (2026-11-07)

The assistant may file a review item at any time for a target a human has not
reviewed yet. A proposal is not a decision: it enters the review center as
`ai_review` with the target, the field, the value it suggests, the value the
store actually holds, the rationale and the evidence ids it read. A human
confirms or rejects it, and only that decision writes a value.

- Entry points: `POST /api/v1/review/propose` (any caller). The removed
  credential-scoped research route and its chat tool were the sidecar's delivery
  path; the HTTP endpoint remains.
- Idempotent and freeze-safe: one item per
  `(doc_id, target_kind, target_id, field)` (`stable_id`). A second proposal for
  the same field while it is pending **revises** that item (revision counter plus
  a bounded history of superseded proposals). Once a human confirms or rejects
  it, the item is in `confirmed`/`rejected` and every further proposal for that
  target is **refused** with `a human already decided this target`; nothing is
  overwritten. Reopening is a human action (`reopen`), never an AI one.
- Anti-hallucination: the target must exist (evidence rows and molecules are
  resolved before insert; an invented id is refused), and `before_actual` is read
  from the store next to the model's claimed `before`, so a wrong claim is
  visible in the item instead of trusted.
- What a confirm applies: a molecule `name` (through the existing review
  repository setter) is written on confirm; evidence text, readings, entries and
  designations are **record-only** — rewriting the source text or a reading is a
  pipeline change, so the confirmed item is the audit of the decision instead.
  Extending an applier is a deliberate, testable step per target kind.
- UI: `ai_review` is a filter kind in the review center with a before/after
  card (current store value vs suggested value, field, rationale).

Verified: propose → revise → human confirm applies the molecule name → further
proposal refused (service tests, including an invented target and a record-only
evidence target); the same chain through `POST /api/v1/review/propose` →
`/review/queue?kind=ai_review` → `/review/decide` (router test); the full unit
suite (425 passed) and the frontend lint/type-check.

### In-chat review and batch approval (2026-11-07) — historical

The chat-side version shipped with the removed research workspace and is gone.
What survives is server-side and still current: `POST /api/v1/review/decide`
for one item and `POST /api/v1/review/decide-filtered` for a bounded batch
(`limit` default 200, max 500). The filtered path resolves the filter server-side
and runs every matching pending item through its own decision handler, so the
model never chose what got approved and a kind-specific side effect is not
skipped; the response reports `updated`/`skipped`/per-item results. The review
center keeps its selection-based bulk action. `ResearchReviewEvent`, the
`ResearchEvent` union and the SSE card stream were deleted with the sidecar.

## Review AI assist (2026-11-06) — removed (2026-11-10)

The review center's model-suggested answers were removed with the CLI-only
cutover: `service/use_cases/review_assist.py`, `contracts/review_assist.py`, the
`ReviewAssistRuntime` port, the `review_assists` table and the sidecar's
`POST /v1/review-assist` provider call no longer exist. Also gone with it:
`review.max_items`, `review.auto`, `review.images`, the readiness probe for the
assistant, and the `payload.ai_assist` field on queue rows. The review center
remains a human-decision surface only — the deterministic pipeline mints the
items and a person confirms or rejects them; no model answer is stored beside
an item.

## Structure–activity export (2026-10-30)

[Export contract and real-corpus audit](../docs/qa/structure-activity-export-20261030.md).
The workspace now downloads selected documents (or one document from its menu)
as a ZIP containing matched readings, unresolved readings and exact SQL evidence.
The export uses the committed Patent snapshot, refuses stale sources, preserves
all assays and stereochemistry, and keeps review candidates separate from facts.
Original and canonical units/comparators are separate; known concentrations
convert coherently to nM, unknown units remain unchanged, and missing units are
never guessed. Missing-unit numeric disagreements were the LLM merge's job; that
merge was removed on 2026-11-10, so no current path resolves them. Rejected or identity-changed catalog structures cannot enter matched CSV.

A deterministic replay for 13 development PDFs, after refreshing two damaged
CN121270515A table regions with the current local producer, now produces
**48 readings: 16 matched pending review and 32 unresolved**, with every reading
retained exactly once. The earlier stored-extraction baseline was 41/14/27.
Nonconcrete/rejected crops no longer block a unique concrete designation match;
body references to starting materials no longer replace an example's product
identity. Lost-rowspan headers are quarantined, not shifted by guesswork.
The refreshed selectivity table has the correct MRGPRX1–4 columns. Independent
source-image review found stereo errors in both CN121270515A final-product
recognitions; these remain unresolved and are not added as correct pairs.
These development counts are not precision/recall or scientific validation.
Next: adjudicated structure–reading–assay–source tuples, evidence-backed product
association, stereo review and missing assay context.

## Current Patent harness (2026-10-30) — historical

[Harness implementation and real-provider audit](../docs/qa/patent-harness-20261030.md)
records citable work/context packets, the exported schema as the then-actual Pi
tool contract, exact printed label/value-cell checks (`source_quote` + zero-based
`source_column`), stable work anchors and example namespaces. Four v4.2
real-provider work-chunk trials returned 6, 22, 0 and 1 text-supported readings;
the actual publisher preserved their column provenance as review candidates in
isolated SQL backups, with no new LLM structure links. The zero-result trial
correctly refused damaged OCR; these counts are not whole-page recall. The
printed positive control in CN120943813A p95 now stays in the deterministic
five-reading table, with IC50 preferred over generic activity wording.
Historical provider failures are retained. These are development samples of the
LLM gap path that was removed on 2026-11-10; the deterministic pipeline is the
only Patent path. Cell ownership does not prove assay semantics. The v4.3 follow-up fixes the generic
unit contract: dimensionless pIC50 no longer needs a missing-unit declaration,
while concentration readings still do. Physical units on log endpoints are
rejected; old drafts with a declared missing log unit remain readable.
The v4.3 fresh trial exhausted its gap budget after a structure lookup; v4.4
therefore exposes only excerpt/submit tools to bound table sessions. Separate
association tasks retain structure queries. Unitless pIC50 has passed isolated
tool validation and SQL publication replay. A v4.4 real-provider retest returned
E020 pIC50 6.9 in one turn/submit call (9,178 tokens, 59.675 s), also passing SQL
publication audit. This remains one work chunk; latency gains are not established.

## Current extraction experiments (2026-10-29)

[OCR/OXR bottleneck investigation](../docs/qa/patent-ocr-bottleneck-20261029.md)
records a fresh 13-document rule baseline, direct LLM calls and isolated 4090
server preparation. The baseline is 43 readings / 11 linked to structures, not
the older 52-reading snapshot. A reproduced error assigned an OCR-dropped `6`
to `5` in CN121270515A p20. Cross-column label inheritance is removed; the
ambiguous table now goes to review, leaving 36 readings / 11 structure-linked.
The old-SQL baseline is unchanged by later image fixes. On 8 freshly detected
tables, a 2-pixel cell/text tolerance restores printed `6` without changing other
cells; explicit HTML spans repair an observed MRGPRX1-4 target shift. Mass-only
empty-reading pairs are removed and declared-example joins respect their
namespace. A JP grouped-interval LLM experiment preserves clean-text lists and
identifies a printed conflict for example 258; noisy OCR exhausted its budget.
OXR has now completed 6 frozen-crop requests on the 4090: it restores all
three US structure-table readings and clean JP intervals. The parser now accepts
the structure table's explicit header beneath a spanning title (3 readings);
the assay-only table still needs evidence-scoped metric context. Explicit column
targets now survive SQL publication. An omp review exposed silent loss of malformed
span output; raw HTML is now retained for review with a warning and failure count.
The test service was stopped; no production backend switch
has been made. See the report for the unresolved association/interval work.

## Focus (2026-11-02)

The product scope is the patent reader: import → layout/OCR/table → source
evidence → facts and measurements → review/export. The agent surface is the pi
CLI; the web conversation and its research tools were removed on 2026-11-10.
Removed from the active surface: the notes /
knowledge base, the fake molecule Analytics/Relations panel and its
cluster/relation/analog/substructure stubs, the Markush attachment-site and
enumeration API, and the chat landing page (`/` now opens `/workspace`).

Reading UX pass: the viewer now restores page/zoom/continuous mode and overlay
choices per document, opens result views in focus mode (`f` toggles it), offers
fit-width/fit-page and 50–500% zoom, can hide molecule/layout/text layers,
highlights an evidence paragraph or PDF box in both directions, and the
Markdown reader has a heading TOC plus clickable page-marker links that open the
PDF at that page.

## Code weight pass (2026-11-04)

Deleted the unwired `foundation/chemname` vendored parser (2,511 lines) and
`service/pipeline/examples`, plus 29 dead symbols that had no caller outside
their own definition. `patent_stage.py` shrank 1,917 → 990 lines by moving the
rule extractors into `service/pipeline/patent/rules/`; `molecule_store.py`
shrank 1,026 → 707 by moving detection I/O and candidate persistence into
`detection_store.py` and `molecule_candidates.py`. The six patent test files
went 4,503 → 4,170 lines with no public contract lost. CI now enforces vulture,
import-linter layer contracts and a file-size budget
(`[tool.vulture]`, `.importlinter`, `scripts/check_file_sizes.py`).

## Current pipeline

`Extract → Markdown → Patent` is the registered pipeline, but the stages are
scheduled decoupled: import runs **Extract + Markdown** only and the document
rests at status `extracted` (readable, not yet analyzed), and **Patent runs on
demand** — per document or in batch (`POST /api/v1/documents/patent-analysis`)
— as a `patent`-only run that rebuilds its inputs from the SQL evidence. Both
entries run through the same queue; `enqueue(..., stages=...)` selects the
subset. Extract is the single producer — the layout/text/table producer and the
molecule pass (MolDet + MolParser) both run inside it — and mints and persists
the canonical `SourceEvidence` rows to SQLite itself. SQL is the only evidence
store (there is no branch artifact); Markdown assembles the readable document
from that evidence, and Patent publishes the unified facts artifact. Link and
Persist are removed from the active path.

## Activity data

**Phase A of [the activity extraction plan](../docs/plan-activity-extraction.md)
is implemented.** Printed readings are now first-class SQL rows: they are stored
whether or not a structure owns them, so the dataset is complete and the
extraction backlog is countable instead of silently dropped.

The design is two tables. `measurements` holds a reading exactly as the document
printed it — value, unit, comparator, evidence IDs, page, printed designation —
with **no structural requirement**. `measurement_attribution` holds the optional
`reading -> structure` links, zero or more per reading, filled in as association
improves. `measurements.evidence_grade` separates a printed figure (`measured`)
from a model output; Phase A writes only `measured`, and compute paths must
supply their own grade rather than reuse it.

A table that breaks across a page is now read as one table: a headerless
continuation reuses the previous evidence row's activity header when the column
count matches and the fragment sits on the adjacent page
(`activity/parsing/tables.py::parse_activity_table_continuation`). On
CN119504738A pp.124–125 (Table 1) that took the document from 7 to 14 readings;
the same run attributes 7 of them, so 7 molecules carry `activity`/`activity_type`/
`units` where 3 did before. Readings whose printed designation has no unambiguous
recognized structure (missing or duplicated OCR labels) stay unattributed and
pending review rather than guessed.

An earlier development replay (`.tmp/e2e` artifacts): **36 artifact readings → 36
SQL rows, 0 dropped, 12 attributed**. Before this change the same data reached
SQL as 8 `molecules.activity` scalars.

What was wrong before: the only persisted activity was that scalar, written by
`documents/patent_facts.py::_derived_rows` → `activity_updates` →
`UPDATE molecules SET activity = ?, activity_type = ?, units = ?`. It dropped
every reading it could not attribute to a structure (across 18 artifacts: 526
entries, 144 carrying an `entity_id` = 27%, and **0 of 130 readings carrying a
`mol_id`**) and then kept only `measurements_by_smiles[...][0]` — **the first
reading per molecule**, discarding the document's other assays, targets and
doses. The legacy `activities` table and the `activity_match` review kind were removed
with `db/activity_store.py` and `activity/family_gate.py`; no read path or
test-only producer remains. Readings live only in `measurements`.

## Model assets

Every model is downloaded into and read from one directory: the
`ResourceManager` cache (`library/models` by default, overridable via
`model_cache_dir`). Weights elsewhere on the machine (a repo-root `models/`,
`assets/models/`, the global HF/ModelScope caches) are deliberately ignored, so
a `ready` status always means the app can load the model from that directory.

Downloads are ModelScope-first with a HuggingFace fallback. The SDK channel
verifies its snapshot and hands off to the direct-HTTP channel when it writes
nothing, because the SDK does not raise when individual files fail. Both local
backends keep one process-wide model instance reused by every task, and
`foundation/inference/load_guard.py` cools down a failed load instead of
retrying it per crop.

The ingest queue does not claim a row until every model in
`REQUIRED_PIPELINE_MODEL_IDS` (`moldet`, `molparser`, `hiro_layout`,
`slanet_table`, defined beside `RESOURCE_CATALOG`) is `ready`. That set is the
single source of truth: `service/use_cases/pipeline/model_gate.py` reads it
through the runtime port, the queue worker consults the gate before
`_claim_rows`, and both `GET /api/v1/pipeline/worker/status` and
`/api/v1/readiness/summary` report the verdict. Blocked rows stay `pending` and
resume automatically once the downloads land — enqueueing is never gated.
`ppocrv6` is deliberately excluded: RapidOCR's weights ship with the
`rapidocr` package rather than the catalog, and OCR has a degradation path, so
gating on it would deadlock the queue.

## LLM ownership

The pi CLI (`agent/src/extension.ts` + `agent/src/capabilities.ts`) is the only
thing that talks to an LLM provider. It keeps provider login, model switching
and sessions in its own agent directory — `agent/.pi-agent/` via
`PI_CODING_AGENT_DIR`, launched by `agent/scripts/cli.mjs` — and never merges
`~/.pi/agent` config or reads the Python `settings.json`. There
is no Node HTTP server, no `POST /v1/models` model-list probe and no
`POST /v1/probe` connectivity probe. Python used to carry a LangChain client, a
LiteLLM mapping module, a provider default-URL table and a model-list probe in
`server/llm/`; that package, its `LlmCapability` port and the readiness
`probe-llm` endpoints are gone. Python persists `AppConfig.llm` and readiness
reports only whether those settings are complete (config-derived, no network);
the frontend no longer fetches a provider model list or tests a connection.

Python resolves `settings.json` at `<source root>/library` when
`pyproject.toml` is present, else `~/MBForge`, overridable with
`MBFORGE_SETTINGS_PATH`. That single rule matters — when Python defaulted to
`~/MBForge/settings.json`, a source checkout read no settings at all and every
saved key was silently lost. The CLI does not consume this file; its own
credentials, models and settings live under `agent/.pi-agent/`.

## Research tools and Pi upgrade (2026-10-14) — removed (2026-11-10)

The research workspace, its SQL `search_library` tool, the optional Tavily
`web_search` / `web_fetch` extension, the RCSB PDB and Europe PMC searches, the
skill-routing prompt stack and the research/review SSE streams were removed with
the CLI-only cutover. `@tavily/pi-extension` is no longer a dependency, the
web-search settings and keys are gone from `AppConfig`, and no research route,
`research_sessions` table or `research_task_requests` queue hook remains. What
replaces them is the pi CLI with the capability tools generated from
`/api/v1/capabilities`; `agent/skills/` and `agent/schemas/` were deleted with
the cutover, so no skill or schema artifact remains.

## Layer boundaries

Repository and runtime ports live in the neutral `mbforge/ports/` (implemented
by `db`), and the cross-layer request/read models they reference in
`mbforge/contracts/` (re-exported by the `service` DTO modules), so `db`
implements the ports without importing `service`. The review-queue SQL lives in
`db/review_store.py` behind `ReviewRepository`, so no `service`/`api` module can
obtain a raw connection. `foundation/inference/assets.py` defines the
`ResourceResolver` seam the composition root injects, so the inference backends
never import `server`.

## Recognition order and value rules (2026-10-23)

- `source_evidence` now persists `reading_order` (zero-based inside the page);
  `list_source_evidence` orders by it, so a two-column page is read column-major
  in the Patent stage. Legacy rows keep `0` and fall back to the geometric order
  until the document is re-extracted.
- `match_section_heading` normalizes digit-separating spaces and full-width
  digits before matching, so `実施例 1 0 3` and `実施例1 04` yield `103`/`104`
  without rewriting the stored `heading_line`; the range `実施例２および3` is
  normalized but still refused as one section.
- `ND`/`NA`/`NT` are missing values: `_qualitative_rank` no longer assigns rank
  `0`, and the table parser excludes them from the completeness count, so a row
  with `ND` does not become an inactivity measurement.
- Covered by `tests/unit/core/test_evidence.py`,
  `tests/unit/services/test_source_evidence.py`,
  `tests/unit/pipeline/test_sections_sql.py`,
  `tests/unit/pipeline/test_activity_normalization.py` and
  `tests/unit/pipeline/test_activity_parsing.py`.

## Known gaps

- Patent facts now also carry the printed **chemistry names**, **spectra/elemental
  lines** and **synthesis routes** (`PatentFactsArtifact.names` / `characterizations`
  / `synthesis_steps`), extracted by rule from SQL evidence with zero model calls.
  A zero-token sweep of all 13 corpus documents extracts 407 hydrogen spectra, 268
  mass spectra, 179 routes with 80 steps and 5 printed names, and every emitted
  string is a substring of the evidence row it cites (`fabricated = 0`). Elemental
  analysis has a live rule and no corpus hit. Forms and real strings:
  [docs/wiki/patent-extraction-forms.md](../docs/wiki/patent-extraction-forms.md) §11.
- **Association, not extraction, is the bottleneck.** The same sweep leaves 646 of
  854 extracted names/spectra/routes unattributed: the passage prints no designation
  the rules can bind, and rules cannot decide whether `77-A` or `77-B` owns a reading.
  Those residuals are the only thing the gap path sends to the model, which may
  associate and correct but never write a fact or a SMILES. Rules can detect a mass
  mismatch (`MS m/z` vs monoisotopic mass, ±0.6 Da) but not which structure is right,
  so a mismatch becomes a `smiles_correction` review item and a human decides; the
  `mol_id` is preserved and the fingerprint recomputed only on confirmation.
- An `assay_method_unresolved` gap no longer makes the model resend the reading it
  already extracted: a method-only answer is valid, and Python rebuilds the reading
  from the rule fact named by `rule_context.related_fact_id` (the value is copied,
  never retyped). One fact is bound per gap, so a refused 15-row table still binds
  its named reading only.
- **(Historical) The live LLM gap pass submitted nothing; live quality was never
  verified, and the path was removed on 2026-11-10.**
  A live run (`patent_analysis.enabled=true`, LongCat-2.5-Preview) on CN121270515A
  and CN120329282A shows 14–24 tool calls, all of them `get_gap`, and `answered=0`,
  ending `no_submission` / `budget_exceeded`. Ruled out by instrumentation, not
  assumption: no agent HTTP failure (`postTool` now logs unreachable/failed), no
  backend refusal (`_failure` now logs every rejection), no contract rejection, and
  `get_gap` returns a gap every time. The runtime now refuses another gap while
  one is unanswered, and its four-turn per-gap budget resets only on an accepted
  answer, never on another fetch. Offline agent tests cover both guards; a new
  live run on 2026-10-16 verified four CYP3A4 table cells and their candidate
  references, but completed only 2/3 gaps in CN120329282A and 0/3 in CN121270515A
  within 240 seconds each. See [live acceptance](../docs/qa/patent-live-llm-20261016.md).
  A **full-stage** run on 2026-10-16 (same model and prompt version, its own agent
  server built from `agent/dist`, 600 s wall / 240 s per request) answered **1 of 40** gaps
  in CN120329282A (7 turns, 602 s, ≈86 s per turn) and **0 of 28** in CN121270515A
  (3 turns — one per gap, none finishing inside its 240 s). The binding constraint is
  per-turn latency against the per-gap budget, not the tool surface: the accepted
  answer took 3 turns, one of them spent on a contract rejection it then fixed. See
  [the live association test](../docs/qa/patent-live-association-20261016.md).
  Scientific accuracy and complex-table stability remain unproven. The deterministic
  artifact is now the only Patent output, so there is no LLM fallback mode any more.
- Label aliases stored as lists now reach the gap as individual designations, and a
  candidate's `name` is read as a designation too (a label that lived only there
  used to be invisible to every rule). Automatic activity-to-structure attachment
  requires exactly one distinct structure for the printed label; duplicate
  candidates stay unresolved (`molecule_candidate_ambiguous`), and `Example 7` is
  not automatically `Compound 7`. The printed row designation takes precedence over
  a model-supplied normalized key. A designation no candidate carries is now
  **reported** (`molecule_label_unresolved`, info, keyed by the entry) instead of
  ending in silence, and `dangling_fact_reference` — a printed designation no
  section declares — reaches the model as a gap. Explicit model associations still
  require source review; a model-declared designation is published with
  `review_status="pending"`. MolDet/MolParser remain the structure producers: the
  LLM cannot invent or edit SMILES, and this change does not validate
  stereochemistry or recognition accuracy.
- A gap's excerpt is capped at the contract's own limit (`MAX_EXCERPT_CHARS`): a live
  run of CN120329282A failed the whole Patent stage because the excerpt budget (8000)
  exceeded the contract's cap (4000) and one invalid gap took the stage down.
- The unused `pages/`, `artifacts/` and `runs/` layout paths and their readers,
  writers and id-collision scan were removed. `report.json` is written by run
  finalization (`run/checkpoint.write_merged_report` →
  `LibraryLayout.report_json`).
- Extract classifies recognized image structures and persists their canonical
  source-evidence links; the `complete`-only gate keeps Markush scaffolds and
  fragments out of the concrete molecule library. It no longer queues Markush
  review candidates. Prose-only Markush definitions must not be fabricated as
  SMILES.
- The molecule↔evidence association is now persisted in `evidence.evidence_id`
  (pointing at the canonical `source_evidence` row); the legacy
  `text_molecule_links` table was dropped.
- A reading with no molecule is first-class: `measurements` stores it with no
  structural requirement and `measurement_attribution` fills links in later.
  The removed `activities.mol_id` `NOT NULL` table no longer blocks such rows.
  The full cause list — including the silent entry-without-molecule case and the
  `name`-vs-`properties` label trap — with real text cases is in
  [docs/wiki/activity-association.md](../docs/wiki/activity-association.md).
- Import starts processing in the same request and the workspace lists every
  imported document right away: a fresh import rests at `pending` and shows as
  "待处理" while the queue reports the live stage. Auto-enqueue can be turned off
  (`ingest.auto_enqueue_on_import`); a failed enqueue leaves the document
  imported but unprocessed (`run_id` is `None`). Deleting a queue task clears
  that run's outputs (Markdown/report/crops/molecule data) and returns the
  document to `pending`; only deleting the document card removes the source PDF.
- The `agent/` workspace is CLI-only and guards itself with `tsc`
  (`npm --prefix agent run check`). No agent test files remain, so `npm test`
  compiles and then finds nothing under `dist/*.test.js`; the simulated provider
  and model-list/probe code are gone. Those contracts used to live
  in `tests/unit/test_llm_probe.py` and `tests/unit/routers/test_settings.py`,
  deleted with the Python implementation they covered; the later agent-side
  tests were deleted with the sidecar.
- The frontend locale files were pruned to keys the components reference;
  dynamic-key prefixes (`nav.*`, `mol.status.*`, `errors.*`, …) were preserved.
- Markush structure classification remains (the `complete`-only persist gate),
  but Markush review was removed: the unreachable frontend workspace, its HTTP
  client, the attachment-site/enumeration API, the `/api/v1/markush` review
  router, the Extract candidate producer, and the `markush_link` review kind are
  gone. The review center no longer handles Markush structures.
- SAR was removed: the fail-closed `/api/v1/sar` stub and
  `frontend/src/components/sar/` are gone. The follow-up molecule analysis
  panel (Analytics/Relations) was also removed: every backend function it called
  threw “no HTTP route available yet”. MoleculeLibrary keeps the list, detail,
  correction and bulk actions. Reintroducing SAR requires the Phase C
  preconditions in [the activity plan](../docs/plan-activity-extraction.md).
- Deterministic activity extraction is proven on a 13-patent corpus (CN/US/WO/KR/
  JP/IL) but only 2 of those documents yield any measurement today: the others
  publish their activity as tables the parser refuses by design (split headers,
  structure-OCR columns, merged cells) or as glyph-damaged prose (`ICs0`,
  `ρIC50`). CJK bioassay headings, lettered US assay examples, Japanese
  `実施例` headings (400-page filing: 1 → 85 examples) and document-level bin
  legends are handled; the remaining JP obstacle is glyph damage, not headings.
  Every observed form — with the real strings, the issue code it raises and its
  state (handled / refused by design / open) — is cataloged in
  [docs/wiki/patent-extraction-forms.md](../docs/wiki/patent-extraction-forms.md).
  The measurable headroom, in order: table shapes still refusing (largest),
  CN120329282A's 24 measurements lacking an assay section form, and
  machine-translated filings whose heading labels were dropped in translation.

- **(Historical) The live gap path consumed the model's associations.** Every accepted
  `PatentGapLink` (a printed designation + a recognized structure) was applied by
  `association.apply_gap_links` before the artifact is built, and `associate_facts`
  runs a second time on the result: a designation a section prints is resolved in
  place, a designation **no** section declares is declared by the link itself
  (the existing `CompoundEntry`, `review_status="pending"`), the reference is
  stored in the identity persistence reads (canonical SMILES, translated from the
  `mol_id` the payload carries), and the reading whose provenance cites the
  resolved designation carries it in `measurement.mol_id` — which is what lets it
  reach `molecules.activity` with no entry path. A designation the rules already
  resolved is never overwritten, and the relation reports are recomputed per pass,
  so the failure the model answered disappears instead of standing in the artifact.
  Corpus measurement (`.tmp/e2e/assoc_probe.py`, zero tokens): 310 entries, 63 with
  a structure, **247 designations now reported and handed over** as gaps instead of
  failing silently. Two things the live run forced: the work list is now sized to the
  turn budget (`max_gaps = min(DEFAULT_MAX_GAPS, max_model_turns // TURNS_PER_GAP)`,
  3 turns per gap measured live), so a run finishes and reports the rest as
  `skipped.over_cap` instead of dying mid-list; and `list_molecules(label=…)` answers
  "which structures carry this designation" in one call — the live model paged the
  catalogue blind twice per gap because a 130–355 candidate list only ever showed one
  page and refused a second lookup. Both are unit-verified; in the live run itself the
  model answered a *table* gap (`llm_links_applied = 0`), so the link path was not
  reached — see [the live association test](../docs/qa/patent-live-association-20261016.md).
  The agent wiring that hosted only the gap tools was deleted with that path, as
  were every `patent_analysis.*` setting and the `llm_analysis_fallback` mode, so
  no LLM Patent stage exists to run this flow.
- **Activity recall round (2026-10-16).** `uv run python .tmp/e2e/activity_recall.py`
  measures what the corpus prints against what the parser reads: **36 → 52
  measurements, 30 → 47 with a declared owner, parsable activity tables 3 → 6** of 31.
  The levers: the table metric vocabulary (a target-qualified CN header
  `CYP3A4(咪达唑仑)抑制率(%)` produced no metric at all, so one document's 24
  measurements were LLM-only), the merged label cell (`| 5 | ++++ | | ++++ |`), the
  header-declared example space (`实施例编号` + `2` is `@example:2`, not compound `2`),
  and suffix designations (`化合物77-A`). One rule change followed: the rule pass now
  declares the printed designation itself (`association._declare_entry`, reusing
  `CompoundEntry` with `review_status="pending"`), so the removed
  `dangling_fact_reference` has no producer left and no reading is ownerless. What
  remains is the **structure behind the designation** (247 of 310 corpus entries have
  no `entity_id`): the model binds it with `list_molecules(label=…)` plus a link. See
  [forms](../docs/wiki/patent-extraction-forms.md) §10 and
  [association](../docs/wiki/activity-association.md).
- **The worklist is shaped for the measured model budget.** Latency is ~86 s per turn
  and a gap takes ~3 turns, so one 40-minute run settles ~9 gaps; the corpus worklist
  had 735 entries. A refused table now travels `TABLE_ROWS_PER_GAP` rows at a time,
  family (spectra/name/route) and designation reports are grouped to
  `MAX_GAP_PASSAGES`, a gap is built only on **printed** rows, and an association issue
  citing the candidates' detection payloads resolves its rows through the **entry** that
  names the designation. Result: **735 → 142 gaps carrying 251 designations**, and
  CN120329282A's 40+ became 7, so one document is one run. Two live runs measured it:
  a designation-only one finished `complete=true` in 4 turns / 118 s and answered
  `no_attribution` because its gap was a payload (fixed); a full-stage one (7 gaps, 24
  turns / 1800 s) ran 17 turns / 27 min, accepted 3 answers (two assay methods became
  review candidates, the designation answer was again `unanswerable`) and exhausted the
  token budget with 4 gaps unprocessed. In both cases the refusal was *correct for what
  it was given* — and in the second, the 34 ambiguous designations had been silenced as
  `no_text_location` by the payload filter. The entry-aware resolution makes them
  answerable; it is not yet live-verified.
- **页级最简文本提问优于缺口契约包装（2026-10-17 实测）。** 同一模型、同一页面 payload：缺口
  契约版单轮 300–400 秒且不提交；两句话的最简文本版 24–47 秒给出答案，123 个数字里 1 个不在页内、
  23 个编号无一编造，覆盖规则 28 条读数中的 19 条。让模型卡住的是 prompt 里的契约/工具/提交框架，
  不是上下文体积（§8 的相反结论已更正）。
- **关联的瓶颈是索引，不是提问（2026-10-17 实测）。** 全语料 52 条规则读数**没有一条**带 mol_id；
  编号条目↔检出结构解析率 20%（63/314），结构带任何编号率 13%（343/2605）。关联链是跨页多跳
  （行 → 编号/实施例号 → example 小节 → 检出结构，CN121270515A 的 14 条绑定全部跨页，400 页文档里
  结构分布在 152–396 页），所以下一步是页级补 `编号 → 结构` 这一跳并落库，而不是加大 prompt。
  证据与三张实测表：`docs/qa/patent-live-association-20261016.md` §9。
- **"按页阅读"作为一个替代架构已被真实实验否定（2026-10-16）。** 用生产契约把一页做成一个 gap
  （页面证据 + 候选）跑真实模型：开放式措辞下 5 页里 4 页单轮 >300 秒超时、1 页答 `unanswerable`、
  0 条读数；有界措辞下 20 分钟 3 轮、0 次工具调用、0 条提交、0 条读数。单轮延迟随 excerpt 体积
  单调上升（0.7k→30 秒、1–2k→96 秒、3.7k→300–400 秒且不提交），所以**窄任务是承重设计**：
  放大任务不会让模型读得更多，只会让它推理到超时。要放宽必须先确定"单次预算 vs 页面规模"的可行
  边界。证据与两次运行的完整数据：`docs/qa/patent-live-association-20261016.md` §8。
- ~~Review items are re-pended on every publication.~~ **No longer true:**
  `review_audit.insert_review_item`'s `ON CONFLICT` clause updates the payload
  but not `status`, and `set_review_item_status` is called only from the human
  decision path (`service/use_cases/review_queue.py`). A rejected item that is
  still a candidate keeps its status across re-runs.

- **The relation-pair contract is accepted but not implemented.**
  `page_geometry`, `label_anchor` and `relation_pair` exist only in
  [ADR 0001](../docs/adr/0001-relation-pair-contract.md). The write path still
  stores canonical SMILES in `CompoundEntry.entity_id`, reports
  `structure_status="resolved"` without a verification axis, and drops a Markush
  candidate after `molecule_candidate_rejected`. The
  [gold standard](../docs/plan-gold-standard.md) has a development manifest
  (`tests/gold/manifest.json`, 13 documents) and a validator. Unadjudicated
  pilot annotations now cover five documents / 36 records
  (`tests/gold/annotations/*.pilot.jsonl`); the first-document findings are in
  [the pilot report](../docs/qa/gold-pilot-cn121270515a-20261023.md) and the
  cross-document rules in
  [patent layout rules](../docs/wiki/patent-layout-rules.md). There is no
  held-out split and no pair-level metric yet.

## Active plans

- [Relation-pair contract](../docs/adr/0001-relation-pair-contract.md) and
  [gold standard](../docs/plan-gold-standard.md) — **ADR accepted, tables not
  yet applied**. First implementation step is the `label_anchor` index in
  Extract, then the pair write path. Pilot annotations now cover five documents
  / 36 records in `tests/gold/annotations/`; the layout survey is
  [patent layout rules](../docs/wiki/patent-layout-rules.md). Human adjudication
  and the held-out split are pending.
- [Activity data extraction and persistence](../docs/plan-activity-extraction.md) — **Phase A implemented**: readings are first-class SQL rows independent of structure attribution. Phase B (compute layer: Boltz-2, reproducible `compute_runs`, `evidence_grade` for predictions) and Phase C (SAR, synthesis suggestions) are recorded with their preconditions and are not scheduled.
- [Source layout reorganization](../docs/plan-source-layout-reorganization.md)
- [Capability platform](../docs/plan-capability-platform.md)
- [SLANet-1M as table parser on the Hiro-Layout path](../docs/plan-slanet-1m-table-parser.md)
- [Backend architecture](../docs/wiki/architecture.md)
- [Pipeline contract](../docs/wiki/pipeline.md)

## Conventions

- Treat `docs/wiki/pipeline.md` as the per-stage contract.
- Keep SQL source evidence separate from the shared `domain.molecule.Molecule`
  entity and inferred facts.
- `Molecule` is the only structure-bearing molecule domain object across
  detection normalization, correction, Markush handling, hydration, query,
  and future persistence. `ExtractionResult`/`DetectionSource` remain raw
  observations; `CompoundEntry` remains a document-level patent record.
- Cross-business-package imports use absolute `mbforge...` paths; relative
  imports are for a package and its immediate local modules.

## Binding repair is an agent loop, not a rule (2026-11-12)

Measured across the six CN test patents: 235 stored readings, 143 linked by the
deterministic pass (61%), 92 unowned — 57 `label_not_read`, 27
`structure_detected_unmatched`, 8 `no_printed_designation`. The classes have
different owners: the first two are decisions a reader makes by looking at the
page, and no rule that must stay evidence-tight can make them safely. So the
repair path is agent-driven, and the code's job is to hand the agent the
material and to accept its adjudication.

- `agent/skills/patent-binding-repair/SKILL.md` is the loop: measure →
  triage by reason → packet → decide → one validated batch → re-measure →
  record. It carries a per-reason playbook and an evidence ladder (printed
  product statement > printed mass > page-text caption > section locality >
  geometry). `patent-active-molecules` stays the read-only diagnostic skill and
  points at it.
- `get_binding_candidates` now also publishes what a `label_not_read` decision
  needs: `unlabeled_structures` (every drawing with no designation, with
  formula, exact mass, printed-MS verdict) and, per designation with no
  candidate, `nearby_structures` limited to that designation's reading pages.
  Before this the packet was empty exactly where the gap was.
- `verify_structures` fills `mol_id` from the canonical SMILES when the evidence
  row carries none, so the agent has an id `assign_attributions` accepts.
- New mutating capability `assign_attributions`: up to 200
  `{measurement_id, mol_id, evidence_id?, confidence?}` decisions, all validated
  before any is written (one unknown reading or molecule rejects the batch).
  Writing 40 links one tool call at a time is why a pass used to stop halfway.
- Also fixed in this round: an example reading now binds through the printed
  product sentence (`实施例29 … 得到55mg化合物29`) and through a drawing
  captioned with the example heading (the page-text pass stores `@example:N`,
  which the candidate index now reads). `_ROUTE_PRODUCT_RE` accepts the printed
  amount in a yield sentence. Measured effect: CN121270515A 5/34 → 29/34 linked
  (the 5 left are positive controls and a WO comparator with no compound),
  CN120943813A 14/45 → 25/45 (the rest still need label repair).

Verified: `uv run pytest tests/unit -q` (456 passed), `uv run ruff check` on the
touched modules. Batch writer covered by
`test_assign_attributions_writes_a_validated_batch`; the product-sentence path
by `test_an_example_reading_goes_to_the_compound_its_body_prints`; the example
key space by `test_an_example_captioned_drawing_answers_to_its_example_identity`.

One correction from running the loop: `unlabeled_structures` for CN121717757A was
1133 rows of Markush scaffolds, which buries the handful of concrete drawings a
`label_not_read` decision actually compares against. The packet now publishes
only concrete, designation-less structures (no `*` in the SMILES).

## The remaining binding backlog is mostly a role gate, not a decision (2026-11-12)

Running the repair loop on CN120118069A (41 unattributed of 69) showed where the
readings actually die. The activity tables cite `化合物30A`, `50A`…`53A`; every
one of those designations *has* a drawing that owns it (`owns: true`,
`designation_counts` 2–4) — but the drawing is not in `molecules`, so
`assign_attribution` cannot reference it and the packet's `entry` reports
`structure_status: missing`. `search_molecules("30A")` returns only the
intermediates `30A-1` / `30A-5`.

Cause: `classify_structure_role` withholds a closed, labelled drawing as
`review_required` when the *prose around it* matches a Markush marker
(`R1`-style groups, `A1`-style abstract labels, mixture/isomer wording). Persist
drops anything whose role is not `complete`, so a final compound whose example
section also prints R-group definitions never becomes a molecule. The gate is
right to refuse silent promotion; what is missing is the other half — a way to
promote a specific drawing to a concrete structure with the evidence that
vouches for it, which is exactly the agent/human adjudication this workflow
assumes.

Consequence for the loop: `structure_detected_unmatched` and `label_not_read`
are not one class. Some are decisions (settled by the evidence ladder in
`patent-binding-repair`), and some are *promotions* the write path does not
offer yet. The next capability to build is that promotion (drawing + evidence →
concrete molecule), before another adjudication pass over the remaining 90
readings.

## A withheld drawing can be promoted, and the role rule learns the printed-twice case (2026-11-12)

Two changes answer the gap the previous section recorded:

- `promote_structure` (use case `structure_promotion`, mutating capability)
  stores exactly one drawing a caller names by structure evidence or canonical
  SMILES, with the reason recorded in `molecules.properties`. It refuses a
  scaffold, a dummy-atom fragment and a rejected structure, and is idempotent.
  Molecule persistence now writes `properties` at all (it previously discarded
  them), so `structure_role` and the promotion record are durable.
- `classify_structure_role` treats the same compound number read on two or more
  drawings of one structure as the document's own naming, exactly as it already
  treated a number the page text prints. A single crop read stays a guess. On
  CN120118069A this is what withheld the finalized compounds: the example
  sections print R-group definitions beside them, and each of those numbers is
  printed 2–4 times.

Verification status: `uv run pytest tests/unit` 458 passed (promotion contract
and the printed-twice case have their own tests). The CN120118069A re-ingest
that would show the scoreboard move could not be run: port 18792 is served by a
`dev:all` backend this CLI does not own (its recorded pid is dead), so
`backend_control restart` refuses. Re-run the measurement after that backend is
restarted from its own launcher:
`submit_extraction(6f7496525086)` → `submit_patent_analysis(...)` →
`query_activities(doc 6f7496525086)`; expected movement is the 29 readings of
23A/30A/49A/50A/51A/52A/53A.

## Measured after the role fix: CN120118069A 28/69 → 68/69 (2026-11-12)

Re-ingesting CN120118069A with the printed-twice role rule, the stderr-tolerant
MolParser load, and the example-label fallback moved its scoreboard:

| stage | attributed | remaining |
| --- | --- | --- |
| before | 28/69 | 29 `label_not_read`, 11 `structure_detected_unmatched` |
| after role fix + example fallback | **68/69** | 1 `no_printed_designation` (对照化合物1, no compound) |

`label_not_read` reached zero: those readings were never a label problem, they
were the seven withheld final compounds. The example rows (`Example 27A` …
`Example 53A`) bound once the example label could cite the compound the document
actually drew.

Two classes remain in the other documents, and neither is a code gap:

- **Stereoisomer pairs printed under one number** (CN120943813A p72:
  `19-P1 or 19-P2` over each drawing, `19` between them). The table cites
  `化合物19`; the drawings are its two enantiomers. Reading the labels alone
  cannot settle which structure a racemate reading belongs to, and there is a
  second reading-level question (does 19 mean the pair or one member). This is a
  review-queue decision, not a rule.
- **Suffix-bearing designations** (`化合物1-P4`, `化合物6-P2`, `化合物7-P1` …):
  the cited token never appears on any drawing; the drawings carry the pair
  labels above. Same decision.

Also verified in this round: `promote_structure` is now a live capability, so a
withheld drawing can be promoted one at a time when the printed-twice rule does
not reach it.
