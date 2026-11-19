"""Except-handler audit (scripts/except_audit.py) — extraction + rule mapping.

The LLM judge is never called here; these tests cover the deterministic
half: candidate extraction, hunk filtering, rule selection, suppression.
"""

from __future__ import annotations

from scripts.except_audit import find_candidates

SRC = '''
async def check_token(db, tok):
    try:
        return await verify(db, tok)
    except Exception:
        logger.warning("verify failed")
        return None


async def save_stuff(db, row):
    try:
        await db.add(row)
    except Exception:
        logger.exception("add failed")
        return {"ok": True}


def no_except():
    return 42
'''


def test_extracts_enclosing_function():
    cands = find_candidates(SRC, "internal/x.py", [])
    assert len(cands) == 2
    assert cands[0].fn_name == "check_token"
    assert cands[1].fn_name == "save_stuff"
    assert "return await verify" in cands[0].fn_source


def test_hunk_ranges_filter():
    # Hunk touching only lines 12-18 → only save_stuff's handler qualifies.
    cands = find_candidates(SRC, "internal/x.py", [(12, 18)])
    assert [c.fn_name for c in cands] == ["save_stuff"]
    # Hunk outside both functions → nothing.
    assert find_candidates(SRC, "internal/x.py", [(40, 50)]) == []


def test_guard_name_gets_err02():
    cands = find_candidates(SRC, "internal/x.py", [])
    check = next(c for c in cands if c.fn_name == "check_token")
    assert "ERR-02" in check.rules


def test_guard_file_gets_err02():
    cands = find_candidates(SRC, "internal/auth/deps.py", [])
    assert all("ERR-02" in c.rules for c in cands)


def test_err03_only_when_no_exit():
    cands = find_candidates(SRC, "internal/x.py", [])
    # Both handlers return → ERR-03 off.
    assert all("ERR-03" not in c.rules for c in cands)


def test_err03_on_blackhole():
    src = """
def f():
    try:
        work()
    except Exception:
        pass
"""
    cands = find_candidates(src, "internal/x.py", [])
    assert cands[0].rules == ["ERR-01", "ERR-03"]


def test_audit_allow_suppression():
    src = """
def f():
    try:
        work()
    except Exception:
        # audit-allow(ERR-01): intentionally returns the optimistic shape
        return {"ok": True}
"""
    cands = find_candidates(src, "internal/x.py", [])
    assert cands == []  # ERR-01 suppressed; no ERR-03 (returns)


def test_audit_allow_star_suppresses_all():
    src = """
def f():
    # audit-allow(*): legacy shim
    try:
        work()
    except Exception:
        pass
"""
    assert find_candidates(src, "internal/x.py", []) == []


def test_module_level_except():
    src = """
try:
    import optional_thing
except ImportError:
    optional_thing = None
"""
    cands = find_candidates(src, "internal/x.py", [])
    assert cands and cands[0].fn_name == "<module>"
