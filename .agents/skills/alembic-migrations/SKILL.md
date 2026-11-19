---
name: alembic-migrations
description: Alembic revision conventions for this repo — keep generated hex revision IDs, filename stem starts with the revision, capability-named slugs (not roadmap phases). Use when creating, editing, renaming, or reviewing a migration under migrations/.
---

# Alembic migrations — Unhinted

Use Alembic defaults. Do **not** invent sequential IDs (`001_auth`, `002_phase1`).

```
migrations/versions/{rev}_{slug}.py
revision = "{rev}"
```

- `rev` — Alembic-generated hex ID (leave as generated)
- `slug` — short `snake_case` intent from `-m` (domain/capability, not ROADMAP phase)
- Filename stem starts with `revision`; do not rewrite `revision` to match a pretty name

```text
✅ 8791b607d5bc_auth.py       revision = "8791b607d5bc"
✅ 5dae474953cd_signals.py    revision = "5dae474953cd"

❌ 001_auth.py / revision "001_auth"     # hand-rolled sequential ID
❌ 002_phase1_data.py                    # phase name + stem ≠ revision
```

```bash
alembic revision -m "sessions"
# → versions/<hex>_sessions.py with revision = "<hex>"
# keep the generated revision; only edit upgrade/downgrade
```

Name the schema capability (`auth`, `signals`, `sessions`, `campaigns`), not roadmap phases (`phase1`, `phase2`). Do not list every table in the slug; docstring may list tables. Changing `revision` strings requires updating every DB `alembic_version` row (or `alembic stamp`). Prefer not rewriting history once shared.
