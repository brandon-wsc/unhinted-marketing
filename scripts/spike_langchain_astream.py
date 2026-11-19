"""Spike: verify LangChain `astream` semantics for the `complete_json` seam.

Keyless. Three layers:

1. GenericFakeChatModel — astream chunk flow, first-token timing.
2. TrackedFakeChatModel — cancel mid-stream: does the generator's `finally`
   run (i.e. does cleanup propagate through the outer astream wrapper)?
3. Local OpenAI-compatible SSE stub + ChatOpenAI — does cancelling mid-stream
   actually close the TCP connection (best-effort upstream abort), and what do
   the request body (response_format / stream_options) and usage_metadata
   look like?

Run: .venv/bin/python scripts/spike_langchain_astream.py
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

RESULTS: list[tuple[str, bool, str]] = []


def report(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


# --- 1. Fake model streaming + first token ---------------------------------


async def t1_fake_stream_first_token() -> None:
    model = GenericFakeChatModel(messages=iter(["alpha beta gamma"]))
    t0 = time.monotonic()
    first_at: float | None = None
    parts: list[str] = []
    async for chunk in model.astream([HumanMessage(content="hi")]):
        if first_at is None:
            first_at = time.monotonic()
        parts.append(chunk.content if isinstance(chunk.content, str) else "")
    report(
        "fake: streams chunks incrementally",
        len(parts) >= 2,
        f"chunks={parts!r}",
    )
    report(
        "fake: first-token measurable",
        first_at is not None and first_at >= t0,
        f"ttft={((first_at or t0) - t0) * 1000:.1f}ms",
    )


# --- 2. Cancel propagates into the generator (finally runs) ----------------


class TrackedFakeChatModel(BaseChatModel):
    """Sleeps between chunks; records whether _astream's finally ran."""

    cleaned_up: bool = False
    chunk_delay_s: float = 0.05

    @property
    def _llm_type(self) -> str:
        return "tracked-fake"

    def _generate(self, messages: list[BaseMessage], **kw: Any) -> ChatResult:
        raise NotImplementedError

    async def _astream(self, messages: list[BaseMessage], **kw: Any):
        try:
            for tok in ["a", "b", "c", "d", "e", "f", "g", "h"]:
                await asyncio.sleep(self.chunk_delay_s)
                yield ChatGenerationChunk(message=AIMessageChunk(content=tok))
        finally:
            self.cleaned_up = True


async def t2_cancel_finally_runs() -> None:
    model = TrackedFakeChatModel()
    got: list[str] = []

    async def consume() -> None:
        async for chunk in model.astream([HumanMessage(content="hi")]):
            got.append(chunk.content if isinstance(chunk.content, str) else "")

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.16)  # let ~3 chunks land
    task.cancel()
    cancelled = False
    try:
        await task
    except asyncio.CancelledError:
        cancelled = True
    await asyncio.sleep(0.05)  # let finally settle
    report("cancel: CancelledError reaches consumer", cancelled, f"chunks={got!r}")
    report(
        "cancel: generator finally runs (cleanup propagates)",
        model.cleaned_up,
        "finally in _astream executed on cancel",
    )


# --- 3. Real HTTP path: local SSE stub + ChatOpenAI -------------------------


def _sse_chunk(
    content: str | None, usage: dict | None = None, *, first: bool = False
) -> bytes:
    obj: dict[str, Any] = {
        "id": "chatcmpl-spike",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "spike-model",
    }
    if usage is not None:
        obj["choices"] = []
        obj["usage"] = usage
    else:
        delta: dict[str, Any] = {"content": content}
        if first:
            delta["role"] = "assistant"
        obj["choices"] = [{"index": 0, "delta": delta, "finish_reason": None}]
    return f"data: {json.dumps(obj)}\n\n".encode()


class SseStub:
    """One-shot OpenAI-compatible SSE server; records request body + EOF time."""

    def __init__(self, *, chunks: int, delay_s: float) -> None:
        self.chunks = chunks
        self.delay_s = delay_s
        self.request_body: dict[str, Any] = {}
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
        await reader.read()  # returns b"" at FIN
        self.client_eof_at = time.monotonic()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        length = 0
        for line in head.decode(errors="replace").split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        body = await reader.readexactly(length) if length else b"{}"
        # Watcher must start after the request is fully read: a StreamReader
        # rejects a second concurrent read.
        watcher = asyncio.create_task(self._watch_eof(reader))
        try:
            self.request_body = json.loads(body)
        except json.JSONDecodeError:
            pass
        writer.write(
            b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n"
            b"cache-control: no-cache\r\nconnection: close\r\n\r\n"
        )
        await writer.drain()
        try:
            for i in range(self.chunks):
                writer.write(_sse_chunk(f"part{i} ", first=i == 0))
                await writer.drain()
                await asyncio.sleep(self.delay_s)
            writer.write(
                _sse_chunk(
                    None,
                    usage={
                        "prompt_tokens": 11,
                        "completion_tokens": self.chunks,
                        "total_tokens": 11 + self.chunks,
                    },
                )
            )
            await writer.drain()
            writer.write(b"data: [DONE]\n\n")
            await writer.drain()
            self.served_fully = True
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        writer.close()
        await watcher


async def _consume_n_then_cancel(model: ChatOpenAI, n: int) -> tuple[list[str], bool, dict]:
    """Consume n chunks via astream, then cancel. Returns (parts, cancelled, usage)."""
    parts: list[str] = []
    usage: dict[str, Any] = {}
    agen = model.astream([HumanMessage(content="say hi")])

    async def consume() -> None:
        async for chunk in agen:
            parts.append(chunk.content if isinstance(chunk.content, str) else "")
            if chunk.usage_metadata:
                usage.update(chunk.usage_metadata)

    task = asyncio.create_task(consume())
    while len(parts) < n:
        await asyncio.sleep(0.01)
    task.cancel()
    cancelled = False
    try:
        await task
    except asyncio.CancelledError:
        cancelled = True
    # Explicitly aclose the outer generator — mirrors what our seam will do.
    try:
        await agen.aclose()
    except Exception:
        pass
    return parts, cancelled, usage


async def _consume_all(model: ChatOpenAI) -> tuple[str, dict]:
    parts: list[str] = []
    usage: dict[str, Any] = {}
    async for chunk in model.astream([HumanMessage(content="say hi")]):
        parts.append(chunk.content if isinstance(chunk.content, str) else "")
        if chunk.usage_metadata:
            usage.update(chunk.usage_metadata)
    return "".join(parts), usage


async def t3_real_http() -> None:
    # 3a. cancel mid-stream → client connection must close (upstream abort).
    stub = SseStub(chunks=50, delay_s=0.15)
    port = await stub.start()
    model = ChatOpenAI(
        base_url=f"http://127.0.0.1:{port}/v1",
        api_key="spike",
        model="spike-model",
        model_kwargs={"response_format": {"type": "json_object"}},
    )
    t0 = time.monotonic()
    parts, cancelled, _usage = await _consume_n_then_cancel(model, 3)
    await stub.close()
    aborted = (
        stub.client_eof_at is not None and (stub.client_eof_at - t0) < 3.0
    ) or not stub.served_fully
    report(
        "http: cancel mid-stream aborts connection",
        cancelled and aborted,
        f"chunks={len(parts)} served_fully={stub.served_fully} "
        f"eof={None if stub.client_eof_at is None else round(stub.client_eof_at - t0, 2)}s",
    )

    # 3b. full consume → usage_metadata + request body shape.
    stub2 = SseStub(chunks=4, delay_s=0.02)
    port2 = await stub2.start()
    model2 = ChatOpenAI(
        base_url=f"http://127.0.0.1:{port2}/v1",
        api_key="spike",
        model="spike-model",
        stream_usage=True,
        model_kwargs={"response_format": {"type": "json_object"}},
    )
    text, usage = await _consume_all(model2)
    await stub2.close()
    report(
        "http: full text assembles",
        text.replace(" ", "") == "part0part1part2part3",
        f"text={text!r}",
    )
    report(
        "http: usage_metadata lands on chunks",
        usage.get("total_tokens") == 15,
        f"usage={usage}",
    )
    report(
        "http: request carries stream + usage opts",
        stub2.request_body.get("stream") is not False
        and stub2.request_body.get("stream_options", {}).get("include_usage") is True,
        f"stream={stub2.request_body.get('stream')} "
        f"opts={stub2.request_body.get('stream_options')}",
    )
    report(
        "http: response_format=json_object forwarded",
        stub2.request_body.get("response_format") == {"type": "json_object"},
        f"response_format={stub2.request_body.get('response_format')}",
    )


async def main() -> None:
    await t1_fake_stream_first_token()
    await t2_cancel_finally_runs()
    await t3_real_http()
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
