"""Verify checked-in contract mirrors match their Pydantic sources.

Re-exports `docs/contracts/*.schema.json` + `docs/openapi.json` into an isolated
temp dir (via EXPORT_ROOT) and fails when the committed files have drifted
(e.g. a schema changed but `python -m scripts.export_contracts` was not run).

The frontend TS mirror (`web/src/features/session/generated/`) is generated
separately by `scripts/typescript_gen` and is checked by CI drift (regenerate +
`git diff`) — see `.github/workflows/ci.yml`.

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


def main() -> int:
    problems = regen_and_diff()
    if problems:
        print(
            "Contract mirrors are stale. Run `python -m scripts.export_contracts` "
            "and re-run `npm run generate` in scripts/typescript_gen:"
        )
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("Contract mirrors are fresh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
