"""Contract drift gate — contract-surface diffs must carry docs.

Port of cardex's contract-gate.mjs: mechanizes AGENTS.md's "update
ADR/STATUS first" rule. A PR that touches the contract surface must also
touch ``docs/adr/`` or ``docs/STATUS.md`` in the same diff; the
``contract-exempt`` PR label skips the whole gate (handled in ci.yml).

CONTRACT_SURFACE is deliberately tight — the files whose edits *are* a
product-contract or behavior-rule change:

    schemas/                    HTTP + Pydantic API shapes (AGENTS.md SSOT)
    migrations/                 DB schema history
    internal/tools/             publish adapters — confirm-side I/O (ADR 0003)
    internal/mcp/tools.py       remote-MCP tool surface (ADR 0051)
    internal/mcp/server.py      remote-MCP endpoint surface
    internal/session/service.py park/resume/confirm/stop behavior — the
                                subjects of ADR 0003/0004/0016/0028/0031/0035/0036

internal/session/nodes.py and graph.py are *not* gated: every session
feature touches them, so requiring docs per edit would train everyone to
reach for the exempt label reflexively.

Cardex's gate has a second direction (new PRD behavior rows must land with
a spec). There is no honest unhinted analog: ADR files are not behavior
tables — process ADRs (e.g. 0059 release branches) legitimately ship
without tests, so that check would false-positive. Skipped deliberately.

Usage: python -m scripts.check_contract_drift <base-sha> <head-sha>
"""

from __future__ import annotations

import re
import subprocess
import sys

CONTRACT_SURFACE = re.compile(
    r"^(?:schemas/|migrations/|internal/tools/|internal/mcp/(?:tools|server)\.py"
    r"|internal/session/service\.py)"
)
CONTRACT_DOCS = re.compile(r"^docs/(?:adr/|STATUS\.md)")


def check_changed(changed: list[str]) -> list[str]:
    surface = sorted(f for f in changed if CONTRACT_SURFACE.match(f))
    if not surface:
        return []
    if any(CONTRACT_DOCS.match(f) for f in changed):
        return []
    return [
        "changed contract surface (" + ", ".join(surface) + ") without docs/adr/ "
        "or docs/STATUS.md — update the contract docs first, or apply the "
        "'contract-exempt' label"
    ]


def _changed_files(base: str, head: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [f for f in out.splitlines() if f]


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python -m scripts.check_contract_drift <base-sha> <head-sha>", file=sys.stderr)
        return 2
    failures = check_changed(_changed_files(sys.argv[1], sys.argv[2]))
    for f in failures:
        print(f"::error::{f}")
    if failures:
        return 1
    print("contract drift gate ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
