"""Documented-command drift check — AGENTS.md commands must exist.

Every command an agent doc tells a reader to run should actually run. Ported
from cardex's prd-rows-gate bonus check ("every `pnpm <name>` in AGENTS.md
must be a real package.json script"), extended for this repo's surfaces:

    1. `python -m scripts.<mod>`      → scripts/<mod>.py exists
    2. `pnpm <script>` / `pnpm run <script>` → script exists in some
       package.json (web/, relay/, scripts/typescript_gen/) unless it is a
       pnpm builtin
    3. `npm <script>` / `npm run <script>`   → same, for npm builtins
    4. `tests/<path>` tokens          → file or directory exists

Scans every AGENTS.md in the tree (root + nested packs) plus project
skills under `.agents/skills/`, so new agent docs are covered
automatically. Run:

    python -m scripts.check_agents_commands
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PNPM_BUILTINS = set(
    ["install", "i", "add", "remove", "rm", "un", "uninstall", "update", "up", "upgrade", "run", "exec", "dlx", "create", "init", "publish", "pack", "patch", "audit", "outdated", "list", "ls", "ll", "la", "why", "info", "view", "rebuild", "rb", "prune", "link", "ln", "unlink", "import", "dedupe", "fetch", "store", "server", "root", "bin", "env", "config", "cache", "doctor", "help", "version", "licenses", "self-update", "deploy", "approve-builds", "ignored-builds", "setup"]
)
NPM_BUILTINS = set(
    ["install", "i", "ci", "add", "remove", "rm", "uninstall", "update", "up", "upgrade", "run", "run-script", "exec", "exec-all", "start", "stop", "restart", "test", "t", "tst", "publish", "pack", "init", "create", "link", "ln", "unlink", "ls", "ll", "la", "outdated", "prune", "rebuild", "rb", "audit", "fund", "doctor", "cache", "config", "env", "explore", "explain", "repo", "version", "view", "why", "ping", "whoami", "owner", "access", "deprecate", "diff", "dist-tag", "docs", "edit", "find-dupes", "help", "hook", "org", "pkg", "profile", "query", "search", "set", "shrinkwrap", "star", "stars", "token", "unpublish", "unstar"]
)

PY_MODULE_RE = re.compile(r"\bpython3?\s+-m\s+scripts\.([a-z_][a-z0-9_]*)")
PNPM_RE = re.compile(r"\bpnpm\s+(?:run\s+)?([a-z][a-z0-9:_-]*)")
NPM_RE = re.compile(r"\bnpm\s+(?:run\s+)?([a-z][a-z0-9:_-]*)")
TEST_PATH_RE = re.compile(r"(?<![\w./-])tests/[\w./_-]+")
# `pnpm --dir web lint` / `pnpm --filter=web lint` / `npm -C web run types`
# — drop the option so the real subcommand token is what gets checked.
PKG_OPTION_RE = re.compile(r"\b(pnpm|npm)\s+(?:--dir|--filter|-C|-w|--workspace|-F)(?:\s+|=)\S+")


def _script_names() -> set[str]:
    names: set[str] = set()
    for pkg in ROOT.rglob("package.json"):
        if "node_modules" in pkg.parts:
            continue
        names.update(json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {}))
    return names


def check_text(text: str, rel: str, scripts: set[str]) -> list[str]:
    text = PKG_OPTION_RE.sub(r"\1", text)
    failures: list[str] = []

    for m in PY_MODULE_RE.finditer(text):
        mod = m.group(1)
        if not (ROOT / "scripts" / f"{mod}.py").is_file():
            failures.append(f"{rel}: documents `python -m scripts.{mod}` but scripts/{mod}.py does not exist")

    for regex, builtins, pm in ((PNPM_RE, PNPM_BUILTINS, "pnpm"), (NPM_RE, NPM_BUILTINS, "npm")):
        for m in regex.finditer(text):
            cmd = m.group(1)
            if cmd not in builtins and cmd not in scripts:
                failures.append(
                    f"{rel}: documents `{pm} {cmd}` but no package.json has a \"{cmd}\" script"
                )

    for m in TEST_PATH_RE.finditer(text):
        tok = m.group(0).rstrip(".")
        if not (ROOT / tok).exists():
            failures.append(f"{rel}: documents `{tok}` but no such test path exists")

    return failures


def check_file(path: Path, scripts: set[str]) -> list[str]:
    rel = path.relative_to(ROOT).as_posix()
    return check_text(path.read_text(encoding="utf-8"), rel, scripts)


def doc_paths() -> list[Path]:
    agents = (
        p
        for p in ROOT.rglob("AGENTS.md")
        if "node_modules" not in p.parts and ".venv" not in p.parts
    )
    skills = ROOT.glob(".agents/skills/*/SKILL.md")
    return sorted([*agents, *skills])


def main() -> int:
    docs = doc_paths()
    scripts = _script_names()
    failures: list[str] = []
    for doc in docs:
        failures.extend(check_file(doc, scripts))

    if failures:
        for f in failures:
            print(f"::error::{f}")
        print(f"\nagents-commands: {len(failures)} drifted command(s) — fix the doc or add the target")
        return 1
    print(f"agents-commands ok — {len(docs)} agent doc(s) checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
