# Markush Review Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Markush review-to-enumeration workflow so only confirmed, server-validated relationships can generate candidates and only explicitly confirmed generated candidates enter `molecules` with provenance.

**Architecture:** Keep the existing development-stage SQLite schema and current router/service boundaries. Add derived eligibility fields to candidate detail, centralize server-side enumeration authorization in `core/markush_enumerate.py`, make generated decisions state-aware and provenance-preserving, then synchronize TypeScript clients, focused tests, browser acceptance, and living docs.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite, pytest, React 19, TypeScript 6, React Query 5, Vitest, Testing Library.

---

## File Map

### Backend

- Modify `src/mbforge/models/markush.py`: add stable candidate-detail identity and enumeration eligibility fields.
- Modify `src/mbforge/core/markush_review.py`: derive stable IDs/eligibility from canonical rows; preserve existing optimistic locking and role transitions.
- Modify `src/mbforge/core/markush_enumerate.py`: validate confirmed scaffold/site/option/mount/fragment state, resolve server-side SMILES, reject invalid selections before creating a run, enforce generated-candidate one-time decisions, and write molecule provenance.
- Modify `src/mbforge/routers/markush/enumeration.py`: pass database connection and selection into the authorization-aware core path; retain structured error propagation.
- Modify `src/mbforge/routers/markush/_shared.py`: add a typed selection conversion only if needed by the new core validation; do not allow client SMILES to become authoritative.
- Modify `src/mbforge/models/markush_enumerate.py`: type request/response fields and generated decision response consistently.
- Modify `src/mbforge/core/database.py`: only add canonical indexes/constraints if tests prove required; do not add migration code or historical compatibility paths.

### Frontend

- Modify `frontend/src/api/http/markush.ts`: mirror candidate eligibility fields, use strict generated decision and enumeration response types, and represent selections as server-validated fragment IDs.
- Modify `frontend/src/api/query/useMarkush.ts`: propagate updated response types and invalidate candidate/site/enumeration/molecule caches after decisions.
- Modify `frontend/src/components/markush/MarkushReviewPanel.tsx`: use stable candidate fields first, show explicit block reasons, and render `SiteEditor`/`EnumerationPanel` only when eligibility permits.
- Modify `frontend/src/components/markush/EnumerationPanel.tsx`: preserve site/option IDs, disable preview/run when server eligibility data is not satisfied, and handle generated decisions as one-time transitions.
- Modify `frontend/src/components/markush/__tests__/MarkushReviewPanel.test.tsx`: cover stable identity, eligibility, action states, and blocked enumeration.
- Create `frontend/src/components/markush/__tests__/EnumerationPanel.test.tsx`: cover server selections, preview/run gating, and generated-candidate review.

### Tests

- Modify `tests/unit/core/test_markush_review.py`: add stable identity and eligibility assertions.
- Modify `tests/unit/core/test_markush_enumerate.py`: add authorization, identity, state-transition, provenance, and rollback tests.
- Modify `tests/unit/core/test_markush_sites.py`: add confirmed-state and cross-scaffold/site relationship cases if existing service tests do not cover them.
- Modify `tests/unit/routers/test_markush_router.py`: add candidate-detail API contract and structured error cases.
- Create or modify `tests/unit/routers/test_markush_enumeration_router.py`: cover preview/run/generated-decision endpoint contracts and invalid selection behavior.

### Documentation and acceptance

- Modify `docs/wiki/pipeline.md`: document Markush state and enumeration gates.
- Modify `docs/api/README.md`: update only if endpoint payload/contract grouping changes.
- Modify `TODO/INDEX.md`: record implementation and browser acceptance evidence.
- Modify `CHANGELOG.md`: record user-visible review/enumeration behavior if project convention requires an Unreleased entry.
- Create `tests/eval/markush_review_closure.md` or equivalent acceptance record only if the repository's eval convention accepts Markdown evidence; otherwise keep browser evidence in the task/PR record and document the command.

---

## Task 1: Lock candidate-detail contract

**Files:**
- Modify: `src/mbforge/models/markush.py:103-108`
- Modify: `src/mbforge/core/markush_review.py:174-199`
- Modify: `frontend/src/api/http/markush.ts:54-88`
- Test: `tests/unit/core/test_markush_review.py`
- Test: `tests/unit/routers/test_markush_router.py`

- [ ] **Step 1: Write failing backend tests for stable identity and eligibility**

Add tests after `test_confirm_fragment_writes_markush_fragment`:

```python
def test_candidate_detail_exposes_destination_id_and_blocks_unlinked_fragment(database):
    candidate_id = _seed_one(database)
    with database.mol_conn() as conn:
        apply_decision(
            conn,
            candidate_id=candidate_id,
            expected_version=1,
            action="confirm_fragment",
        )
        detail = get_candidate_detail(conn, candidate_id)
    assert detail.fragment_id
    assert detail.scaffold_id is None
    assert detail.enumeration_eligible is False
    assert detail.enumeration_block_reasons


def test_candidate_detail_exposes_scaffold_id_after_confirmation(database):
    candidate_id = _seed_one(database, label="Formula I")
    with database.mol_conn() as conn:
        apply_decision(
            conn,
            candidate_id=candidate_id,
            expected_version=1,
            action="confirm_scaffold",
        )
        detail = get_candidate_detail(conn, candidate_id)
    assert detail.scaffold_id
    assert detail.fragment_id is None
    assert detail.enumeration_eligible is False
    assert "confirmed attachment site" in " ".join(detail.enumeration_block_reasons)
```

Add API assertion that `/api/v1/markush/get` contains keys `scaffold_id`, `fragment_id`, `enumeration_eligible`, and `enumeration_block_reasons`.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
uv run pytest tests/unit/core/test_markush_review.py -q
uv run pytest tests/unit/routers/test_markush_router.py -q
```

Expected: FAIL because `MarkushCandidateDetail` lacks the four fields.

- [ ] **Step 3: Add Pydantic fields**

In `MarkushCandidateDetail`, add:

```python
scaffold_id: str | None = None
fragment_id: str | None = None
enumeration_eligible: bool = False
enumeration_block_reasons: list[str] = Field(default_factory=list)
```

Mirror exact fields in the TypeScript `MarkushCandidateDetail` interface.

- [ ] **Step 4: Add canonical-row lookup and derived eligibility**

Add a helper in `src/mbforge/core/markush_review.py`:

```python
def _candidate_destination(
    conn: sqlite3.Connection,
    candidate_id: str,
) -> tuple[str | None, str | None]:
    scaffold = conn.execute(
        """
        SELECT scaffold_id FROM markush_scaffolds
        WHERE json_extract(properties, '$.review_candidate_id') = ?
        ORDER BY created_at DESC, scaffold_id DESC
        LIMIT 1
        """,
        (candidate_id,),
    ).fetchone()
    fragment = conn.execute(
        """
        SELECT fragment_id FROM markush_fragments
        WHERE json_extract(properties, '$.review_candidate_id') = ?
        ORDER BY created_at DESC, fragment_id DESC
        LIMIT 1
        """,
        (candidate_id,),
    ).fetchone()
    return (
        scaffold["scaffold_id"] if scaffold else None,
        fragment["fragment_id"] if fragment else None,
    )
```

Add a helper that returns `True` only when a confirmed scaffold has at least one confirmed site and one confirmed option/mount connected to a confirmed fragment. Return explicit reasons such as:

```python
["candidate is not a confirmed scaffold"]
["no confirmed attachment site"]
["no confirmed fragment relationship"]
```

Use these values while constructing `MarkushCandidateDetail`. Keep `properties.scaffold_id` as a fallback only when canonical lookup finds no row.

- [ ] **Step 5: Run focused tests and type-check**

Run:

```bash
uv run pytest tests/unit/core/test_markush_review.py tests/unit/routers/test_markush_router.py -q
npm --prefix frontend run build
```

Expected: focused backend tests pass; frontend build passes.

- [ ] **Step 6: Commit atomic contract change**

```bash
git add src/mbforge/models/markush.py src/mbforge/core/markush_review.py frontend/src/api/http/markush.ts tests/unit/core/test_markush_review.py tests/unit/routers/test_markush_router.py
git commit -m "feat(markush): expose review eligibility contract"
```

---

## Task 2: Enforce server-side enumeration authorization

**Files:**
- Modify: `src/mbforge/core/markush_enumerate.py:48-74,207-362`
- Modify: `src/mbforge/routers/markush/enumeration.py:29-79`
- Modify: `src/mbforge/models/markush_enumerate.py:15-53`
- Modify: `tests/unit/core/test_markush_enumerate.py`
- Create or modify: `tests/unit/routers/test_markush_enumeration_router.py`

- [ ] **Step 1: Add failing authorization tests**

Add helpers and tests:

```python
def _seed_confirmed_relationship(database):
    _seed_scaffold(database, scaffold_id="sc-1", smiles="[*:1]C1CCCCC1")
    with database.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_sites
                (site_id, scaffold_id, site_label, atom_map_num, status)
            VALUES ('site-1', 'sc-1', 'R1', 1, 'confirmed')
            """
        )
        conn.execute(
            """
            INSERT INTO markush_fragments
                (fragment_id, scaffold_id, doc_id, label, smiles, status)
            VALUES ('frag-1', 'sc-1', 'doc-1', 'F', 'F', 'confirmed')
            """
        )
        conn.execute(
            """
            INSERT INTO markush_options
                (option_id, site_id, fragment_id, status)
            VALUES ('opt-1', 'site-1', 'frag-1', 'confirmed')
            """
        )
        conn.commit()


def test_run_rejects_unconfirmed_site_or_fragment(database):
    _seed_scaffold(database)
    with database.mol_conn() as conn, pytest.raises(MarkushEnumerationError):
        run_enumeration(
            conn,
            scaffold_id="sc-1",
            selection=[SiteSelection("R1", 1, ["frag-1"])],
            requested_limit=10,
        )


def test_run_resolves_fragment_id_from_database(database):
    _seed_confirmed_relationship(database)
    with database.mol_conn() as conn:
        result = run_enumeration(
            conn,
            scaffold_id="sc-1",
            selection=[SiteSelection("R1", 1, ["frag-1"])],
            requested_limit=10,
        )
        items = list_run_results(conn, result.run_id)
    assert result.status == "completed"
    assert items
    assert items[0]["assignments"][0]["fragment_id"] == "frag-1"


def test_run_rejects_fragment_from_other_scaffold(database):
    _seed_confirmed_relationship(database)
    with database.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_scaffolds(scaffold_id, doc_id, smiles, status)
            VALUES ('sc-2', 'doc-2', '[*:1]CC', 'confirmed')
            """
        )
        conn.execute(
            """
            INSERT INTO markush_fragments(fragment_id, doc_id, smiles, status)
            VALUES ('frag-2', 'doc-2', 'Cl', 'confirmed')
            """
        )
        conn.commit()
        with pytest.raises(MarkushEnumerationError):
            run_enumeration(
                conn,
                scaffold_id="sc-1",
                selection=[SiteSelection("R1", 1, ["frag-2"])],
                requested_limit=10,
            )
```

Use the repository's existing `MBForgeError` subclass pattern for `MarkushEnumerationError`, with status 422 and a machine-readable validation code.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/core/test_markush_enumerate.py tests/unit/routers/test_markush_enumeration_router.py -q
```

Expected: FAIL because current `run_enumeration` requires client-provided `scaffold_smiles` and treats fragment strings as raw SMILES.

- [ ] **Step 3: Change core signature to use only server identity**

Replace the authoritative part of the signature with:

```python
def run_enumeration(
    conn: sqlite3.Connection,
    *,
    scaffold_id: str,
    selection: list[SiteSelection],
    requested_limit: int,
) -> GenerationResult:
```

Add `_load_authorized_selection()` that:

1. Loads scaffold row and requires `status == "confirmed"`.
2. Loads sites by `(scaffold_id, site_label, atom_map_num)` and requires `status == "confirmed"`.
3. Loads each selected `fragment_id` and requires `status == "confirmed"`.
4. Requires a confirmed `markush_options` row or confirmed `markush_mounts` row connecting site and fragment.
5. Returns `(scaffold_smiles, resolved_selection)` where resolved selection contains server-side fragment SMILES but retains fragment IDs for assignments.
6. Raises `MarkushEnumerationError` before any generation-run insert if any check fails.

Use an internal resolved dataclass rather than changing the public wire type:

```python
@dataclass(frozen=True)
class ResolvedFragment:
    fragment_id: str
    smiles: str

@dataclass(frozen=True)
class ResolvedSiteSelection:
    site_label: str
    atom_map_num: int
    fragments: list[ResolvedFragment]
```

Do not accept arbitrary SMILES as selection identity. If an old test or client sends a non-ID value, return a validation error.

- [ ] **Step 4: Update generation assignment payload**

Write assignments with both stable ID and resolved SMILES:

```python
{
    "site_label": site.site_label,
    "atom_map_num": site.atom_map_num,
    "fragment_id": fragment.fragment_id,
    "fragment_smiles": fragment.smiles,
}
```

Keep `combination_key` deterministic using fragment IDs, not raw client strings.

- [ ] **Step 5: Update router and request models**

Remove `scaffold_smiles` loading from `enumeration.py`. Call:

```python
result = await run_db_sync(
    db,
    lambda conn: run_enumeration(
        conn,
        scaffold_id=body.scaffold_id,
        selection=selections,
        requested_limit=body.requested_limit,
    ),
)
```

Apply the same authorization path to preview. Preview must validate IDs and return the theoretical count only after validation succeeds.

Set TypeScript `EnumerationPreviewResponse` and `EnumerationRunResponse` to mirror Pydantic fields:

```ts
export interface EnumerationPreviewResponse {
  theoretical_count: number
  requested_limit: number
  truncated: boolean
}

export interface EnumerationRunResponse {
  run_id: string
  theoretical_count: number
  written_count: number
  truncated: boolean
  status: string
  error: string | null
}
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/unit/core/test_markush_enumerate.py tests/unit/routers/test_markush_enumeration_router.py -q
npm --prefix frontend run build
```

Expected: all focused tests pass and frontend build passes.

- [ ] **Step 7: Commit authorization change**

```bash
git add src/mbforge/core/markush_enumerate.py src/mbforge/routers/markush/enumeration.py src/mbforge/models/markush_enumerate.py tests/unit/core/test_markush_enumerate.py tests/unit/routers/test_markush_enumeration_router.py frontend/src/api/http/markush.ts
 git commit -m "fix(markush): gate enumeration on confirmed relations"
```

---

## Task 3: Make generated-candidate decisions one-time and provenance-preserving

**Files:**
- Modify: `src/mbforge/core/markush_enumerate.py:365-432`
- Modify: `src/mbforge/models/markush_enumerate.py:74-80`
- Modify: `frontend/src/api/http/markush.ts:421-498`
- Modify: `frontend/src/api/query/useMarkush.ts:285-302`
- Test: `tests/unit/core/test_markush_enumerate.py`
- Test: `tests/unit/routers/test_markush_enumeration_router.py`

- [ ] **Step 1: Add failing decision tests**

```python
def test_generated_candidate_confirm_writes_provenance(database):
    _seed_confirmed_relationship(database)
    with database.mol_conn() as conn:
        result = run_enumeration(
            conn,
            scaffold_id="sc-1",
            selection=[SiteSelection("R1", 1, ["frag-1"])],
            requested_limit=10,
        )
        generated_id = list_run_results(conn, result.run_id)[0]["generated_id"]
        decision = apply_generated_decision(
            conn,
            entity_id=generated_id,
            action="confirm",
            reason="verified",
        )
        row = conn.execute(
            "SELECT properties, review_status FROM molecules WHERE mol_id = ?",
            (generated_id,),
        ).fetchone()
    assert decision["review_status"] == "confirmed"
    assert json.loads(row["properties"])["markush_generation"]["generated_id"] == generated_id
    assert row["review_status"] == "confirmed"


def test_generated_candidate_cannot_be_decided_twice(database):
    _seed_confirmed_relationship(database)
    with database.mol_conn() as conn:
        result = run_enumeration(
            conn,
            scaffold_id="sc-1",
            selection=[SiteSelection("R1", 1, ["frag-1"])],
            requested_limit=10,
        )
        generated_id = list_run_results(conn, result.run_id)[0]["generated_id"]
        apply_generated_decision(conn, entity_id=generated_id, action="reject", reason="bad")
        with pytest.raises(MarkushEnumerationError):
            apply_generated_decision(
                conn, entity_id=generated_id, action="confirm", reason="retry"
            )
```

- [ ] **Step 2: Run focused tests and verify failure**

```bash
uv run pytest tests/unit/core/test_markush_enumerate.py -q
```

Expected: FAIL because current implementation does not reject non-pending rows and writes `{}` properties without provenance.

- [ ] **Step 3: Implement state check and provenance**

Load all generated fields:

```python
row = conn.execute(
    """
    SELECT generated_id, run_id, scaffold_id, combination_key,
           smiles, canonical_smiles, assignments, properties, review_status
    FROM markush_generated_candidates
    WHERE generated_id = ?
    """,
    (entity_id,),
).fetchone()
```

Require `row["review_status"] == "pending"`. Reject unsupported actions before writes. Parse assignments/properties with `safe_json_loads` or validated JSON.

For confirm, write:

```python
properties = {
    "markush_generation": {
        "generated_id": row["generated_id"],
        "run_id": row["run_id"],
        "scaffold_id": row["scaffold_id"],
        "combination_key": row["combination_key"],
        "assignments": assignments,
    }
}
```

Use the canonical SMILES for both `smiles` and `canonical_smiles` only if current molecule schema requires that shape; otherwise preserve generated `smiles` in `smiles` and canonical value in `canonical_smiles`.

Insert molecule, update candidate, and append decision in one caller-owned transaction. Use actual `previous_state` in the decision row. Return `mol_id` on confirm.

- [ ] **Step 4: Synchronize response types and cache invalidation**

Define:

```ts
export type GeneratedReviewStatus = 'pending' | 'confirmed' | 'rejected'
export interface GeneratedDecisionResponse {
  generated_id: string
  review_status: GeneratedReviewStatus
  mol_id: string | null
}
```

Update `markushGeneratedDecide()` and `useMarkushGeneratedDecide()` to use it. Invalidate enumeration results, Markush detail, Markush list, and molecule caches after success.

- [ ] **Step 5: Run focused tests and build**

```bash
uv run pytest tests/unit/core/test_markush_enumerate.py tests/unit/routers/test_markush_enumeration_router.py -q
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 6: Commit generated-candidate change**

```bash
git add src/mbforge/core/markush_enumerate.py src/mbforge/models/markush_enumerate.py frontend/src/api/http/markush.ts frontend/src/api/query/useMarkush.ts tests/unit/core/test_markush_enumerate.py tests/unit/routers/test_markush_enumeration_router.py
git commit -m "fix(markush): preserve generated molecule provenance"
```

---

## Task 4: Harden relation service state and audit behavior

**Files:**
- Modify: `src/mbforge/core/markush_sites.py:117-400`
- Modify: `src/mbforge/models/markush_sites.py:24-138` only if response/action types need tightening
- Test: `tests/unit/core/test_markush_sites.py`

- [ ] **Step 1: Add failing relation-gate tests**

Cover these exact cases:

```python
def test_create_site_requires_confirmed_scaffold(database):
    # Insert scaffold with status='pending'; create_site must raise MarkushSiteError.


def test_create_option_rejects_unconfirmed_fragment(database):
    # Insert confirmed site and pending fragment; fragment-backed option must raise.


def test_confirmed_mount_requires_confirmed_site_and_fragment(database):
    # Insert suggested mount, then reject site or fragment; decide_mount('confirm') must raise.


def test_mount_reject_is_not_reopenable_without_explicit_transition(database):
    # Reject mount; repeated confirm must raise and leave one rejection audit row.
```

Use the existing `MarkushSiteError` and assert no destination row or unintended audit row is written after rejected operations.

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest tests/unit/core/test_markush_sites.py -q
```

Expected: FAIL where current service checks existence but not confirmed state.

- [ ] **Step 3: Add minimal state checks**

Require:

- `create_site`: scaffold status `confirmed`.
- `create_option` with `fragment_id`: fragment status `confirmed`.
- `create_mount`: site status `confirmed`, fragment status `confirmed`.
- `decide_mount(confirm)`: current mount `suggested`, connected site and fragment still confirmed.
- Any repeated transition: raise `MarkushSiteError` before mutation.

Every successful mutation appends an audit decision with actual previous/new state. Preserve existing attachment-count validation.

- [ ] **Step 4: Run tests and commit**

```bash
uv run pytest tests/unit/core/test_markush_sites.py -q
 git add src/mbforge/core/markush_sites.py src/mbforge/models/markush_sites.py tests/unit/core/test_markush_sites.py
 git commit -m "fix(markush): enforce confirmed relation states"
```

Expected: PASS.

---

## Task 5: Update Markush UI to use stable eligibility fields

**Files:**
- Modify: `frontend/src/components/markush/MarkushReviewPanel.tsx:145-241`
- Modify: `frontend/src/components/markush/EnumerationPanel.tsx:23-111`
- Modify: `frontend/src/api/http/markush.ts:54-114`
- Test: `frontend/src/components/markush/__tests__/MarkushReviewPanel.test.tsx`
- Create: `frontend/src/components/markush/__tests__/EnumerationPanel.test.tsx`

- [ ] **Step 1: Add failing component tests**

Extend candidate fixture with:

```ts
scaffold_id: null,
fragment_id: 'frag-1',
enumeration_eligible: false,
enumeration_block_reasons: ['no confirmed attachment site'],
```

Add assertions:

```tsx
it('shows server eligibility reason and does not render enumeration for blocked candidate', () => {
  render(<MarkushReviewPanel candidate={candidate} ... />)
  expect(screen.getByText('no confirmed attachment site')).toBeInTheDocument()
  expect(screen.queryByTestId('markush-enumeration-panel')).not.toBeInTheDocument()
})

it('renders enumeration only for eligible scaffold', () => {
  // Mock useMarkushSites and enumeration hooks; set enumeration_eligible=true.
  // Assert panel exists and scaffold_id comes from candidate.scaffold_id.
})
```

`EnumerationPanel.test.tsx` must assert preview/run buttons stay disabled with no selected confirmed fragment and call the mutation with fragment IDs, not SMILES.

- [ ] **Step 2: Run frontend tests to verify failure**

```bash
npm --prefix frontend run test -- src/components/markush/__tests__/MarkushReviewPanel.test.tsx
```

Expected: FAIL because fixture lacks new fields and component still reads `properties.scaffold_id`.

- [ ] **Step 3: Update component logic**

Use:

```tsx
const scaffoldId = candidate.scaffold_id ?? ''
const blocked = !candidate.enumeration_eligible
```

Render block reasons as a list. Render `SiteEditor` only when `candidate.scaffold_id` is present. Render `EnumerationPanel` only when `candidate.enumeration_eligible && candidate.scaffold_id`.

Do not infer eligibility from a truthy `properties.scaffold_id`. Keep one narrow fallback only if required for old API fixtures, and mark it with a removal comment tied to this contract change.

Update `EnumerationPanel` selection handling to use `option.fragment_id` only. Disable options lacking confirmed fragment identity or with non-confirmed status. Show API error messages through existing UI conventions.

- [ ] **Step 4: Run frontend tests and build**

```bash
npm --prefix frontend run test -- src/components/markush/__tests__/MarkushReviewPanel.test.tsx src/components/markush/__tests__/EnumerationPanel.test.tsx
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 5: Commit UI contract change**

```bash
git add frontend/src/components/markush/MarkushReviewPanel.tsx frontend/src/components/markush/EnumerationPanel.tsx frontend/src/api/http/markush.ts frontend/src/components/markush/__tests__
git commit -m "feat(markush): show enumeration eligibility in review UI"
```

---

## Task 6: Add router contract coverage and full regression tests

**Files:**
- Modify: `tests/unit/routers/test_markush_router.py`
- Create or modify: `tests/unit/routers/test_markush_enumeration_router.py`
- Modify: `tests/unit/core/test_markush_review.py`
- Modify: `tests/unit/core/test_markush_enumerate.py`

- [ ] **Step 1: Add API contract tests**

Cover:

- candidate detail contains four stable eligibility fields;
- stale candidate decision returns existing conflict envelope;
- preview with pending site/fragment returns HTTP 422 and no `markush_generation_runs` row;
- run with other-scaffold fragment returns HTTP 422;
- generated confirm returns `generated_id`, `review_status`, and `mol_id`;
- repeated generated decision returns HTTP 422 and does not append a second state transition.

Use the existing app fixture and temporary `library_root`; do not create a second database setup pattern.

- [ ] **Step 2: Run backend full suite**

```bash
uv run pytest tests/unit/core/test_markush_review.py tests/unit/core/test_markush_sites.py tests/unit/core/test_markush_enumerate.py tests/unit/routers/test_markush_router.py tests/unit/routers/test_markush_enumeration_router.py -q
```

Expected: PASS.

- [ ] **Step 3: Run all backend tests and lint**

```bash
uv run pytest tests/ -q
uv run ruff check src tests
uv run ruff format src tests --check
```

Expected: PASS. Any failure must be fixed in the relevant task before documentation updates.

- [ ] **Step 4: Commit test coverage**

```bash
git add tests/unit/core tests/unit/routers
 git commit -m "test(markush): cover review and enumeration contracts"
```

---

## Task 7: Browser acceptance and documentation synchronization

**Files:**
- Modify: `docs/wiki/pipeline.md`
- Modify: `docs/api/README.md` if payload contract changed
- Modify: `TODO/INDEX.md`
- Modify: `CHANGELOG.md` if required by current Unreleased convention
- Create: acceptance record only if repository convention supports it

- [ ] **Step 1: Document state and gates**

Add a concise section to `docs/wiki/pipeline.md` covering:

- candidate role/review states;
- scaffold/site/option/mount/fragment confirmation requirement;
- generated candidates remain pending until human confirmation;
- molecule provenance fields;
- re-import does not revive rejected decisions;
- enumeration rejects unconfirmed identities before creating a run.

Update `docs/api/README.md` only with the stable candidate-detail fields and any changed enumeration request semantics. Keep generated OpenAPI as endpoint source of truth.

- [ ] **Step 2: Start ephemeral backend/frontend servers**

Use project commands on non-default ports:

```bash
uv run uvicorn mbforge.app:app --host 127.0.0.1 --port 28792
npm --prefix frontend run dev -- --port 25173
```

Do not leave either server running after acceptance.

- [ ] **Step 3: Execute browser workflow**

Run the existing browser test harness if present. Otherwise use Playwright against `http://127.0.0.1:25173` and record:

1. open Review Center;
2. select pending candidate;
3. confirm scaffold;
4. create and confirm site;
5. confirm fragment and relationship;
6. verify blocked state before relationship confirmation;
7. verify enumeration becomes enabled after confirmation;
8. preview and run bounded enumeration;
9. inspect generated candidates;
10. confirm one candidate and reject another;
11. verify confirmed candidate in molecule search/detail with provenance;
12. re-import or replay same source and verify rejected data does not revive.

Capture screenshots or trace at steps 6, 7, 9, and 11. Record exact command, result, and any known environment limitation.

- [ ] **Step 4: Update TODO and changelog**

Mark the Markush closure items complete only when backend tests and browser acceptance both pass. Leave a separate note for any missing real-PDF acceptance; do not claim that browser tests replace document-level validation.

- [ ] **Step 5: Stop temporary servers and verify status**

Stop processes started in Step 2, then run:

```bash
git status --short
git diff --check
```

Expected: no generated logs, PDFs, screenshots, model weights, or temporary database files are tracked.

- [ ] **Step 6: Commit documentation and acceptance record**

```bash
git add docs/wiki/pipeline.md docs/api/README.md TODO/INDEX.md CHANGELOG.md tests/eval
git commit -m "docs(markush): record review closure gates"
```

---

## Task 8: Final verification and review checkpoint

**Files:**
- No new source files unless verification exposes a defect.

- [ ] **Step 1: Run complete backend verification**

```bash
uv run pytest tests/ -q
uv run ruff check src tests
uv run ruff format src tests --check
```

Expected: all tests pass; Ruff exits 0.

- [ ] **Step 2: Run complete frontend verification**

```bash
npm --prefix frontend run lint
npm --prefix frontend run build
npm --prefix frontend run test
```

Expected: lint, type-check/build, and all Vitest tests pass. Existing `window.scrollTo` jsdom noise may remain but must not be a test failure.

- [ ] **Step 3: Inspect final diff for scope and security**

```bash
git diff main...HEAD --stat
git diff main...HEAD --check
git status --short
```

Confirm:

- no migration framework was added;
- no client-provided SMILES authorizes enumeration;
- no unconfirmed fragment reaches generated candidates;
- no generated candidate auto-promotes to molecules;
- no secrets, PDFs, model weights, logs, or real library data are included.

- [ ] **Step 4: Request code review before declaring completion**

Use the repository review workflow on the final diff. Resolve correctness findings before completion. Do not claim the task complete until verification output and browser acceptance evidence are recorded.

---

## Plan Self-Review

- **Spec coverage:** State transitions are covered in Tasks 1, 3, and 4; stable API fields in Task 1; server-side enumeration gates in Task 2; generated provenance in Task 3; frontend behavior in Task 5; API/SQLite coverage in Task 6; browser acceptance and living docs in Task 7; final verification in Task 8.
- **No placeholders:** Every task names exact files, tests, commands, expected results, and concrete implementation shapes. No `TBD`, `TODO`, or unspecified “add validation” steps remain.
- **Type consistency:** Python and TypeScript field names match: `scaffold_id`, `fragment_id`, `enumeration_eligible`, `enumeration_block_reasons`; generated response uses `generated_id`, `review_status`, and nullable `mol_id`. Enumeration requests use fragment IDs as identity.
- **Scope check:** Existing tables and router structure remain. No migration machinery, unrelated UI redesign, or new inference algorithm included.
