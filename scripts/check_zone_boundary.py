"""LLM-zone commit boundary check — mechanizes the AGENTS.md hard boundaries.

Zone (LangGraph / LLM code): ``internal/session/**`` minus the two HTTP-side
siblings, ``internal/perception/**``, ``internal/llm/**``. Commit paths are
HTTP-only: publishing via ``POST /confirm`` (ADR 0003), org-catalog upserts
via the proposals/approvals routes (ADR 0011), preview persist + confirm in
``internal/session/service.py`` (ADR 0005). Nothing in the zone may reach
them — today this holds by convention and code review; this check is the gate.

Rules (all file-scoped to zone files):

    R1  A zone file may not import a commit-side module (BANNED_MODULES).
    R2  ``from internal.memory.repos import <name>`` with a write-shaped
        <name> must appear in ZONE_WRITE_ALLOW — the allowlist is the triage
        record for "turn-state/ingest write" vs "commit write". The same
        rule applies at call sites that go through a module alias
        (``repos.<write>(...)``).
    R3  Raw ORM writes — ``db.add/delete/merge/execute`` on a db-ish
        receiver — are banned. Reads go through repos, so a raw call is
        either a commit bypass or a new kind of turn-state write to triage.
        ``flush``/``commit`` stay legal (turn-state bookkeeping in
        trace.py, ingest.py, question_graph/runner.py).
    R4  ``schemas.tools`` ``PublishSocialPost*`` symbols are confirm-side —
        banned in zone.

Escape hatch: ``# zone-boundary-allow: <reason>`` on the offending line —
mirrors the ``audit-allow(ERR-NN): reason`` convention; a bare marker with
no reason does not suppress.

Known hole: ORM dirty-tracking (``row.status = "confirmed"; db.flush()``)
bypasses R2/R3 — without type info, ``row.status`` cannot be told apart
from a plain dataclass assignment. The named-heuristic advisory pass is
deferred until a scoped type checker exists. Run:

    python -m scripts.check_zone_boundary
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ZONE_DIRS = ("internal/session", "internal/perception", "internal/llm")
# HTTP-side siblings living inside the zone packages — callers import them,
# they are not graph code and this gate does not constrain them.
ZONE_EXCLUDE = {
    "internal/session/service.py",  # confirm / preview persist / park-resume bridge
    "internal/session/guards.py",  # access guards imported by cmd/ and internal/mcp
}

# Commit-side modules a zone file may never import — matched on the module
# itself or any descendant, and on `from <pkg> import <module>` forms.
BANNED_MODULES = {
    "internal.tools": "publish adapters — publishing is confirm-only (ADR 0003/0022)",
    "internal.session.service": "HTTP-side orchestration — confirm/persist lives here (ADR 0005)",
    "internal.mcp": "remote-agent surface — it calls the zone, never the reverse (ADR 0051)",
    "cmd": "HTTP layer",
}

REPOS = "internal.memory.repos"
SCHEMAS_TOOLS = "schemas.tools"

# First verb of a repos symbol decides write-shape. get_or_create_* is a
# write despite the get_ prefix.
WRITE_VERBS = {
    "add",
    "approve",
    "confirm",
    "create",
    "delete",
    "enqueue",
    "finish",
    "grant",
    "insert",
    "issue",
    "mark",
    "persist",
    "publish",
    "record",
    "remove",
    "revoke",
    "rotate",
    "save",
    "set",
    "store",
    "supersede",
    "update",
    "upsert",
}

# Write-named repos symbols the zone may import — the triage record. Adding
# an entry is the moment to decide "turn-state/ingest write" (fine) vs
# "commit-class" (must stay HTTP-side).
ZONE_WRITE_ALLOW = {
    # Signal + knowledge ingest — the zone's job
    "upsert_signal",
    "create_edge",
    "get_or_create_topic_entity",
    "update_company_profile",
    # Perception question-run bookkeeping — turn-state, not commits
    "create_question_run",
    "finish_question_run",
    "enqueue_job",
    "save_question_node_step",
    "save_recommended_questions",
}

BANNED_SCHEMA_RE = re.compile(r"^PublishSocialPost")

DB_RECEIVERS = {"db", "session", "conn", "tx", "engine"}
# Factory calls whose result is a db session — `get_db().execute(...)` is the
# same bypass as `db.execute(...)`.
DB_FACTORIES = {
    "get_db",
    "get_session",
    "question_db",
    "db_session",
    "session_factory",
    "SessionLocal",
    "async_session",
}
DB_WRITE_METHODS = {"add", "delete", "merge", "execute"}

ALLOW_MARKER = "zone-boundary-allow"


@dataclass
class Finding:
    file: str
    line: int
    rule: str
    message: str


def _is_write_name(name: str) -> bool:
    return name.startswith("get_or_create") or name.split("_", 1)[0] in WRITE_VERBS


def _is_banned_module(module: str) -> str | None:
    """Return the matched banned root, or None."""
    for banned in BANNED_MODULES:
        if module == banned or module.startswith(banned + "."):
            return banned
    return None


def _dotted(node: ast.expr | None) -> str | None:
    """Dotted path of a Name/Attribute chain (``repos`` → 'repos',
    ``internal.memory.repos`` → 'internal.memory.repos')."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _resolve_module(node: ast.ImportFrom, file_pkg: str) -> str:
    """Resolve an ImportFrom's module against the importing file's package,
    handling relative forms (``from .service import x``)."""
    if not node.level:
        return node.module or ""
    parts = file_pkg.split(".")
    base = parts[: len(parts) - node.level + 1]
    if node.module:
        base += node.module.split(".")
    return ".".join(base)


def check_source(source: str, filename: str) -> list[Finding]:
    """Run the boundary rules over one zone file's source."""
    rel = filename
    findings: list[Finding] = []
    lines = source.splitlines()
    tree = ast.parse(source, filename=filename)
    # Package the file lives in — for `a/b/nodes.py` it is `a.b`; for
    # `a/b/__init__.py` it is already `a.b`.
    file_pkg = rel.removesuffix("/__init__.py").removesuffix(".py").replace("/", ".")
    if not rel.endswith("/__init__.py") and "." in file_pkg:
        file_pkg = file_pkg.rsplit(".", 1)[0]

    def _marked(line_no: int) -> bool:
        if not 0 < line_no <= len(lines):
            return False
        text = lines[line_no - 1]
        if ALLOW_MARKER not in text:
            return False
        tail = text.split(ALLOW_MARKER, 1)[1].strip()
        return tail.startswith(":") and bool(tail[1:].strip())

    def allowed(*linenos: int) -> bool:
        # Marker suppresses on the offending line, or in a comment block
        # directly above it (scan up while lines are comments or blank).
        for n in linenos:
            if _marked(n):
                return True
            line_no = n - 1
            while 0 < line_no <= len(lines):
                text = lines[line_no - 1].strip()
                if not text:
                    break
                if _marked(line_no):
                    return True
                if not text.startswith("#"):
                    break
                line_no -= 1
        return False

    # Local names bound to watched modules (``from internal.memory import
    # repos`` → "repos"; ``import internal.memory.repos as r`` → "r"), plus
    # the fully-qualified dotted form for ``import internal.memory.repos``.
    module_bindings: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                banned = _is_banned_module(alias.name)
                if banned and not allowed(node.lineno):
                    findings.append(
                        Finding(rel, node.lineno, "R1", f"import {alias.name} — {BANNED_MODULES[banned]}")
                    )
                if alias.name == REPOS:
                    module_bindings[alias.asname or REPOS] = REPOS
                elif alias.name == SCHEMAS_TOOLS:
                    module_bindings[alias.asname or SCHEMAS_TOOLS] = SCHEMAS_TOOLS

        elif isinstance(node, ast.ImportFrom):
            module = _resolve_module(node, file_pkg)
            for alias in node.names:
                if alias.name == "*":
                    if module in (REPOS, SCHEMAS_TOOLS) and not allowed(node.lineno):
                        findings.append(
                            Finding(
                                rel,
                                node.lineno,
                                "R2",
                                f"star import from {module} hides symbol names — name the imports",
                            )
                        )
                    continue
                full = f"{module}.{alias.name}" if module else alias.name
                banned = _is_banned_module(module) or _is_banned_module(full)
                if banned and not allowed(node.lineno, alias.lineno):
                    findings.append(
                        Finding(
                            rel,
                            alias.lineno,
                            "R1",
                            f"from {module or '<pkg>'} import {alias.name} — {BANNED_MODULES[banned]}",
                        )
                    )
                    continue
                if module == REPOS and _is_write_name(alias.name) and alias.name not in ZONE_WRITE_ALLOW:
                    if not allowed(node.lineno, alias.lineno):
                        findings.append(
                            Finding(
                                rel,
                                alias.lineno,
                                "R2",
                                f"repos.{alias.name} is write-shaped but not in ZONE_WRITE_ALLOW — "
                                "triage: turn-state/ingest write (allowlist it) or commit-class (keep it HTTP-side)",
                            )
                        )
                elif (
                    module == SCHEMAS_TOOLS
                    and BANNED_SCHEMA_RE.match(alias.name)
                    and not allowed(node.lineno, alias.lineno)
                ):
                    findings.append(
                        Finding(
                            rel,
                            alias.lineno,
                            "R4",
                            f"schemas.tools.{alias.name} is confirm-side — zone emits previews/drafts only (ADR 0003)",
                        )
                    )
            # Module-alias binding — `from internal.memory import repos`
            # and `from schemas import tools` bind the module under a local
            # name; call sites are checked below (R2/R4 on `repos.<name>(…)`).
            for alias in node.names:
                if module == "internal.memory" and alias.name == "repos":
                    module_bindings[alias.asname or "repos"] = REPOS
                elif module == "schemas" and alias.name == "tools":
                    module_bindings[alias.asname or "tools"] = SCHEMAS_TOOLS

        elif isinstance(node, ast.Call):
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            receiver = _dotted(func.value)
            # Module-alias call: repos.<write>(...) / tools.PublishSocialPost*(...)
            if receiver and receiver in module_bindings:
                bound = module_bindings[receiver]
                if bound == REPOS and _is_write_name(func.attr) and func.attr not in ZONE_WRITE_ALLOW:
                    if not allowed(node.lineno):
                        findings.append(
                            Finding(
                                rel,
                                node.lineno,
                                "R2",
                                f"{receiver}.{func.attr}(...) is write-shaped but not in ZONE_WRITE_ALLOW — "
                                "triage: turn-state/ingest write (allowlist it) or commit-class (keep it HTTP-side)",
                            )
                        )
                elif (
                    bound == SCHEMAS_TOOLS
                    and BANNED_SCHEMA_RE.match(func.attr)
                    and not allowed(node.lineno)
                ):
                    findings.append(
                        Finding(
                            rel,
                            node.lineno,
                            "R4",
                            f"{receiver}.{func.attr}(...) is confirm-side — zone emits previews/drafts only (ADR 0003)",
                        )
                    )
                continue
            # Raw ORM writes on a db-ish receiver — direct, attribute-tailed
            # (self.db.execute), or via a factory call (get_db().execute(...)).
            recv_name = receiver.rsplit(".", 1)[-1] if receiver else None
            if recv_name is None and isinstance(func.value, ast.Call) and isinstance(
                func.value.func, ast.Name
            ):
                recv_name = func.value.func.id
            if (
                recv_name in DB_RECEIVERS | DB_FACTORIES
                and func.attr in DB_WRITE_METHODS
                and not allowed(node.lineno)
            ):
                findings.append(
                    Finding(
                        rel,
                        node.lineno,
                        "R3",
                        f"{recv_name}.{func.attr}(...) is a raw ORM write — reads/writes go through "
                        "internal.memory.repos so commit-class names stay visible to the gate",
                    )
                )

    return findings


def zone_files() -> list[Path]:
    files: list[Path] = []
    for zone_dir in ZONE_DIRS:
        for path in sorted((ROOT / zone_dir).rglob("*.py")):
            if path.relative_to(ROOT).as_posix() not in ZONE_EXCLUDE:
                files.append(path)
    return files


def main() -> int:
    findings: list[Finding] = []
    files = zone_files()
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        findings.extend(check_source(path.read_text(encoding="utf-8"), rel))

    if findings:
        for f in sorted(findings, key=lambda x: (x.file, x.line)):
            print(f"{f.file}:{f.line}: {f.rule}: {f.message}")
        print(
            f"\nzone boundary: {len(findings)} finding(s) — commit paths are HTTP-only "
            "(AGENTS.md hard boundaries; ADR 0003/0005/0011/0051). "
            "Suppress with '# zone-boundary-allow: <reason>' if justified."
        )
        return 1
    print(f"zone boundary ok — {len(files)} zone file(s) checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
