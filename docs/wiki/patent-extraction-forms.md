# Patent extraction forms (real-corpus catalog)

Design input for the deterministic Patent stage. Every parser rule must name the
published form it handles and the form it must refuse; this page records those
forms with the real strings they were observed in, so a rule is never written
from memory. When code and this page disagree, the code wins and the page is
wrong.

## Corpus and provenance

Thirteen real MRGPRX2 patents (CN/US/WO/KR/JP/IL), 23–400 pages, extracted into
an isolated library (`Extract` → SQL evidence) and analysed by the
deterministic path (`patent_analysis.enabled=false`). Sources: the `03-patent`
set gathered from CNPatent, Espacenet and SciFinder exports. Nothing here is a
synthetic sample: every example string below was read from `source_evidence`
or from a published artifact.

Status vocabulary used in every table:

- **handled** — the parser recognizes this form and the artifact shows the fact.
- **refused by design** — the parser deliberately reports instead of guessing.
- **open** — observed in the corpus, not handled yet.

## 1. Document structure and headings

| Form | Real example (source) | Status |
|---|---|---|
| Chinese numbered example | `[0143]实施例7` | handled |
| Example whose number runs into a chemical name | `[0095] 实施例1N-((1R,3S)-3-…的合成` — the label is `1`, `N-` starts the name (CN121270515A) | handled |
| Publication paragraph marker | `[0144]`, `(0159)`, `143.` prefixes on nearly every block | handled |
| English example with dash title | `Example 2—Screening of Compounds` (US20260027089A1) | handled |
| Lettered example | `Example A. MRGPRX2 FLIPR Calcium Mobilization Assay`, `Example E50:(first eluting)` (US20250206734A1, IL292693A) | handled |
| Group heading without a number | `[00114] Examples`, `EXAMPLES` (IL292693A, US) | refused by design (no fact keyed to it) |
| Prose that starts like a label | `Examples of 6,6-fused heteroaryl groups include…` | refused by design (only an uppercase letter labels an example) |
| Japanese heading | `【実施例】`, `実施例1` (JP2023544789A) | handled — one vocabulary entry turned that 400-page filing from 1 section into 85 examples |
| Chinese bioassay heading | `[0144]生物活性研究(一)本发明化合物对MRGPRX2的抑制活性` (CN121270515A) | handled |
| Numbered assay subsection | `3. 检测结果`, `(二)…选择性`, `(三)…代谢稳定性` (CN121270515A) | handled |
| Protocol sentence inside a step | `3. 稳定性测定步骤a. 将198 μL肝细胞移液到96孔平板` (WO2025223036A1) | refused by design (length + unit/pipetting words) |
| Generic numbered step | `1. 材料与仪器` (CN121270515A) | refused by design (no assay domain word) |

Consequences in the corpus: 12 of 13 documents yield sections. Before this
round US20250206734A1 yielded 0 sections and 0 assays (it is assay-lettered),
WO/KR yielded 0, JP2023544789A yielded 1, and CN121270515A's assay sections did
not exist at all. Prose that merely looked like a label (`Examples of 6,6-fused
…`, `Example s`) had started to be cut as sections and was removed again.

## 2. Compound designations and references

| Form | Real example (source) | Status |
|---|---|---|
| Numbered compound | `化合物1`, `化合物44` (CN120329282A) | handled |
| Numbered compound with a suffix | `化合物77-A`, `化合物77-B` (CN120329282A) | handled |
| Example as the compound's identity | `实施例2` indexes the activity table though the section never prints `化合物2` (CN121270515A) | handled, document-local |
| Internal code | `E020` (US20260027089A1), `IGP-20024-01` (CN) | handled |
| Cross-patent reference compound | `4（化合WO2022067094物1）` — compound 4 of another publication (CN121270515A) | refused by design (`compound_reference_unresolved`) |
| Multi-compound list in prose | `Examples 4, 25, 28 and 30 exhibited a pIC50 ≥ 8.0.` (WO2022152853A1) | open (one measurement, reference unresolved) |
| Lettered bin inside a title | `A: …` in a legend line | see §4 (scale symbol, not a compound) |
| Mass reading that looks like a number | `参考实施例1方法，制得化合物36.8mg，收率16.5%` (CN121270515A) | refused by design (quantity after the token) |
| Chemistry-named example | `实施例1：N-(5-(3,5-二氟苄基)噻唑-2-基)-2-甲基丙硫酰胺` (WO2025002360A1) | handled (example identity entry) |

Design rule the corpus forced: `实施例7` and `7` are different key spaces
(`@example:7` vs `7`), and an example designates only the compound its own
section prepares — a bare number never borrows another section's compound.

## 3. Activity data forms

| Form | Real example (source) | Status |
|---|---|---|
| Matrix table, one row per compound | `\| 化合物编号 \| IC50(nM) \|`, rows `\| 实施例1 \| …` (CN121270515A p21) | handled |
| Header split over two rows | metric row `\| 化合物编号 \| IC50(nM) \| \| \| \|` + target row `\| MRGPRX1 \| MRGPRX2 \| MRGPRX3 \| MRGPRX4 \|` (CN121270515A) | handled |
| Repeated (label, value) column pairs | `\| 实施例编号 \| MRGPRX2 抑制 \| 实施例编号 \| MRGPRX2 抑制 \|`, row `\| 1 \| ++++ \| 2 \| ++++ \|` (CN121270515A p20) | handled (the metric word is read out of the header cell, and the header's own space decides whether a row label is `实施例N` or `化合物N`) |
| Metric qualified by its target inside one header cell | `\| \| CYP3A4(咪达唑仑)抑制率(%) \| CYP3A4(睾酮)抑制率(%) \|`, rows `\| 化合物77 \| 26.3 \| 31.7 \|` (CN120329282A p113) | handled (metric `抑制率`, unit `%`, and the substrate kept as `provenance.column_target`) |
| OCR-dropped label across sibling pairs | `\| 5 \| ++++ \| \| ++++ \|` (CN121270515A p20; image prints `6`) | refused (a blank Markdown cell does not prove a span or an owner) |
| Qualitative bins | `++++`, `+++`, `++`, `+` (CN), `A/B/C` bins (KR/WO) | handled (ordinal rank + scheme) |
| OCR plus-sign substitution | `十` where the table means `+` (CN121270515A) | handled (normalized to `+`) |
| Bin legend outside the table | `注：“+”：IC50>1μM`, `“++”100nM<IC₅0<1μM`, `“++++"1nM<IC50<20nM` (CN121270515A) | rule extraction collects document legends; LLM packets cite bounded nearby context as candidate scope, never a document-wide default |
| Bin scale with letter labels | `A: IC50 < 500 nM, B: 500 nM ≤ IC50 < 1 uM, C: 1 uM ≤ IC50 < 3 uM` (WO2025163462A1, KR20250121245A) | refused by design (scale definition, not a measurement) |
| Log-scale single value | `E020 \| 6.9` under `MrgprX2 Antagonist pIC50` (US20260027089A1) | rules refuse the damaged table; v4.2 LLM recovers only the quoted E020 cell in the selected p63 chunk (one reading, not whole-page recall) |
| Prose value with a named compound | `Compound 21 showed an IC50 of < 0.1 μM.` | handled |
| Prose value without a compound | `本实验测得 IC50 小于 100 nM。` | refused by design (`activity_reference_missing`) |
| Percent inhibition / fold / range values | `%`, `fold`, `< 0.1 μM` forms | handled by value normalization |
| Structure column OCR noise | `\| N. HN S \| 6.4 \|`, `\| H3C \| 6.6 \|` (US20260027089A1, WO2025223036A1) | refused by design; v4.2 also refuses the selected US p60 chunk rather than attach 6.4 to a separately printed E003 |
| Printed positive control | `阳参化合物 \| 0.2` under `MRGPRX2 拮抗剂活性IC50(nM)` (CN120943813A p95) | all five table readings retained; explicit IC50 wins over generic activity wording; control stays unresolved, pending and unlinked |
| Unparsed metric tokens | `ICs0`, `IC₅0` (subscript OCR), `ρIC50` (JP), `Λ:` for `A:` | open (`activity_value_unparsed`; 45 occurrences in JP2023544789A) |

Fail-closed contract: a table is published only when **every** non-empty value
cell becomes a record attributed to a compound designation. Otherwise the whole
table is reported as `complex_activity_table` and no deterministic measurement
is written. Opt-in LLM table gaps may instead propose individually grounded
cells for review; pipe-table drafts must preserve the full row, exact printed
label/value cells and zero-based value column. This is not a completeness claim.

## 4. Assay sections and attribution

| Form | Real example (source) | Status |
|---|---|---|
| Chinese assay block | `生物活性研究(一)本发明化合物对MRGPRX2的抑制活性` (CN121270515A) | handled → assay method with target |
| English lettered assay | `Example A. MRGPRX2 FLIPR Calcium Mobilization Assay`, `Example B: MRGPRX2 IP1 HTRF Assay`, `Example C: MRGPRX2 β-Arrestin Assay`, `Example D: Caco2 Assay` (US20250206734A1) | handled (9 methods) |
| Named assay protocol block | `Assay Protocol` (WO2022152853A1) | open (no numbered/bracketed marker) |
| Assay declared only by a table caption | `Table of Assay Data for the Assays of Examples A-C` (US20250206734A1) | open |
| Assay section absent entirely | WO/KR tables sit under prose only | open (`assay_method_unresolved`) |

Effect: CN121270515A went from 12 `assay_method_unresolved` to 0 and 8 of its 12
measurements became fully linked (compound + assay). CN120329282A still holds 24
measurements with no assay section of a recognized form.

## 5. Table and provenance forms

| Form | Real example (source) | Status |
|---|---|---|
| Markdown pipe table from layout | `\| 化合物编号 \| IC50(nM) \| …` | handled |
| HTML-rendered table | `<table>…</table>` normalized to markdown | handled |
| Missing label with a printed value | `\| 5 \| ++++ \| \| ++++ \|` (CN121270515A p20) | refused by design (unattributable cell blocks the table; inspect the image) |
| Synthesis table | `The following compounds were synthesized using a similar method…`, `LCMS Method` (US20260027089A1) | refused by design (not an activity table) |
| Characterization / NMR table | `\| No \| 7至 \| 号B2 \| 0日 \|`, `H NMR (400 MHz CDCl) δ …` (KR20250121245A, JP) | refused by design |
| Materials table | `\| 试剂和耗材 \| 来源 \| 批号 \|` (CN121270515A) | refused by design |

## 6. Text-quality and language forms

| Form | Real example | Status |
|---|---|---|
| Machine-translated English | KR20250121245A and WO2025163462A1 contain no Hangul/Kana and no `Example`-style headings — they are translated texts | open (heading vocabulary cannot match a translation that dropped the label) |
| Paragraph markers everywhere | `[0267]`, `[0095]` | handled |
| Scanned or structure-heavy pages | US20260027089A1 pages whose text is entirely structure fragments | refused by design (no fact invented) |
| Subscript / glyph damage | `IC₅0`, `ICs0`, `ρIC50`, `Λ:` | open |

## 7. Problems ledger (issue code → form → state)

| Issue code | Form that raises it | State |
|---|---|---|
| (none, fabricated facts) | scale-legend lines read as measurements — 15 invented values across CN/KR/WO | fixed: definitions are skipped, bins are not values |
| `activity_reference_missing` | prose value that names no compound | correct report |
| `activity_value_unparsed` | OCR/glyph variants, unparseable prose | to reduce (JP: 45) |
| `complex_activity_table` | split header, merged cells, structure-noise rows | deliberate refusal → LLM/hybrid input |
| `compound_reference_unresolved` | cross-patent compound, unresolvable label | correct report |
| `compound_entry_ambiguous` | several compounds claim one example label | correct report (split headings deduped) |
| `assay_method_unresolved` | no assay section of a recognized form | reduced (CN125: 12→0); CN120329282A: 24 open |
| `molecule_label_unresolved` | no recognized structure carries the designation, or the candidate carries no label at all | reported per entry (info) and handed to the model as a gap |
| `molecule_candidate_ambiguous` | several candidates claim one designation | reported; the model decides from the excerpt |
| ~~`dangling_fact_reference`~~ | a printed designation no section declares | **removed**: the rules now declare the printed designation themselves (`association._declare_entry`, review pending), so no reading is left ownerless |

## 8. Design rules these forms forced

1. **Fail closed per table** — publish only a fully attributed table; otherwise report.
2. **Never invent a number** — a bin's stated range is a definition (legend), never a value; unknown stays unknown.
3. **Report, do not guess** — unresolvable references and ambiguous owners become issues, not links.
4. **Declaration beats inference** — a compound the section prints wins over the section's own identity.
5. **Document-local identity** — `实施例N` means the compound that section prepares; no global alias, separate key space (`@example:N`).
6. **Forms must be named** — a rule is added only with a corpus example and a test that pins the rejected neighbour (prose that looks like a heading, protocol sentence, mass reading).
7. **The header states the key space** — a label column headed `实施例编号` prints example numbers, so its bare cells are `@example:N`, never compound `N`.
8. **A printed designation declares itself** — a row or sentence that prints a designation declares it for the document (review pending) even when no section does; the rules never leave a reading without an owner.
9. **Blank is not a span** — a missing label in Markdown may be OCR loss. Never inherit a neighbouring designation without explicit source span evidence; CN121270515A p20 prints `6`, not a second reading for `5`.

## 9. Where each form is handled

- Headings and identity: `service/pipeline/patent/sections.py` (`match_section_heading`, `match_assay_heading`, `example_token`, `parse_source_evidence_sections`).
- Entries and assay methods: `service/pipeline/stages/patent_stage.py` (`extract_entries_from_title`, `extract_entries_from_body`, `_example_identity_entry`, `_mentioned_labels`, `_ASSAY_HINT_RE`, `_ASSAY_ENDPOINT_MAP`).
- Activity extraction: `service/pipeline/activity/extraction.py` (prose pass, scale definitions, document legend), `activity/parsing/tables.py` (`_TableLayout`, `_read_table_layout`, `_is_row_label`, `_simple_activity_table_is_complete`), `activity/normalization.py` (`normalize_reference_label`, `extract_qualitative_legend`).
- Association: `service/pipeline/patent/association.py` (document-local example resolution, dedupe, ambiguity).
- Contracts: `domain/activity.py` (`MeasurementValue` qualitative rank/scheme/label), `domain/patent.py` (`EXAMPLE_KEY_PREFIX`).

## 10. Open forms, by expected yield

Measured after this round (`uv run python .tmp/e2e/activity_recall.py`, zero tokens,
all 13 documents): 31 activity tables, **6 parsed** (3 before), **52 measurements**
(36), **47 with a declared owner** (30), **16 with a resolved molecule**.

1. **15 activity tables whose header names only assays, or whose metric sits in a
   rotated cell below the separator** (US20210128561A1, US20250206734A1 ×2,
   US20260027089A1 ×12). The metric lives in a caption or a later row and the
   designations sit on other evidence rows; the model is the tool for these — its
   `table` gaps already carry the chunks — and stitching evidence rows by hand
   would guess.
2. **The structure behind a declared designation** (247 of 310 corpus entries still
   carry no `entity_id`): the rules declare the print, the model binds the structure
   (`list_molecules(label=…)` plus a link). The candidate's own label usually differs
   from the print (`77A` vs `化合物77`), which no rule can bridge.
3. **Glyph damage**: JP2023544789A's unparsed values (`ρIC50`, full-width digits) and
   `ICs0` / `IC₅0`-style headers.
4. Machine-translated documents: heading labels were dropped in translation.
5. Plural/list references (`Examples 4, 25, 28 and 30`) could split into one
   measurement per listed compound.
6. Ambiguous designation forms, including CN120943813A's disjunction
   `化合物 4-P2 or 4-P4` and WO2025002360A1's `79`. The printed
   `阳参化合物` control is now recognized; see the dated harness audit rather
   than treating the historical corpus counts above as a current rerun.

## 11. Name, spectra and synthesis-route forms (measured over all 13 documents)

Added by the deterministic extraction pass. These three families are **rule/code
only, zero token**: the LLM never writes a name, a spectrum or a route, it may only
associate an already-extracted item with an already-identified structure and
correct a structure behind a review item.

That association may also **declare** a designation the rules could not bind: the
entry is minted from the printed label (`review_status="pending"`), the reading that
cites it carries the structure in `measurement.mol_id`, and the second association
pass binds them — so an activity whose designation no section printed still reaches
`molecules.activity` instead of stopping at the artifact.

The same link attributes the passage it cites: a spectrum, a printed name or a
preparation route that names no designation in its own text takes the label when
exactly one such passage sits on the cited evidence row and exactly one link claims
that row. A row carrying two spectra, or two links over one row, stays unattributed.

| form | one real string | rule location | status |
| --- | --- | --- | --- |
| Chemistry name in a title, verbatim | `2-((3,5-二氟苄基)氨基)-5-硝基苯甲酸甲酯` (CN120943813A) | `patent_stage.extract_compound_names` | extracted |
| Hydrogen spectrum line | `1H NMR (400 MHz, CDCl3) δ 7.42 (s, 1H)` (CN120329282A) | `patent_stage.extract_characterization` | extracted |
| Mass spectrum line | `化合物77：MS (ESI) m/z: 456.2 [M+H]+` | same | extracted |
| Elemental analysis | `Anal. Calcd for C13H10FN3O: C, 63.15; H, 4.08; N, 17.00` | same | rule live, zero corpus hits |
| Preparation route, body of an existing example | `参考实施例1方法，制得化合物36.8mg，收率16.5%。` | `patent_stage.extract_synthesis_routes` | extracted |
| Route step split | `步骤1：将中间体与酸反应。` | same | extracted |
| Printed yield | `收率41%` | same | extracted |

Measured on the 13-document corpus (zero tokens, `fabricated = 0`):

| family | count |
| --- | --- |
| hydrogen spectra | 407 |
| mass spectra | 268 |
| elemental analyses | 0 |
| synthesis routes | 179 |
| route steps | 80 |
| printed names | 5 |
| mass mismatches raised for review | 1 |

Two findings this measurement forced:

1. **Synthesis routes carry no heading.** `合成路线` / `合成方法` were removed from
   the heading vocabulary because no document in the corpus prints such a heading —
   routes are pulled from the body of the existing `实施例` / `制备例` / `Example`
   sections instead. Adding a heading rule would have matched nothing and invented
   a form the corpus does not contain.
2. **Printed chemistry names are rare in titles.** Only 5 of 13 documents name a
   compound in the title; the rest print `实施例N`, `実施例7` or `…的合成`. The
   name rules are narrow on purpose (a real string plus the rejected neighbor), so
   the yield is small and honest rather than large and guessed.

Fidelity invariant, checked mechanically: **every emitted string must be a
substring of the evidence row it cites**; an item whose text is not found in its
own cited evidence is a fabrication and is counted separately from recall.

## 12. How to extend this page

Add a row when a new document shows a form the corpus did not contain yet:
form, one real string with its document, and the status. If a rule changes,
update the status in the same change that touches the parser — the page is a
design record, not a wish list.
