# Development Workflow

This is the single workflow reference. Product priorities live in
[`TODO/INDEX.md`](../../TODO/INDEX.md); Issues track collaboration; ADRs record
decisions that affect architecture, persistence, compatibility, or security.

## Work item

Before coding, record the goal, scope, acceptance checks, priority, owner,
dependencies, and risks. Write a plan when work spans more than three modules,
more than three days, a migration, or a public contract.

Use `Backlog → Ready → In Progress → Review → Done`; use `Blocked` only with a
recorded external dependency and review date. One PR should represent one
logical topic and be independently verifiable and reversible.

## Branch and commit

Use short branches named `<type>/<issue-id>-<description>`; omit the issue ID
only for small maintenance. Use Conventional Commits:

```text
<type>(<scope>): <subject>
```

Common types are `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `release`,
and `hotfix`. Do not mix unrelated formatting or dependency changes into a
feature. A commit may touch many files when they form one change.

## Pull request

The PR description records background, scope, verification, risks, migrations,
and rollback. Link the Issue or task-board item. Update user documentation,
API contracts, migration notes, and `CHANGELOG.md` when applicable. Do not
merge known data loss, secret exposure, or startup failures.

## Release

`pyproject.toml` is the package version source. Use SemVer and tags
`vMAJOR.MINOR.PATCH`. Release work updates consumers, `CHANGELOG.md`, and
required migration notes, then runs the full Python and frontend checks. Never
move or reuse a published tag; roll back with `git revert` or a documented
data migration strategy.

## Decision and document maintenance

Create an ADR for module boundaries, storage layout, hard-to-replace
dependencies, compatibility, or security changes. Do not rewrite ADR history;
add a new decision or status note. Keep current behavior in `docs/wiki/` and
API contracts in `docs/api/`. Put dated audits, research, and implementation
plans in `docs/archive/` or leave them clearly marked as drafts.
