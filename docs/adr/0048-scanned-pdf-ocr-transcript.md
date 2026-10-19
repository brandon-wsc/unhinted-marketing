# ADR 0048 — Scanned-PDF OCR via client transcript

- **Status:** Proposed
- **Date:** 2026-10-19
- **Supersedes:** [ADR 0047](./0047-session-file-attachments.md) §10 in part — a no-text-layer PDF parks at `needs_ocr` instead of terminal `failed`; OCR leaves the §53 deferred non-goal list and lands as a client-first transcript path. Chunking, embedding, grounding and the object-key layout are unchanged.

## Context

ADR 0047 shipped document ingest as text-layer only: `pypdfium2` extracts per-page text, and a PDF with no extractable text (scans, image-only exports) fails permanently with 「讀唔到字」. Real HK corpora make that a mainstream case, not an edge — scanned menus, printed price lists, receipts and faxed supplier sheets are exactly the docs users want to ground drafts on.

The obvious fix (run OCR in the worker) fights the on-prem floor ([ADR 0047](./0047-session-file-attachments.md) Context): the server is a 2–4-core Celeron where the embedder already costs ~500 MB RSS and runs at ~4–12 chunks/s. Meanwhile the deployment is **asymmetric compute** — the machine uploading the scan is typically a marketing laptop that is an order of magnitude faster, already authenticated, already showing progress UI, and already holding the file.

So the split that makes sense is: **OCR is someone-else's problem (the client); the transcript is ours.** The server owns everything that must stay consistent — chunking (the embedder's own tokenizer, §4), `doc_profile`, grounding, scope checks — while the client contributes per-page text in a shape any OCR engine can produce, including a future worker-side one.

## Decision

1. **New status `needs_ocr` replaces `failed` for no-text documents.** Ingest that finds a document with no extractable text parks the row at `needs_ocr` with the honest error text (「讀唔到字」— OCR path pending) and a minimal profile carrying the page count (`{"pages": N, "ocr": "pending"}`) so the UI can say how much work is involved. `failed` remains for corrupt/encrypted files and transcripts that yield no chunks — the job still succeeds; a parse fault never burns retries (0047 §10). `ck_attachments_status` and `schemas.session.AttachmentStatus` gain the value via a normal Alembic revision that amends the CHECK constraint.
2. **The transcript contract is the seam.** `POST /api/attachments/{id}/transcript` accepts

   ```json
   { "engine": "tesseract.js", "pages": [ { "page": 1, "text": "…" } ] }
   ```

   Only `needs_ocr` rows accept a transcript (others → 409); unknown / cross-tenant / out-of-scope ids → 404, same existence-never-leaks rule as download/save (0047 §14). Pages are validated against the profile's page count (out-of-range → 400); total payload is capped (~2 MB text, ~500 pages) since the client's JSON is untrusted input — same posture as upload bytes. `engine` is recorded as provenance metadata, never trusted.
3. **A transcript feeds the same ingest path, not a parallel one.** The endpoint stores the transcript under `attachments/{id}/transcript.json` in the media object store and enqueues a fresh `attachment_ingest` job (dedupe key `attachment_ingest:{id}:transcript`). The worker parses the transcript into `DocumentBlock`s (paragraph per blank-line run, `page` from the entry), then runs the unchanged `chunk_blocks → doc_profile → ready_lexical → embed → ready` pipeline. One chunker, one tokenizer, one honest-status flow — `partial` on over-cap applies identically.
4. **Transcripts are persisted, not just chunks.** `transcript.json` is the canonical parsed text for OCR'd docs: a future re-chunk (chunker change) or re-embed (model change per 0047 §9) reuses it and never re-OCRs. It follows the original bytes' lifecycle — same `attachments/` prefix, same join-table GC, never served by `GET /api/media/{key}`.
5. **`doc_profile` carries OCR provenance.** On transcript ingest the profile gains `"ocr": true` plus `"engine"` — a grounding/UI honesty marker, not a trust signal. A slice built from OCR text should be quotable with that caveat.
6. **Client-side first; engine is not locked.** The web client renders pages (pdf.js) and OCRs them in-browser — leading candidate `tesseract.js` (`chi_tra`, Apache-2.0, WASM/CPU, workers, ~MB-scale traineddata served from our own origin — `langPath` must not point at a CDN on-prem). Accuracy on real HK scans is a **ship gate**: if `chi_tra` output is too corrupt to ground against, the fallback is onnxruntime-web with a PP-OCR CHT recognition model (can reach WebGPU), not a contract change. Either way the contract above is what ships.
7. **Worker OCR is the same contract, second producer — deferred.** A future `attachment_ocr` job (RapidOCR / PP-OCR `chinese_cht` on ONNXRuntime — Apache-2.0, wheels-only, runtime already in the tree via fastembed) renders no-text pages via pdfium and writes `transcript.json` itself. It exists for paths with no browser: API/automation uploads, bulk import, rescuing `needs_ocr` rows whose client never came back. It is **not** v1 — triggers are a headless ingest path landing or telemetry showing abandoned `needs_ocr` rows.
8. **Hybrid PDFs stay whole-document v1.** A PDF whose *some* pages have a text layer still ingests the text pages and silently drops the image pages (today's behavior); a PDF with *no* text layer goes `needs_ocr` and the client OCRs the whole document. Per-page merge (pdfium text where present, OCR where absent) is a known gap deferred until the real corpus says it matters.
9. **Honesty posture is unchanged.** `needs_ocr` is a state, not an error; the UI polls it via the existing `GET …/attachments` and offers the browser-OCR action chip (same spirit as ADR 0047 §8 ambiguity chips). A transcript that chunks to nothing still fails with readable error. OCR output is treated as noisy text — `grounding_check` sees it like any other chunk; the `ocr` profile flag is how the UI can caveat it.

## Consequences

- New surface: `POST /api/attachments/{id}/transcript` + `AttachmentTranscriptRequest`/`TranscriptPage` schemas; `needs_ocr` in `AttachmentStatus` + `ck_attachments_status` (new Alembic revision); `transcript.json` object keys; `NoExtractableTextError` (carries `page_count`) as a `DocumentParseError` subclass so ingest can park instead of fail; `parse_transcript(pages) -> ParsedDocument` seam beside `parse_document`.
- Web picks up `pdfjs-dist` + an OCR engine dep; OCR work happens in a Web Worker off the chat UI thread; per-page progress is natural since the client owns the loop. `SharedArrayBuffer` threading is a bonus, not a requirement — the SPA works without COOP/COEP (single-threaded WASM is just slower).
- Headless hole is explicit: a scan uploaded outside a browser session sits at `needs_ocr` until a client appears or decision §7's worker path lands. That is the honest version of today — the row was already `failed` before.
- Mobile clients can participate but aren't the target form factor (iOS tab memory caps ~200 dpi rendering; low-end Androids thermal-throttle on long docs). Feature-detect `WebAssembly`/SIMD and let a weak client still finish slowly — the transcript endpoint doesn't care who produced it.
- Re-ingest without a stored transcript for a `needs_ocr` row is a no-op (stays parked); with a transcript it re-chunks locally — no OCR engine on the server path at all.
- Deferred to the worker-OCR ADR when it lands: engine model pinning, ONNX thread caps next to the embedder, per-page hybrid merge (§8), a 「server 慢慢搞」 rescue action for weak clients.
- Eval: before enabling the client path in a release, run a fixed corpus of real HK scans through the chosen engine and eyeball zh-HK accuracy — a wrong-char transcript silently corrupts every chunk, which is worse than a `needs_ocr` park.
