# Prompt tuning with Admin Trace

How to use the admin LLM records, node steps, and Session Trace to fine-tune graph prompts. Product contracts stay in [ADR 0005](./adr/0005-platform-levels-and-llm-records.md) / [ADR 0007](./adr/0007-admin-trace-viewer.md); this doc is the **operator workflow**.

**Entry:** sign in as `platform_level ≥ 6` → UserMenu → **Admin** → SPA `/admin` (API is `/api/admin/*`)  
**Tabs:** LLM calls · Node steps · Research · Session Trace

---

## What each tab is for

| Tab | Answers |
|-----|---------|
| **LLM calls** | What did the model *see* and *return*? (`system_prompt`, `user_prompt`, `response_text`, tokens, latency, `parse_ok`, `fallback_used`) |
| **Node steps** | Which graph nodes ran in a turn, in what order? (`seq`, `mode_in`/`mode_out`, `intent_out`, capped `output`) |
| **Research** | ADR 0009 gate + ingest: `semantic_route`, `search_queries`, Tavily∪PG `research_signals` (per turn) |
| **Session Trace** | What did the *user* experience? Messages, draft revisions, signal grounding, turns grouped by `turn_id` |

Join key: **`turn_id`** (one graph `ainvoke` / resume). LLM rows and node steps for the same turn share it. Session-level join: **`session_id`**.

### Research tab — what “good” looks like

Paste `session_id` (or jump from LLM detail / Session Trace):

- **semantic_route** / **rule_pass** — gate decision before `query_generator`
- **search_queries** — should be short English/keyword atomic queries, **not** spoken Cantonese and **not** mixed pastes like `usagi 兔糧`
- **Signals** — Tavily∪PG hits with `source`, title, url; `metrics.query` shows which atomic query produced the hit

If queries still look like entity_surface verbatim, check `query_generator` LLM (`parse_ok` / fallback) and the gloss path in `fast_rules`.

---

## Workflow: optimize one node at a time

### 1. Find the failing step

In **LLM calls**, filter for:

- `status` ≠ `ok` (provider / empty / cancelled / error)
- **Fallback only**
- or scan for `parse_ok = false` in the flags column

Open a row → note `node` (e.g. `reviewer`, `route_intent`). Use **View steps for this turn** to open **Node steps** filtered by that `turn_id`.

Ask: was this a **bad prompt**, or did an **earlier node** feed bad state? Check previous `seq` outputs (`output_keys`, mode/intent transitions).

### 2. Diff input vs output for that LLM call

| Field | Questions to ask |
|-------|------------------|
| `system_prompt` | Contradictory rules? Missing JSON schema / language / Hong Kong context? |
| `user_prompt` | Missing company profile, signals, or prior draft? |
| `response_text` | Did the model follow a specific instruction, or invent? |
| tokens / latency | Prompt too large? Wrong model tier? |

Node-step **output** of step *N* is usually the real feedstock for step *N+1* — many “prompt bugs” are contract/state bugs.

### 3. Check product outcome in Session Trace

Paste `session_id` (or use **View session trace** from a detail sheet):

- **Messages** — what the user actually said
- **Draft revisions** — how copy evolved
- **Signal grounding** — citations vs hallucination
- **Graph turns** — step list + LLM count per turn

Success criteria after a prompt change: fewer parse/fallback flags, stabler turn paths, drafts that stay grounded.

### 4. Change → re-run → compare

1. Collect **5–10 bad cases** for the *same* node (don’t tune from a single fluke).
2. **Cluster** failures: JSON/schema, language (spoken Cantonese vs written Chinese), weak grounding, verbosity, wrong `route_intent`.
3. Edit **only that node’s** prompt (or its JSON schema instructions) — not the whole graph.
4. Re-run similar sessions; compare in admin:
   - `parse_ok` / `fallback_used` rate
   - turn path length / flapping
   - draft revision quality in Session Trace
5. Only then move to the next node.

### Signals worth watching

- High `fallback_used` + low `parse_ok` → tighten JSON/schema first, then creativity.
- Frequent wrong `route_intent` → fix the router before tuning downstream copy prompts.
- `reviewer` always failing → align reviewer criteria with `executor_post` output shape.
- Tokens up, quality flat → cut context; don’t pile on more instructions.
- Treat `image` and `chat_json` as separate tuning tracks.

### Bookmarking cases (until retention tooling exists)

There is no “save this bad case” UI yet. Keep a short list of `session_id` / `turn_id` / `node` (notes app or ticket) for before/after comparison.

---

## Retention / purge (what it means)

**Retention** = how long debug rows stay in Postgres, and **how we delete** them.

Today every LLM call and every graph node step can insert a row (`llm_call_records`, `session_node_steps`), including prompts that may contain company profile text. With recording on (`LLM_RECORD_ENABLED`, `NODE_TRACE_ENABLED`), tables **grow without bound**. ADR 0005 deliberately deferred a policy for early/dev scale.

A retention policy would typically decide:

| Decision | Examples |
|----------|----------|
| **Keep for how long?** | e.g. 30 / 90 days, then delete |
| **What to keep longer?** | Always keep `fallback_used` / `parse_ok = false` / `provider_error`; expire boring `ok` rows sooner |
| **How to delete?** | Periodic worker/scheduler `DELETE … WHERE created_at < …`, or partitioned tables |
| **Privacy on user delete** | FKs are `SET NULL` today — row content can remain after the user is gone; policy may require scrubbing prompts when an account is deleted |

**Why it matters for prompt tuning**

- Short retention → old bad cases disappear before you finish a tuning cycle; bookmark IDs early.
- No retention → disk growth + longer exposure of prompt payloads (admin-only, but still sensitive).
- A good default for this project later: e.g. keep 90 days, optional longer keep for non-`ok` / fallback rows, env like `LLM_RECORD_RETENTION_DAYS`.

**Status:** not implemented. Toggle recording off with `LLM_RECORD_ENABLED=false` / `NODE_TRACE_ENABLED=false` if you need to stop growth immediately. Designing the purge job is a follow-up (see [STATUS.md](./STATUS.md) Phase 3 later / hardening notes).

---

## Related

- [VOICE.md](./VOICE.md) — default HK 小編 craft + `roast_level` (tune `EXECUTOR_POST` / `BRAINSTORM` / `REVIEWER` against this)
- [ADR 0005](./adr/0005-platform-levels-and-llm-records.md) — platform levels + LLM call records  
- [ADR 0007](./adr/0007-admin-trace-viewer.md) — node steps + Session Trace  
- Bootstrap admin: `python -m cmd.worker set-platform-role --email … --level superadmin`  
- Apply DB: `alembic upgrade head` (includes `session_node_steps` / `turn_id`)
