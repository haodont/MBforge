"""The gap worklist and the LLM-led Patent merge (P2), one contract per test.

Protects the decisions the reviewer and the publisher rely on: one refused
table becomes exactly one bounded gap carrying its own rows, the highest-yield
kind is handed over first, leftover work is counted (never silently dropped), a
clipped excerpt says it was clipped, a gap hands over only the structures its
excerpt prints, and — on the merge side — a slot is never keyed on a value, an
identical reading changes nothing, a bounded reading is never conflated with an
exact one, distinct assays and species stay distinct, and nothing uncorroborated
enters the valid set.

Functions under test: ``build_gaps``
(``mbforge.service.pipeline.patent.llm_gaps``) and ``merge_submission``
(``mbforge.service.pipeline.patent.llm_merge``).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from mbforge.contracts.patent import PatentDraft
from mbforge.domain.evidence import SourceEvidence
from mbforge.service.pipeline.patent.llm_gaps import (
    MAX_EXCERPT_CHARS,
    TRUNCATION_MARK,
    build_gaps,
)
from mbforge.service.pipeline.patent.llm_merge import merge_submission

DOC = "doc-1"

#: The real CN activity table the deterministic parser refuses (page 21).
CN_TABLE = (
    "| 化合物编号 | IC50(nM) |  |  |  |\n"
    "| MRGPRX1 | MRGPRX2 | MRGPRX3 | MRGPRX4 |  |\n"
    "| 实施例1 | 十 | ++++ | 十 | 十 |"
)
#: A real glyph-damaged JP line (page 83).
JP_LINE = "実施例1~304の化合物は、およそ9.6~4.5のρIC50を示した。"


# ── the gap worklist ────────────────────────────────────────────────


def _evidence(evidence_id: str, page: int, raw_text: str) -> SourceEvidence:
    return SourceEvidence(
        doc_id=DOC,
        page=page,
        bbox=(0.0, 0.0, 10.0, 10.0),
        evidence_id=evidence_id,
        raw_text=raw_text,
        kind="tab" if raw_text.startswith("|") else "text",
    )


def _rows() -> list[SourceEvidence]:
    return [
        _evidence("ev-tab-21", 21, CN_TABLE),
        _evidence("ev-line-83", 83, JP_LINE),
        _evidence("ev-line-84", 84, JP_LINE),
    ]


def test_an_over_budget_excerpt_is_clipped_and_says_so() -> None:
    """A structure payload stored as raw_text outruns the contract's excerpt cap.

    A live run of CN120329282A failed the whole Patent stage here: the excerpt was
    built up to the excerpt budget, the contract refused it, and nothing published.
    Real evidence, a real failure — the excerpt is clipped instead, whether the cap
    comes from the contract or from an explicit budget.
    """
    payload = "| 化合物编号 | IC50 (nM) |\n" + '{"esmiles": "' + "C" * 12_000 + '"}'
    gaps, skipped = build_gaps(
        issues=[
            {
                "code": "complex_activity_table",
                "message": "activity table contains unparsed cells",
                "evidence_ids": ["ev-huge"],
            }
        ],
        evidence=[_evidence("ev-huge", 21, payload)],
    )

    assert skipped == {}
    assert len(gaps) == 1
    assert len(gaps[0].excerpt) <= MAX_EXCERPT_CHARS
    assert gaps[0].excerpt.endswith(TRUNCATION_MARK)

    clipped, _ = build_gaps(
        issues=[{"code": "complex_activity_table", "evidence_ids": ["ev-tab-21"]}],
        evidence=_rows(),
        excerpt_char_budget=20,
    )
    assert clipped[0].excerpt.endswith(TRUNCATION_MARK)
    assert clipped[0].evidence_ids == ["ev-tab-21"]


def test_a_refused_table_becomes_one_gap_with_its_rows_and_bins() -> None:
    """Tables are handed over before prose, carrying rows and bin definitions."""
    gaps, skipped = build_gaps(
        issues=[
            {
                "code": "complex_activity_table",
                "message": "activity table contains unparsed cells",
                "evidence_ids": ["ev-tab-21"],
            }
        ],
        evidence=_rows(),
    )

    assert skipped == {}
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.gap_kind == "table"
    assert gap.page_start == gap.page_end == 21
    assert gap.evidence_ids == ["ev-tab-21"]
    assert "实施例1" in gap.excerpt
    assert gap.gap_id == "complex_activity_table:ev-tab-21"
    assert gap.rule_context["rule_reason"]

    ordered, _ = build_gaps(
        issues=[
            {"code": "activity_value_unparsed", "evidence_ids": ["ev-line-83"]},
            {"code": "complex_activity_table", "evidence_ids": ["ev-tab-21"]},
        ],
        evidence=_rows(),
    )

    assert [item.gap_kind for item in ordered] == ["table", "prose_measurement"]

    # A bin symbol without its bound is not a reading, so it travels along.
    with_bins = _rows() + [
        _evidence("ev-legend", 20, "注：“+”：IC50>1μM"),
        _evidence("ev-legend-2", 20, '"++++"1nM<IC50<20nM'),
        _evidence("ev-prose", 21, "无关的散文"),
    ]

    binned, _ = build_gaps(
        issues=[{"code": "complex_activity_table", "evidence_ids": ["ev-tab-21"]}],
        evidence=with_bins,
    )

    packet = binned[0].rule_context["evidence"]
    context = {row["evidence_id"]: row for row in packet if row["role"] == "context"}
    assert context["ev-legend"]["raw_text"] == "注：“+”：IC50>1μM"
    assert context["ev-legend-2"]["raw_text"] == '"++++"1nM<IC50<20nM'
    assert set(context) <= set(binned[0].evidence_ids)
    assert binned[0].rule_context["work_evidence_ids"] == ["ev-tab-21"]
    # A distant assay's scale is not a document-wide default.
    distant, _ = build_gaps(
        issues=[{"code": "complex_activity_table", "evidence_ids": ["ev-tab-21"]}],
        evidence=with_bins + [_evidence("ev-other-assay", 50, '"++++" IC50>1000nM')],
    )
    assert "ev-other-assay" not in distant[0].evidence_ids


def test_leftover_gap_work_is_counted_and_dangling_references_are_no_location() -> None:
    """One located gap, one over the cap, one with nothing to hand over.

    Duplicates on one row are one paid work item, a dangling reference is never
    turned into an empty excerpt, and two different issues on the same row stay
    distinct gaps.
    """
    gaps, skipped = build_gaps(
        issues=[
            {"code": "activity_value_unparsed", "evidence_ids": ["ev-line-83"]},
            {"code": "activity_value_unparsed", "evidence_ids": ["ev-line-84"]},
            {"code": "activity_value_unparsed", "evidence_ids": []},
            {"code": "llm_analysis_incomplete", "evidence_ids": ["ev-line-83"]},
        ],
        evidence=_rows(),
        max_gaps=1,
    )

    assert len(gaps) == 1
    assert skipped == {
        "activity_value_unparsed:over_cap": 1,
        "activity_value_unparsed:no_location": 1,
    }

    dangling, dangling_skipped = build_gaps(
        issues=[{"code": "complex_activity_table", "evidence_ids": ["ev-gone"]}],
        evidence=_rows(),
    )

    assert dangling == []
    assert dangling_skipped == {"complex_activity_table:no_location": 1}

    # Fifteen identical excerpts must not become fifteen paid work items.
    deduped, deduped_skipped = build_gaps(
        issues=[
            {"code": "assay_method_unresolved", "evidence_ids": ["ev-tab-21"]}
            for _ in range(15)
        ],
        evidence=_rows(),
    )

    assert len(deduped) == 1
    assert deduped_skipped == {"assay_method_unresolved:same_location": 14}

    distinct, _ = build_gaps(
        issues=[
            {"code": "activity_value_unparsed", "evidence_ids": ["ev-line-83"]},
            {"code": "activity_reference_missing", "evidence_ids": ["ev-line-83"]},
        ],
        evidence=_rows(),
    )

    assert [gap.gap_id for gap in distinct] == [
        "activity_value_unparsed:ev-line-83",
        "activity_reference_missing:ev-line-83",
    ]
    assert len({gap.gap_id for gap in distinct}) == 2


def _structure_candidate(
    *,
    mol_id: str,
    name: str | None,
    properties: dict[str, Any],
) -> SimpleNamespace:
    """A structure as the persist filter expects to see it.

    ``build_gaps`` runs its candidates through the shared persist filter, so a
    fake must carry the attributes that filter reads (status, role, detections,
    canonical SMILES) to be handed over like a real one.
    """
    return SimpleNamespace(
        mol_id=mol_id,
        name=name,
        canonical_smiles=f"C{mol_id}",
        status="complete",
        properties={"structure_role": "complete", **properties},
        detections=[SimpleNamespace(page=0)],
    )


def _structure(name: str) -> SimpleNamespace:
    return _structure_candidate(
        mol_id=f"mol-{name}",
        name=name,
        properties={"ocr_labels_primary": name},
    )


def test_table_chunks_keep_printed_rows_and_only_resolved_example_structures() -> None:
    """The live repeated-header table must not use values as compound identities."""
    from mbforge.domain.molecule import Molecule
    from mbforge.domain.types import DetectionSource

    table = (
        "| 实施例编号 | IC50(nM) | 实施例编号 | IC50(nM) |\n"
        "| --- | --- | --- | --- |\n"
        "| 1 | ++++ | 2 | +++ |\n"
        "| 3 | 26.3 | 4 | 31.7 |\n"
        "| 5 | +++ |  | ++ |"
    )
    complete = _structure("1")
    fragment = Molecule(
        mol_id="fragment-1",
        canonical_smiles="*N1CCC1",
        name="1",
        detections=[DetectionSource(source="image", page=0)],
    )
    kwargs = {
        "issues": [{"code": "complex_activity_table", "evidence_ids": ["ev-table"]}],
        "evidence": [_evidence("ev-table", 20, table)],
        "structures": [fragment, complete, _structure("26")],
        "entries": [
            {
                "entry_id": "existing-entry",
                "label_raw": "实施例1",
                "entity_id": complete.mol_id,
                "structure_status": "resolved",
            }
        ],
    }
    gaps, skipped = build_gaps(**kwargs)
    assert skipped == {}
    # One task carries the whole run of data rows (three here): the answer may return
    # 200 items, and splitting at two rows turned one document's refused tables into
    # 192 separate gaps.
    assert len(gaps) == 1
    assert gaps[0].rule_context["row_labels"] == ["1", "2", "3", "4", "5"]
    assert gaps[0].rule_context["row_label_type"] == "example"
    assert {s["mol_id"] for s in gaps[0].rule_context["structures"]} == {
        complete.mol_id
    }
    assert gaps[0].excerpt.endswith("| 5 | +++ |  | ++ |")
    assert gaps[0].excerpt.startswith(table.splitlines()[0])
    assert gaps[0].evidence_ids == ["ev-table"]
    capped, skipped = build_gaps(**kwargs, max_gaps=1)
    assert len(capped) == 1 and skipped == {}


def _structure_labels(gap: Any) -> list[str]:
    return sorted(item["label"] for item in gap.rule_context["structures"])


def test_a_gap_hands_over_only_the_structures_its_excerpt_prints() -> None:
    """The answer can name a structure without another round trip — but only one
    the excerpt actually prints.

    A designation in a table cell matches with or without the ``化合物`` marker
    (``| 1 | ++++ |``); a reading in the same table does not (``26.3``, ``37``);
    and a label inside a unit does not either (``9.6nM`` must not hand over the
    structure labelled ``9``). A gap with no recognizable label carries no
    ``structures`` key at all rather than an empty list.
    """

    def gaps_for(text: str, structures: list[object], evidence_id: str = "ev-tab"):
        gaps, _ = build_gaps(
            issues=[{"code": "complex_activity_table", "evidence_ids": [evidence_id]}],
            evidence=[_evidence(evidence_id, 4, text)],
            structures=structures,
        )
        return gaps[0]

    aliases = gaps_for(
        "化合物 E020 的 IC50 为 10 nM",
        [
            _structure_candidate(
                mol_id="mol-alias",
                name=None,
                properties={"ocr_labels": ["E020", "20"]},
            )
        ],
    )
    assert aliases.rule_context["structures"][0]["mol_id"] == "mol-alias"
    assert _structure_labels(aliases) == ["E020"]

    designated = gaps_for(CN_TABLE, [_structure("1")])
    assert [item["mol_id"] for item in designated.rule_context["structures"]] == [
        "mol-1"
    ]

    markerless = gaps_for(
        "| 1 | ++++ |\n| 3 | ++++ |", [_structure("1"), _structure("3")]
    )
    assert _structure_labels(markerless) == ["1", "3"]

    readings = gaps_for(
        "| 化合物编号 | 抑制率(%) |\n| 化合物77 | 26.3 |\n| 化合物3 | 77.5 |",
        [_structure("77"), _structure("3"), _structure("26")],
    )
    assert _structure_labels(readings) == ["3", "77"]

    cell_values = gaps_for(
        "| 化合物编号 | IC50(nM) |\n| 化合物77 | 37 |\n| 化合物80 | 27 |",
        [_structure("77"), _structure("37"), _structure("27"), _structure("80")],
    )
    assert _structure_labels(cell_values) == ["77", "80"]

    in_unit = gaps_for(
        "该化合物 IC50 9.6nM を示した。", [_structure("9")], evidence_id="ev-line-83"
    )
    assert "structures" not in in_unit.rule_context

    without, _ = build_gaps(
        issues=[{"code": "complex_activity_table", "evidence_ids": ["ev-tab-21"]}],
        evidence=_rows(),
    )
    assert "structures" not in without[0].rule_context


# ── the LLM-led merge ───────────────────────────────────────────────


def _rule_measurement(
    *,
    measurement_id: str = "m-1",
    metric: str = "IC50",
    value: float = 10.0,
    unit: str = "nM",
    operator: str = "=",
    raw_text: str = "IC50 = 10 nM",
    evidence_id: str = "ev-1",
    reference_key: str = "12",
    assay_method_id: str = "assay-1",
) -> dict[str, Any]:
    return {
        "measurement_id": measurement_id,
        "doc_id": DOC,
        "compound_entry_id": f"entry-{reference_key}",
        "assay_method_id": assay_method_id,
        "mol_id": None,
        "metric": metric,
        "linking_status": "linked",
        "value": {
            "raw_text": raw_text,
            "operator": operator,
            "original_value": value,
            "original_unit": unit,
            "canonical_value": None,
            "canonical_unit": "",
            "qualitative_value": "",
        },
        "evidence_ids": [evidence_id],
        "provenance": {
            "reference_raw": reference_key,
            "reference_key": reference_key,
            "reference_type": "compound",
        },
    }


def _rule_assay(
    *,
    assay_method_id: str = "assay-1",
    target: str = "MRGPRX2",
    system: str = "human",
    endpoint: str = "calcium flux",
) -> dict[str, Any]:
    return {
        "assay_method_id": assay_method_id,
        "doc_id": DOC,
        "target": target,
        "system": system,
        "endpoint": endpoint,
        "assay_type": "IC50",
        "conditions": {},
        "raw_text": "",
        "section_id": "s-1",
        "page_start": 1,
        "page_end": 1,
        "comparison_key": None,
        "evidence_ids": ["ev-1"],
    }


def _llm_measurement(
    *,
    local_key: str = "measurement-1",
    metric: str = "IC50",
    value: float | None = 10.0,
    unit: str = "nM",
    operator: str = "=",
    raw_text: str = "IC50 = 10 nM",
    evidence_id: str = "ev-1",
    compound_raw: str = "Compound 12",
    compound_key: str = "12",
    assay_local_key: str = "",
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "local_key": local_key,
        "metric": metric,
        "value": {
            "raw_text": raw_text,
            "operator": operator,
            "value": value,
            "unit": unit,
            "missing_fields": ["unit"] if not unit else [],
        },
        "compound_label_raw": compound_raw,
        "compound_label_key": compound_key,
        "assay_local_key": assay_local_key,
        "page": 1,
        "evidence_ids": [evidence_id],
    }
    payload.update(extra)
    return payload


def _submission(
    *measurements: dict[str, Any], assays: list[dict[str, Any]] | None = None
) -> PatentDraft:
    return PatentDraft.model_validate(
        {
            "protocol_version": "1",
            "doc_id": DOC,
            "attempt_id": "attempt-1",
            "evidence_signature": "sig-1",
            "assay_methods": assays or [],
            "measurements": list(measurements),
            "coverage": {"pages_viewed": [1], "pages_uncovered": []},
        }
    )


def _merge(
    *,
    rule_measurements: list[dict[str, Any]] | None = None,
    rule_assay_methods: list[dict[str, Any]] | None = None,
    submission: PatentDraft,
    pages: dict[str, int] | None = None,
    scope_fact_ids: list[str] | None = None,
    scope_work_evidence_ids: list[str] | None = None,
):
    return merge_submission(
        doc_id=DOC,
        rule_measurements=rule_measurements or [],
        rule_assay_methods=rule_assay_methods or [],
        submission=submission,
        evidence_pages=pages,
        scope_fact_ids=scope_fact_ids,
        scope_work_evidence_ids=scope_work_evidence_ids,
    )


def test_an_agreed_reading_changes_nothing_and_distinct_facts_stay_distinct() -> None:
    """An identical reading is agreed; a different assay or species is not merged."""
    log_rule = _rule_measurement(metric="pIC50", value=7, unit="", operator="<")
    log_rule["value"]["canonical_value"] = 100.0
    log_rule["value"]["canonical_unit"] = "nM"
    log = _merge(
        rule_measurements=[log_rule],
        submission=_submission(
            _llm_measurement(metric="pIC50", value=7, unit="", operator=">")
        ),
    )
    assert log.stats["agreed"] == 1
    assert log.conflicts == []
    agreed = _merge(
        rule_measurements=[_rule_measurement()],
        rule_assay_methods=[_rule_assay()],
        submission=_submission(_llm_measurement()),
    )

    assert agreed.stats["agreed"] == 1
    assert agreed.stats["conflict"] == 0
    assert agreed.conflicts == []
    assert agreed.candidates == []
    assert len(agreed.measurements) == 1

    # Context citations must not move the reading's slot away from its data table.
    supported = _merge(
        rule_measurements=[_rule_measurement()],
        rule_assay_methods=[_rule_assay()],
        submission=_submission(_llm_measurement(evidence_ids=["ctx-0", "ev-1"])),
        scope_work_evidence_ids=["ev-1"],
    )
    assert supported.stats["agreed"] == 1
    assert supported.candidates == []
    example = _merge(
        rule_measurements=[_rule_measurement()],
        rule_assay_methods=[_rule_assay()],
        submission=_submission(
            _llm_measurement(compound_raw="12", compound_key="@example:12")
        ),
    )
    assert example.stats["agreed"] == 0
    assert len(example.candidates) == 1

    distinct = _merge(
        rule_measurements=[
            _rule_measurement(measurement_id="m-a", assay_method_id="assay-A"),
            _rule_measurement(measurement_id="m-b", assay_method_id="assay-B"),
        ],
        rule_assay_methods=[
            _rule_assay(assay_method_id="assay-A", endpoint="calcium flux"),
            _rule_assay(assay_method_id="assay-B", endpoint="binding"),
        ],
        submission=_submission(
            _llm_measurement(assay_local_key="a1"),
            assays=[
                {
                    "local_key": "a1",
                    "target": "MRGPRX2",
                    "system": "human",
                    "endpoint": "calcium flux",
                    "evidence_ids": ["ev-1"],
                }
            ],
        ),
    )

    assert distinct.stats["agreed"] == 1
    assert distinct.stats["conflict"] == 0
    # Both rule measurements stay valid: the second assay was never touched.
    assert len(distinct.measurements) == 2

    species = _merge(
        rule_measurements=[_rule_measurement()],
        rule_assay_methods=[_rule_assay(target="MRGPRX2", system="human")],
        submission=_submission(
            _llm_measurement(assay_local_key="mouse-assay"),
            assays=[
                {
                    "local_key": "mouse-assay",
                    "target": "Mrgprb2",
                    "system": "mouse",
                    "endpoint": "calcium flux",
                    "evidence_ids": ["ev-1"],
                }
            ],
        ),
    )

    assert species.stats["llm_only"] == 1
    assert species.stats["conflict"] == 0
    # The rule fact is untouched and nothing uncorroborated was adopted.
    assert len(species.measurements) == 1
    assert species.candidates[0]["reason"] == "llm_only"
    assert species.candidates[0]["review_item_id"]
    assert species.stats["prose_assay_methods"] == 1


def test_a_conflicting_reading_is_held_back_with_both_values() -> None:
    """A bounded reading is never conflated with an exact one, and a slot that
    holds two readings keeps both for the reviewer."""
    missing_units = _merge(
        rule_measurements=[_rule_measurement(value=1, unit="")],
        submission=_submission(_llm_measurement(value=1000, unit="")),
    )
    assert missing_units.stats["conflict"] == 1
    assert missing_units.measurements == []
    assert [
        c.fields["value_unconverted"] for c in missing_units.conflicts[0].candidates
    ] == [1, 1000]
    bounded = _merge(
        rule_measurements=[
            _rule_measurement(operator="<", value=100.0, raw_text="IC50 < 100 nM")
        ],
        rule_assay_methods=[_rule_assay()],
        submission=_submission(
            _llm_measurement(operator="=", value=100.0, raw_text="IC50 = 100 nM")
        ),
        pages={"ev-1": 7},
    )

    assert bounded.stats["conflict"] == 1
    conflict = bounded.conflicts[0]
    deterministic, llm = conflict.candidates
    assert deterministic.source == "deterministic"
    assert deterministic.fields["operator"] == "<"
    assert llm.fields["operator"] == "="
    # Units survive normalization on both sides.
    assert deterministic.fields["unit_canonical"] == "nM"
    assert llm.fields["unit_canonical"] == "nM"
    # The questioned rule fact is held back until a human decides.
    assert bounded.measurements == []
    assert bounded.stats["held_back"] == 1
    assert bounded.candidates[0]["review_item_id"] == conflict.conflict_id
    assert conflict.page == 7

    both = _merge(
        rule_measurements=[_rule_measurement(value=10.0)],
        rule_assay_methods=[_rule_assay()],
        submission=_submission(_llm_measurement(value=100.0, raw_text="IC50 = 100 nM")),
    )

    assert both.stats["conflict"] == 1
    rule, model = both.conflicts[0].candidates
    assert rule.fields["value_canonical"] == 10.0
    assert model.fields["value_canonical"] == 100.0
    assert both.measurements == []
    assert len(both.conflicts[0].evidence_ids) == 1

    # The structure a reading was attached to stays visible to the reviewer.
    referenced = _merge(
        submission=_submission(_llm_measurement(molecule_ref="E020")),
    )

    assert referenced.candidates[0]["llm"]["molecule_ref"] == "E020"


def test_a_scoped_gap_is_answered_against_its_named_fact_and_ids_are_stable() -> None:
    """Naming one measurement turns an ``ambiguous`` shrug into a real answer.

    Two rule facts share a slot; the gap names one of them, so the answer is
    compared with that fact and the neighbour stays out of scope. The item ids
    the browser sees are derived, so they are stable across runs.
    """
    first = _rule_measurement(measurement_id="m-1")
    second = _rule_measurement(measurement_id="m-2")
    submission = _submission(_llm_measurement(value=55.0))

    unscoped = _merge(rule_measurements=[first, second], submission=submission)
    scoped = _merge(
        rule_measurements=[first, second],
        submission=submission,
        scope_fact_ids=["m-1"],
    )

    assert unscoped.stats["ambiguous"] == 1
    assert unscoped.stats["conflict"] == 0
    assert unscoped.conflicts == []
    assert len(unscoped.measurements) == 2
    assert scoped.stats["ambiguous"] == 0
    assert scoped.stats["conflict"] == 1
    assert [candidate["reason"] for candidate in scoped.candidates] == ["conflict"]

    def ids() -> tuple[str, str]:
        result = _merge(
            rule_measurements=[_rule_measurement(value=10.0)],
            rule_assay_methods=[_rule_assay()],
            submission=_submission(_llm_measurement(value=100.0)),
        )
        return result.conflicts[0].conflict_id, result.candidates[0]["review_item_id"]

    assert ids() == ids()


def test_a_reading_with_no_owner_is_dropped_not_queued() -> None:
    """A value whose row prints no designation and names no structure is noise."""
    result = _merge(
        submission=_submission(
            _llm_measurement(
                row_label_raw="",
                compound_raw="",
                compound_key="",
                molecule_ref="",
            )
        ),
    )

    assert result.candidates == []
    assert result.stats["unattributed"] == 1

    attributed = _merge(
        submission=_submission(
            _llm_measurement(
                row_label_raw="",
                compound_raw="",
                compound_key="",
                molecule_ref="mol-1",
            )
        ),
    )

    assert attributed.stats["unattributed"] == 0
    assert attributed.candidates[0]["llm"]["molecule_ref"] == "mol-1"
