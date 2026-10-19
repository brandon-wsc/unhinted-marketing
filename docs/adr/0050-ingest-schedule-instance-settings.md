# ADR 0050 — Ingest schedule knobs in instance settings

## Status

Accepted

## Context

The signal-ingest schedule is env-only today: `SCHEDULER_HOT_SEARCH_INTERVAL_MINUTES` (60m), `SCHEDULER_QUESTIONS_INTERVAL_HOURS` (12h), `NEWS_PROMOTE_WINDOW_HOURS` (24h) and `NEWS_PROMOTE_TRENDS_RANK_MAX` (10) are read from `internal.config.settings` — the scheduler once at boot, the promoter per run. Tuning any of them means editing `.env` and restarting processes, which the on-prem operator cannot do from the portal.

These knobs are all **instance-scoped**: `hot_search` / `promote_signals` maintain the shared `raw_news_events` pool (region `HK`) with no per-company dimension, and `questions` runs every company on one global tick. Per-company cadence is explicitly out of scope — a future need would key off the company entity, not this row.

## Decision

- New nullable columns on `instance_settings` (singleton, ADR 0026):
  `scheduler_hot_search_interval_minutes`, `scheduler_questions_interval_hours`,
  `news_promote_window_hours`, `news_promote_trends_rank_max`, and the boolean
  `scheduler_hot_search_enabled`.
- `NULL` = unset → the env value is the effective default (env seeds semantics,
  unchanged). `InstanceSnapshot` resolves the fallback; the API response always
  returns the effective value so the portal shows what is actually running.
- `PUT /api/instance/settings` accepts the four fields with bounds
  (interval minutes 5–1440; question/promote hours 1–168; rank 1–50). Portal
  writes win afterwards — same "env seeds, portal wins" rule as Meta creds.
- The scheduler loop re-reads the snapshot each minute tick
  (`load_snapshot` when `cache_is_stale()`), so a portal save takes effect
  within ~1 minute with no restart. `promote_signals` loads the snapshot at
  job start. Intervals remain whole units (minutes / hours), matching env.
- `scheduler_hot_search_enabled = false` gates the periodic hot tick only —
  the scheduler skips enqueuing `hot_search` and `promote_signals` (elapsed
  keeps accruing, so re-enabling fires on the next tick). Manual runs
  (`worker hot-search`, `worker promote`, `--once`) are unaffected.
- `question_cache_ttl_hours` stays env-only, but the question runner clamps
  the effective TTL to `max(env_ttl, questions_interval_hours + 1)` so the
  ADR 0018 invariant (TTL must outlive the tick) survives a longer configured
  interval.

## Consequences

- On-prem operators tune ingest cadence from Platform → Instance without a
  restart or shell access; env-only installs behave exactly as before.
- Widening an interval mid-window changes the dedupe tick bucket, so one
  extra enqueue per cycle kind is possible — harmless; job dedupe is
  best-effort.
- Bounds are enforced by the Pydantic schema, not the DB — the row stays
  simple nullable integers.
