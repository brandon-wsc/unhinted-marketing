# ADR 0039 — Postgres-backed job queue; `worker` becomes a long-running service

- **Status:** Accepted
- **Date:** 2026-10-04
- **Supersedes:** —
- **Related:** [ADR 0018](./0018-recommended-questions-worker-graph.md) (question run contract), [ADR 0027](./0027-docker-deploy-packages.md) (compose packages)

## Context

`cmd/scheduler` used to run the periodic pipelines itself inside an
`asyncio.sleep(60)` loop (hot search ingest → RSS ingest → promote, then
question generation per company), and `cmd/worker` was only an operator CLI
invoked inside the api container. There was no queue: the recommended-questions
fill on a GET miss ran the LangGraph in the API process as an
`asyncio.create_task`, and a deploy was really one api service plus a
do-everything scheduler.

We want three genuinely separate long-running processes — `api`, `scheduler`,
`worker` — **without new infrastructure**. ROADMAP has always listed "Redis
when provisioned; PG job queue fallback"; nothing else in the deployment needs
a broker.

## Decision

### 1. Postgres is the queue — no broker

A `jobs` table (`id`, `kind`, `payload jsonb`, `dedupe_key unique`, `status`,
`attempts`, `max_attempts`, `run_after`, `locked_at`, `locked_by`, `error`,
timestamps) is the only queue. No Redis / Celery / RQ / RabbitMQ / SQS /
apscheduler, and no new runtime dependency.

Why Postgres and not a broker:

- **Transactional enqueue.** Enqueueing can commit in the same transaction as
  the domain write that motivates it (a questions fill request, a scheduler
  tick). A broker cannot participate in that transaction — the classic
  dual-write / outbox problem.
- **One source of truth.** Jobs live next to the domain tables they mutate;
  the same backup, the same `psql`, the same migrations cover them.
- **No extra failure mode.** Every supported install already runs Postgres
  (bundled or external, ADR 0027). A second stateful service would be a second
  thing to back up, monitor, and keep alive on a single-box install.

Claim is one atomic statement — an `UPDATE … RETURNING` whose inner
`SELECT … FOR UPDATE SKIP LOCKED` picks the oldest due `pending` row:

```sql
UPDATE jobs
   SET status='running', locked_at=now(), locked_by=:worker_id,
       attempts=attempts+1
 WHERE id = (SELECT id FROM jobs
              WHERE status='pending' AND run_after <= now()
              ORDER BY run_after, created_at
              FOR UPDATE SKIP LOCKED LIMIT 1)
RETURNING *;
```

**The design only works because of `SKIP LOCKED`.** A claim written as a
separate `SELECT` then `UPDATE` is a race — two workers read the same pending
row and both run it. `internal/memory/repos.py::claim_next_job` keeps this as
a single statement; do not split it.

### 2. What flows through the queue

Off-request / periodic work only: `hot_search` (Google Trends + RSS ingest),
`promote_signals`, `questions` (recommended-questions fill per company).

- **Scheduler = enqueue-only.** Each tick inserts deduped jobs; the hot tick
  enqueues `hot_search:{bucket}` + `promote_signals:{bucket}`, the questions
  tick one `questions:{company}:{bucket}` job per company with the existing
  per-company jitter carried in `run_after`. A scheduler restart mid-window
  cannot double-enqueue.
- **Worker = `python -m cmd.worker serve`.** `reclaim` sweep → `claim_next_job`
  → dispatch on `kind` via a handler map → `finish_job`. The existing
  `cmd.worker` subcommands are unchanged; `serve` is additive.
- **Recommended-questions fill goes through the queue.** The GET-miss / POST
  refresh path enqueues a `questions` job and still answers `202 generating`
  (ADR 0018 shape unchanged; `run_id` is now `null` until the worker claims).
  `question_runs` stays the execution log — the worker creates the row when it
  starts the job, finishes it when the job finishes, and keeps the existing
  `get_miss | refresh | scheduler` trigger values via the job payload.

### 3. Delivery, retry, leases

- **At-least-once.** A job is not deleted on success; `dedupe_key` makes
  enqueue idempotent within a scope (interval bucket for the scheduler, a
  minute bucket for the HTTP fill path). Handlers must stay idempotent —
  retries and a slow claim can both re-execute a job.
- **Backoff.** `finish_job` failures return to `pending` with an exponential
  `run_after` while `attempts < max_attempts` (3), then land `failed`.
- **15-minute lease + reclaim.** `running` rows whose `locked_at` is older
  than 15 minutes go back to `pending` with `locked_by = NULL`. A crashed
  worker must not wedge the queue.
- **Graceful shutdown.** SIGTERM/SIGINT stop claiming; the in-flight job runs
  to `finish_job` before the process exits 0. A hard kill leaves a `running`
  lease that the reclaim sweep takes back.

### 4. What stays in-process — and why

The **session/agent turn is not a job**. `internal/session/events.py` (the
in-memory SSE fan-out bus), `internal/session/turn_registry.py` ("in-process
registry … single-process only"), and `post_message → run_session_turn(...)`
are deliberately unchanged:

- A turn streams `message.delta` / `agent.progress` to *that* API process's
  open SSE connection; moving the turn would require cross-process event
  transport — exactly the infrastructure this ADR avoids.
- Stop/interrupt/park semantics (ADR 0004/0016/0035/0036) are tied to the
  in-process registry. Queueing turns would silently change that contract.
- Turns are request-scoped work with an open HTTP response waiting on them;
  jobs are fire-and-forget. Different shape, different tool.

If session turns ever need to outlive the API process, that is a separate ADR
(probably a broker + per-session event relay), not a `jobs` row.

## Consequences

- Three long-running services per install: `api`, `scheduler` (enqueue-only),
  `worker` (`cmd.worker serve`); plus one-shot `migrate` and `web`. Both
  compose packages ship all three.
- **Throughput ceiling.** `SKIP LOCKED` polling is fine for a handful of
  periodic pipelines; it does not scale to thousands of short jobs a second.
  This queue is a poor fit for **wide fan-out** (thousands of near-identical
  jobs in one burst) — if the workload ever looks like that, revisit with a
  real broker instead of growing this table.
- **Poll latency.** Idle workers poll every `WORKER_POLL_SECONDS` (default 5s,
  doubling to 30s while empty). A questions fill now waits for a worker tick —
  same 202 contract, slightly later start.
- `question_runs` is observability only; queue state lives in `jobs`. A
  `running` row abandoned by a dead worker is still expired by the ADR 0018
  stale/abandon sweep, independent of job leases.
- Multi-worker concurrency is safe by construction (`SKIP LOCKED`, unique
  `dedupe_key`, run-level partial unique index); running more than one worker
  replica works but is not required.
- `cmd.worker` ops subcommands (`signals`, `questions`, `promote`, `all`,
  `reset-signals`, `set-platform-role`, `connect-social-account`) are
  unchanged and still run inside the api container via `docker compose exec`.
