# ADR 0061 — `create_agent` inner loop; amends 0060's no-nested-graph clause

- **Status:** Accepted
- **Date:** 2026-11-20
- **Amends:** [ADR 0060](./0060-langchain-inner-harness.md) (§1 "no `create_agent` / `ToolNode` / nested `StateGraph`" clause and the §Rejected restatement — everything else stands)
- **Related:** [ADR 0002](./0002-rest-source-of-truth-sse-enhancement.md) (REST SSOT + SSE unchanged); [ADR 0003](./0003-confirm-without-llm.md) (Confirm stays HTTP); [ADR 0004](./0004-stop-discard-and-image-resume.md) (Stop → abort semantics — re-verified through the inner graph); [ADR 0019](./0019-pydantic-ai-inner-harness.md) (original nested-graph objection); [ADR 0047](./0047-session-file-attachments.md) (`read_attachment` contract + budget)

## Context

ADR 0060 ported the inner harness to `langchain-core` chat models but kept the tool loop hand-rolled (`bind_tools` + `astream`/`ainvoke` + manual `ToolMessage` dispatch + output-schema matching), declining `create_agent`/`ToolNode` under the original 0019 objection: a nested graph inside our graph makes state ownership ambiguous.

What the hand-rolled loop costs:

- ~150 lines of loop machinery (`_stream_round`, `_run_lc_tool_call`, `run_lc_tool_loop`) duplicating what `ToolNode` + `create_agent` already do — parallel tool calls, malformed-call handling, unknown-tool error messages, iteration caps.
- Every edge case is ours to test: tool calls mid-round vs end-round, invalid args, models that answer instead of calling the out-schema, usage across multi-round prompts.

What changed the calculus — a keyless spike (`scripts/spike_langchain_create_agent.py`, 8/8 checks) verified the two semantics the objection rested on:

1. **Cancel still aborts upstream through the graph.** `agent.astream(..., stream_mode="messages")` cancelled mid-stream closes the ChatOpenAI HTTP connection (stub-observed client EOF at 0.32s) — the ADR 0004 Stop→abort requirement survives the graph boundary.
2. **State ownership stays unambiguous because we give the inner graph nothing.** `create_agent` returns a leaf `CompiledStateGraph`; we never pass `checkpointer`, `store`, `context_schema`, or callbacks that touch `SessionState`. Its state is a per-call scratchpad (`messages` + `structured_response`) discarded when the node returns — the 0019 objection was about *shared* state, which this still does not do.

Two findings made `langgraph.prebuilt.create_react_agent` a dead end: it is deprecated since langgraph 1.0 (moved to `langchain.agents`, removal in v2.0), and its `response_format` runs a **separate** `generate_structured_response` node — an extra model call per typed node. `create_agent` + `ToolStrategy` keeps our single-call output-as-tool mechanism.

## Decision

### 1. The inner loop is `create_agent` — a leaf graph, not a subsystem

- `internal/session/harness.py` builds one agent per call: `create_agent(chat, tools=[...], system_prompt=...)`; typed loops add `response_format=ToolStrategy(OutT)`.
- The agent is **never** given `checkpointer`, `store`, `context_schema`, or `interrupt_*` — its state is per-call scratch owned by no one else. If a future change needs any of those, it needs a new ADR (the 0019 objection would be live again).
- `SessionState`, the outer checkpointer, `interrupt_before`, `turn_registry` — all unchanged. Graph semantics stay single-level *for state*; the inner graph is function-call depth, not orchestration depth.
- Deps stop being injected through the args dict (`InjectedToolArg` is gone — under `ToolNode` it injects `ToolRuntime`, not our dataclass). Tools are built per call and **close over** `deps` (`read_attachment_tool(deps)`, `research_tools(deps)`); the per-turn `attachment_reads` budget and owner re-scope are unchanged.

### 2. Streaming + recording + cancel keep their shapes

- Chat: `agent.astream({"messages": [HumanMessage(user)]}, stream_mode=["messages", "values"], config={"recursion_limit": …})`. `messages` payloads (`AIMessageChunk`, `langgraph_node="model"`) fan out to `message.delta` with the same 24-char flush; `values` payloads yield the final message list (output text + usage estimate input). `recorder.track` / `mark_first_token` / `set_usage` / partial-stash-on-cancel unchanged.
- The `stream_options`-ignoring-provider estimate keeps working: when no chunk carried `usage_metadata`, one estimate runs over the final state messages (`SystemMessage` prepended — `create_agent` keeps `system_prompt` out of state). On cancel it estimates over sent messages + the merged partial reply.
- Recursion cap: LangGraph counts supersteps (~2 per tool round), so `recursion_limit = 2 * _MAX_TOOL_ROUNDS + 2` replaces the hand-rolled round counter. `GraphRecursionError` maps to the old cap semantics — chat returns partial text; typed loops return a parse miss (`None`).
- The zero-chunk `ValueError` ("generation chunks") keeps mapping to an empty reply.

### 3. Typed outputs: `ToolStrategy`, not plain `response_format`

- `response_format=ToolStrategy(out_type)` binds the schema as a tool inside the loop — one model call, the mechanism ADR 0060 §1 already chose. Plain `response_format=Out` would pick a provider strategy and cost a second call.
- Fallback preserved: a model that answers with plain text instead of calling the out-schema still parses via `_structured_from_text`.
- `structured_response` lands on the returned state; `run_typed_lc_agent`'s contract is unchanged (provider error → `LlmProviderError`; cancel propagates; anything else → `None`).

## Consequences

- New dep: `langchain` 1.x (meta-package) — pinned `>=1.5.0,<1.5.1` (1.5.0 released 2026-11-11, inside the 7-day gate; 1.5.1+ same-day releases). `langgraph` already ships.
- `run_lc_tool_loop`/`run_typed_lc_agent` lose their `deps` param (tools close over it); `chat_tools`/`research_tools` gain a required `deps` param; `read_attachment`/`ingest_web_search` module-level tools become factories — test call sites updated, tool names/schemas unchanged.
- `_ScriptedChat` fakes keep working unmodified — `bind_tools` → `self` still satisfies `create_agent`, and scripted `out_call` replies drive `ToolStrategy`.
- Wins: middleware becomes available when a real need lands (summarization for long threads, HITL for in-loop approval per 0019 §3) — adopting either is its own ADR. Invalid/unknown/parallel tool-call handling is now framework-maintained.
- Unchanged and restated: Confirm/publish/catalog stay HTTP; PostgreSQL-only knowledge; REST SSOT; no publish-class tools; inner graph never receives checkpointer/store.
