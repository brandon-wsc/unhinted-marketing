# Web UI — agent notes

If the agent walks `AGENTS.md` from the git root to the current directory, this file applies under `web/` in addition to the repository root [`AGENTS.md`](../AGENTS.md).

Follow the **Web UI system** section in the root file. Do not add a second control stack or a second copy of those rules here.

Session API + SSE shapes are generated (`web/src/features/session/generated/` from `schemas/` via `scripts/typescript_gen`) — edit Pydantic sources, not generated files; re-export + regenerate after backend contract changes (see root `AGENTS.md`).
