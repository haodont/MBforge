"""Scope boundary of the Patent-analysis tool endpoints (P1 boundary case).

Functions: submit_gap_answer, get_gap, list_molecules, request_excerpt.
Protects: a tool call is authorized only by the attempt's credential, resolves
to the credential's bound document, and refuses foreign evidence ids; a draft is
staged only when it matches the bound document, attempt and evidence set.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from mbforge.contracts.patent import PatentGap
from mbforge.contracts.patent_runtime import PatentAnalysisBudget, PatentTaskScope
from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.evidence import SourceEvidence
from mbforge.service.ports.patent_analysis import get_patent_task_registry

DOC = "doc-bound"
OTHER_DOC = "doc-other"
CRED = "credential-bound-0001"
ATTEMPT = "attempt-1"
SIGNATURE = "signature-1"
TOOLS = "/api/v1/patent-analysis/tools"


def _seed_evidence(
    root: Path,
    doc_id: str,
    page: int,
    box: tuple[float, float, float, float],
    text: str,
    kind: str = "text",
) -> str:
    """Seed one ``source_evidence`` row and return its canonical id."""
    evidence = SourceEvidence.create(
        doc_id=doc_id, page=page, bbox=box, raw_text=text, kind=kind
    )
    db = DatabaseManager.get(str(root))
    db.initialize()
    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO source_evidence
                (evidence_id, doc_id, page,
                 bbox_x0, bbox_y0, bbox_x1, bbox_y1, raw_text, kind)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (evidence.evidence_id, doc_id, page, *evidence.bbox, text, kind),
        )
        conn.commit()
    return evidence.evidence_id


def _seed_structure(
    root: Path,
    page: int,
    label: str,
    smiles: str,
    box: tuple[float, float, float, float] = (0.0, 0.0, 10.0, 10.0),
) -> str:
    """Seed one recognized structure as its ``molecule`` evidence payload.

    That row is the only place a candidate's labels live: the read path rebuilds
    every candidate from its own observation payload, so a fixture that wrote
    ``molecules`` rows instead would produce label-less candidates.
    """
    from mbforge.domain.types import ExtractionResult

    payload = ExtractionResult(
        smiles=smiles,
        esmiles=smiles,
        moldet_conf=0.9,
        bbox_pdf=box,
        page_idx=page - 1,
        name="",
        mol_img_path=f"storage/{DOC}/crops/{label}.png",
        properties={"ocr_labels": [label], "ocr_labels_primary": label},
    ).to_dict()
    return _seed_evidence(
        root, DOC, page, box, json.dumps(payload, ensure_ascii=False), kind="molecule"
    )


def _register(
    root: Path,
    *,
    gaps: list[Any] | None = None,
) -> None:
    get_patent_task_registry().register(
        CRED,
        PatentTaskScope(
            library_root=str(root),
            doc_id=DOC,
            run_id="run-1",
            attempt_id=ATTEMPT,
            evidence_signature=SIGNATURE,
            budget=PatentAnalysisBudget(
                max_model_turns=24,
                wall_clock_seconds=600,
                max_total_tokens=80_000,
                digest_char_budget=60_000,
            ),
        ),
        gaps=gaps,
    )


def _seed_gap(root: Path) -> PatentGap:
    """Seed the gap's excerpt rows and return the gap over them."""
    table = _seed_evidence(
        root,
        DOC,
        21,
        (0.0, 0.0, 10.0, 10.0),
        "| 化合物编号 | IC50(nM) |\n| --- | --- |\n| 实施例1 | 十 |",
        "tab",
    )
    return PatentGap(
        gap_id="complex_activity_table:ev-21",
        gap_kind="table",
        code="complex_activity_table",
        message="activity table contains unparsed cells",
        page_start=21,
        page_end=21,
        evidence_ids=[table],
        excerpt="| 化合物编号 | IC50(nM) |\n| --- | --- |\n| 实施例1 | 十 |",
    )


def _gap_answer(gap: PatentGap, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "gap_id": gap.gap_id,
        "gap_kind": gap.gap_kind,
        "doc_id": DOC,
        "attempt_id": ATTEMPT,
        "evidence_signature": SIGNATURE,
        "status": "answered",
        "evidence_ids": list(gap.evidence_ids),
        "items": [
            {
                "local_key": "m-1",
                "metric": "IC50",
                "value": {"raw_text": "+", "qualitative": "+"},
                "row_label_raw": "实施例1",
                "compound_label_key": "1",
                "page": 21,
                "evidence_ids": list(gap.evidence_ids),
            }
        ],
    }
    base.update(overrides)
    return base


def _reading_item(
    gap: PatentGap,
    *,
    local_key: str,
    row_label_raw: str,
    compound_label_key: str,
    **extra: Any,
) -> dict[str, Any]:
    """One numeric reading row attached to ``row_label_raw``."""
    item: dict[str, Any] = {
        "local_key": local_key,
        "metric": "CYP3A4抑制率",
        "value": {
            "raw_text": "26.3",
            "operator": "=",
            "value": 26.3,
            "unit": "%",
        },
        "row_label_raw": row_label_raw,
        "compound_label_key": compound_label_key,
        "page": 21,
        "evidence_ids": list(gap.evidence_ids),
    }
    item.update(extra)
    return item


def test_table_answer_requires_quoted_work_and_consistent_number(
    app_client: TestClient, tmp_library: Path
) -> None:
    """Citing a real legend ID must not authorize invented or unsupported readings."""
    gap = _seed_gap(tmp_library)
    work_id = gap.evidence_ids[0]
    context_id = _seed_evidence(
        tmp_library, DOC, 21, (0.0, 20.0, 10.0, 30.0), '"+" means IC50 > 1000 nM'
    )
    gap.evidence_ids.append(context_id)
    gap.rule_context["row_label_type"] = "example"
    gap.rule_context["evidence"] = [
        {"evidence_id": work_id, "role": "work", "raw_text": gap.excerpt},
        {
            "evidence_id": context_id,
            "role": "context",
            "raw_text": '"+" means IC50 > 1000 nM',
        },
    ]
    _register(tmp_library, gaps=[gap])
    answer = _gap_answer(gap)
    item = answer["items"][0]
    item["value"] = {"raw_text": "十", "qualitative": "+"}

    def submit() -> dict[str, Any]:
        return app_client.post(
            f"{TOOLS}/submit-gap-answer", json={"credential": CRED, "answer": answer}
        ).json()

    assert submit()["success"] is False
    item["source_quote"] = "| 实施例1 | 十 |"
    item["source_column"] = 1
    item["value"]["value"] = 999
    assert submit()["success"] is False
    item["value"].pop("value")
    item["evidence_ids"] = [context_id]
    assert submit()["success"] is False
    item["evidence_ids"] = [work_id, context_id]
    item["metric"] = "pIC50"
    assert submit()["success"] is False
    item["metric"] = "IC50"
    assert submit()["success"] is True
    staged = get_patent_task_registry().gap_answers(CRED)
    assert staged[0].items[0].source_quote == "| 实施例1 | 十 |"
    assert not staged[0].items[0].molecule_ref
    assert staged[0].items[0].compound_label_key == "@example:1"


def test_table_answer_keeps_each_value_in_its_printed_label_pair(
    app_client: TestClient, tmp_library: Path
) -> None:
    """A whole-row quote must not transfer a sibling column's value to a label."""
    from mbforge.service.pipeline.patent.llm_gaps import build_gaps

    text = (
        "| 化合物编号 | IC50(nM) | 化合物编号 | IC50(nM) |\n"
        "| --- | --- | --- | --- |\n"
        "| 化合物1 | 10 | 化合物2 | 20 |\n"
        "| 化合物3 | 30 |  | 40 |"
    )
    eid = _seed_evidence(tmp_library, DOC, 21, (0.0, 0.0, 10.0, 10.0), text, "tab")
    gap = build_gaps(
        issues=[{"code": "complex_activity_table", "evidence_ids": [eid]}],
        evidence=[
            SourceEvidence(
                doc_id=DOC,
                page=21,
                bbox=(0, 0, 10, 10),
                evidence_id=eid,
                raw_text=text,
                kind="tab",
            )
        ],
    )[0][0]
    _register(tmp_library, gaps=[gap])
    answer = _gap_answer(gap)
    item = answer["items"][0]
    item.update(
        row_label_raw="化合物1",
        compound_label_key="1",
        source_quote="| 化合物1 | 10 | 化合物2 | 20 |",
    )
    item["value"] = {"raw_text": "20", "value": 20, "unit": "nM"}

    def submit() -> dict[str, Any]:
        return app_client.post(
            f"{TOOLS}/submit-gap-answer", json={"credential": CRED, "answer": answer}
        ).json()

    assert submit()["success"] is False
    item["source_column"] = 3
    assert submit()["success"] is False
    item["source_column"] = 1
    assert submit()["success"] is False
    item["value"] = {"raw_text": "10", "value": 10, "unit": "nM"}
    item["row_label_raw"] = "1"
    assert (
        submit()["success"] is False
    )  # A substring of 化合物1 is not the printed cell.
    item["row_label_raw"] = "化合物3"
    item["source_quote"] = "| 化合物3 | 30 |  | 40 |"
    item["value"] = {"raw_text": "40", "value": 40, "unit": "nM"}
    item["source_column"] = 3
    assert (
        submit()["success"] is False
    )  # The missing sibling label cannot borrow 化合物3.
    item.update(
        row_label_raw="化合物1",
        source_quote="| 化合物1 | 10 | 化合物2 | 20 |",
        source_column=1,
    )
    item["value"] = {"raw_text": "10", "value": 10, "unit": "nM"}
    assert submit()["success"] is True
    assert get_patent_task_registry().gap_answers(CRED)[0].items[0].source_column == 1


def test_tools_require_a_registered_credential_and_never_invent_structures(
    app_client: TestClient, tmp_library: Path
) -> None:
    """An unknown credential is refused; a bound document without structures is []."""
    unknown = app_client.post(
        f"{TOOLS}/get-gap",
        json={"credential": "credential-not-registered"},
    )
    assert unknown.status_code == 422

    _register(tmp_library)
    payload = app_client.post(
        f"{TOOLS}/list-molecules", json={"credential": CRED}
    ).json()
    assert payload["success"] is True
    assert payload["items"] == []
    assert payload["total"] == 0


def test_a_label_lookup_returns_every_structure_that_carries_it(
    app_client: TestClient, tmp_library: Path
) -> None:
    """``list_molecules(label=…)`` answers the designation question in one call.

    The catalogue is paged, so a session that needs "the structure for 化合物77" saw
    one blind page of it and had its second lookup refused — the live v3 run answered
    two lookups inside one gap and then died on the gap budget. The lookup compares in
    the key space the association uses, so the example spelling reaches the structure
    carrying the number while a *different* designation (``77A``) does not.
    """
    _register(tmp_library)
    # A recognized structure is read back from its own ``molecule`` evidence row,
    # so the fixture stores it the way the detection pass does.
    _seed_structure(tmp_library, 30, "77", "CCO")
    _seed_structure(tmp_library, 30, "77A", "CCN", (20.0, 0.0, 30.0, 10.0))
    _seed_structure(tmp_library, 31, "9", "CCC")

    def lookup(label: str) -> dict[str, Any]:
        return app_client.post(
            f"{TOOLS}/list-molecules",
            json={"credential": CRED, "label": label},
        ).json()

    compound = lookup("化合物77")
    assert compound["success"] is True
    assert compound["total"] == 1
    assert [item["mol_id"] for item in compound["items"]] == ["CCO"]

    # ``实施例77`` prints no compound number, but the catalogue stores whichever
    # spelling the crop carried -- the reader's designation still finds it.
    example = lookup("实施例77")
    assert [item["mol_id"] for item in example["items"]] == ["CCO"]

    # A *different* designation is not a fuzzy match, and the unlabelled catalogue
    # still pages whole.
    assert lookup("化合物77A")["total"] == 1
    assert lookup("化合物404")["total"] == 0
    assert lookup("")["total"] == 3


def test_gap_worklist_serves_the_gap_then_advances_after_a_valid_answer(
    app_client: TestClient, tmp_library: Path
) -> None:
    """``get-gap`` serves the excerpt and its remaining count; a valid
    ``submit-gap-answer`` stages it and leaves no next gap. Resubmitting the same
    gap replaces that staged answer, and a cancelled attempt refuses new ones."""
    gap = _seed_gap(tmp_library)
    _register(tmp_library, gaps=[gap])

    payload = app_client.post(f"{TOOLS}/get-gap", json={"credential": CRED}).json()

    assert payload["success"] is True
    assert payload["gap"]["gap_id"] == gap.gap_id
    assert payload["gap"]["gap_kind"] == "table"
    assert payload["gap"]["page_start"] == 21
    assert payload["remaining"] == 1

    staged = app_client.post(
        f"{TOOLS}/submit-gap-answer",
        json={"credential": CRED, "answer": _gap_answer(gap)},
    ).json()
    assert staged["success"] is True
    assert staged["staged"] is True
    assert staged["status"] == "answered"
    assert staged["next_gap_id"] is None

    after = app_client.post(f"{TOOLS}/get-gap", json={"credential": CRED}).json()
    assert after["success"] is False
    assert "all gaps are answered" in after["error"]

    # The same gap submitted twice replaces its staged answer instead of forking.
    resubmitted = app_client.post(
        f"{TOOLS}/submit-gap-answer",
        json={"credential": CRED, "answer": _gap_answer(gap)},
    ).json()
    assert resubmitted["success"] is True
    counted = app_client.post(
        f"{TOOLS}/get-gap", json={"credential": CRED, "gap_id": gap.gap_id}
    ).json()
    assert counted["answered"] == 1

    # A cancelled attempt refuses further answers, through the same endpoint.
    assert get_patent_task_registry().request_cancel(CRED) is True
    cancelled = app_client.post(
        f"{TOOLS}/submit-gap-answer",
        json={"credential": CRED, "answer": _gap_answer(gap)},
    ).json()
    assert cancelled["success"] is False
    assert "attempt was cancelled" in cancelled["error"]


def _structure_gap(root: Path) -> PatentGap:
    """A gap whose excerpt prints a label the document already owns."""
    gap = _seed_gap(root)
    gap.rule_context = {
        "structures": [
            {"label": "77", "mol_id": "MOL-77", "name": "77", "page": 21},
            {"label": "46", "mol_id": "MOL-46", "name": "46", "page": 21},
        ]
    }
    return gap


def test_row_label_attachment_is_deterministic_over_the_gaps_structures(
    app_client: TestClient, tmp_library: Path
) -> None:
    """Python makes the label→structure link: ``化合物77`` reaches the structure
    labelled ``77``, an unowned designation stays unattached, a duplicated label
    is never silently picked, and an 实施例 designation is a distinct identity."""
    gap = _structure_gap(tmp_library)
    gap.rule_context.update({"row_labels": ["77"]})

    _register(tmp_library, gaps=[gap])
    attached = app_client.post(
        f"{TOOLS}/submit-gap-answer",
        json={
            "credential": CRED,
            "answer": _gap_answer(
                gap,
                items=[
                    _reading_item(
                        gap,
                        local_key="m-1",
                        row_label_raw="化合物77",
                        compound_label_key="77",
                        compound_label_raw="化合物77",
                    )
                ],
            ),
        },
    ).json()
    assert attached["success"] is True
    assert attached["structures_attached"] == 1
    assert (
        get_patent_task_registry().gap_answers(CRED)[0].items[0].molecule_ref
        == "MOL-77"
    )

    _register(tmp_library, gaps=[gap])
    outside_chunk = app_client.post(
        f"{TOOLS}/submit-gap-answer",
        json={
            "credential": CRED,
            "answer": _gap_answer(
                gap,
                items=[
                    _reading_item(
                        gap,
                        local_key="outside",
                        row_label_raw="化合物46",
                        compound_label_key="46",
                    )
                ],
            ),
        },
    ).json()
    assert outside_chunk["success"] is False
    assert "outside the assigned table chunk" in outside_chunk["error"]

    gap.rule_context.pop("row_labels")
    _register(tmp_library, gaps=[gap])
    unowned = app_client.post(
        f"{TOOLS}/submit-gap-answer",
        json={
            "credential": CRED,
            "answer": _gap_answer(
                gap,
                items=[
                    _reading_item(
                        gap,
                        local_key="m-1",
                        row_label_raw="化合物999",
                        compound_label_key="999",
                    )
                ],
            ),
        },
    ).json()
    assert unowned["success"] is True
    assert unowned["structures_attached"] == 0

    # A second structure printed with the same label makes ``77`` ambiguous;
    # examples and compounds sharing a number are still distinct identities.
    gap.rule_context["structures"].append({"label": "77", "mol_id": "MOL-other"})
    _register(tmp_library, gaps=[gap])
    ambiguous = app_client.post(
        f"{TOOLS}/submit-gap-answer",
        json={
            "credential": CRED,
            "answer": _gap_answer(
                gap,
                items=[
                    _reading_item(
                        gap,
                        local_key="ambiguous",
                        row_label_raw="化合物77",
                        compound_label_key="77",
                    ),
                    _reading_item(
                        gap,
                        local_key="example",
                        row_label_raw="实施例46",
                        compound_label_key="46",
                    ),
                    _reading_item(
                        gap,
                        local_key="compound",
                        row_label_raw="化合物46",
                        compound_label_key="46",
                    ),
                ],
            ),
        },
    ).json()
    assert ambiguous["success"] is True
    assert ambiguous["structures_attached"] == 1
    staged = get_patent_task_registry().gap_answers(CRED)[0]
    assert [item.molecule_ref for item in staged.items] == ["", "", "MOL-46"]

    example_gap = gap
    example_gap.rule_context = {
        "row_labels": ["1"],
        "row_label_type": "example",
        "structures": [{"label": "实施例1", "mol_id": "MOL-example-1"}],
    }
    _register(tmp_library, gaps=[example_gap])
    example = app_client.post(
        f"{TOOLS}/submit-gap-answer",
        json={
            "credential": CRED,
            "answer": _gap_answer(
                example_gap,
                items=[
                    _reading_item(
                        example_gap,
                        local_key="example-row",
                        row_label_raw="实施例1",
                        compound_label_key="1",
                    )
                ],
            ),
        },
    ).json()
    assert example["success"] is True
    assert example["structures_attached"] == 1

    # A publication designation under an example header must not normalize to
    # the same empty key as every unrecognized label.
    example_gap.rule_context["row_labels"].append("WO2022067094")
    _register(tmp_library, gaps=[example_gap])
    external = _gap_answer(example_gap)
    external["items"][0]["row_label_raw"] = "unknown-control"
    rejected = app_client.post(
        f"{TOOLS}/submit-gap-answer", json={"credential": CRED, "answer": external}
    ).json()
    assert rejected["success"] is False
    external["items"][0]["row_label_raw"] = "WO2022067094"
    accepted = app_client.post(
        f"{TOOLS}/submit-gap-answer", json={"credential": CRED, "answer": external}
    ).json()
    assert accepted["success"] is True
    item = get_patent_task_registry().gap_answers(CRED)[0].items[0]
    assert item.compound_label_key == "wo2022067094" and not item.molecule_ref


def test_gap_answer_validation_refuses_outside_evidence_kind_and_unknown_refs(
    app_client: TestClient, tmp_library: Path
) -> None:
    """A gap answer may only cite its own excerpt, must match its gap kind, and
    may only reference a structure ``list_molecules`` returned."""
    gap = _seed_gap(tmp_library)
    outsider = _seed_evidence(
        tmp_library, DOC, 40, (0.0, 0.0, 10.0, 10.0), "其它页的文本"
    )
    _register(tmp_library, gaps=[gap])

    outside = app_client.post(
        f"{TOOLS}/submit-gap-answer",
        json={
            "credential": CRED,
            "answer": _gap_answer(gap, evidence_ids=[outsider]),
        },
    ).json()
    assert outside["success"] is False
    assert outside["outside_evidence_ids"] == [outsider]

    mismatch = app_client.post(
        f"{TOOLS}/submit-gap-answer",
        json={
            "credential": CRED,
            "answer": _gap_answer(gap, gap_kind="prose_measurement"),
        },
    ).json()
    assert mismatch["success"] is False
    assert "does not match the gap" in mismatch["error"]

    answer = _gap_answer(gap)
    answer["items"][0]["molecule_ref"] = "CCO"  # a SMILES is not a reference
    unknown_ref = app_client.post(
        f"{TOOLS}/submit-gap-answer",
        json={"credential": CRED, "answer": answer},
    ).json()
    assert unknown_ref["success"] is False
    assert unknown_ref["unknown_molecule_refs"] == ["CCO"]


def test_a_follow_up_excerpt_is_single_shot_and_widens_what_the_answer_may_cite(
    app_client: TestClient, tmp_library: Path
) -> None:
    """A gap gets exactly one follow-up excerpt; once fetched, the answer may
    cite it, and coverage counts real returns (a truncated row is not a read)."""
    gap = _seed_gap(tmp_library)
    neighbour = _seed_evidence(
        tmp_library, DOC, 20, (0.0, 0.0, 10.0, 10.0), "测定方法：FLIPR 实验"
    )
    _register(tmp_library, gaps=[gap])

    before = app_client.post(
        f"{TOOLS}/submit-gap-answer",
        json={
            "credential": CRED,
            "answer": _gap_answer(gap, evidence_ids=[neighbour]),
        },
    ).json()
    assert before["success"] is False

    fetched = app_client.post(
        f"{TOOLS}/request-excerpt",
        json={"credential": CRED, "gap_id": gap.gap_id, "evidence_ids": [neighbour]},
    ).json()
    assert fetched["success"] is True
    assert fetched["items"]

    second = app_client.post(
        f"{TOOLS}/request-excerpt",
        json={"credential": CRED, "gap_id": gap.gap_id, "page_from": 20, "page_to": 22},
    ).json()
    assert second["success"] is False
    assert "already asked for a follow-up excerpt" in second["error"]

    after = app_client.post(
        f"{TOOLS}/submit-gap-answer",
        json={
            "credential": CRED,
            "answer": _gap_answer(gap, evidence_ids=[neighbour]),
        },
    ).json()
    assert after["success"] is True

    # A fresh attempt: the truncated row is returned but never recorded as read.
    truncated = _seed_evidence(tmp_library, DOC, 22, (0.0, 0.0, 10.0, 10.0), "x" * 4000)
    _register(tmp_library, gaps=[gap])
    coverage = app_client.post(
        f"{TOOLS}/request-excerpt",
        json={"credential": CRED, "gap_id": gap.gap_id, "evidence_ids": [truncated]},
    ).json()
    assert coverage["success"] is True
    assert coverage["items"][0]["truncated"] is True
    reads = get_patent_task_registry().evidence_reads(CRED)
    assert reads[truncated] is False
    assert gap.evidence_ids[0] not in reads  # never read at all
