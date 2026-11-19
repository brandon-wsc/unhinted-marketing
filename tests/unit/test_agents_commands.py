"""Documented-command drift check (scripts/check_agents_commands.py)."""

from __future__ import annotations

from scripts.check_agents_commands import check_file, check_text, doc_paths
from scripts.check_zone_boundary import ROOT

SCRIPTS = {"lint", "test", "build", "generate", "types"}


def test_python_module_must_exist():
    bad = check_text("run `python -m scripts.no_such_module`", "AGENTS.md", SCRIPTS)
    assert len(bad) == 1 and "scripts.no_such_module" in bad[0]
    assert check_text("run `python -m scripts.check_zone_boundary`", "AGENTS.md", SCRIPTS) == []


def test_pnpm_script_names():
    assert check_text("`pnpm run lint`", "AGENTS.md", SCRIPTS) == []
    bad = check_text("`pnpm run typecheck`", "AGENTS.md", SCRIPTS)
    assert len(bad) == 1 and "typecheck" in bad[0]
    # Builtins are never treated as scripts.
    assert check_text("`pnpm install` and `pnpm dlx shadcn`", "AGENTS.md", SCRIPTS) == []


def test_npm_script_names():
    assert check_text("`npm run types` then `npm test`", "AGENTS.md", SCRIPTS) == []
    assert check_text("`npm ci` and `npm install`", "AGENTS.md", SCRIPTS) == []
    assert len(check_text("`npm run shipit`", "AGENTS.md", SCRIPTS)) == 1


def test_pkg_dir_option_is_stripped():
    assert check_text("`pnpm --dir web run lint`", "AGENTS.md", SCRIPTS) == []
    assert check_text("`npm -C relay run types`", "AGENTS.md", SCRIPTS) == []


def test_test_paths_must_exist():
    assert check_text("`pytest tests/unit`", "AGENTS.md", SCRIPTS) == []
    assert check_text("`pytest tests/unit/test_zone_boundary.py`", "AGENTS.md", SCRIPTS) == []
    bad = check_text("`pytest tests/unit/test_deleted.py`", "AGENTS.md", SCRIPTS)
    assert len(bad) == 1 and "test_deleted.py" in bad[0]


def test_real_agents_files_have_no_drift():
    failures = []
    for doc in doc_paths():
        failures.extend(check_file(doc, _scripts()))
    assert failures == []


def _scripts() -> set[str]:
    import json

    names = set()
    for pkg in ROOT.rglob("package.json"):
        if "node_modules" in pkg.parts:
            continue
        names.update(json.loads(pkg.read_text()).get("scripts", {}))
    return names
