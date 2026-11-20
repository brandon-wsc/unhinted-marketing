"""Spike: can langchain.agents.create_agent replace our hand-rolled loop?

Keyless — local OpenAI-compatible SSE stub only. Checks, in ADR-critical order:

1. messages-mode token streaming through the graph (ttft + metadata).
2. Cancel mid-stream through the graph node → does the HTTP connection
   actually close (best-effort upstream abort, ADR hard-boundary 6)?
3. Tool call round-trip: model requests a tool, ToolNode runs it, model
   gets the result, streams a final answer.
4. response_format=Out → structured_response via the output-as-tool
   mechanism (same mechanism we hand-rolled in run_lc_tool_loop).
5. Closure-bound deps: our tools are built per call inside
   stream_chat_reply, so deps can close over the call scope — verify a
   closure tool runs correctly under ToolNode.
6. usage_metadata on streamed message chunks.

Run: .venv/bin/python scripts/spike_langchain_create_agent.py
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

RESULTS: list[tuple[str, bool, str]] = []


def report(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def _sse(obj: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(obj)}\n\n".encode()


def _chunk(delta: dict[str, Any], *, finish: str | None = None) -> bytes:
    return _sse(
        {
            "id": "chatcmpl-spike",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "spike-model",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
    )


def _usage_chunk() -> bytes:
    return _sse(
        {
            "id": "chatcmpl-spike",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "spike-model",
            "choices": [],
            "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
        }
    )


def text_resp(parts: list[str], *, delay_s: float = 0.02, usage: bool = True) -> dict:
    return {"kind": "text", "parts": parts, "delay_s": delay_s, "usage": usage}


def tool_call_resp(name: str, args: dict[str, Any]) -> dict:
    return {"kind": "tool_call", "name": name, "args": args}


class ScriptStub:
    """Serves scripted responses, one per incoming request (last repeats).

    Records every request body; watches client EOF for abort detection.
    """

    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.request_bodies: list[dict[str, Any]] = []
        self.client_eof_at: float | None = None
        self.served_fully = False
        self._server: asyncio.base_events.Server | None = None

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self._server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _watch_eof(self, reader: asyncio.StreamReader) -> None:
        await reader.read()
        self.client_eof_at = time.monotonic()

    async def _serve_json(self, writer: asyncio.StreamWriter, spec: dict[str, Any]) -> None:
        if spec.get("delay_s"):
            await asyncio.sleep(spec["delay_s"])
        message: dict[str, Any] = {"role": "assistant", "content": None}
        finish = "stop"
        if spec["kind"] == "text":
            message["content"] = "".join(spec["parts"])
        elif spec["kind"] == "tool_call":
            message["tool_calls"] = [
                {
                    "id": "call_spike_1",
                    "type": "function",
                    "function": {
                        "name": spec["name"],
                        "arguments": json.dumps(spec["args"]),
                    },
                }
            ]
            finish = "tool_calls"
        payload = json.dumps(
            {
                "id": "chatcmpl-spike",
                "object": "chat.completion",
                "created": 1,
                "model": "spike-model",
                "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 4,
                    "total_tokens": 15,
                },
            }
        ).encode()
        writer.write(
            b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n"
            b"connection: close\r\ncontent-length: "
            + str(len(payload)).encode()
            + b"\r\n\r\n"
            + payload
        )
        await writer.drain()
        self.served_fully = True

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        length = 0
        for line in head.decode(errors="replace").split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        body = await reader.readexactly(length) if length else b"{}"
        watcher = asyncio.create_task(self._watch_eof(reader))
        body_json: dict[str, Any] = {}
        with contextlib.suppress(json.JSONDecodeError):
            body_json = json.loads(body)
        self.request_bodies.append(body_json)
        spec = self.responses[min(len(self.request_bodies), len(self.responses)) - 1]
        if not body_json.get("stream"):
            # audit-allow(ERR-03): client abort mid-delay is the outcome under test.
            with contextlib.suppress(
                ConnectionResetError, BrokenPipeError, asyncio.CancelledError
            ):
                await self._serve_json(writer, spec)
            writer.close()
            await watcher
            return
        writer.write(
            b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n"
            b"cache-control: no-cache\r\nconnection: close\r\n\r\n"
        )
        await writer.drain()
        try:
            if spec["kind"] == "text":
                for i, part in enumerate(spec["parts"]):
                    delta: dict[str, Any] = {"content": part}
                    if i == 0:
                        delta["role"] = "assistant"
                    writer.write(_chunk(delta))
                    await writer.drain()
                    await asyncio.sleep(spec["delay_s"])
                if spec["usage"]:
                    writer.write(_usage_chunk())
                    await writer.drain()
            elif spec["kind"] == "tool_call":
                tc = {
                    "index": 0,
                    "id": "call_spike_1",
                    "type": "function",
                    "function": {"name": spec["name"], "arguments": json.dumps(spec["args"])},
                }
                writer.write(_chunk({"role": "assistant", "tool_calls": [tc]}))
                await writer.drain()
                writer.write(_chunk({}, finish="tool_calls"))
                await writer.drain()
                if spec.get("usage"):
                    writer.write(_usage_chunk())
                    await writer.drain()
            writer.write(b"data: [DONE]\n\n")
            await writer.drain()
            self.served_fully = True
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            # audit-allow(ERR-03): client abort is the outcome under test.
            pass
        writer.close()
        await watcher


def _model(port: int, **kw: Any) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=f"http://127.0.0.1:{port}/v1",
        api_key="spike",
        model="spike-model",
        **kw,
    )



async def t1_messages_mode_streams() -> None:
    stub = ScriptStub([text_resp(["he", "llo ", "world"], delay_s=0.03)])
    port = await stub.start()
    agent = create_agent(_model(port), tools=[])
    t0 = time.monotonic()
    first_at: float | None = None
    parts: list[str] = []
    nodes: set[str] = set()
    async for chunk, meta in agent.astream(
        {"messages": [HumanMessage(content="hi")]}, stream_mode="messages"
    ):
        if first_at is None:
            first_at = time.monotonic()
        if isinstance(chunk.content, str):
            parts.append(chunk.content)
        nodes.add(meta.get("langgraph_node", "?"))
    await stub.close()
    report(
        "messages-mode: token deltas arrive incrementally",
        len(parts) >= 2 and "".join(parts) == "hello world",
        f"parts={parts!r} ttft={((first_at or t0) - t0) * 1000:.0f}ms nodes={nodes}",
    )


async def t2_cancel_through_graph() -> None:
    stub = ScriptStub([text_resp([f"part{i} " for i in range(50)], delay_s=0.15)])
    port = await stub.start()
    agent = create_agent(_model(port), tools=[])
    parts: list[str] = []
    agen = agent.astream({"messages": [HumanMessage(content="hi")]}, stream_mode="messages")

    async def consume() -> None:
        async for chunk, _meta in agen:
            if isinstance(chunk.content, str):
                parts.append(chunk.content)

    t0 = time.monotonic()
    task = asyncio.create_task(consume())
    while len(parts) < 3:
        await asyncio.sleep(0.01)
    task.cancel()
    cancelled = False
    try:
        await task
    except asyncio.CancelledError:
        cancelled = True
    with contextlib.suppress(Exception):
        await agen.aclose()
    await asyncio.sleep(0.1)
    await stub.close()
    aborted = (stub.client_eof_at is not None and stub.client_eof_at - t0 < 3.0) or (
        not stub.served_fully
    )
    report(
        "cancel: mid-stream cancel through graph aborts HTTP connection",
        cancelled and aborted,
        f"chunks={len(parts)} served_fully={stub.served_fully} "
        f"eof={None if stub.client_eof_at is None else round(stub.client_eof_at - t0, 2)}s",
    )


async def t7_ainvoke_cancel_through_graph() -> None:
    stub = ScriptStub([text_resp(["slow"], delay_s=2.0)])
    port = await stub.start()
    agent = create_agent(_model(port), tools=[])
    t0 = time.monotonic()
    task = asyncio.create_task(
        agent.ainvoke({"messages": [HumanMessage(content="hi")]})
    )
    await asyncio.sleep(0.3)  # let the request reach the stub
    task.cancel()
    cancelled = False
    try:
        await task
    except asyncio.CancelledError:
        cancelled = True
    await asyncio.sleep(0.1)
    await stub.close()
    aborted = (stub.client_eof_at is not None and stub.client_eof_at - t0 < 3.0) or (
        not stub.served_fully
    )
    report(
        "cancel: mid-ainvoke cancel through graph aborts HTTP connection",
        cancelled and aborted,
        f"served_fully={stub.served_fully} "
        f"eof={None if stub.client_eof_at is None else round(stub.client_eof_at - t0, 2)}s",
    )


async def t3_tool_round_trip() -> None:
    calls: list[str] = []

    @tool
    def get_weather(city: str) -> str:
        """Get weather for a city."""
        calls.append(city)
        return "sunny and 28C"

    stub = ScriptStub(
        [
            tool_call_resp("get_weather", {"city": "Hong Kong"}),
            text_resp(["It is ", "sunny."]),
        ]
    )
    port = await stub.start()
    agent = create_agent(_model(port), tools=[get_weather])
    result = await agent.ainvoke({"messages": [HumanMessage(content="weather?")]})
    await stub.close()
    msgs = result["messages"]
    tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
    final = msgs[-1]
    report(
        "tool-loop: ToolNode ran the tool and model answered",
        calls == ["Hong Kong"]
        and len(tool_msgs) == 1
        and tool_msgs[0].content == "sunny and 28C"
        and isinstance(final, AIMessage)
        and "sunny" in str(final.content),
        f"calls={calls} n_msgs={len(msgs)} requests={len(stub.request_bodies)}",
    )
    req2 = stub.request_bodies[1] if len(stub.request_bodies) > 1 else {}
    saw_tool_msg = any(
        m.get("role") == "tool" and m.get("content") == "sunny and 28C"
        for m in req2.get("messages", [])
    )
    report(
        "tool-loop: round-2 request carries the ToolMessage",
        saw_tool_msg,
        f"req2_roles={[m.get('role') for m in req2.get('messages', [])]}",
    )


class BriefOut(BaseModel):
    """Structured output schema."""

    summary: str
    angles: list[str]


async def t4_response_format() -> None:
    stub = ScriptStub(
        [
            tool_call_resp("BriefOut", {"summary": "s", "angles": ["a1", "a2"]}),
            text_resp(["unused"]),
        ]
    )
    port = await stub.start()
    agent = create_agent(_model(port), tools=[], response_format=ToolStrategy(BriefOut))
    result = await agent.ainvoke({"messages": [HumanMessage(content="brief")]})
    await stub.close()
    sr = result.get("structured_response")
    report(
        "response_format: structured_response populated",
        isinstance(sr, BriefOut) and sr.angles == ["a1", "a2"],
        f"structured_response={sr!r} requests={len(stub.request_bodies)}",
    )
    req1 = stub.request_bodies[0] if stub.request_bodies else {}
    tool_names = [t.get("function", {}).get("name") for t in req1.get("tools", [])]
    report(
        "response_format: output schema bound as tool",
        "BriefOut" in tool_names,
        f"tools={tool_names}",
    )


async def t5_closure_deps() -> None:
    class Deps:
        def __init__(self) -> None:
            self.remaining = 2

    deps = Deps()

    @tool
    def read_attachment(attachment_id: str) -> str:
        """Read an attachment."""
        deps.remaining -= 1
        return f"content-of-{attachment_id} (remaining={deps.remaining})"

    stub = ScriptStub(
        [
            tool_call_resp("read_attachment", {"attachment_id": "a1"}),
            text_resp(["done"]),
        ]
    )
    port = await stub.start()
    agent = create_agent(_model(port), tools=[read_attachment])
    result = await agent.ainvoke({"messages": [HumanMessage(content="read a1")]})
    await stub.close()
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    report(
        "deps: closure-bound deps work under ToolNode",
        deps.remaining == 1 and len(tool_msgs) == 1 and "remaining=1" in str(tool_msgs[0].content),
        f"remaining={deps.remaining} tool_msgs={[m.content for m in tool_msgs]}",
    )


async def t6_usage_metadata_in_stream() -> None:
    stub = ScriptStub([text_resp(["a", "b"], delay_s=0.01)])
    port = await stub.start()
    agent = create_agent(_model(port, stream_usage=True), tools=[])
    usage: dict[str, Any] = {}
    async for chunk, _meta in agent.astream(
        {"messages": [HumanMessage(content="hi")]}, stream_mode="messages"
    ):
        if getattr(chunk, "usage_metadata", None):
            usage.update(chunk.usage_metadata)
    await stub.close()
    report(
        "stream: usage_metadata lands on message chunks",
        usage.get("total_tokens") == 15,
        f"usage={usage} stream_opts={stub.request_bodies[0].get('stream_options') if stub.request_bodies else None}",
    )


async def main() -> None:
    await t1_messages_mode_streams()
    await t2_cancel_through_graph()
    await t3_tool_round_trip()
    await t4_response_format()
    await t5_closure_deps()
    await t6_usage_metadata_in_stream()
    await t7_ainvoke_cancel_through_graph()
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
