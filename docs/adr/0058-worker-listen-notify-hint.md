# ADR 0058 — Worker wake hints: LISTEN/NOTIFY + HTTP kick; poll demoted to backstop sweep

- **Status:** Proposed
- **Date:** 2026-10-31
- **Supersedes:** —
- **Related:** [ADR 0039](./0039-postgres-job-queue.md) (jobs queue + claim contract), [ADR 0018](./0018-recommended-questions-worker-graph.md) (questions fill 202 contract), [ADR 0044](./0044-azure-aca-demo.md) (ACA demo on external Postgres)

## Context

ADR 0039 made the `jobs` table the only queue and `cmd.worker serve` a
long-running consumer. Discovery is pure polling: claim attempt every
`WORKER_POLL_SECONDS` (5s) doubling to a 30s cap while the queue stays empty,
plus a 60s reclaim sweep. Two costs have become concrete:

- **Dispatch latency = poll interval.** An idle worker drifts to the 30s cap;
  a `questions` fill (ADR 0018's 202 path) or an `attachment_ingest` can sit
  unclaimed for up to half a minute even though the enqueuer knew exactly when
  the row landed. Scheduler jobs don't care (hourly cadence); user-facing
  fills do.
- **Idle chatter is unconditional.** ~2 claim attempts/min + a reclaim sweep
  every 60s, forever — including the ~99% of wall time the queue is empty.
  On an always-on Postgres this is noise. On a scale-to-zero Postgres it is
  the dominant cost: Neon's autosuspend timer resets on any client activity,
  so the hosted demo's compute (ADR 0044, free plan ≈100 CU-hours/mo) never
  sleeps — measured 84.5 CU-hours consumed by 2026-10-31 and ~70% uptime over
  the project's 20-day life. Raising `WORKER_POLL_SECONDS` cannot fix it: any
  poll interval under the suspend timeout still resets the timer.

The enqueue side already knows the moment work lands; the ideal wake hint is
event-driven. But no single mechanism reaches every deployment:

- **`pg_notify` inside the enqueue transaction** fires iff the row commits —
  atomic, zero-infra — but LISTEN is session state, so it cannot cross a
  transaction-mode pooler (Neon's `-pooler` host, any pgbouncer in
  transaction pooling).
- **An HTTP kick** to the worker crosses anything (it's not a DB channel at
  all), and — uniquely — it does not require the worker to hold a DB
  connection, so a scale-to-zero compute can actually sleep between jobs.
  Its weakness is the classic dual-write window: a POST issued after commit
  can be lost if the producer dies in between.

Either way, the `jobs` row remains the source of truth and a slow sweep
remains as backstop — the same reason mature PG-backed queues keep sweeping
after adding wake mechanisms.

## Decision

1. **Two wake lanes plus a permanent backstop.** Producers emit whichever
   lanes are wired for the environment; the worker listens on whichever it
   can; the sweep always runs. Nothing in delivery correctness depends on a
   hint arriving.

2. **`enqueue_job` marks the session; lanes fire on commit.** The repo
   function records a flag on the DB session (`db.info`) when an insert
   actually lands (dedupe no-op marks nothing). Two emission paths hang off
   that flag:

   - **LISTEN lane:** `SELECT pg_notify('jobs', :job_id)` inside the same
     transaction — delivered iff commit; a rollback or dedupe no-op sends
     nothing. Every producer already funnels through `enqueue_job`
     (scheduler ticks, session questions fill, attachments, document_ingest,
     question runner, ops subcommands), so one insertion point covers all
     enqueuers. Payload is the job id for observability only.
   - **Kick lane:** a session `after_commit` hook POSTs a fire-and-forget
     `POST /kick` to `WORKER_KICK_URL` when set (unset → lane skipped
     silently). Binding to `after_commit` — not issuing the POST inline —
     preserves fires-iff-commit semantics: the kick cannot race ahead of the
     row's visibility, and a rollback sends nothing. A producer crash between
     commit and hook execution can still drop the kick; the sweep covers it.

3. **Worker — LISTEN lane:** a dedicated LISTEN connection separate from
   claim sessions (asyncpg `add_listener` on channel `jobs`) wakes the drain
   loop — claim → dispatch → finish until empty, unchanged. NOTIFY is
   broadcast: every replica wakes; `FOR UPDATE SKIP LOCKED` still
   single-claims.

4. **Worker — kick lane:** `serve` optionally runs a minimal HTTP listener
   (`WORKER_KICK_PORT`; unset → listener off) exposing only `POST /kick`,
   which wakes the same drain loop. The deployment network is the security
   boundary — ACA internal ingress / the compose bridge network — so the
   kick needs no app-level auth; it is a wake signal, not a control plane.
   The listener must never hold a DB connection of its own — that is what
   lets a scale-to-zero database suspend while the worker stays "on call".

5. **Backstop replaces idle polling.** With any healthy hint lane the loop
   waits on whichever fires first: NOTIFY, kick, a due-time timer set to
   `min(run_after)` over pending rows — deferred jobs (retry backoff,
   questions jitter) stay prompt — or `WORKER_SWEEP_SECONDS` (default 300),
   which also runs reclaim. With no healthy lane the worker runs today's
   cadence (`WORKER_POLL_SECONDS` → 30s cap, 60s reclaim). Worst-case
   dispatch latency = sweep interval; delivery semantics identical to today.

6. **Startup self-test picks the lane — no mode config for correctness.**
   After `LISTEN jobs`, a loopback `pg_notify` on a normal session must
   arrive within a few seconds or the LISTEN lane is marked unavailable (log
   once). This empirically detects transaction-mode poolers instead of
   trusting a flag; reconnect re-tests. `WORKER_LISTEN_ENABLED=false` is the
   ops escape hatch. The kick lane needs no test — it exists iff
   `WORKER_KICK_URL` is wired.

7. **Environment matrix — each deployment uses the lane(s) that work:**

   | Environment | Lane | Effect |
   |---|---|---|
   | On-prem bundled/external PG (direct) | LISTEN | ~0 latency; idle chatter → ~1 sweep/5min + held conn |
   | ACA demo, Neon via `-pooler` | Kick | ~0 latency; **compute can suspend between jobs** — the free-tier quota fix path |
   | Compose + transaction pooler (rare) | Kick | same as above via service DNS |
   | Any env, nothing wired | None | legacy polling, no regression |

8. **ADR 0039 semantics unchanged.** Row = source of truth; one-statement
   `SKIP LOCKED` claim; `finish_job` retry/lease; reclaim sweep. Hints are a
   wake-up layer only — never required for delivery. Session turns are still
   not jobs (0039 §4).

## Consequences

- Typical dispatch latency drops from ≤30s to ~0 in every environment with a
  wired lane; worst case is the sweep interval — never worse than today.
- **The Neon free-tier burn becomes solvable:** on the kick lane the worker
  holds no DB connection and issues no idle queries, so the compute can
  actually suspend between enqueues. Residual activity is real work only —
  scheduler enqueues (~hourly), user-triggered fills, and the 5-min sweep —
  taking idle CU-hours from ~70% duty to roughly sweep-interval duty. This is
  the mechanism; enabling it on the ACA demo is `WORKER_KICK_URL` +
  `WORKER_KICK_PORT` + worker internal ingress in `infra/main.bicep` — an ops
  change, not more code.
- Kick hits one worker replica (per-replica listener, no broadcast) —
  harmless under SKIP LOCKED; multi-replica fan-out is a non-goal.
- New settings: `WORKER_KICK_URL` (producers), `WORKER_KICK_PORT` (worker),
  `WORKER_LISTEN_ENABLED` (default on, self-test still gates),
  `WORKER_SWEEP_SECONDS` (default 300). `WORKER_POLL_SECONDS` keeps its
  meaning as the fallback cadence.
- NOTIFY is fire-and-forget: payloads cap at 8000 bytes and the queue can
  overflow under extreme volume — harmless; the sweep covers and the payload
  carries no correctness. Kicks are fire-and-forget too: no retry, short
  timeout, failure logged — the sweep covers.
- Deferred `run_after` jobs stay prompt via the due-time timer — no
  regression for retry backoff or questions jitter.
- Testing: notify is one statement inside `enqueue_job` (session spy); the
  `after_commit` kick hook is testable by asserting the POST fires after
  commit and not after rollback; the no-lane fallback is today's cadence
  already covered by `tests/api/test_jobs.py`; a live LISTEN round-trip needs
  real Postgres (compose CI), not SQLite.
