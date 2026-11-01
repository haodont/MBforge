# Patent taxonomy for extraction and gold-set stratification

This page classifies patent documents by the dimensions that change the
extraction path. It is not a legal taxonomy: a category exists here only if it
changes what a producer reads, what a relation pair means, or how the gold set
must be stratified.

## 1. Default input: a scanned PDF

The default input is a page-image PDF with no usable text layer. The producer is
the scanned path:

```
render (layout 144 DPI, structure crops 200 DPI)
  → Hiro-Layout regions
  → RapidOCR text
  → SLANet table structure
  → MolDet structure boxes
  → MolParser SMILES / E-SMILES
```

A native text layer is a possible cost optimization, not the contract. Only the
**molecule-pass** renderer skips a page with more than
`text_page_char_threshold` native characters and no raster images
(`detection/extraction/page_renderer.py`). The independent layout/text pass in
`layout/parse.py::parse_pdf_layout` still renders and OCRs each page. Native text
availability therefore does not establish that the active text producer uses it.
The contract speaks in terms of `source_evidence` rows and PDF-point geometry.
The 2026-10-29 JP396 native-text control worked better than RapidOCR; region-level
native-text production remains unimplemented and needs geometry/quality validation.

Corpus measurement on 2026-10-23 (13 documents, 1,188 pages):

| Rendering | Documents | Pages | Note |
|---|---:|---:|---|
| Scanned (no text layer) | 11 | 778 | CN, US, WO, KR, IL |
| Native text | 1 | 400 | `JP2023544789A` |
| Hybrid | 1 | 67 | `US20210128561A1`, 64 native / 3 scanned pages |

Two documents are in `error` state in the current library (`CN120329282A`,
`CN120943813A`); their evidence rows still cover forms and page layout, but they
must not enter a metrics split until their run completes.

Consequence: **OCR quality is the first-class risk**. Page skew, bleed-through,
low contrast, rotated tables, subscript loss and full-width digits are not edge
cases; they are the default failure surface. The gold set is stratified by scan
quality, not by jurisdiction alone.

## 2. Dimension A — legal / document kind

| Kind | Typical codes | What it is | Extraction consequence | Corpus |
|---|---|---|---|---|
| Application publication | `A`, `A1`, `A2` | Published application, usually 18 months after filing | Claims + description + examples; claims may be broader than the examples | 13/13 |
| Granted patent | `B1`, `B2` | Granted claims | Claims may be amended vs the A publication; examples usually unchanged; compare the family | 0 |
| Utility model | `U`, `Y` | Petty patent (CN/DE/JP/KR) | Often no substantive chemistry examples; exclude when no chemistry | 0 |
| PCT publication | `WO ... A1/A2` | International application | Often English; A1 carries the search report; family leakage risk | 4 |
| EP publication | `EP ... A1/A2/B1` | Regional application / grant | A1 with search report; B1 granted; multilingual | 0 |
| Translation | e.g. JP→EN, CN→EN | Translated text | Heading labels are frequently dropped or translated inconsistently; abstain when the section label is gone | 2 (`KR20250121245A`, `WO2025163462A1`) |
| Search / examination report | — | Not a patent | Out of scope | 0 |
| Reissue / correction | `E`, certificate | Amended grant | Out of scope in v1 | 0 |

The development corpus is application/PCT only. A held-out set that claims
generalization must add at least one granted `B`, one utility model and one EP
document; otherwise the claim is untested.

## 3. Dimension B — chemistry disclosure pattern

This is the dimension that determines which relation types exist.

| Pattern | What the document prints | Relation types | Primary risk |
|---|---|---|---|
| `example_per_compound` | One example prepares one compound; structure, name, spectra | `exemplified_by`, `designated_as`, `reported_as` | Label ↔ structure binding; the 20% bottleneck |
| `markush_genus` | Generic formula + R-group definitions in claims or a table | `member_of_genus`, `claim_scope` | Enumerating the genus; losing the variable table |
| `table_only_sar` | Activity table, one row per compound, labels in a column | `reported_as` | Split headers, merged cells, structure-image columns |
| `reaction_scheme` | Arrows, reactants, products, conditions | `prepared_from` | Arrow direction; unlabeled nodes; multi-step routes |
| `prophetic` | “may be prepared”, “compound of formula I” | `exemplified_by` with `example_status=prophetic` | Reporting a plan as a fact |
| `formulation` | Composition, excipients, doses | `formulated_as` | No per-compound structure; combination identity |
| `salt_polymorph` | Salt forms, crystal forms, solvates | `salt_of`, `solvate_of`, `stereoisomer_of`, `tautomer_of` | Parent identity; collapsing distinct forms |
| `biotech_sequence` | Sequences, antibodies, peptides | Out of scope | No small-molecule structure |
| `polymer` | Repeat units, Markush-like materials | Out of scope | No single molecule |
| `no_chemistry` | Mechanical/electrical/design | Out of scope | Exclude from the corpus |

A document may carry several patterns. The taxonomy records the set, not one
label; the gold set samples pairs per pattern, not documents per pattern.

**Isotopologues are a separate identity problem.** Full standard InChIKeys
distinguish isotopologues, but their first connectivity block can be identical.
Never truncate the key when comparing isotope identity. The gold set compares canonical isomeric SMILES at
`exact_isotopes`. Deuterated patents are present in the corpus
(`CN121270515A`), so this is not a theoretical case.

## 4. Dimension C — rendering and file format

| Format | Typical source | Text layer | Tables | Structures | MBForge v1 | Producer |
|---|---|---|---|---|---|---|
| **PDF, scanned** | CNIPA, older USPTO, IL, vendor scans | None | Image | Raster | **Yes (default)** | Render + layout + OCR |
| PDF, native | JPO, USPTO, EPO | Selectable | Native or text | Raster/vector | Yes (control arm) | Render + layout; text layer may be used as an optimization |
| PDF, hybrid | Mixed page sets | Per page | Mixed | Mixed | Yes | Per-page classification |
| PDF, OCR layer | Vendor OCR | Invisible, quality unknown | Image | Raster | Yes, but never trusted blindly | Compare layer vs OCR; prefer the evidence row |
| TIFF / JPEG | USPTO pre-2001, archives | None | Image | Raster | No | Page assembly + OCR (future) |
| XML ST.36 / ST.96 | WIPO, EPO, USPTO, JPO, KIPO, CNIPA | Structured | Structured | References/images | No | XML adapter (future) |
| DOCX | Applicant drafts, internal | Yes | Native | Embedded objects | No | DOCX adapter (future) |
| Paper / microfilm | Archives | None | Image | Raster | No | Scan + OCR (out of scope) |
| SDF / MOL / CDX | Chemistry attachments | n/a | n/a | Exact | Imported as molecules only | Molecule importer; not a patent page |

Two distinctions matter:

1. `foundation/file_scanner.py::SUPPORTED_EXTS` (`.pdf`, `.md`, `.txt`, `.sdf`,
   `.mol`, `.mol2`, `.pdb`, `.smi`) is the **file browser** vocabulary. It is not
   the Extract producer vocabulary. Extract's page producer is PDF-only
   (`page_renderer.py` opens the file with PyMuPDF); a non-PDF import has no page
   producer today.
2. The relation contract is **producer-agnostic**. Any producer that writes
   `source_evidence` rows (PDF OCR, XML, TIFF, DOCX) can feed `label_anchor` and
   `relation_pair`. Adding a format changes the producer, not the pair schema.

## 5. Dimension D — language and translation

| Form | Real corpus evidence | Extraction consequence |
|---|---|---|
| Chinese original | `[0143]实施例7`, `化合物77-A`, `IC50` | CJK headings, bracketed paragraph markers, qualitative bins |
| Japanese original | `【実施例】`, `実施例1`, `ρIC50`, full-width digits | 400-page filing; native text layer, but glyph damage remains |
| Korean original | Hangul headings | Not present in the translated sample; detect before choosing a vocabulary |
| Machine-translated English | `KR20250121245A`, `WO2025163462A1`: no Hangul/Kana, no `Example`-style headings | Heading labels were dropped in translation; abstain when no section is found |
| English original | `Example A`, `Example 2`, `Examples 4, 25, 28 and 30` | Lettered assays vs numbered compounds; plural references |
| Bilingual | Some WO/EP publications | Pick one language per document; never mix headings across languages |

Language detection belongs to the producer, not to the relation layer. The pair
carries the document's language in the gold metadata; the runtime reads the
evidence text as produced.

## 6. Dimension E — table form

| Form | Real example | Current status | Extraction consequence |
|---|---|---|---|
| Simple pipe table | `\| 化合物编号 \| IC50(nM) \|` | Handled | Row label ↔ value |
| Split header | Metric row + target row | Handled | Header state machine |
| Repeated (label, value) pairs | `\| 实施例编号 \| MRGPRX2 抑制 \| 实施例编号 \| ... \|` | Handled | Header decides `@example:N` vs compound `N` |
| Missing label / unproven span | `\| 5 \| ++++ \| \| ++++ \|` | Refused | Inspect image/span evidence; the CN121270515A p20 image prints `6` |
| Target inside the metric cell | `CYP3A4(咪达唑仑)抑制率(%)` | Handled | Keep substrate as `column_target` |
| Rotated table | Metric in a rotated cell below the separator | Open | Detect rotation before parsing; otherwise refuse |
| Structure-image column | `\| N. HN S \| 6.4 \|` | Refused by design | A structure fragment is not a designation |
| Table spanning pages | Header on one page, rows on the next | Open | Bind by caption/continuation, not by page-local guess |
| Legend outside the table | `注：“+”：IC50>1μM` | Handled | Document-level legend, never a value |

The fail-closed contract is unchanged: publish a table only when every non-empty
value cell is attributed; otherwise report `complex_activity_table`.

## 7. Targeted extraction design

Each row is a gold-set stratum and the design that applies to it.

| Stratum | Default producer | Anchor extraction | Structure path | Relation types | Verification | Abstain when |
|---|---|---|---|---|---|---|
| CN scanned, example-per-compound | Render + Hiro + RapidOCR | `实施例N` headings, `化合物N` labels, `[0143]` markers | MolDet + MolParser | `exemplified_by`, `designated_as` | MS mass ±0.6 Da; label sequence; geometry | Label ambiguous; crop clipped; no structure |
| CN scanned, table SAR | Render + SLANet + OCR | Header key space, row label, merged-cell span | Structure column OCR or label ↔ structure | `reported_as` | Every cell attributed; header/legend consistency | Any cell unparsed; rotated header |
| US/WO scanned, lettered examples | Render + Hiro + OCR | `Example 1`, `Example A`, assay headings | MolDet + MolParser | `exemplified_by`, `reported_as` | Distinguish assay letter from compound number; MS mass | Lettered example is an assay, not a compound |
| WO/EP Markush | Render + Hiro + OCR + scaffold detection | Claims, generic formula, variable table | Scaffold E-SMILES + variable table | `member_of_genus`, `claim_scope` | Variable definitions complete; no enumeration | Variable table missing; scaffold not recognized |
| JP scanned/native CJK | Native text or OCR + CJK normalization | `【実施例】`, `実施例N` | MolDet + MolParser | `exemplified_by` | Glyph normalization; MS mass | Glyph-damaged value; no section |
| KR machine-translated | OCR + language detection | `Example` variants or translated headings | MolDet + MolParser | `exemplified_by` | Heading recovery; if lost, no section | No heading survives translation |
| EP/IL granted | Render or native | Claims + examples | MolDet + MolParser | `claim_scope`, `exemplified_by` | Claim vs example consistency | Claim ambiguity; no examples |
| Reaction scheme | Render + scheme detection | Scheme nodes, arrow | Per-node MolDet + MolParser | `prepared_from` | Arrow direction; mass balance | Arrow ambiguous; node unlabeled |
| Salt/polymorph | Render or native | Names, formulas, crystal-form labels | MolDet + MolParser | `salt_of`, `solvate_of` | Parent/salt mass; name | Parent unknown |
| XML/TIFF (future) | New producer | Structured text or page images | Embedded structures or OCR | Same as above | Schema validation | Producer missing; page pairing unknown |
| Biotech sequence | Sequence extractor | Sequence listing | Not applicable | Out of scope | Not applicable | Always excluded from small-molecule metrics |

### What changes for scanned input specifically

1. **Page quality is a gate, not a metric.** Grade each page `clean / degraded /
   unreadable` before extraction. An `unreadable` page may still contribute
   evidence rows, but no committed pair.
2. **Render DPI is recorded.** Layout runs at 144 DPI; structure crops at 200 DPI.
   A review crop at 150–200 DPI must not re-derive the scale from a guess.
3. **OCR errors are evidence, not noise to clean.** The anchor stores the OCR
   string verbatim; normalization lives in `label_key`. A corrected string never
   replaces the evidence.
4. **Rotation is detected before the table parser.** A 90° table otherwise turns
   every value into a structure-noise row.
5. **Chemical-label OCR is a separate reader.** Atom labels, `R¹/R²`, `OMe`,
   `Boc`, `TBS` are not page prose; one recognizer for both is a known failure.
6. **Native text is a control arm.** Run the same gold pages through the native
   text layer and through OCR to measure the OCR penalty; do not mix the two in
   one metric.

## 8. What the corpus already proves

- **Scanned is the default.** 11 of 13 documents have no text layer; the one
  native 400-page filing is an exception, not the design target.
- **Association is the bottleneck.** 63/314 entries (20%) have a structure;
  343/2605 structures (13%) carry a designation.
- **Tables are the largest recoverable block.** 31 activity tables, 6 parsed;
  15 need header/metric stitching.
- **Markush is dropped.** A Markush candidate becomes
  `molecule_candidate_rejected` and disappears; the genus has no relation.
- **Translation breaks headings.** `KR20250121245A` and `WO2025163462A1` contain
  no Hangul/Kana and no `Example` headings.
- **Glyph damage is real.** `ICs0`, `IC₅0`, `ρIC50`, `Λ:` are page-level OCR
  failures, not parser bugs.

## 9. Out of scope

- Biotech sequences, antibodies, peptides and polymers.
- Design patents and mechanical/electrical patents.
- XML/TIFF/DOCX producers in v1.
- Cross-document family entity resolution in the document-local pass.
- Markush enumeration as stored fact.

## 10. How to extend

Add a row only with a real corpus string and the rejected neighbour, following
[patent extraction forms](patent-extraction-forms.md) §12. A category that does
not change the producer, the relation type or the gold stratum does not belong
on this page.
