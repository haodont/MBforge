# RSI evidence log — the patent-binding loop, 2026-11-12/13

Evidence that the agent's own improvement process works, written down as it
happened rather than reconstructed. Every entry cites the probe output that moved
the decision, the commit that changed the code, and the measured effect. Failures
are kept: they are the part that shows the loop is real and not a narrative.

## The loop that produced the gains

1. **Measure the gap** with the canonical read (`query_activities` → `stats`),
   never from Markdown or a printed table.
2. **Classify the reason** (`unattributed_by_reason`) and pick one class.
3. **Probe the real document** — one log line at the rule that decides, or call the
   rule directly on the text the page prints. Guessing first was tried four times
   and failed every time (see "Wrong turns").
4. **Fix the smallest thing the probe justifies**, with a unit test that encodes the
   document case.
5. **Re-run the cheapest stage that touches the fix** (Patent ≈ 1 min, Extract
   reingest ≈ 7 min) and read the scoreboard again.
6. **Write the finding where the next session will look**: `TODO/INDEX.md` (facts and
   next probe), `docs/known-limitations.md` (what is deliberately unsupported), and
   `agent/skills/patent-binding-repair/SKILL.md` (the procedure).

## Measured series (readings attributed / total, six CN patents)

| when | scoreboard | what changed |
| --- | --- | --- |
| session start | 143/235 (61%) | deterministic rules only |
| after agent adjudication | 175/235 | example-scoped binding, batch cohort writes |
| after label/spelling work | 187/235 | caption geometry, `1-`/`I-` spellings |
| after caption-row fix | 188/235 | a four-caption row kept its inner columns |
| after Patent-only re-runs | **196/235 (83.4%)** | characterization cap, example-heading ownership, duplicate collapse, mass "any line" |

## Iterations that moved the number

| symptom (measured) | probe evidence | fix | effect |
| --- | --- | --- | --- |
| 94dd 15/42 after a reingest | `verify_structures(p137)`: `1-255-A`, `1-255-D` labelled; inner columns blank; caption at y 461–470 inside a box ending 482 | `7c589a8` caption inside the swallowed box | enables later +12 |
| same, still 15/42 | caption sits inside the columns but **above** the drawing → judged a foot caption and dropped | `c1fc4fe` try the head too; foot carries its real distance | **15 → 27** |
| `search_molecules("I-233-A")` empty | `compound_label_key("1-256-A") == None` — the bare branch allowed one suffix group, the token has two | `bb80285` digit-headed series = lettered series, with spelling variants | unblocks the whole series space |
| 8cb5 24/45, 7 sdm | `owned=2 names=['44','44']` — one drawing detected twice | `cb47622` + SMILES dedupe before the one-owner rule | 24 → 25 |
| 8cb5 25/45 | `chars=60` while the document prints hundreds; page 90 (实施例44) produced **no** characterization | raise `MAX_CHARACTERIZATIONS` | 60 → 177 characterizations; issues 139 → 221 (new information, not damage) |
| 8cb5 25/45 | `key=44 printed=[470.2, 478.2]`, right structure off by 0.063 Da, still rejected | "a single molecule cannot explain two masses" → one match + exactly one candidate | **25 → 26** |
| five other documents | the four fixes above are Patent-stage | Patent-only re-run, no re-extraction | 188 → **196** |

## Wrong turns (kept on purpose)

Each was a confident hypothesis that a probe destroyed. They are why step 3 exists.

1. **"MolDet split the drawings into fragments."** The six dummy-atom crops on p32
   were the 式I template at the top of the claims page; the nine compounds were
   intact. Killed by listing the page's evidence with bboxes.
2. **"The table's columns were flattened into the compound space."** The parser was
   correct: `实施例 44 → key 44, type example`. Killed by calling
   `_parse_simple_activity_table` on the page's own markdown.
3. **"Ownership should be uniqueness across structures, not a majority."** Measured
   by trying it: it broke a cross-structure contest the old rule handled well.
   Reverted; the surgical fix (dedupe of same-SMILES detections) was right.
4. **"The mass tie-break has no data."** It had data; the comparison asked for *all*
   lines to match, which no single molecule can satisfy.

## Artifacts the loop produced beyond the fixes

- `docs/known-limitations.md` — a class the pipeline now **declares** unsupported
  (one caption naming a stereoisomer family) and reports as
  `designation_group_caption` instead of hiding it in `label_not_read`.
- `explain_reading` capability — one read that returns the six links between a
  printed reading and its structure, plus the next step. It exists because every
  diagnosis in this log rebuilt that chain by hand.
- `agent/skills/patent-binding-repair/SKILL.md` — the procedure, including the four
  caption bands, the `1-`/`I-` equivalence, the group-caption class, and "verify the
  rule on the text before re-running the pipeline".
- `TODO/INDEX.md` — every measured fact and the **next probe**, so a new session
  resumes at the frontier instead of at the beginning.

## What is still manual (the honest gap for RSI)

The loop is agent-driven: the probe is written by hand each time, and the choice of
which rule to instrument is judgement. Turning this into self-improvement needs:

1. a registry of diagnosis recipes ("no structure" → these five probes, in order),
   so the agent does not re-derive them;
2. auto-instrumentation: run the pipeline against a single reading with the deciding
   rule's inputs logged, instead of editing logging into the source;
3. a scoreboard that is a first-class artifact (per document, per reason code, with
   run ids), so "did it improve" never depends on memory.

Items 1 and 3 are partially covered today (the skill and `TODO/INDEX.md`); item 2 is
the missing piece, and `explain_reading` is its first read-only half.
