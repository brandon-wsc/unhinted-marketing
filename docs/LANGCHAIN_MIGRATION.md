# LangChain migration — working notes (temporary)

Scratch doc for `chore/langchain-migration`. **Delete once the migration lands** — the permanent record will be the ADR that supersedes [ADR 0019](./adr/0019-pydantic-ai-inner-harness.md). Not a SSOT; ROADMAP/STATUS/ADRs stay authoritative.

## Goal

Replace the **Pydantic AI inner harness** with LangChain chat models / chains inside the existing LangGraph session graph. The LangGraph outer layer (StateGraph, `interrupt_before`, Postgres checkpointer, `service.py` turn lifecycle) already exists and **stays**.

## Scope

**In scope — the three Pydantic AI harnesses + the hand-rolled completion seam:**

| File | What it is now | LangChain target |
|------|----------------|------------------|
| `internal/session/harness.py` | Chat agent — `query_market_trends` + `read_attachment` tools, streaming `message.delta` | ChatModel + `bind_tools` + `astream` (or `create_agent`/ToolNode loop) |
| `internal/session/research_harness.py` | `query_generator` agent — `ingest_web_search` + `query_market_trends` tools, typed `QueryGenOut` | tool loop + structured output |
| `internal/session/execute_harness.py` | `executor_post` draft + `edit_copy` agents — `query_market_trends` only, typed `DraftOut`/`EditOut` | tool loop + structured output |
| `internal/llm/router.py` `complete_json` / `complete_text` | hand-rolled litellm/OpenAI-compat streaming | LangChain ChatModel behind the **same signatures** |
| `scripts/eval_agent.py` | calls `EH.run_executor_post_agent` directly | re-point to new runner seam |

**Out of scope (do not touch):**

- `internal/session/graph.py`, `service.py`, `turn_registry`, checkpointer — graph/lifecycle layer
- REST/SSE contract, `schemas/`, confirm/publish/proposals HTTP paths (ADR 0003/0011)
- `generate_image` path (`internal/llm` image API) — separate hand-rolled provider path
- `internal/llm/pricing.py` litellm cost map, `probes.py` — keep unless they break
- `internal/perception/question_graph` uses `complete_json` — it inherits the swap via the seam, no direct port

## Hard constraints (must not move)

- Publish-class tools never registered — `PUBLISH_TOOL_NAMES` allowlist contract (ADR 0003/0011)
- `read_attachment` refusal contract: `slices=[]` + non-empty `error`, 3-read/turn budget (ADR 0047 §6/§14), owner re-scope per call
- Cancel semantics: stream + `aclose` on `CancelledError`; pydantic_ai `RunCancelled` → `asyncio.CancelledError` mapping needs a langchain equivalent (`astream` propagates task cancel — verify)
- `recorder.track()` call records preserved: `kind`, `tier`, `mark_first_token`, `set_usage`, `response_text` — `llm_call_records` + `eval_cost_from_records` + Session Trace depend on the shape
- `message.delta` SSE fan-out, 24-char flush (`_DELTA_FLUSH_CHARS`)
- BYOK provider matrix: `openai_compatible`/OpenRouter (slug stripping), OpenAI, Anthropic, Gemini/Vertex **Express api_key-only** (ADR 0021 §4 — no ADC)

## Seam strategy — the thing that saves ~115 test patch sites

`test_session_nodes.py` (~28), `test_session_thread_recap.py` (~20), `test_question_graph_nodes.py` (~24) patch `N.complete_json` / `N.complete_text` at the **module seam** (`from internal.llm.router import complete_json` re-exports). If we keep the seam signature — `async complete_json(*, tier, system, user, temperature) -> str` returning the raw JSON string — every one of those tests passes **unmodified**.

Same for harness runners: keep `RH.run_query_generator_agent`, `EH.run_executor_post_agent`, `EH.run_edit_copy_agent`, `H.stream_chat_reply` signatures + a model-override test hook. Tests that patch those names keep working; only the 5 harness-own test files get rewritten.

## Test plan

**Survive untouched** (do not re-baseline):
- `tests/api/*` — HTTP + real DB, LLM zone behind seams
- `test_session_stop.py` / `test_session_turn_errors.py` / `test_session_recency.py` — service-level seams (`_invoke_graph`, `session_is_parked`, event bus, repos); these carry the ADR 0004/0016/0035/0036 contracts
- `test_session_routing.py`, `test_session_guards.py`, `test_fast_rules.py`, `test_semantic_gate.py`, `test_session_image_format.py`, `test_session_media.py` — deterministic
- `test_session_angle_gate.py` — already builds real mini-StateGraphs w/ MemorySaver + interrupts; this is the **template** for new graph-level tests
- `test_session_snapshot_interrupt.py`, `test_session_trace.py`, schema/contract/zone gates

**Rewrite at the same abstraction** (Pydantic AI `TestModel` → langchain fakes):
- `test_session_harness.py`, `test_session_research_harness.py`, `test_session_execute_harness.py` → `langchain_core.language_models.fake_chat_models` (`FakeMessagesListChatModel` / `GenericFakeChatModel` / `FakeListChatModel` — scripted outputs, streaming, `tool_calls` on AIMessage)
- `test_read_attachment_tool.py`, `test_session_chat_attachments.py` → invoke via `tool.ainvoke(ToolCall)` or keep at inner-fn level; refusal-shape assertions unchanged

**Safety net around the swap:**
1. Before: `python -m scripts.eval_agent --suite regression --out reports/eval/baseline.json` on main
2. After: rerun + `python -m scripts.eval_diff` — set-coverage metrics must not regress (`--strict-models` for a model change)

## Steps

- [ ] **ADR 0060** — LangChain inner harness, supersedes ADR 0019 (required before/with code per AGENTS.md; this doc links out, ADR holds the decision)
- [ ] Add deps: `langchain-core`, `langchain-openai`, provider packages as needed (`langchain-anthropic`, `langchain-google-genai`) — pin versions ≥7 days old
- [ ] `complete_json` / `complete_text`: langchain impl behind the same signature (`init_chat_model` or provider mapping + `astream`; `response_format json_object` or `with_structured_output` — keep returning `str`)
- [ ] Port `harness.py` — tools → `@tool`, deps/`ChatDeps` → tool context (`InjectedToolArg`/config), keep `stream_chat_reply` + `set_chat_model_override` hook shape
- [ ] Port `research_harness.py` + `execute_harness.py` — keep `run_*_agent` signatures + override hooks; typed outputs via `with_structured_output`
- [ ] Re-point `scripts/eval_agent.py` runner seam
- [ ] Rewrite the 5 coupled test files; confirm all other unit tests pass unmodified
- [ ] `pytest tests/unit` + API suite + eval baseline diff
- [ ] Remove `pydantic-ai-slim` last

## Open questions

- [ ] **Vertex Express** — current path is api_key-only, no ADC (ADR 0021 §4). `langchain-google-vertexai` assumes ADC. Options: `langchain-google-genai` (AI Studio key) mapping, or keep vertex hand-rolled behind the seam.
- [ ] **OpenRouter slug** — `live_harness_model` strips `openrouter/` provider prefix + `openai_compat_model_id`; where does this live in the langchain provider mapping?
- [ ] **Attachment budget** — `deps.attachment_reads` is per-turn mutable state inside `RunContext`; langchain equivalent = `InjectedState`/config-scoped counter or keep the check inside the tool's inner fn with a turn-scoped object passed via `RunnableConfig`.
- [ ] **litellm** — `router.py` hand-rolls streaming on litellm/`acompletion`; `pricing.py` uses litellm cost map lazily. Migration likely keeps litellm for pricing even after the completion path moves — confirm before dropping the dep.
- [ ] **Structured output fidelity** — `complete_json` callers `json.loads`/`model_validate` the raw string; `with_structured_output` returns parsed objects. Keeping the `str` seam means serializing back — decide whether the seam returns `str` (zero test churn) or a new name is introduced (then re-point ~115 sites — avoid).
