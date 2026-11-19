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
- [x] Add deps: `langchain-openai>=1.7.4,<1.8` pinned (1.8.x was <7 days old); `langchain-core` rides transitively. `langchain-anthropic` / `langchain-google-genai` deferred — those providers stay on litellm
- [x] `complete_json`: langchain impl behind the same signature. `_lc_chat_model` (openai/openai_compatible → `ChatOpenAI`, `stream_usage=True`, `max_retries=0`, `response_format` via `model_kwargs`) + `_lc_astream_text` (joins delta `.content`, `usage_metadata` → `rec.set_usage`, aclose on cancel) + `_wrap_lc_error` (openai exceptions → `LlmProviderError` kinds). anthropic/gemini fall back to the litellm path; vertex untouched
- [x] `complete_text` / `astream_text`: same `_lc_chat_model` + `_lc_astream_text` helpers (no `json_mode`); both stream + join so cancel stays `aclose`-able. litellm fallback remains for anthropic/gemini
- [x] Port `harness.py` — tools → `@tool` + `deps: Annotated[ChatDeps, InjectedToolArg]` (loop injects via `args["deps"]`), hand-rolled `bind_tools` + `astream` loop (`_stream_chat_reply_lc`, `_MAX_TOOL_ROUNDS=32`), usage summed across rounds → `rec.set_usage`. openai/compat → LangChain path via `router._lc_chat_model` (`temperature=None`, provider default); anthropic/gemini/vertex + claude-by-name keep the pydantic path verbatim (`_stream_chat_reply_pa`, `Tool(_pa_*, name=…)` preserves model-facing names). `set_chat_model_override` accepts either model type — `BaseChatModel` → LC path, pydantic `Model` → pydantic path. `chat_tools()` is the new allowlist seam; `build_chat_agent`/`registered_function_tool_names`/`live_harness_model` stay for the fallback + research/execute harnesses. Test fakes: `GenericFakeChatModel` + `bind_tools→self` + `_stream` yielding `AIMessageChunk(tool_calls=…)` (helpers ported in `attachment_helpers._fn_chat_model`)
- [x] Port `research_harness.py` + `execute_harness.py` — `run_*_agent` signatures + override hooks kept (`BaseChatModel` → LC path, pydantic `Model` → fallback). Typed outputs via **output-as-tool**: `bind_tools([*tools, OutType])` so the model finishes by "calling" the output schema — same mechanism Pydantic AI used for `output_type`, no extra model call. Plain-JSON-text replies also parse (prompts already say "Return JSON only"). Shared helpers in `harness.py`: `_live_lc_model(tier)` (tier-parametrised `_live_lc_chat_model`), `run_lc_tool_loop`, `run_typed_lc_agent` (track/mark_last_call/valid-check contract identical to the PA runners). `test_session_nodes.py` TestModel sites re-scripted via shared `tests/unit/lc_fakes.py` (`_ScriptedChat` + `out_call`)
- [x] `scripts/eval_agent.py` runner seam — no work needed; it calls `EH.run_executor_post_agent` through the preserved signature and now rides the LC path automatically
- [x] `tests/eval/voice_judge.py` ported — `run_lc_tool_loop` with `tools=[]` + `out_type=VoiceJudgeOut`; test re-scripted via `out_call`
- [x] Rewrite the 5 coupled test files; confirm all other unit tests pass unmodified
- [x] Full provider coverage — `router._lc_harness_model` replaces `live_harness_model`: anthropic + claude-by-name → `ChatAnthropic` (`langchain-anthropic>=1.7.10,<1.7.11`), gemini/vertex_ai → `ChatGoogleGenerativeAI` (`langchain-google-genai>=4.4.3,<4.5.1`, `vertexai=True` = Express mode, verified client-side). `google-genai` promoted to a direct dep (vertex_express.py uses it). `_wrap_lc_error` maps anthropic + google-genai exceptions. `complete_json`/`complete_text`/`astream_text` fallbacks unchanged: anthropic/gemini → litellm, vertex_ai → `express_client`
- [x] Remove `pydantic-ai-slim` — all PA agents, `_pa_*` tool wrappers, `build_*_agent`, `live_harness_model`, `live_chat_model`, `registered_function_tool_names`, `_stream_chat_reply_pa`, `_run_*_pa`, `TestModel` sites deleted; zero `pydantic_ai` imports remain
- [ ] `pytest tests/unit` + API suite + eval baseline diff

## Spike findings (2026-11-19, `scripts/spike_langchain_astream.py` — keyless, 9/9)

Verified against `langchain-core` 1.8.3 + `langchain-openai` 1.8.3 with `GenericFakeChatModel` and a local OpenAI-compatible SSE stub:

- **Cancel propagates.** Cancelling the consumer task mid-stream raises `CancelledError` in the consumer AND runs `finally` blocks inside `_astream` — cleanup propagates through the outer `astream` wrapper. `BaseChatOpenAI._astream` holds the HTTP stream inside `async with context_manager`, so early close `aclose()`s the response.
- **HTTP abort is real.** Server-side: after 3 consumed chunks + cancel, the stub never served the remaining ~47 chunks and the client connection closed (EOF at ~0.34s of a ~7.5s stream). Best-effort upstream abort holds. Port note: the seam should still `aclose()` the outer generator on cancel.
- **First-token is per-chunk.** `mark_first_token` maps to "first `astream` chunk received" (fake ttft ~2ms). Equivalent semantics.
- **usage_metadata works.** With `stream_usage=True` the request carries `stream_options.include_usage`; a final `AIMessageChunk` carries `usage_metadata={input_tokens, output_tokens, total_tokens}` — map onto `rec.set_usage` (field names differ from litellm's `prompt_tokens`/`completion_tokens`: langchain normalises to `input_*`/`output_*`).
- **`response_format` routes to the beta `.stream()` path.** With `response_format` in the payload, `BaseChatOpenAI._astream` uses `root_async_client.beta.chat.completions.stream()` instead of `async_client.create()`. Consequences: (a) after the deltas it yields a **final-completion chunk with `content=''`** — naive `"".join(chunk.content)` is still safe; (b) the final-completion parser needs `role` in the first delta (a stub without `delta.role` crashed `_convert_dict_to_message` — real OpenAI/compat servers send it, but a compat provider that doesn't would hard-fail JSON mode).
- **Request body parity confirmed:** `stream=True`, `response_format={"type":"json_object"}` forwarded as-is via `model_kwargs`.

## Open questions

- [ ] **Vertex Express** — current path is api_key-only, no ADC (ADR 0021 §4). `langchain-google-vertexai` assumes ADC. Options: `langchain-google-genai` (AI Studio key) mapping, or keep vertex hand-rolled behind the seam.
- [ ] **OpenRouter slug** — `live_harness_model` strips `openrouter/` provider prefix + `openai_compat_model_id`; where does this live in the langchain provider mapping?
- [x] ~~**Attachment budget**~~ — resolved: `ChatDeps` is an `InjectedToolArg` param; the hand-rolled loop passes it via `args["deps"]` on every `tool.ainvoke` — per-turn counter semantics unchanged.
- [ ] **litellm** — `router.py` hand-rolls streaming on litellm/`acompletion`; `pricing.py` uses litellm cost map lazily. Migration likely keeps litellm for pricing even after the completion path moves — confirm before dropping the dep.
- [x] ~~**Structured output fidelity**~~ — **resolved by spike:** keep the `str` seam. `model_kwargs={"response_format":{"type":"json_object"}}` + join `astream` delta `.content` reproduces `complete_json` exactly; the trailing final-completion chunk is `content=''` so join stays clean. `with_structured_output` stays an option for nodes wanting schema validation, but is not needed for the seam.
- [ ] **response_format → beta path caveat** — JSON mode now depends on the openai client's beta streaming parser; a compat provider sending first-delta without `role` hard-fails (pydantic ValidationError, not LlmProviderError). Port should wrap that path so it surfaces as `LlmProviderError` like today.
