"""Contract drift gate (scripts/check_contract_drift.py) — pure file-list checks."""

from __future__ import annotations

import pytest

from scripts.check_contract_drift import check_changed


@pytest.mark.parametrize(
    "surface",
    [
        "schemas/contracts.py",
        "schemas/tools.py",
        "schemas/session.py",
        "migrations/versions/abc123_sessions.py",
        "internal/tools/publish.py",
        "internal/mcp/tools.py",
        "internal/mcp/server.py",
        "internal/session/service.py",
    ],
)
def test_surface_files_require_docs(surface):
    assert check_changed([surface]) != []
    assert check_changed([surface, "docs/adr/0060-new-thing.md"]) == []
    assert check_changed([surface, "docs/STATUS.md"]) == []


@pytest.mark.parametrize(
    "non_surface",
    [
        "internal/session/nodes.py",
        "internal/session/graph.py",
        "internal/mcp/auth.py",
        "internal/memory/repos.py",
        "cmd/api/routes/sessions.py",
        "web/src/features/session/api.ts",
        "docs/PRD.md",
        "docs/ROADMAP.md",
        "README.md",
        "AGENTS.md",
    ],
)
def test_non_surface_files_pass(non_surface):
    assert check_changed([non_surface]) == []


def test_docs_subdirs_count():
    assert check_changed(["schemas/contracts.py", "docs/adr/README.md"]) == []


def test_other_docs_do_not_satisfy():
    failures = check_changed(["schemas/tools.py", "docs/TESTING.md"])
    assert failures != []
