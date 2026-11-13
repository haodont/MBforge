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

## Page-verified residue after the repair passes (2026-11-12)

Scoreboard by `query_activities` (6 CN documents, 235 readings):

| document | linked | remaining | what the pages show |
| --- | --- | --- | --- |
| CN119504738A | 17/18 | 1 | one SMILES carries both `1` and `22`; two printings disagree about one compound |
| CN120118069A | 68/69 | 1 | `对照化合物1` — a comparator, no compound of this document |
| CN120329282A | 24/27 | 3 | `77-A` / `77-B` are named and characterized (MS 562.2) on p89 but **never drawn** — only the racemate `77` is (p88, MS 562.1); `177-A` is an OCR duplicate of `77-A` (same 27 nM row, p110) |
| CN121270515A | 29/34 | 5 | positive controls and a WO comparator |
| CN121717757A | 25/42 | 17 | `I-273-A`/`I-273-B` share one racemate drawing captioned "I-273-A 或I-273-B" (p180); `I-2`, `I-109`, `I-298-A`, `实施例15 组分1/2`, `实施例52 组分2` are cited in the table (p195) with no drawing anywhere |
| CN120943813A | 24/45 | 21 | `-P1/-P2/-P4` designations are never printed beside a drawing; `19` is a pair captioned "19-P1 or 19-P2" (p72) |

Total 187/235 linked (80%, from 143/235 at the start). Two adjudications were
made from the page in this pass and written with `method=agent`:
`化合物80 → ` the quinoline drawing (its printed name is
`1-(1-(甲基磺酰基)乙基)…`, MS 558.1 on p91), and `化合物86 → ` the
`N-CH2-SO2Me` drawing (printed name `1-((甲基磺酰基)甲基)…`, p91). In both the
document drew the compound twice; the printed name and MS settled which drawing
is right.

The residue is not a pipeline gap: each remaining designation is either a
compound the patent never drew, a pair printed under one shared caption, or a
comparator. Those are review-queue decisions, and `list_review_queue` already
holds the `designation_unbound` items for them.

## The queue now follows the data, and adjudications survive re-runs (2026-11-12)

Two lifecycle defects surfaced while re-running Patent over all six documents:

- **A resolved reading stayed queued.** Thirty `designation_unbound` items for
  `实施例…` readings were still pending after the example-label fallback bound
  them — a human was being asked to decide a link that already existed. The
  publication pass now closes the pending item of every reading it bound
  (`review_store.resolve_bound_designations`), and only those: a reading whose
  section drew nothing keeps its item because no structure was found for it.
  Measured: the queue went from 99 pending to 27, and the 27 are the readings
  that really need a decision.
- **A re-run erased human and agent links.** Both write paths
  (`replace_document_measurements` and `patent_analysis_store`) deleted the
  document's readings and inserted fresh ones, taking every attribution with
  them; CN119504738A lost its two agent-decided links on three separate runs.
  Only rule links are recomputed now; a human or agent link is kept while its
  reading exists and dropped when the reading is gone.

Verified: `uv run pytest tests/unit` 464 passed, including
`test_republishing_keeps_an_agent_adjudication`,
`test_a_reading_bound_by_a_later_pass_closes_its_queue_item` and the
measurement-replace counterpart. After the fixes, a Patent re-run of
CN119504738A leaves 17/18 with both agent links intact.

## A review candidate can be the comparator's drawing (2026-11-12)

CN120943813A p95 prints a second activity table and, under it,
`[0687]阳参化合物结构如下：` with one undesignated drawing. Because the queue
scopes candidates by page, that comparator drawing appears in the candidate list
of every unbound reading on p95 — including `化合物7-P1`, whose own structure the
document never draws. A reviewer could pick it and bind a compound to the
positive control. The page text says what it is, so the fix is a scope rule: a
drawing introduced by a comparator/positive-control caption is not a candidate
for a compound designation. Not implemented yet; the page evidence is recorded
here so the rule is written against the printed caption rather than a heuristic.

## CN121717757A: which readings cannot be placed, and why (2026-11-12)

After linking `I-281`, the document stands at 26/42; 16 readings over 9
designations remain, and each was checked on the page:

| designation | readings | page fact |
| --- | --- | --- |
| `I-281` | 1.59 | **resolved**: p50 (claims) prints `1-280 / 1-281 / 1-282` in a row; the drawing under `1-281` is the compound. The 1/I OCR split plus a stray `I-284` prose token had made the identity a three-way tie — written with `method=agent` |
| `I-2` | 39.43, 8.3 | cited only by the p195/p196 tables; no drawing carries `I-2` |
| `I-109` | 14.60, 8.11 | same |
| `I-298-A` | 55.06 | same |
| `I-273-A` / `I-273-B` | 15.45 / 7.23, 15.27 / 15.43 | p180 draws one racemate captioned `I-273-A 或I-273-B`; p181 gives only the separated enantiomer's MS (584.0) |
| `I-274-A` | 8.96, 36.7 | the document draws `I-274` (p131) without the `-A` suffix; the single enantiomer is never drawn |
| `实施例15 组分1` / `组分2` | 16.2 / 129.7, 6.23 / 34.88 | p161 names 实施例15 as `化合物I-233-A, I-233-B, I-233-C, I-233-D`; `组分1/2` is printed nowhere beside a structure |
| `实施例52 组分2` | 11.83 | same pattern as 实施例15 |

So "cannot be found" splits into two truths: seven designations are never drawn
at all, and two name one member of a pair the document prints under a shared
caption. Neither is a label-reading or binding bug.

## Corrected: CN121717757A does draw I-2, I-109, I-273-A/​B (2026-11-12)

The user pointed at the pages and was right — those drawings exist. Two label
rules were losing them, and both are now fixed and measured (94dd: 26/42 → 30/42):

- a `figno` caption is a designation even when its head reads as a digit
  (`1-2`, `1-109`, `1-273-A`), and a 1/I head is answered with the series letter;
- a caption centred *over* a drawing names it too (p32 prints one column's
  caption under its structure and the middle column's 7 pt above it), applied as
  a recovery pass so it cannot displace a pairing the page convention settled.

Newly bound: I-273-A, I-273-B, I-274-A (both assays each).

What still cannot be placed, after the fixes (12 readings over 7 designations):

| designation | readings | page fact |
| --- | --- | --- |
| `I-2` | 39.43, 8.3 | p32 prints the caption (`1-2`) but the same recognized SMILES also carries `1-1` (p114) and `7-1`, so three numbers claim one structure — a structure check is needed, not a label |
| `I-109` | 14.60, 8.11 | two drawings are named `1-109`: p38 (C25H26Cl2F3N5O2, also labelled 1-146/1-288) and p169 (C26H28…); one of the two printings is a misread |
| `I-266-A` | 8.52, 3.76 | same shape: p57 (claims, C26H30…) and p139 (example, C25H28…) both carry the caption |
| `实施例15 组分1/2` | 16.2 / 129.7, 6.23 / 34.88 | p161 heads 实施例15 as `化合物I-233-A, I-233-B, I-233-C, I-233-D`; `组分1/2` is printed nowhere beside a structure |
| `实施例52 组分2` | 11.83 | the same pattern |
| `I-298-A` | 55.06 | no drawing carries it |

So the residue is now two decisions a reader must make (which of two drawings
owns `I-109` / `I-266-A` / `I-2`) and five designations the document never ties to
a structure.

## MS decides a contested number (2026-11-12)

Three designations had two drawings each. The example section that prepares the
compound prints its own `LC-MS`, which settles it — the filing's own statement,
not a guess:

| designation | printed MS | structure that matches | other candidate |
| --- | --- | --- | --- |
| `I-266-A` | 实施例26, p171: `(M+H)+ = 558.0` | p139 `C25H28Cl2F3N5O2` (558.16) | p57 `C26H30…` (572.2) |
| `I-109` | 实施例23, p169: `(M+H) = 570.2` | p169 `C26H28Cl2F3N5O2` (570.16) | p38 `C25H26…` (556.15) |

Both were written with `method=agent` (2 readings each), taking the document to
34/42. `I-2` is the same shape and the last of the trio: 实施例3 opens on p152
with the product captioned `1-2`, while the claims list (p32) captions another
drawing `1-2`; the example's MS on p153 decides it. The remaining 8 readings are
`I-2` (2), `实施例15 组分1/2` (4), `实施例52 组分2` (1) and `I-298-A` (1) — the
last three groups are designations the document never ties to a structure.

Rule worth having in the pipeline: when several candidates claim one
designation, the printed MS of the section that prepares it already decides —
`find_mass_mismatches` computes the same comparison today, so the association
could use it as a tie-break instead of leaving an ambiguity.

## I-2: one compound, two printings — and the drawing is withheld (2026-11-12)

Repeated printing is normal, so the fix for `I-2` is one instance, not an
ambiguity. The example's own statement names it: 实施例3 (p153)
`LC-MS:m/z:(M+H)+=504.1` with a para-anisyl NMR — that is
`C26H25ClF3N3O2` (503.16), the claims-list drawing at p32
(`COc1ccc(C(=O)NC23CCC(CC2)C(Nc2…Cl)…C3)cc1`, bbox 249.81–358.15 × 339.82–419.74).
The other `1-2` printing (p114) is `C25H23…` (490.1) and does not match.

That drawing is **not a stored molecule** (`assign_attributions` → molecule not
found): it is a concrete drawing on a claims page whose neighbouring prose is the
R-group definition, so the role gate withheld it. The repair is
`promote_structure(smiles=…, reason="I-2, 实施例3 p153 MS 504.1")` and then the
two readings (39.43, 8.3). That capability exists in the backend but not in the
session that ran this pass, so `I-2` stays open with everything needed written
down.

## The mass tie-break is in the pipeline (2026-11-12)

`associate_facts` now receives the document's characterizations and, when more
than one drawing claims a designation, keeps the structure whose calculated ion
mass matches every `LC-MS` printed for it (`mass_consistent_structures`), with
an `info` issue `designation_settled_by_printed_mass`. No mass line, or two
structures both matching, leaves the ambiguity to the review queue exactly as
before. Covered by `test_the_printed_mass_settles_a_designation_two_drawings_claim`
(CN121717757A I-266-A: 558.0 picks `C25H28…`, not the `C26H30…` claims drawing).

Still open, in order of value:

1. **A withheld drawing is invisible.** `classify_structure_role` returns
   `review_required` and nothing queues it: 6f74 had 40 `designation_unbound`
   items and zero `review_required` ones, and I-2's p32 drawing is exactly such a
   case (matching the example's MS but never stored, so `promote_structure` is
   the only path). Queueing those structures at publication, with their smiles,
   page and role reasons, would turn the gate's refusals into a worklist.
2. **`promote_structure` needs to be reachable from the pass that finds the
   gap.** The capability exists; the session that discovered I-2 predates it.

## The mismatch -> reprint loop is live, and its gate is now the honest one (2026-11-12)

`recover_structures_by_printed_mass` re-renders a mismatching drawing at 2× and
re-reads it, keeping the new structure only when it matches the printed mass.
Running it on CN121717757A showed the loop works but nothing was recovered —
and the reasons are worth keeping:

- **Characterizations were unlabelled.** All 60 of 94dd's printed spectra had an
  empty `label_key`, so `find_mass_mismatches` (and the new mass tie-break) saw
  nothing. Two gaps caused it: `_DESIGNATION_MENTION_RE` accepted only a
  digit-headed token, so `化合物I-50-2` was invisible in prose; and a preparation
  paragraph names its reagent *and* its product, so the line carried two
  designations and the owner stayed empty. The product verb (`得/得到/制得`) now
  breaks that tie. After the fix: **8 labelled `smiles_mass_mismatch` issues**
  (I-47-4, I-2-2, I-2-3, I-60-5, I-30-2, I-30-5, I-32-2) where there were none.
- **The recovery refused every one of them, correctly.** Several "mismatches" are
  adduct-notation artefacts, not recognition errors: `I-30-2` prints
  `(M+H-100)+=128.0` and `printed_ms_mz` read `100.0` out of the adduct text;
  a plain `[M+H]+` is what a mismatch gate may act on. Until the parser either
  reads `(M+H-x)` or skips it, the loop must not rewrite a structure — and it
  does not.

Next: make the mismatch gate adduct-aware (only `+H`/`-H`/`+Na`-style plain
ions, or parse the arithmetical form), then re-run: 94dd's I-47-4/I-30-5 are
off by ~0.7 Da, which is the reprint's target shape.

## Mass checks are adduct-aware, and loss notation is not comparable (2026-11-12)

`printed_ms_mz` read the first number after `m/z`, which in `(M+H-100)†=128.0`
is the `100` inside the adduct — a 128 Da "mismatch" against a correct structure.
The value is now read where the document prints it (both orders:
`(M+H)+=558.0` and `m/z 456.2 [M+H]+`), and the adduct is parsed fragment by
fragment with unknown fragments leaving the line unreadable.

One more gate the corpus forces: `(M+H-t-Bu)+` is a *loss* expression used
loosely — on Boc-protected amines it means the whole Boc (I-50-2: 348.20 → 249.1,
i.e. −Boc 100.05, not −isobutene 56.06), elsewhere the alkene. A line whose
adduct subtracts a named group is now skipped rather than compared, so it cannot
invent a 44 Da mismatch and cannot drive the reprint recovery.

What 94dd reports after both fixes (6 real mismatches, down from 8 with two
false ones): I-47-4 +0.70, I-30-5 +0.67, I-60-5 +1.57, I-32-2 −2.44, I-2-2
+27.8, I-2-3 +13.8. The ±0.7 pair is where the reprint loop should act next; the
+27.8/+13.8 pair looks like a misread intermediate rather than a rounding.

Measured after the gate: 94dd reports exactly the six genuine disagreements
(I-47-4 +0.70, I-30-5 +0.67, I-60-5 +1.57, I-32-2 −2.44, I-2-2 +27.8,
I-2-3 +13.8) and no reprint passed the mass check, so nothing was rewritten.
The ±0.7 pair re-reads identically at 2×, which says the disagreement is the
printed value, not the recognition; the +27.8/+13.8 pair is the remaining
re-recognition target (an intermediate read one fragment short/long).

## Correction: I-2's p32 drawing is an unparseable read, not a withheld structure (2026-11-12)

`COc1ccc(C(=O)NC23CCC(CC2)C(Nc2cc(C(F)(F)F)nc4ccc(Cl)cc34)C3)cc1` fails RDKit
("unclosed ring"), so `promote_structure` was never the right tool: the drawing
has no valid structure to promote, and no molecule row exists because the read is
invalid, not because the role gate withheld it. Two consequences:

- the `designation_promoted_by_printed_mass` pass (added this round) refuses it
  too, correctly: it only considers drawings whose structure parses;
- the reprint recovery is the right home, but it currently only fires on a
  **mass mismatch** — it has no case for "the read does not parse at all".

Next rule to write: extend `recover_structures_by_printed_mass` to also re-read a
drawing whose SMILES RDKit rejects, keep the reprint when it parses and matches
the printed mass of the designation the drawing is scoped to, and then let
`promote_structures_by_printed_mass` name it. That is I-2's whole chain in one
pass, and the same for the `+27.8`/`+13.8` intermediates if their reads are partly
broken rather than merely wrong.

## "Every printed designation has a structure" — so the residual is a resolution bug (2026-11-13)

Owner's rule for CN patents: a printed designation always has a structure. Checking
the 8 residual readings of CN121717757A against that rule shows the pipeline
conflates three different situations under one reason code (`label_not_read`):

- **The structure is drawn and even labelled, the label never attached.** `I-2`:
  page 32 (claims) prints `1-1`, `1-3`, `1-4`, `1-5`, `1-6`, `1-8`, `1-9` next to
  six drawings, and the drawing whose mass is 503.16 (matches the `(M+H)+=504.1`
  printed for 化合物I-2 in 实施例3) is the one whose label `1-2` did not attach.
  The OCR read `1-2` (there is already a `designation_ocr_reconciled` issue for
  it) — the pairing step is what failed. The mass-based promotion cannot help:
  five unlabelled isomeric drawings share mass 503.16, so "exactly one match"
  correctly refuses.
- **The token is an example and a chromatographic fraction, not a compound.**
  `实施例15 组分1/2`: 实施例15 is I-233-A/B/C/D (p161-162, all four drawn and
  labelled) and the text says 组分1 gives "化合物I-233-A、I-233-B、I-233-C、
  I-233-D中的一个或两个". The document itself does not name one structure, so no
  structure can own the reading; the correct outcome is an attribution to the
  example's compound set, or a refusal whose reason says *mixture*, not
  `label_not_read`. Same shape for `实施例52 组分2`.
- **The designation is only a name in a claims enumeration.** `I-298-A` is printed
  on p60 and p143 as one of "所述如式I所示的化合物为以下任一化合物" with no drawing
  beside it; the preparation on p191 covers I-298-1/2/3. Still to confirm: whether
  a later page draws I-298-A unlabelled.

Actions: (a) attach a page-text designation block to the drawing it belongs to even
when the nearest drawing already owns a label (the p32 grid is regular, so a
page-scoped grid pass is the right shape, not a wider radius); (b) resolve an
example-scoped token to the example's compound set and attribute as a set, or
refuse with `document_declares_mixture`; (c) split `label_not_read` into
`structure_exists_label_unattached` vs `not_a_compound_designation`.

Live check of the new promotion pass: run 20261113014801 promoted `I-35-2`
(unlabelled p156 drawing, printed 250.1) — the mechanism works, it just needs
unambiguous masses.

## Re-extraction must go through reingest, not submit_extraction (2026-11-13)

`submit_extraction` on a document that already has evidence fails closed:
`source evidence batch is immutable: it would drop 3272 existing id(s)` — the
Extract producer mints canonical SQL evidence and refuses to replace an existing
set. Changing anything in the detection/label path therefore requires
`reingest_document` (which clears pipeline outputs first), not a second Extract.

Cost to remember: reingest re-mints measurements, so agent/human attribution rows
keyed by measurement id do not survive it — the adjudications already written for
94dd (I-281, I-109, I-266-A) have to be re-applied after the re-extraction.

## The 94dd reingest regression: p32 yields 15 crops, most of them fragments (2026-11-13)

After `reingest_document(94dd6070bbd4)` the same page 32 that had produced three
full compounds now produces **15 crops**, and the reads are dummy-atom fragments
(`*C1CC(NC(=O)c2cn(CC(C)(C)O)nc2Cl)CC(F)(F)C1`) instead of complete structures.
Scoreboard fell 34/42 → 15/42 (`label_not_read` 22, `structure_detected_unmatched`
5). Nothing in the detection or recognition path changed in this session, so the
difference is in how the crops were cut, and the crop files were overwritten —
the previous run's boxes are gone.

Measured from what survives: crop `page_0031_mol_0001.png` is 421×297 px for a
bbox of 132×93 pt, i.e. ~230 DPI (Extract renders at 144), so the crop has grown
with padding while the box shrank. Two candidate causes, to check in this order:

1. MolDet split a drawing at internal whitespace (one compound → several boxes,
   each reading only its own fragment). Compare the 15 boxes' x-extents on p32:
   if they tile a single drawing's width, that is the cause.
2. A padding change grew the crop beyond the box while MolParser still frames on
   the original box, so it reads the surroundings instead of the whole structure.

Do not reingest again until one of these is confirmed: each reingest destroys the
detection set that would show the difference, and 94dd is now the only document
at the regressed count (the other five keep their earlier extractions).

## CORRECTION: the labels are read; they sit *inside* the detected drawing box (2026-11-13)

The "p32 became fragments / MolDet split the drawing" explanation was wrong. The six
dummy-atom crops on p32 are the 式I template at the top of the claims page; the nine
compounds are intact and now carry `1-1` … `1-9` (evidence: `1-2` = exchange-coupled
C25 structure at bbox 252.33,442.42,338.71,523.78). The letterless-series rule works.

The regression is label *pairing geometry*. Live read of p137 returns 19 text blocks
including `1-255-A`, `1-256-A`, `1-257-A`, `1-255-B/C/D`, `1-256-C/D`, `1-257-B/D`
(all `kind: figno`), so the number is present and read. But the caption sits **inside**
the detected drawing box: `1-256-A` at PDF y 372.49–380.82 → top-down 461.2–469.5,
while I-256-A's drawing box is top-down 387.3–481.7. `_printed_at_a_drawing` (and the
producer's head/foot bands) only look *outside* the box, so a caption printed within
the drawing's own lower strip is neither head nor foot and never attaches.

That is why the scoreboard fell 34/42 → 15/42: roughly seventy `A-R` captions in the
compound-list pages (p137–p142) land inside their drawing's box, so their readings lost
the structure. Designations 594 → 520, candidates 569 → 505.

Fix to write: when a designation block lies inside a drawing's box, treat it as that
drawing's caption iff no other drawing claims it and the block is in the box's lower
strip with no other drawing's box overlapping it; keep the current head/foot rules
first so nothing that already attaches is disturbed. Then reingest once and re-check
the scoreboard before anything else.

## The real class: a stereoisomer family captioned "A or B or C or D" (2026-11-13)

Counter-example to "the document gave no structure", 8cb5 (CN120943813A) page 50.
Four drawings sit in one row, and all four are read correctly as four distinct
stereoisomers of one constitution:

| bbox (top-down) | read |
| --- | --- |
| 113.74,443.14,197.25,582.09 | `CC(C)(O)Cn1cc(C(=O)N[C@@H]2CCCC[C@H](Nc3cc(C(F)(F)F)nc4ccc(Cl)cc34)C2)c(Cl)n1` |
| 210.93,443.50,295.16,582.09 | `…[C@H]2CCCC[C@@H](…)…` |
| 310.64,443.14,394.15,582.09 | `…[C@H]2CCCC[C@H](…)…` |
| 407.11,443.14,490.97,582.09 | `…[C@@H]2CCCC[C@@H](…)…` |

Under them the page prints four captions, each a four-way list in a different order
(`1-P2 or 1-P1 or 1-P3 or 1-P4`, `1-P1 or 1-P2 or 1-P3 or 1-P4`, `1-P4 or 1-P1 or
1-P2 or 1-P3`, `1-P3 or 1-P1 or 1-P2 or 1-P4`) — the leading token is that
drawing's own designation, the rest are the stereoisomers it may be supplied as.
The bare-token rule rejects the phrase on purpose, and "one number names one
drawing" cannot map four numbers onto four drawings, so all four readings
(`1-P1`…`1-P4`) stay unowned and are recorded as `label_not_read`.

So this is a *notation* gap, not a missing structure: the pipeline has no
representation for a stereoisomer family. The fix: parse an `A or B or C or D`
caption, take the leading token as the drawing's designation and the rest as
accepted alternates, and require the drawings it names to share formula/mass
(which is what `or` means). The same shape covers 94dd's `实施例15 组分1/2`
("I-233-A、I-233-B、I-233-C、I-233-D 中的一个或两个") and `19-P1 or 19-P2`.

Reading-level coverage now reports `designation_group_caption` separately
(declared in `docs/known-limitations.md`), computed on read from the document's
own evidence (`db.measurement_store.group_caption_designations`), so these
readings no longer inflate `label_not_read`. Nothing in the binding path changed.

## 94dd after the caption-inside-box fix: persistence is fine, label spelling is not (2026-11-13)

Reingest `20261113082742` + Patent `20261113083452` with `7c589a8` still gives
15/42, and the next link is *not* persistence: `verify_structures` reports **1496
structures** for the document. What is wrong is narrower:

- `search_molecules("I-233-A")` and `verify_structures(label="I-256-A")` find
  nothing, while page 137's molecule evidence carries `name: "I-233-A"` /
  `"I-176-A"` with `label_source: page_text`. So the drawings and their labels
  exist; the label does not reach the *molecule* record under the spelling the
  activity table uses (`I-` vs the page's `1-`).
- **41 printed MS lines, only 12 structures own one** (`printed_ms_unowned: 30`).
  The characterizations therefore have almost nothing to bind to, which also
  disables the mass tie-break and the reprint recovery on this document.

Next: compare `designation_key` on a molecule's `label_keys` (`1-256-A`) against the
reading's `reference_key` (`I-256-A`) and fix the one place that does not reconcile;
then make MS-line ownership work again (12/41 is the metric to watch).

## p137: the outer columns get their captions, the inner ones do not (2026-11-13)

Measured on the current extraction (`verify_structures(page=137)`): the four
`I-255-*` drawings of one row carry `I-255-A` (leftmost, bbox x 113.38–204.81) and
`I-255-D` (rightmost, 435.90–526.97) with `label_keys` `[1-255-A, I-255-A, …]`,
while the two middle drawings (x 212.73–304.16 and ~304–390) have
`printed_labels: []` — and the I-256-A structure (`…C2)cn1`, bbox
113.38,387.34,211.29,481.66) is one of the unlabelled ones. The page prints
`1-255-A/B/C/D`, so B and C are read and then dropped.

So the attachment is not failing at OCR nor at the token rule (both fixed), and not
at persistence; it is the **column/greedy matcher** in `assign_text_labels`: a
print that sits between two drawings of one row is either assigned to the wrong
column by `_column_of` or loses the one-drawing-one-number race. Next: instrument
that page (four drawings, four captions, one row) as a unit test and fix the
column rule — the four-caption row is the smallest failing case and covers p137,
p139–p142 and p32.

Also still open from this run: `printed_ms_unowned` 30/41 and extraction that
returns different boxes on each run (three runs, three geometries).

`c1fc4fe` measured: reingest `20261113084959` + Patent `20261113085743` took
CN121717757A from **15/42 to 27/42** (label_not_read 20 → 11, sdm 5 → 2), and the
six-document total back to 187/235. The caption-row rule was the whole of it: a
print inside a drawing's columns is now also tried at the head, and a foot pairing
carries its real distance so a caption between two rows belongs to the nearer one.

Remaining on that document: `label_not_read` 11, `designation_group_caption` 2,
`structure_detected_unmatched` 2, plus `printed_ms_unowned` and the run-to-run
detection instability.

Same fixes on CN120943813A (reingest `20261113090006`, Patent `20261113090658`): **no
change, 24/45** — its gap is `structure_detected_unmatched` 7 plus the 9 declared
`designation_group_caption`, not caption geometry. So re-extracting the remaining
four documents buys almost nothing (their `label_not_read` counts are 3/0/1/1);
the next real target is `structure_detected_unmatched` (17 readings across the six),
which is Patent-stage only and needs no re-extraction.

## `structure_detected_unmatched` on 8cb5: the drawing *is* named after the designation (2026-11-13)

The seven `sdm` readings of CN120943813A are all in the page-94 IC50 table
(designations `43`, `44`, `48`, `6-P2`, `19`, …). For each, the review payload
lists a candidate whose **`name` is exactly the designation** — e.g. `44`:
`Cn1cc(C(=O)N[C@@H]2CCC[C@H](Nc3c(F)c(C(F)(F)F)nc4ccc(Cl)cc34)C2)cn1`, page 90,
bbox 113.74,559.05,209.13,707.01 — and the reading still has no attribution.

So this class is not a label problem at all: the molecule row carries the right
name, and the reading still does not bind. That points at the **compound-entry**
side of the association (an entry for `44` either missing or left
`structure_status != resolved`, which is also why the review item's own reason says
`designation_without_structure` while the dataset says `structure_detected_unmatched`
— the two disagree about the same reading, and that disagreement is itself the bug
to fix first).

Next: take designation `44` on that page, print the entry rows the Patent stage
extracted for it, and make the two reason paths read the same source of truth.

## The designation-ownership fallback is in, but it does not reach the reading (2026-11-13)

`3171c4a` adds, at the end of `associate_facts`, a deterministic binding: a reading
whose designation exactly one persisted candidate owns takes that candidate's
SMILES, whether or not any entry declared it. The review item's reason now comes
from the same drawings, so queue and dataset agree.

Live check: Patent `20261113092856` on CN120943813A is **unchanged** (24/45, sdm
still 7). So either the fallback's ownership test rejects these rows
(`candidate_owns_designation` for a molecule whose only label is its own name), or
`mol_id` set here is discarded because the published attribution is recomputed from
entries downstream in `measurement_records._resolve_structure`, which returns
`direct or indirect` only when an entry exists.

Next: instrument one reading end to end — print `measurement["mol_id"]` right after
`associate_facts` and again in `measurement_attributions` — and fix whichever of the
two drops it. Do not add more rules before that is measured.

## Reading p94 for real: the table's second pair of columns is by 实施例, not by 化合物 (2026-11-13)

The page itself (`inspect_visual page_text`, p94) prints one four-column table whose
**both headers say 化合物编号**:

```
| 化合物编号 | MRGPRX2 IP-1 IC50(nM) | 化合物编号 | MRGPRX2 IP-1 IC50(nM) |
| 化合物1-P4 | 21 | 实施例 29 | 29 |
...
| 化合物19  | 66 | 实施例 43 | 40 |
| 化合物20  | 20 | 实施例 44 | 17 |
```

The right-hand cells read `实施例 29 … 实施例 50`, i.e. they cite **examples**, and the
header is wrong (both say 化合物编号). Our extraction stored those rows in the
compound space: `实施例 44` became `compound 44`. That is a semantic flattening
defect that will bind the wrong structure whenever an example's number differs from
the compound it prepares (it happens to coincide for 实施例44 → 化合物44, which is
why `44` looks like a binding problem rather than a reference-space problem).

So `structure_detected_unmatched` on this table is at least partly this: the reading
is asking for `化合物43/44/48` when the document said `实施例43/44/48`.

Fix: when a cell's own text carries an example prefix, that wins over the column
header — `label_space` is a default, not a rule — and the reading lands in
`@example:N`, where the existing example-product binding already knows the compound
the example prepares.

Still unmeasured: why the entry-free ownership fallback (`3171c4a`, `b4e908e`) does
not bind `化合物44` to the p90 drawing named 44. Run `20261113093503` is unchanged at
24/45. Instrument that reading end to end before changing more rules.

## The example→product chain reads `section.raw_text`, which the artifact does not carry (2026-11-13)

Measured on CN120943813A after two fixes (`167fe49`, plus the own-text trim): the
issue count is **unchanged at 139**, and `designation @example:10 …:32 … has no
recognized structure` is still reported ~45 times. So the identity resolution never
fires.

What the artifact actually shows:

- `sections` (45) expose `section_id / title / kind / page_start / page_end` and
  **no raw text**; the product statements live in `source_evidence` rows.
- `entries` (94) include the p94 table's own rows as entries with **`section_id: ""`**
  (`化合物1-P4`, `化合物6-P2`, `实施例 45-P1`, …) — declared from a passage that belongs
  to no section, so nothing joins them to a drawing or to a section.
- the section that swallowed the table (`实施例50`) holds `化合物19…26` entries whose
  `entry_role` is `example`, i.e. the table's left column was read as that section's
  compounds.

Consequence: every rule that resolves an example through its product statement
(`_example_product_entry`, and the identity pass added in `167fe49`) reads
`section.raw_text`; if the section object reaching association carries no raw text,
that resolution is dead for the whole document — which is exactly what "45 examples
unresolved" looks like.

Next: build the product text from the section's body evidence rows
(`body_evidence_ids` → `raw_text`, which association already has via
`valid_evidence_ids`/the evidence store) and pass that to `declared_product_labels`,
then re-run Patent only. Do not touch the section splitter before that is measured.

## The blocker is one rule: "majority of its own drawings" ownership (2026-11-13)

Three fixes in a row (`167fe49`, `3dcea5b`, and the identity pass) left CN120943813A
at exactly 139 issues, so I stopped guessing and ran the real section text through
the rules:

```
_own_example_text(p90 blocks, "实施例44")  →  "...1.27 (m,1H)."          # right cut
declared_product_labels(own)               →  ['化合物44']                # one product
```

Both correct. So the chain dies one link earlier: the **product entry** `化合物44`
is itself unresolved, and an identity can only inherit a resolved product. Why it is
unresolved is the rule visible in the issues list — `molecule_candidate_ambiguous:
compound label 24 matches multiple Detection candidates`.

`candidate_owns_designation` requires a designation to be the **strict majority of
that structure's own drawings**. A compound printed twice (``44`` once, something
else once — a second printing that read a different number) therefore owns *neither*
name, the entry stays `structure_type: missing`, and every reading that cites it is
unowned. This is the same rule that defeated the entry-free binding fallback earlier
(`3171c4a`, `b4e908e`).

Proposed rule, to implement with a test: a structure owns every designation any of
its drawings printed, contested only when a *different* structure printed the same
designation — uniqueness across structures, not majority across its own drawings.
Do not implement it blind: it changes which entry wins everywhere, so measure
`molecule_candidate_ambiguous` count and the six-document scoreboard before/after.
