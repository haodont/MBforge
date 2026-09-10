# Markush Review Closure Design

## Goal

Complete the Markush review workflow from candidate review through confirmed scaffold/fragment relationships, bounded enumeration, generated-candidate review, and final molecule provenance.

The primary safety invariant is: **unconfirmed Markush data must never become an enumerable or concrete molecule record**.

## Scope

In scope:

- Markush review candidate state transitions and optimistic concurrency.
- Stable API response fields for scaffold/fragment identity and enumeration eligibility.
- Enumeration authorization based on server-side database state.
- Generated-candidate review, promotion, rejection, and provenance.
- SQLite integration tests and HTTP contract tests.
- Frontend Markush review/enumeration component tests and required type updates.
- Browser acceptance checklist for the complete workflow.
- Living documentation updates.

Out of scope:

- New Markush inference algorithms.
- Rewriting RDKit substitution logic except where required to enforce eligibility.
- Multi-user permissions or collaboration.
- Database migration machinery.
- Visual redesign unrelated to workflow state.

## Existing Model

The current canonical schema already contains:

- `markush_review_candidates`
- `markush_scaffolds`
- `markush_fragments`
- `markush_decisions`
- `markush_sites`
- `markush_options`
- `markush_mounts`
- `markush_generation_runs`
- `markush_generated_candidates`

The implementation will extend the current development schema directly. No historical migration path or compatibility layer will be added.

## State Contract

Candidate review state:

- `pending`
- `confirmed`
- `rejected`

Candidate role:

- `complete`
- `scaffold`
- `fragment`
- `review_required`

Site and option state:

- `pending`
- `confirmed`
- `rejected`

Mount state:

- `suggested`
- `confirmed`
- `rejected`

Generated candidate state:

- `pending`
- `confirmed`
- `rejected`

Rules:

1. `confirm_complete` is the only review transition that writes to the concrete `molecules` table.
2. `confirm_scaffold` writes only to `markush_scaffolds` and returns a stable `scaffold_id`.
3. `confirm_fragment` writes only to `markush_fragments` and does not attach the fragment to any scaffold.
4. A fragment without a confirmed scaffold relationship is not enumerable.
5. `rejected` candidate decisions must not be revived by re-import.
6. `reopen` returns a review candidate to `pending`; it does not restore enumeration eligibility or relation status.
7. A generated candidate may be confirmed or rejected only while `pending`.
8. Generated candidates enter `molecules` only after explicit confirmation.
9. Every promotion or rejection writes an audit decision with the actual previous and new state.
10. All multi-row promotion operations are transactionally atomic.

## API Contract

`MarkushCandidateDetail` will expose stable fields for the review UI:

- `scaffold_id: string | null`
- `fragment_id: string | null`
- `enumeration_eligible: bool`
- `enumeration_block_reasons: list[str]`

The backend computes these fields from canonical rows and decisions. `properties.scaffold_id` may remain as a temporary read fallback, but it is no longer the primary contract.

Enumeration requests continue to identify a scaffold and site selections, but the service validates every identifier against the database. Client-provided fragment SMILES are not trusted as authorization or identity. The service resolves canonical fragment data from confirmed database rows.

Enumeration validation requires:

- scaffold exists and is `confirmed`;
- every site belongs to that scaffold and is `confirmed`;
- every selected fragment exists and is `confirmed`;
- every selected fragment is linked through a confirmed option or mount;
- selection identifiers match server-side records;
- invalid selections produce structured validation errors without creating a generation run.

## Provenance

A confirmed generated candidate writes provenance into `molecules.properties`, including:

- `generated_id`
- `run_id`
- `scaffold_id`
- `combination_key`
- assignment details

The generated row remains the source of review history. Rejected generated candidates never enter molecule search.

## Data Flow

```text
review candidate
  ├─ confirm complete → molecules
  ├─ confirm scaffold → markush_scaffolds → sites/options/mounts
  └─ confirm fragment → markush_fragments
                                      ↓
                         confirmed relation validation
                                      ↓
                               enumeration run
                                      ↓
                         generated candidate: pending
                           ├─ confirm → molecules + provenance
                           └─ reject  → audit only
```

## Testing Strategy

Backend integration tests using fresh temporary SQLite databases:

- state transitions and stale-version conflicts;
- scaffold and fragment identity returned after confirmation;
- no concrete molecule write for scaffold/fragment;
- reject/reopen/re-import behavior;
- multiple scaffolds, sites, and same-label R-groups;
- enumeration eligibility and server-side identity validation;
- invalid selection creates no run or candidates;
- generated candidate one-time decisions;
- provenance on promotion;
- transaction rollback on promotion failure.

HTTP contract tests:

- candidate detail fields;
- structured transition and enumeration errors;
- generated decision responses;
- response status and payload shape.

Frontend tests:

- `MarkushReviewPanel` states and actions;
- stable scaffold/fragment fields;
- enumeration disabled/enabled reasons;
- generated-candidate review actions;
- API failure and stale response behavior.

Browser acceptance:

```text
review queue
→ candidate detail
→ confirm scaffold
→ create/confirm site
→ confirm fragment/link
→ enumeration preview
→ enumeration run
→ generated candidate review
→ confirm one candidate
→ molecule search/detail
→ verify provenance and evidence
```

Acceptance evidence must include the test result and screenshots or equivalent browser trace. The workflow must demonstrate that an unconfirmed fragment cannot be enumerated and that a rejected candidate does not reappear as a confirmed molecule after re-import.

## Documentation

After implementation:

- update `docs/wiki/pipeline.md` with Markush state and enumeration gates;
- update `docs/api/README.md` only for contract/grouping changes;
- update `TODO/INDEX.md` to record closure evidence and remaining browser-only gaps;
- update `CHANGELOG.md` if the user-visible review behavior changes.

## Completion Criteria

The task is complete only when:

- the backend no longer relies on client input or an unstructured property for enumeration authorization;
- stable identity and eligibility fields are returned to the frontend;
- unconfirmed relationships cannot generate candidates;
- generated candidates require explicit review before molecule promotion;
- rejected states do not silently revive;
- audit and provenance are preserved;
- backend and frontend focused tests pass;
- browser acceptance completes the end-to-end workflow;
- living documentation matches the implementation.
