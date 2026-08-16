"""Verify checked-in contract mirrors match their Pydantic sources.

Re-exports `docs/contracts/*.schema.json` + `docs/openapi.json` into an isolated
temp dir (via EXPORT_ROOT) and fails when the committed files have drifted
(e.g. a schema changed but `python -m scripts.export_contracts` was not run).

Also performs a lightweight consistency probe on the hand-written frontend
mirror (`web/src/features/session/types.ts`) so preview draft contract keys
stay aligned with the SSE payload. The strictly enforced bridge (CI) is the
generated JSON mirrors; the TS file check is informational until a generator
lands (option 1 plan).

Usage:
    python -m scripts.check_contracts_fresh
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
TYPE_MIRROR = ROOT / "web" / "src" / "features" / "session" / "types.ts"

# Keys that must remain present in the frontend mirror while `preview.updated`
# is the canonical draft event (ADR 0001 / ADR 0008).
REQUIRED_PREVIEW_KEYS = ("copy", "revision", "approval_token", "media", "image_url")


def regen_and_diff() -> list[str]:
    """Re-run export into a temp EXPORT_ROOT and return drifted relative paths."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "EXPORT_ROOT": tmp}
        subprocess.run(
            [sys.executable, "-m", "scripts.export_contracts"],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
        )
        tmp_root = Path(tmp) / "docs"
        drifted: list[str] = []
        for generated in tmp_root.rglob("*"):
            if generated.is_dir():
                continue
            rel = generated.relative_to(tmp_root)
            committed = ROOT / "docs" / rel
            if not committed.exists() or committed.read_bytes() != generated.read_bytes():
                drifted.append(str(rel))
        return drifted


def check_ts_mirror() -> list[str]:
    """Return preview contract keys missing from the hand-written TS mirror."""
    if not TYPE_MIRROR.exists():
        return [f"missing frontend mirror: {TYPE_MIRROR.relative_to(ROOT)}"]
    text = TYPE_MIRROR.read_text()
    return [
        f"types.ts missing key `{key}` (see schemas/contracts.py)"
        for key in REQUIRED_PREVIEW_KEYS
        if key not in text
    ]


def main() -> int:
    problems = regen_and_diff() + check_ts_mirror()
    if problems:
        print("Contract mirrors are stale. Run `python -m scripts.export_contracts` and sync web types:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("Contract mirrors are fresh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
