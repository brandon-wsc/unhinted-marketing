"""Unit tests for ADR 0047 document chunking (blocks -> bounded chunks).

Production module under test: internal/memory/document_chunk.py (not yet written).
Imports stay inside helpers/test bodies so collection succeeds while the module
is missing — every test should fail, not error at import time.

API contract exercised here:
- chunk_blocks(blocks, config: ChunkConfig | None = None) -> ChunkResult
- ChunkConfig(budget=110, max_chunks=150, overlap_sentences=1, counter=None)
  `budget` bounds the embed input ("[heading_path] " + text) in `counter` units;
  `counter` defaults to len() (char fallback for the embedder tokenizer).
- Chunk: index, text, kind ("text" | "table"), heading_path, page_start, page_end
- ChunkResult: chunks (ordered), truncated (True when max_chunks was hit)
- embed_text_for(chunk) -> "[heading_path] " + text (bare text when no path)
"""

from __future__ import annotations


def _parse_blocks(md: str):
    from internal.memory.document_parse import parse_document

    return parse_document("doc.md", md.encode()).blocks


def _chunk(md: str, **config_kwargs):
    from internal.memory.document_chunk import ChunkConfig, chunk_blocks

    return chunk_blocks(_parse_blocks(md), config=ChunkConfig(counter=len, **config_kwargs))


def _embed_text(chunk) -> str:
    from internal.memory.document_chunk import embed_text_for

    return embed_text_for(chunk)


def _sentences(text: str) -> list[str]:
    return [s + "。" for s in text.split("。") if s]


def test_chunk_never_spans_two_headings() -> None:
    md = (
        "## 甲部\n\n甲一句子。甲二句子。甲三句子。甲四句子。\n\n"
        "## 乙部\n\n乙一句子。乙二句子。\n"
    )
    result = _chunk(md, budget=24)
    assert len(result.chunks) >= 3
    assert not any("甲" in c.text and "乙" in c.text for c in result.chunks)
    for chunk in result.chunks:
        if "甲" in chunk.text:
            assert chunk.heading_path == "甲部"
        else:
            assert chunk.heading_path == "乙部"


def test_overlap_carries_previous_sentence() -> None:
    md = "## 細節\n\n第一句話甲。第二句話乙。第三句話丙。第四句話丁。第五句話戊。第六句話己。\n"
    result = _chunk(md, budget=30)
    assert len(result.chunks) >= 2
    first, second = result.chunks[0], result.chunks[1]
    assert _sentences(second.text)[0] == _sentences(first.text)[-1]


def test_no_overlap_across_heading_boundary() -> None:
    md = (
        "## 前段\n\n前句子一。前句子二。前句子三。前句子四。前句子五。前句子六。\n\n"
        "## 後段\n\n後句子一。\n"
    )
    result = _chunk(md, budget=25)
    assert len(result.chunks) >= 3
    tail = [c for c in result.chunks if c.heading_path == "後段"]
    assert len(tail) == 1
    assert tail[0].text == "後句子一。"


def test_chunks_respect_length_budget() -> None:
    body = "".join(f"第{i}句測試文字。" for i in range(12))
    result = _chunk(f"## 說明\n\n{body}\n", budget=40)
    assert len(result.chunks) >= 2
    for chunk in result.chunks:
        assert chunk.text.strip()
        assert len(_embed_text(chunk)) <= 40


def test_heading_path_nested_and_embed_input() -> None:
    md = "# 產品目錄\n\n## 優惠詳情\n\n買一送一優惠。\n"
    result = _chunk(md, budget=80)
    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.heading_path == "產品目錄 > 優惠詳情"
    assert "產品目錄" not in chunk.text and "優惠詳情" not in chunk.text
    assert _embed_text(chunk) == "[產品目錄 > 優惠詳情] " + chunk.text


def test_heading_path_single_level() -> None:
    result = _chunk("# 產品目錄\n\n只有一層。\n", budget=80)
    chunk = result.chunks[0]
    assert chunk.heading_path == "產品目錄"
    assert _embed_text(chunk) == "[產品目錄] " + chunk.text


def test_embed_text_without_heading_has_no_prefix() -> None:
    result = _chunk("沒有標題的段落。\n", budget=80)
    chunk = result.chunks[0]
    assert chunk.heading_path == ""
    assert _embed_text(chunk) == chunk.text


def test_table_within_cap_is_single_chunk() -> None:
    md = (
        "## 價目\n\n簡介一句。\n\n"
        "| 名稱 | 價格 |\n"
        "| --- | --- |\n"
        "| 奶茶 | 48 |\n"
        "| 咖啡 | 52 |\n\n"
        "表後補充。\n"
    )
    result = _chunk(md, budget=80)
    tables = [c for c in result.chunks if c.kind == "table"]
    assert len(tables) == 1
    table = tables[0]
    assert "名稱" in table.text and "奶茶" in table.text and "咖啡" in table.text
    assert "簡介" not in table.text and "補充" not in table.text
    assert "名稱" in table.text.splitlines()[0]
    assert result.chunks[-1].text == "表後補充。"


def test_oversized_table_splits_by_row_group_repeating_header() -> None:
    rows = "\n".join(f"| 產品{i:02d} | {i} |" for i in range(10))
    md = f"## 價目\n\n| 名稱 | 價格 |\n| --- | --- |\n{rows}\n"
    result = _chunk(md, budget=60)
    tables = [c for c in result.chunks if c.kind == "table"]
    assert len(tables) >= 2
    for chunk in tables:
        first_line = chunk.text.splitlines()[0]
        assert "名稱" in first_line and "價格" in first_line
        assert len(_embed_text(chunk)) <= 60
    joined = "".join(c.text for c in tables)
    for i in range(10):
        assert f"產品{i:02d}" in joined


def test_cjk_paragraph_splits_near_char_budget_not_byte_budget() -> None:
    body = "".join(f"第{i:02d}句係密集中文內容測試。" for i in range(8))
    result = _chunk(f"## 內容\n\n{body}\n", budget=100)
    assert 2 <= len(result.chunks) <= 3
    for chunk in result.chunks:
        assert len(chunk.text) <= 100


def test_unbroken_long_text_falls_back_to_char_split() -> None:
    body = "無句讀的連續中文文字" * 6
    result = _chunk(f"## 密集\n\n{body}\n", budget=30)
    assert len(result.chunks) >= 2
    assert all(len(c.text) <= 30 for c in result.chunks)


def test_latin_sentence_separators_split_cleanly() -> None:
    md = "## Spec\n\nAlpha one. Beta two! Gamma three? Delta four.\n"
    result = _chunk(md, budget=30)
    assert len(result.chunks) >= 2
    for chunk in result.chunks:
        assert chunk.text.rstrip()[-1] in ".!?"


def test_chunk_cap_truncates_and_flags() -> None:
    body = "".join(f"句{i:02d}測試內容。" for i in range(30))
    result = _chunk(f"## 長文\n\n{body}\n", budget=40, max_chunks=5)
    assert len(result.chunks) == 5
    assert result.truncated is True


def test_chunk_cap_not_flagged_when_under() -> None:
    result = _chunk("## 短文\n\n一句。\n", budget=40, max_chunks=5)
    assert result.truncated is False
    assert len(result.chunks) == 1


def test_parse_then_chunk_end_to_end() -> None:
    from internal.memory.document_chunk import ChunkConfig, chunk_blocks
    from internal.memory.document_parse import parse_document

    md = "# 產品目錄\n\n目錄簡介段落。\n\n## 優惠詳情\n\n優惠內容段落。\n"
    doc = parse_document("catalog.md", md.encode())
    result = chunk_blocks(doc.blocks, config=ChunkConfig(counter=len, budget=80))
    chunks = result.chunks
    assert len(chunks) == 2
    assert [c.index for c in chunks] == [0, 1]
    assert chunks[0].kind == "text" and chunks[0].heading_path == "產品目錄"
    assert chunks[1].kind == "text" and chunks[1].heading_path == "產品目錄 > 優惠詳情"
    assert all(c.page_start is None and c.page_end is None for c in chunks)
    assert result.truncated is False
