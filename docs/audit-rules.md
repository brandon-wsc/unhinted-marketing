# Audit rules — error handling

Working rules for the advisory except-handler audit (`scripts/except_audit.py`,
workflow `.github/workflows/audit-gate.yml`). The gate is **warning-only —
never a merge blocker**: findings post as check-run annotations and the run
always concludes `success` or `neutral`. Missing API keys, API errors, and
crashes degrade to `neutral`, not `failure`.

The question text under each rule below is what the judge receives verbatim —
update `scripts/except_audit.py` and this file together.

## Gate flow

1. `git diff` → files under `internal/`, `cmd/`, `scripts/` (tests excluded).
2. AST walk → every `except` handler + its enclosing function, filtered to
   functions whose line range overlaps the diff hunks.
3. Per candidate, the applicable rules fire (see table) and are judged by an
   LLM (`AUDIT_MODEL`, default `gpt-4.1-mini`, via litellm).
4. Confidence ≥ 0.8 → `warning` annotation; 0.5–0.8 → `notice`.

## Rules

| Rule | Applies when | The question (verbatim) |
|------|--------------|-------------------------|
| ERR-01 | every `except` | When the operation in the try block fails, does the handler hand the caller a success-shaped value — ok/success status, a fabricated populated object, an applied/created status — so the caller cannot tell the operation failed? |
| ERR-02 | guard-like file/function (`auth`, `guard`, `valid`, `oauth`, `deps` in path; `is_`/`has_`/`can_`/`verify`/`check`/`require`/`enforce`/`guard` names) | In a guard that decides whether input is allowed or trusted, does the exception path return a permissive verdict? A catch returning the denying verdict (False, None treated as rejection) is compliant fail-closed — answer false for those. |
| ERR-03 | handler body has no `return`/`raise` | Is the caught error discarded entirely — no rethrow, no error result, no fallback value — so execution continues as though the operation never failed? A log line alone still counts as discarded unless the failure is expected (best-effort cleanup, optional sync). |

## Suppression

`# audit-allow(ERR-NN): reason` or `# audit-allow(*): reason` inside the
enclosing function suppresses the named rules for that candidate. The
`audit-exempt` PR label skips the run. A bare marker without a reason is not
a suppression — leave the why.

## Known context

`BLE001` per-file-ignores in `pyproject.toml` are the repo's existing map of
deliberate broad catches (`internal/llm/**`, `internal/perception/**`,
`internal/memory/database.py`, …). The audit does not read them — a judged
finding on an exempted file is still worth a look, because BLE001 only says
"broad catch intended", not "the handler semantics are right".
