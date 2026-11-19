"""Advisory except-handler audit — LLM-judged, never blocks.

Port of cardex's audit-gate (docs/audit-rules.md, ADR 0010 over there):
``except`` candidates in the PR diff are scored against the rules below by
an LLM, and findings post as GitHub check-run annotations. Advisory by
construction — the process exits 0 in every case: missing API key, missing
token, API errors, or findings all conclude ``neutral``/``success``, never
``failure``. The ``audit-exempt`` PR label skips the run (workflow env).

Rules (question text is what the judge receives — update this file and
``docs/audit-rules.md`` together):

    ERR-01  failure → success-shaped result the caller can't tell apart
            (ok: True, fabricated payload, applied status)
    ERR-02  in a guard, the exception path returns a permissive verdict
            (fail-open). catch → deny is compliant — fail-closed is fine.
    ERR-03  the error is fully discarded — no rethrow, no error result, no
            fallback; execution continues as if nothing failed.

Suppression: ``# audit-allow(ERR-NN): reason`` or ``# audit-allow(*): …``
anywhere inside the enclosing function body. A bare marker with no reason
does not suppress.

Usage: python -m scripts.except_audit <base-sha> <head-sha>
Env:   AUDIT_MODEL (litellm model string, default gpt-4.1-mini),
       OPENAI_API_KEY / OPENROUTER_API_KEY / provider key the model needs,
       GITHUB_TOKEN + GITHUB_REPOSITORY for check-run posting,
       AUDIT_EXEMPT, GITHUB_STEP_SUMMARY (optional summary append).
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCOPE = re.compile(r"^(internal|cmd|scripts)/.+\.py$")
SKIP = re.compile(r"^tests/|/test_|__pycache__")

WARN_AT = 0.8
NOTICE_AT = 0.5
MAX_ANNOTATIONS = 50  # check-runs API cap per request
MODEL = os.environ.get("AUDIT_MODEL", "gpt-4.1-mini")

GUARD_NAME = re.compile(r"^(is|has|can|allow|valid|verify|check|auth|require|enforce|guard)_?", re.I)
GUARD_FILE = re.compile(r"auth|guard|valid|oauth|deps", re.I)
ALLOW_RE = re.compile(r"audit-allow\((ERR-\d+|TEST-\d+|\*)\)\s*:\s*\S")

RULES = {
    "ERR-01": (
        "When the operation in the try block fails, does the handler hand the caller a "
        "success-shaped value — ok/success status, a fabricated populated object, an "
        "applied/created status — so the caller cannot tell the operation failed?"
    ),
    "ERR-02": (
        "In a guard that decides whether input is allowed or trusted, does the "
        "exception path return a permissive verdict? A catch returning the denying "
        "verdict (False, None treated as rejection) is compliant fail-closed — "
        "answer false for those."
    ),
    "ERR-03": (
        "Is the caught error discarded entirely — no rethrow, no error result, no "
        "fallback value — so execution continues as though the operation never "
        "failed? A log line alone still counts as discarded unless the failure is "
        "expected (best-effort cleanup, optional sync)."
    ),
}

JUDGE_PROMPT = """\
You audit Python error handlers. For each rule below answer whether it is
VIOLATED, with a confidence 0..1 and a one-line reason.

File: {file}
Enclosing function `{fn_name}`:
```python
{fn_source}
```

Rules:
{rules}

Reply with JSON only: {{"answers": {{"RULE-ID": {{"verdict": true, "confidence": 0.0, "reason": "..."}}}}}}
"""


@dataclass
class Candidate:
    file: str
    line: int
    # Nearest line inside the PR diff — check-run annotations only render
    # inline on diff lines, and the ``except`` line usually isn't one.
    annot_line: int
    fn_name: str
    fn_source: str
    handler_source: str
    rules: list[str] = field(default_factory=list)


class _ExceptFinder(ast.NodeVisitor):
    """Collect ExceptHandler nodes with their enclosing function range."""

    def __init__(self) -> None:
        self.stack: list[ast.AST] = []
        self.found: list[tuple[ast.ExceptHandler, ast.AST | None]] = []

    def visit(self, node: ast.AST) -> None:
        is_fn = isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
        )
        if is_fn:
            self.stack.append(node)
        if isinstance(node, ast.ExceptHandler):
            self.found.append((node, self.stack[-1] if self.stack else None))
        super().visit(node)
        if is_fn:
            self.stack.pop()


def find_candidates(
    source: str, rel: str, hunk_ranges: list[tuple[int, int]] | None
) -> list[Candidate]:
    """Except handlers whose enclosing function overlaps the diff hunks.

    ``hunk_ranges=None`` audits the whole file; an empty list means the diff
    touched the file but added no lines (deletion-only / pure rename) — no
    candidate can overlap, so nothing is audited.
    """
    tree = ast.parse(source, filename=rel)
    finder = _ExceptFinder()
    finder.visit(tree)
    lines = source.splitlines(keepends=True)
    out: list[Candidate] = []
    for handler, fn in finder.found:
        scope_start = getattr(fn, "lineno", 1) if fn else 1
        scope_end = getattr(fn, "end_lineno", len(lines)) if fn else len(lines)
        overlap = None
        if hunk_ranges is not None:
            overlap = [r for r in hunk_ranges if scope_start <= r[1] and scope_end >= r[0]]
            if not overlap:
                continue
        annot = handler.lineno
        if overlap:
            annot = min(
                (max(a, min(b, annot)) for a, b in overlap),
                key=lambda x: abs(x - handler.lineno),
            )
        fn_source = "".join(lines[scope_start - 1 : scope_end])
        cand = Candidate(
            file=rel,
            line=handler.lineno,
            annot_line=annot,
            fn_name=getattr(fn, "name", "<module>") if fn else "<module>",
            fn_source=fn_source,
            handler_source="".join(
                lines[handler.lineno - 1 : getattr(handler, "end_lineno", handler.lineno)]
            ),
        )
        cand.rules = rules_for(cand)
        if cand.rules:
            out.append(cand)
    return out


def rules_for(cand: Candidate) -> list[str]:
    rules = ["ERR-01"]
    if GUARD_NAME.search(cand.fn_name) or GUARD_FILE.search(cand.file):
        rules.append("ERR-02")
    # ERR-03 asks about a discarded error — apply it when the handler body
    # itself neither returns nor raises.
    if not re.search(r"\b(return|raise)\b", cand.handler_source):
        rules.append("ERR-03")
    allowed = set(ALLOW_RE.findall(cand.fn_source))
    if "*" in allowed:
        return []
    return [r for r in rules if r not in allowed]


def _changed_files(base: str, head: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=AMR", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [f for f in out.splitlines() if SCOPE.match(f) and not SKIP.search(f)]


def _hunk_ranges(base: str, head: str, path: str) -> list[tuple[int, int]]:
    diff = subprocess.run(
        ["git", "diff", "--unified=0", f"{base}...{head}", "--", path],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    ranges: list[tuple[int, int]] = []
    for line in diff.splitlines():
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
        if m:
            start = int(m.group(1))
            length = int(m.group(2) or "1")
            if length > 0:
                ranges.append((start, start + length - 1))
    return ranges


async def _judge(cand: Candidate) -> dict[str, dict]:
    """Ask the model to score this candidate against its rules."""
    import litellm

    questions = "\n".join(f"{rid}: {RULES[rid]}" for rid in cand.rules)
    prompt = JUDGE_PROMPT.format(
        file=cand.file, fn_name=cand.fn_name, fn_source=cand.fn_source, rules=questions
    )
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            res = await litellm.acompletion(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                timeout=60,
            )
            data = json.loads(res.choices[0].message.content)
            answers = data.get("answers", {})
            return {
                rid: ans
                for rid, ans in answers.items()
                if isinstance(ans, dict) and rid in cand.rules
            }
        except Exception as exc:  # noqa: BLE001 — advisory: any judge failure → retry/skip
            last_err = exc
            await asyncio.sleep(2**attempt)
    raise RuntimeError(f"judge failed for {cand.file}:{cand.line}: {last_err}")


async def _post_check_run(body: dict) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("no GITHUB_TOKEN/GITHUB_REPOSITORY — check run skipped")
        print(json.dumps(body.get("output", {}), indent=2)[:4000])
        return
    import httpx

    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"https://api.github.com/repos/{repo}/check-runs",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json=body,
        )
        if not res.is_success:
            print(f"check-runs {res.status_code}: {res.text[:500]} — continuing")


async def _finish(head: str, *, conclusion: str, title: str, summary: str, annotations=()) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(f"### {title}\n\n{summary}\n")
    await _post_check_run(
        {
            "name": "except-audit",
            "head_sha": head,
            "status": "completed",
            "conclusion": conclusion,
            "output": {"title": title, "summary": summary, "annotations": list(annotations)[:MAX_ANNOTATIONS]},
        },
    )


async def run(base: str, head: str) -> None:
    if os.environ.get("AUDIT_EXEMPT"):
        await _finish(head, conclusion="success", title="except-audit: exempt",
                      summary="Skipped via the `audit-exempt` label.")
        return
    if not (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("LITELLM_PROXY_API_KEY")
    ):
        await _finish(head, conclusion="neutral", title="except-audit: skipped",
                      summary="No LLM key available (fork PR or missing secret). Nothing was audited.")
        return

    findings = []
    errors = []
    files = _changed_files(base, head)
    candidates = [
        cand
        for f in files
        for cand in find_candidates(
            (ROOT / f).read_text(encoding="utf-8"), f, _hunk_ranges(base, head, f)
        )
    ]
    print(f"{len(candidates)} except candidates in {len(files)} changed files")

    for cand in candidates:
        try:
            answers = await _judge(cand)
        except Exception as exc:  # noqa: BLE001 — report and move on, never block
            errors.append(f"{cand.file}:{cand.line}: {exc}")
            continue
        for rid, ans in answers.items():
            p = float(ans.get("confidence", 0)) if ans.get("verdict") else 0.0
            if p >= NOTICE_AT:
                findings.append({
                    "path": cand.file,
                    "start_line": cand.annot_line,
                    "end_line": cand.annot_line,
                    "annotation_level": "warning" if p >= WARN_AT else "notice",
                    "title": f"except-audit {rid}",
                    "message": f"{rid} (p={p:.2f}): {RULES[rid]}",
                })

    if errors:
        await _finish(head, conclusion="neutral", title="except-audit: unavailable",
                      summary=f"{len(errors)} candidate(s) could not be scored:\n\n"
                              + "\n".join(f"- `{e}`" for e in errors))
        return
    if findings:
        await _finish(head, conclusion="neutral",
                      title=f"except-audit: {len(findings)} finding(s)",
                      summary="Advisory only — review the annotations and either fix, or exempt with "
                              "`# audit-allow(ERR-NN): reason` inside the function.",
                      annotations=findings)
        return
    await _finish(head, conclusion="success", title="except-audit: clean",
                  summary=f"{len(candidates)} except candidate(s) audited, no rule hits.")


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python -m scripts.except_audit <base-sha> <head-sha>", file=sys.stderr)
        return 2
    try:
        asyncio.run(run(sys.argv[1], sys.argv[2]))
    except Exception as exc:  # noqa: BLE001 — advisory: a crashed audit must not block a PR
        # audit-allow(ERR-01): exit 0 is the documented advisory contract, and
        # the crash is surfaced via the neutral check-run below — the caller
        # can tell it apart from a clean run.
        print(f"except-audit crashed: {exc} — exiting 0 anyway")
        # Post the crash as neutral so CI can tell it apart from a clean run;
        # if even that fails there is nothing left to surface it through.
        with contextlib.suppress(Exception):
            asyncio.run(_finish(
                sys.argv[2],
                conclusion="neutral",
                title="except-audit: crashed",
                summary=f"The audit crashed before scoring:\n\n```\n{exc}\n```",
            ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
