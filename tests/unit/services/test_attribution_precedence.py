"""Attribution precedence: which link a reader should trust.

Covers ``activity_queries.effective_attribution`` — the rule that a human link
outranks the agent's adjudication, which outranks the rules'. A reading may
carry several links at once (a rule baseline plus a human override, or a
contested pair); the read surface must not report them as equals, and a
rejected link must never win.
"""

from __future__ import annotations

from mbforge.service.use_cases.documents.activity_queries import (
    effective_attribution,
)


def _link(method: str, status: str, mol_id: str) -> dict[str, str]:
    return {"method": method, "review_status": status, "mol_id": mol_id}


def test_human_outranks_agent_and_rule() -> None:
    links = [
        _link("rule", "accepted", "rule-mol"),
        _link("agent", "accepted", "agent-mol"),
        _link("human", "accepted", "human-mol"),
    ]
    assert effective_attribution(links)["mol_id"] == "human-mol"


def test_agent_outranks_rule() -> None:
    links = [
        _link("rule", "accepted", "rule-mol"),
        _link("agent", "accepted", "agent-mol"),
    ]
    assert effective_attribution(links)["mol_id"] == "agent-mol"


def test_a_rejected_human_link_does_not_win() -> None:
    links = [
        _link("human", "rejected", "human-mol"),
        _link("agent", "accepted", "agent-mol"),
    ]
    assert effective_attribution(links)["mol_id"] == "agent-mol"


def test_accepted_outranks_pending_within_one_method() -> None:
    links = [
        _link("agent", "pending", "pending-mol"),
        _link("agent", "accepted", "accepted-mol"),
    ]
    assert effective_attribution(links)["mol_id"] == "accepted-mol"


def test_no_usable_link_returns_none() -> None:
    assert effective_attribution([]) is None
    assert effective_attribution([_link("human", "rejected", "human-mol")]) is None
