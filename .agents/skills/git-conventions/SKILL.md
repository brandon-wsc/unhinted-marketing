---
name: git-conventions
description: Unhinted git rules — Conventional Commits subjects, Conventional Branch prefixes, PR title/body/merge method, release + hotfix branching, one branch per change, and repo-specific review flags. Use before creating a branch, writing a commit, opening or reviewing a PR, or cutting a release/hotfix.
---

# Git conventions — Unhinted

## Feature work

- **New feature / fix → fresh branch off latest `main`.** Never commit on `main`; never reuse a merged or unrelated branch — one branch + PR per change. (Exception: a fix for a shipped `vX.Y.*` line branches off that `release/vX.Y` branch and PRs into it — ADR 0059.)

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
type(scope): summary

optional body explaining why
```

- `type` — required; see table below
- `scope` — required; short area (`auth`, `signals`, `web`, `db`, `docs`, `ci`, …)
- `summary` — imperative, lowercase after the colon, ≤72 chars total subject line, no trailing period
- `body` — optional; explain **why**, not a file list. Use bullets for multi-part milestones

```text
✅ feat(signals): bootstrap Phase 1 autopilot for HK signal ingestion
✅ refactor(db): replace hand-rolled Alembic IDs with standard hex revisions
✅ chore(web): upgrade TypeScript 7 and document pgvector setup

❌ Bootstrap Phase 1 autopilot backend…     # missing type(scope)
❌ feat: add stuff                          # missing scope; vague summary
❌ feat(signals): Added signal ingestion.   # past tense + trailing period
```

| Type | When |
|------|------|
| `feat` | New user-facing capability or API |
| `fix` | Bug fix |
| `refactor` | Behavior-preserving code change |
| `docs` | Docs / roadmap / status only |
| `chore` | Tooling, deps, ignore files, misc |
| `test` | Tests only |
| `ci` | CI/CD config |
| `perf` | Performance improvement |

Prefer domain names over roadmap phases for `scope`: `auth`, `signals`, `sessions`, `web`, `db`, `llm`, `workers`, `docs`, `repo`. Prefer why over what. Keep Phase 0/1-style milestone bullets when the commit spans many areas. Never put secrets or env values in messages. Keep the **subject line ASCII-only** — CJK/emoji in subjects has broken tooling before; put Chinese detail in the body if needed.

## Branch names

Follow the [Conventional Branch](https://conventionalbranch.org/) purpose prefixes: `feat/…` (or `feature/…`), `fix/…` (or `bugfix/…`), `hotfix/…`, `release/…` (dots OK for versions, e.g. `release/v1.2.0`), `chore/…`. Slug is lowercase, hyphen-separated — e.g. `fix/executor-post-voice`. There is no `ci/`, `docs/`, `test/`, `refactor/`, or `perf/` branch — branch type is work intent, not commit type: CI-config, docs, refactor, and test-only work all branch under `chore/…` (their commits still use the commit-type table above). CI rejects PRs whose head branch does not match.

**Long-lived branches** (`docs/adr/0059-release-branches-demo-track-split.md`): `main` is the only standing integration branch — no `develop`. `release/vX.Y` is cut from `main` on demand only (release hardening, or patching a shipped `vX.Y.*` line). Patch flow: `hotfix/<slug>` off the release branch → PR into `release/vX.Y` → tag `vX.Y.Z` from it → merge or cherry-pick the fix back to `main`. Every `v*` tag also auto-deploys the hosted demo (`release.yml` `demo` job → ACA).

## Pull requests

- **Title** — same format as commit subjects (`type(scope): summary`, ≤72 chars, ASCII-only); use the dominant change's type/scope. CI's `conventions` job rejects non-conforming titles. Release notes (`generate_release_notes`) read PR titles, so keep them accurate.
- **Body** — follow `.github/pull_request_template.md`: `## Summary` (what + why), `#### Test plan`, plus the `ADR:` / `Breaking:` lines.
- **Merge method** — merge commit only (squash/rebase disabled): commit subjects land on `main` individually; the PR title does not.

## When reviewing changes

- Flag chat/LLM paths that publish, confirm, or upsert org catalog products; those are HTTP-only (ADR 0003, ADR 0011). `python -m scripts.check_zone_boundary` gates the import-level version of this; `# zone-boundary-allow: <reason>` is the suppression convention.
- Flag blocking sync calls (CPU-bound work like ONNX embeds, sync I/O) inside `async def` routes/deps — wrap with `asyncio.to_thread` / `run_in_threadpool`.
- Flag a second knowledge store or a second streaming-markdown stack.
- Flag hand-rolled Alembic revision IDs and parallel `Button`/`Input`/`Dialog` outside `web/src/components/ui`.
- Leave formatting and lint to CI.
