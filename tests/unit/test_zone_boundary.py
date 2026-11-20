"""Zone boundary check (scripts/check_zone_boundary.py) — no Postgres.

Synthetic snippets exercise the rules; the last test runs the real zone
tree, so `pytest tests/unit` fails the same way the CI step does.
"""

from __future__ import annotations

import pytest

from scripts.check_zone_boundary import (
    ALLOW_MARKER,
    ROOT,
    check_source,
    zone_files,
)

F = "internal/session/nodes.py"  # zone filename — resolves relative imports


def findings(src: str, filename: str = F):
    return check_source(src, filename)


def rules(src: str, filename: str = F) -> list[str]:
    return [f.rule for f in check_source(src, filename)]


# --- R1: commit-side module imports -------------------------------------


@pytest.mark.parametrize(
    "src",
    [
        "import internal.tools.publish",
        "import internal.tools.publish as pub",
        "from internal.tools import publish",
        "from internal import tools",
        "from internal.session import service",
        "from internal.session.service import normalize_draft_copy",
        "from internal.session import previews",
        "from internal.session.previews import normalize_draft_copy",
        "from internal.session import image_plan",
        "from internal.session import graph_state",
        "import internal.mcp.tools",
        "from cmd.api.routes import sessions",
        "import cmd",
    ],
)
def test_r1_banned_module_forms(src):
    assert rules(src) == ["R1"]


def test_r1_relative_import_resolves_to_banned():
    assert rules("from .service import normalize_draft_copy") == ["R1"]
    assert rules("from . import service") == ["R1"]
    assert rules("from ..tools import publish") == ["R1"]


@pytest.mark.parametrize(
    "src",
    [
        "import internal.session.state",
        "from internal.memory import repos",
        "from internal.session import events, io",
        "import schemas.tools",
        "from schemas.contracts import DraftCopy",
    ],
)
def test_r1_legit_imports_pass(src):
    assert findings(src) == []


# --- R2: repos write-shaped names ----------------------------------------


def test_r2_write_named_import_flagged():
    assert rules("from internal.memory.repos import upsert_product_row") == ["R2"]
    assert rules("from internal.memory.repos import create_tool_receipt") == ["R2"]
    assert rules("from internal.memory.repos import mark_proposal_reviewed") == ["R2"]


def test_r2_get_or_create_is_a_write():
    # get_ prefix must not launder a write verb.
    assert rules("from internal.memory.repos import get_or_create_other_thing") == ["R2"]
    # …but the allowlisted ingest write stays legal.
    assert findings("from internal.memory.repos import get_or_create_topic_entity") == []


def test_r2_multi_name_import_flags_only_writes():
    found = findings(
        "from internal.memory.repos import (\n"
        "    get_company,\n"
        "    upsert_social_account,\n"
        "    list_personas,\n"
        ")"
    )
    assert [f.rule for f in found] == ["R2"]
    assert found[0].line == 3  # the alias line, not the `from` line


@pytest.mark.parametrize(
    "name",
    [
        "upsert_signal",
        "create_edge",
        "update_company_profile",
        "save_recommended_questions",
        "get_company",
        "list_top_signals",
        "sum_member_tokens_by_source",
    ],
)
def test_r2_allowed_names_pass(name):
    assert findings(f"from internal.memory.repos import {name}") == []


def test_r2_module_alias_call_sites():
    src = (
        "from internal.memory import repos\n"
        "async def f(db):\n"
        "    await repos.create_tool_receipt(db)\n"
    )
    assert rules(src) == ["R2"]
    ok = src.replace("create_tool_receipt", "upsert_signal")
    assert findings(ok) == []


def test_r2_import_alias_forms():
    assert rules(
        "import internal.memory.repos as r\nasync def f(db):\n    await r.delete_company(db, c)"
    ) == ["R2"]
    assert rules(
        "import internal.memory.repos\nasync def f(db):\n    await internal.memory.repos.upsert_product_row(db)"
    ) == ["R2"]


def test_r2_star_import_flagged():
    assert rules("from internal.memory.repos import *") == ["R2"]


# --- R3: raw ORM writes ---------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        "db.add(row)",
        "db.add_all(rows)",
        "db.delete(row)",
        "db.merge(row)",
        "db.execute(stmt)",
        "session.execute(stmt)",
        "conn.execute(stmt)",
        "tx.add(row)",
    ],
)
def test_r3_raw_writes_flagged(call):
    assert rules(f"async def f(db):\n    await {call}") == ["R3"]


def test_r3_factory_call_flagged():
    assert rules("async def f():\n    await get_db().execute(stmt)") == ["R3"]
    assert rules("async def f():\n    await SessionLocal().add(row)") == ["R3"]


def test_r3_attribute_tailed_receiver_flagged():
    assert rules("class C:\n    async def f(self):\n        await self.db.execute(stmt)") == ["R3"]


@pytest.mark.parametrize(
    "call",
    [
        "db.flush()",
        "db.commit()",
        "db.rollback()",
        "session_event_bus.publish(evt)",
        "seen.add(x)",
        "queue.add(x)",
        "repos.get_session(db, sid)",
    ],
)
def test_r3_legit_calls_pass(call):
    src = f"from internal.memory import repos\nasync def f(db):\n    await {call}\n" if "repos" in call else f"async def f(db):\n    await {call}\n"
    assert findings(src) == []


# --- R4: schemas.tools confirm-side symbols -------------------------------


def test_r4_publish_schema_names_flagged():
    assert rules("from schemas.tools import PublishSocialPostRequest") == ["R4"]
    assert rules("from schemas.tools import PublishSocialPostResponse") == ["R4"]
    src = "from schemas import tools\nreq = tools.PublishSocialPostRequest()"
    assert rules(src) == ["R4"]


def test_r4_legit_schema_names_pass():
    assert findings("from schemas.tools import QueryMarketTrendsResponse") == []
    src = "from schemas import tools\nx = tools.QueryMarketTrendsResponse"
    assert findings(src) == []


# --- escape hatch ----------------------------------------------------------


def test_marker_same_line_suppresses():
    src = f"from internal.tools import publish  # {ALLOW_MARKER}: testing only"
    assert findings(src) == []
    src = f"db.add(row)  # {ALLOW_MARKER}: telemetry write"
    assert findings(f"async def f(db):\n    {src}") == []


def test_marker_comment_block_above_suppresses():
    src = (
        f"# {ALLOW_MARKER}: llm telemetry write —\n"
        "# not a commit artifact\n"
        "db.add(rec)"
    )
    assert findings(src) == []


def test_marker_without_reason_does_not_suppress():
    assert rules(f"from internal.tools import publish  # {ALLOW_MARKER}") == ["R1"]
    assert rules(f"from internal.tools import publish  # {ALLOW_MARKER}:") == ["R1"]


def test_marker_on_unrelated_line_does_not_suppress():
    src = (
        "x = 1\n"
        f"# {ALLOW_MARKER}: for the next thing\n"
        "y = 2\n"
        "db.add(row)\n"
    )
    assert rules(src) == ["R3"]


# --- the real tree ---------------------------------------------------------


def test_zone_tree_stays_clean():
    found = []
    for path in zone_files():
        rel = path.relative_to(ROOT).as_posix()
        found.extend(check_source(path.read_text(encoding="utf-8"), rel))
    assert found == []
