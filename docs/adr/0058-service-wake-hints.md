# ADR 0058 — Service wake hints: LISTEN/NOTIFY + HTTP kick; polls demoted to backstop sweeps

- **Status:** Proposed
- **Date:** 2026-10-31
- **Supersedes:** —
- **Amends:** [ADR 0039](./0039-postgres-job-queue.md) (Consequences: poll latency), [ADR 0044](./0044-azure-aca-demo.md) (§1: worker/scheduler gain kick ingress), [ADR 0050](./0050-ingest-schedule-instance-settings.md) (snapshot reload cadence on quiet deployments)
- **Related:** [ADR 0018](./0018-recommended-questions-worker-graph.md) (questions fill 202), [ADR 0027](./0027-docker-deploy-packages.md) (compose packages), [ADR 0034](./0034-relay-per-install-shared-secret.md) (optional kick token precedent)

## Context

ADR 0039 made the `jobs` table the only queue and `cmd.worker serve` a
long-running consumer. Wake discovery is pure polling — every
`WORKER_POLL_SECONDS` (5s) backing off to a 30s cap, plus a 60s reclaim
sweep — and the scheduler separately re-reads instance settings every 60s
(ADR 0050's "edits apply within ~1 minute"). Two costs are now measured, not
theoretical:

- **Dispatch latency = poll interval.** An idle worker sits at the 30s cap;
  a `questions` fill (ADR 0018's 202 path, SPA deadline `POLL_DEADLINE_MS`
  7 min) or an `attachment_ingest` can wait unclaimed even though the
  enqueuer knew the instant the row landed.
- **Idle queries are unconditional — and on scale-to-zero Postgres they are
  the whole bill.** Neon counts *query activity* toward its 300s autosuspend
  timer; idle connections do not block suspend, and suspension severs them.
  The hosted demo (ADR 0044, Neon `free_v3` ≈100 CU-hours/mo) burned 84.5
  CU-hours by 2026-10-31 with ~70% compute uptime. Three independent clients
  keep it awake, and all three must be addressed or nothing improves:

  1. the worker's ≤30s claim polls + 60s reclaim sweep;
  2. the scheduler's 60s `load_snapshot` read (ADR 0050);
  3. real work itself — every enqueue/query costs ≥300s of active time
     because the timer restarts. The hourly scheduler enqueue alone is
     ~10–15% duty; this floor is unavoidable and *desired* (it's real work).

The fix is event-driven wake hints, but no single mechanism reaches every
deployment:

- **`pg_notify` inside the enqueue transaction** fires iff the row commits —
  atomic, zero-infra. But LISTEN is session state: through a
  transaction-mode pooler (Neon `-pooler`, any pgbouncer `pool_mode =
  transaction`) the LISTEN lands on a borrowed server conn, is silently
  dropped on checkin, and notifications route to whoever next borrows it.
  And on a scale-to-zero DB the mechanism self-defeats: suspend severs the
  listener → reconnect + liveness probe become their own keep-awake query
  loop → ~100% duty. LISTEN is an always-on-Postgres feature.
- **An HTTP kick** crosses poolers and — uniquely — needs no held DB
  connection, so a suspended compute can stay suspended while the worker
  stays on call. Its weakness is the classic dual-write: a POST issued after
  commit can be lost (producer crash in the gap). We tolerate exactly that
  dual-write — the thing ADR 0039 §1 rejected — **only because the kick is a
  hint, never the delivery mechanism.** The row stays the truth.

## Decision

1. **Row stays truth; hints wake; the sweep backstops.** The ADR 0039 claim
   (`UPDATE … FOR UPDATE SKIP LOCKED … RETURNING`), `finish_job` retry/lease,
   and reclaim sweep are unchanged. The worker's wake loop waits on three
   triggers — NOTIFY, kick, due-time timer — plus the backstop sweep; a hint
   is never required for delivery.

2. **`enqueue_job` marks the session once per transaction.** On a successful
   insert it sets a flag on `db.info`; a dedupe no-op sets nothing.
   Session-level hooks consume the flag:

   - `before_commit`: one `SELECT pg_notify('jobs', '')` per committing
     transaction — the scheduler's N-company questions tick emits one
     NOTIFY, not N.
   - `after_commit`: fire-and-forget `POST /kick` to each configured
     `WORKER_KICK_URL` (no-op when unset).
   - `after_rollback` / `after_soft_rollback`: clear the flag — savepoint
     rollbacks included — so a rolled-back transaction can never leak a hint
     into the next commit.
   - Kick dispatch is `loop.create_task` with a strong reference held until
     completion; short-lived producers (`scheduler --once`, `asyncio.run`
     scripts) can still lose the kick — the sweep covers.
   - Producers today: scheduler ticks, `sessions.py` fill, `attachments.py`,
     `document_ingest.py`, `question_graph/runner.py` — and the worker
     itself (embed reschedule; self-kick is harmless). `cmd.worker` ops
     subcommands run jobs inline and do not enqueue.

3. **Instance-settings writes get a parallel trigger.** The settings write
   path sets the same flag keyed to `SCHEDULER_KICK_URL`; an `after_commit`
   kick makes the scheduler reload its snapshot — preserving ADR 0050's
   ~1-minute apply without the 60s read (§8).

4. **Worker LISTEN lane (always-on PGs only).** A dedicated raw asyncpg
   connection derived from `DATABASE_URL` (dialect prefix stripped, SSL
   params translated) — never borrowed from the SQLAlchemy pool, where
   `pool_recycle` would retire it. `add_termination_listener` + TCP
   keepalive detect silent death; **every sweep doubles as the liveness
   probe** — a loopback `pg_notify` issued on a *different* connection must
   arrive within a timeout sized for Neon cold starts, else the lane is
   marked down. Capability ≠ policy: the self-test detects what *works*;
   `WORKER_LISTEN_ENABLED=false` is what scale-to-zero deployments set
   *anyway*, because a severed-then-reconnected listener plus its liveness
   probes would itself reset the suspend timer.

5. **Kick lane.** `serve` exposes `POST /kick` on `KICK_PORT` (off when
   unset) behind internal-only ingress — ACA internal ingress /
   compose `expose`, never `ports`; `allowInsecure` on ACA. The endpoint
   takes **no body, no params, no job ids or kinds — ever**; it is a wake
   signal, not a control plane, and must stay that way (ADR 0003/0011
   spirit). Bursts coalesce; kick-triggered claims are rate-limited ≥1s
   apart (each wake is a claim query → each costs ≥300s on Neon).
   Producers' outbound SSRF guards (CIMD fetch, image fetch) must refuse
   internal FQDNs / private ranges — verified before wiring — and an
   optional shared token (ADR 0034 precedent) is available if the boundary
   ever thins. The listener holds **no DB connection**: idle SQLAlchemy
   pool conns from past drains are fine (idle conns don't block suspend),
   held connections that issue queries are not.

6. **Wake semantics.** Lost-wakeup rule: the wake flag is cleared *before*
   each claim attempt, not after an empty claim — a hint arriving mid-drain
   must trigger one more pass. After every drain and every wake, the
   due-time timer is recomputed as `min(run_after) − now()` **on the DB
   clock** — this covers `finish_job` retries (an UPDATE emits no hint) and
   self-enqueued deferred jobs — capped by the sweep interval. The
   recompute reuses the drain's connection; it never issues a query solely
   to arm the timer.

7. **Sweep interval is per-environment, and the worst case is stated
   honestly.** `WORKER_SWEEP_SECONDS` defaults to 300 on always-on PGs. On
   scale-to-zero PGs, each sweep costs ≥300s of compute time, so it must be
   ≥3600 there — and **worst-case dispatch latency becomes the sweep
   interval, which is worse than today's 30s** (correcting the earlier
   "never worse" claim). On a `minReplicas: 0` worker the sweep only
   exists while a replica is up, so the true worst case there is *the
   next external kick* (bounded by the scheduler tick). Mitigations:
   producers retry each kick (backoff 1s, 5s); a missed `questions` hint
   shows as the SPA's existing 7-minute generate-timeout, only during
   quiet periods when nobody is on the demo; the alternative — a 300s
   sweep on Neon — would hold ~50–100% duty and defeat the purpose.

8. **Scheduler quiet mode — required for the Neon claim.** Its 60s
   `load_snapshot` is an independent keep-awake source. When `KICK_PORT` is
   wired the scheduler serves the same listener, sleeps until next
   tick-due or a kick, and reloads the snapshot on each wake — tick-due
   reload is real work; a settings-edit kick preserves the ~1-minute apply
   (amends ADR 0050 on quiet deployments only). Unwired, the 60s loop is
   unchanged. DB-touching-client inventory: api requests (real work;
   `minReplicas: 0` + DB-free `/api/health` — fine), scheduler (this §),
   worker (§1–6), the one-shot migrate job, and manual ops sessions.

9. **ACA target configuration** (amends ADR 0044's shape):

   - **Align `DATABASE_URL` to the direct endpoint** — matching ADR 0044
     §1 and the bicep `@description`. Deployment drift exists today: the
     live azd env carries a `-pooler` URL (confirmed via `pg_stat_activity`
     showing `pgbouncer` backends) and empirically works — Neon's pooler
     fork tolerates asyncpg prepared statements. Direct is still the
     recommendation: at ~10 connections the pooler buys nothing and keeps
     a transaction-mode session-state landmine under every future feature
     (temp tables, `SET`, advisory locks, LISTEN). Reconciling is one
     `azd env set` + redeploy; `WORKER_LISTEN_ENABLED=false` makes either
     host safe in the interim.
   - `WORKER_LISTEN_ENABLED=false` on ACA (§4) — policy, not capability.
   - worker + scheduler gain **internal ingress** exposing `/kick` with
     `allowInsecure` (amends the "no ingress" line in 0044 §1's table).
   - **worker: `minReplicas: 0`, kick-activated.** Deferred jobs (retry
     backoff, questions jitter ≤1800s, embed reschedule) stall until the
     next external kick — bounded by the next scheduler tick (~hourly) or
     user action, accepted for a demo. Cold start + FastEmbed warmup lands
     on the first kick after idle. Unverified ACA behavior to spike at
     deploy: whether ingress+`minReplicas:0`+no scale rule actually scales
     an idle replica down (today's no-ingress apps empirically stay up),
     and whether the activator still starts a replica when the kicking
     client abandons on a short timeout — kick timeout should exceed cold
     start, or the request marked fire-and-forget.
   - **scheduler: `minReplicas: 1`, quiet mode.** The scheduler must be
     resident to tick — nothing else kicks it hourly. Quiet mode
     (sleep-till-due, reload on wake/kick) means residency costs ACA idle
     billing but *zero* DB touches between ticks. Cheaper alternative,
     deferred: convert it to an **ACA scheduled job** running the existing
     `cmd.scheduler` once-mode (`run_scheduler(once=True)` already exists)
     on cron — zero resident cost, but ADR 0050's ~1-minute settings
     apply degrades to next-cron.
   - Wiring: api + scheduler get `WORKER_KICK_URL`; api gets
     `SCHEDULER_KICK_URL`; worker + scheduler get `KICK_PORT`;
     `WORKER_SWEEP_SECONDS=3600` on the demo env.

10. **Environment matrix.**

    | Environment | Lanes | Result |
    |---|---|---|
    | On-prem bundled/external PG (direct) | LISTEN + sweep 300 | ~0 latency; idle chatter → ~1 query/5min + held conn |
    | ACA + Neon (direct, LISTEN off) | kick + sweep 3600 | compute suspends between real work; duty → scheduler-tick bound ≈15–20% ≈ 35–50 CU-h/mo |
    | Any env, nothing wired | none | legacy polling — no regression |

## Alternatives considered

- **Poll-longer-only on Neon:** cannot beat the ≥300s-per-touch math; any
  poll interval still resets the same timer.
- **Neon Launch ($19/mo):** zero code and a defensible ops call; solves the
  demo but not on-prem latency or idle chatter. Revisit if ACA idle cost
  approaches it.
- **KEDA postgres scaler (scale worker on `count(pending)`):** the correct
  serverless shape, but deferred jobs and in-process timers die at zero
  replicas, and the scaler's own query cadence keeps the compute awake.
  Revisit if the demo graduates past a demo.
- **Resident worker (`minReplicas: 1`):** keeps due-time timers and the
  sweep always-on for ~$10–20/mo of ACA idle billing — rejected for the
  demo in favour of kick-activation (deferred-job stalls accepted); a
  valid pick if stall-free retries ever matter more than cost.
- **ACA scheduled job for the scheduler tick:** `run_scheduler(once=True)`
  on cron — zero resident cost; degrades ADR 0050's settings-apply to
  next-cron. Deferred, not rejected.
- **Switch `DATABASE_URL` to `-pooler`:** rejected in §9 — session-state
  hazards exceed the benefit.
- **A real broker:** still rejected per ADR 0039 §1.

## Consequences

- Typical dispatch latency drops from ≤30s to ~0 wherever a lane is wired;
  worst case is the sweep interval — explicitly **worse** than today's 30s
  when a hint is lost on a ≥3600s sweep (mitigated per §7, accepted).
- Idle chatter on always-on installs drops to ~1 sweep query per
  `WORKER_SWEEP_SECONDS` plus one held conn. On the Neon demo, residual
  activity is scheduler enqueues (~hourly), real drains, and the hourly
  sweep → ≈15–20% duty ≈ 35–50 CU-h/mo — under the ~100 free cap with
  headroom. This number is the testable promise of this ADR.
- NOTIFY correctness footnotes: the notify queue is not harmless under
  overflow — a full queue fails the enqueueing **COMMIT** and rolls back
  the domain write. Mitigations: the dedicated LISTEN conn never opens a
  transaction, and `pg_notification_queue_usage()` is a cheap health
  metric. NOTIFY also serializes committers on a global lock — negligible
  at this volume. One notify per transaction bounds the traffic.
- The kick lane *is* the dual-write ADR 0039 rejected — tolerated only
  because it is a hint. The "no new infrastructure" spirit holds (no
  stateful service, no broker), but each topology now carries
  port + ingress + URL wiring.
- Multi-replica fan-out degrades on the kick lane: a kick wakes one
  replica, so a burst drains through it alone until the sweep (NOTIFY is
  broadcast and unaffected). Single-replica installs are unaffected.
- Deferred jobs on a scale-to-zero worker stall until the next external
  kick (bounded by the hourly scheduler tick): retry backoff, questions
  jitter, embed reschedule. Accepted for the demo — the trade is ACA idle
  billing for job promptness; `minReplicas: 1` stays documented.
- The scheduler stays resident (`minReplicas: 1`) because nothing else
  drives its tick — its ACA idle billing is the residual cost of keeping
  ingest alive; the cron-job conversion is the documented exit.
- New settings: `WORKER_KICK_URL`, `SCHEDULER_KICK_URL`, `KICK_PORT`,
  `WORKER_LISTEN_ENABLED` (default on; set false on scale-to-zero DBs),
  `WORKER_SWEEP_SECONDS` (default 300; ≥3600 on Neon).
  `WORKER_POLL_SECONDS` keeps its meaning as the no-lane fallback cadence.
- Deferred `run_after` jobs (retry backoff, questions jitter, embed
  reschedule) stay prompt via the DB-clock due-time timer.
- Testing: session-spy asserts flag/notify/kick per commit, rollback, and
  savepoint; the no-lane fallback is today's cadence (existing
  `tests/api/test_jobs.py` coverage); live LISTEN round-trip needs real
  Postgres (compose CI), not SQLite; kick listener test asserts it never
  opens a DB session.
- Implementation follow-ups: bicep ingress + env wiring; reconcile the
  `-pooler`-vs-direct drift between the live azd env and the bicep
  description; verify SSRF guards refuse internal targets; decide on the
  optional kick token.
