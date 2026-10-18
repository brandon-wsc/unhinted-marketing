"""Structure-aware chunking of parsed document blocks (ADR 0047 §4).

A chunk never spans two headings or a table boundary. The budget bounds the
embed input ``"[heading_path] " + text`` in ``counter`` units — ``counter``
defaults to ``len`` as the char fallback for the embedder tokenizer.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from internal.memory.document_parse import DocumentBlock

# Sentence ends: full/half-width 。！？；!?; runs, Latin "." before whitespace,
# line breaks, and emoji runs (HK copy often breaks on emoji/space).
_SEPARATOR_RE = re.compile(
    r"[。！？；!?;\n]+"
    r"|[.?](?=\s)"
    r"|[\U0001f300-\U0001faff☀-➿]+"
)


@dataclass
class ChunkConfig:
    budget: int = 110
    max_chunks: int = 150
    overlap_sentences: int = 1
    counter: Callable[[str], int] | None = None


@dataclass
class Chunk:
    index: int
    text: str
    kind: str  # "text" | "table"
    heading_path: str = ""
    page_start: int | None = None
    page_end: int | None = None


@dataclass
class ChunkResult:
    chunks: list[Chunk] = field(default_factory=list)
    truncated: bool = False


def embed_text_for(chunk: Chunk) -> str:
    if chunk.heading_path:
        return f"[{chunk.heading_path}] {chunk.text}"
    return chunk.text


def _sentence_pieces(text: str) -> list[str]:
    """Split text at sentence separators; separators stay with the sentence.

    Whitespace-only fragments fold into the next piece so spacing survives.
    """
    raw: list[str] = []
    start = 0
    for match in _SEPARATOR_RE.finditer(text):
        raw.append(text[start : match.end()])
        start = match.end()
    raw.append(text[start:])

    pieces: list[str] = []
    pending = ""
    for piece in raw:
        if piece.strip():
            pieces.append(pending + piece)
            pending = ""
        else:
            pending += piece
    if pending and pieces:
        pieces[-1] += pending
    return pieces


def _char_slices(text: str, allowed: int, counter: Callable[[str], int]) -> list[str]:
    """Split an oversized sentence on chars so every slice fits the budget."""
    text = text.strip()
    slices: list[str] = []
    buf = ""
    for char in text:
        if buf and counter(buf + char) > allowed:
            slices.append(buf)
            buf = ""
        buf += char
    if buf:
        slices.append(buf)
    return slices


def _paragraph_chunk_texts(
    text: str,
    allowed: int,
    counter: Callable[[str], int],
    overlap_sentences: int,
) -> list[str]:
    """Pack sentences greedily; overlap carries previous sentence(s) forward.

    Carry is sentence-aligned only, never a char slice, and is dropped when it
    leaves no room for new text within the budget.
    """
    pieces: list[str] = []
    complete: list[bool] = []
    for piece in _sentence_pieces(text):
        if counter(piece.strip()) <= allowed:
            pieces.append(piece)
            complete.append(True)
        else:
            for fragment in _char_slices(piece, allowed, counter):
                pieces.append(fragment)
                complete.append(False)

    chunk_texts: list[str] = []
    carry: str | None = None
    index = 0
    while index < len(pieces):
        parts: list[str] = []
        used = 0
        if carry is not None and counter(carry + pieces[index]) <= allowed:
            parts.append(carry)
            used += counter(carry)
        carry = None
        start = index
        while index < len(pieces) and used + counter(pieces[index]) <= allowed:
            parts.append(pieces[index])
            used += counter(pieces[index])
            index += 1
        if index == start:  # defensive: always make progress
            parts.append(pieces[index])
            index += 1
        text_out = "".join(parts).strip()
        if text_out:
            chunk_texts.append(text_out)
        if overlap_sentences > 0 and index < len(pieces) and complete[index - 1]:
            emitted = pieces[start:index]
            carry = "".join(emitted[-overlap_sentences:])
    return chunk_texts


def _table_chunk_texts(
    block: DocumentBlock, allowed: int, counter: Callable[[str], int]
) -> list[str]:
    """Keep a table atomic within budget, else split by row group.

    Every row-group chunk repeats the header row. No overlap in or out.
    """
    if not block.rows:
        return _paragraph_chunk_texts(block.text, allowed, counter, overlap_sentences=0)
    lines = ["| " + " | ".join(row) + " |" for row in block.rows]
    if counter("\n".join(lines)) <= allowed:
        return ["\n".join(lines)]

    header_line, row_lines = lines[0], lines[1:]
    if not row_lines:
        return ["\n".join(lines)]

    chunks: list[str] = []
    current = [header_line]
    used = counter(header_line)
    for line in row_lines:
        cost = counter(line) + 1  # +1 approximates the joining newline
        if current[1:] and used + cost > allowed:
            chunks.append("\n".join(current))
            current = [header_line]
            used = counter(header_line)
        if used + cost > allowed:
            # A lone row bigger than the budget can't ride whole — the
            # embedder truncates it. Bounded continuations repeat the header.
            limit = max(1, allowed - used - 1)
            chunks.extend(
                header_line + "\n" + piece for piece in _char_slices(line, limit, counter)
            )
            continue
        current.append(line)
        used += cost
    chunks.append("\n".join(current))
    return [c for c in chunks if c.strip()]


def _heading_path_update(stack: list[tuple[int, str]], block: DocumentBlock) -> str:
    level = block.level or 1
    while stack and stack[-1][0] >= level:
        stack.pop()
    stack.append((level, block.text))
    return " > ".join(title for _, title in stack)


def chunk_blocks(blocks: Sequence[DocumentBlock], config: ChunkConfig | None = None) -> ChunkResult:
    config = config or ChunkConfig()
    counter = config.counter or len
    chunks: list[Chunk] = []
    truncated = False
    stack: list[tuple[int, str]] = []
    path = ""

    def emit(text: str, kind: str, block: DocumentBlock) -> bool:
        if len(chunks) >= config.max_chunks:
            return False
        chunks.append(
            Chunk(
                index=len(chunks),
                text=text,
                kind=kind,
                heading_path=path,
                page_start=block.page,
                page_end=block.page,
            )
        )
        return True

    for block in blocks:
        if block.kind == "heading":
            path = _heading_path_update(stack, block)
            continue
        prefix = f"[{path}] " if path else ""
        allowed = max(1, config.budget - counter(prefix))
        if block.kind == "table":
            texts = _table_chunk_texts(block, allowed, counter)
            kind = "table"
        else:
            texts = _paragraph_chunk_texts(block.text, allowed, counter, config.overlap_sentences)
            kind = "text"
        for text_out in texts:
            if not emit(text_out, kind, block):
                truncated = True
                break
        if truncated:
            break

    return ChunkResult(chunks=chunks, truncated=truncated)
