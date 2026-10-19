# ADR 0049 — Browser OCR client path for `needs_ocr` attachments

- **Status:** Proposed
- **Date:** 2026-10-19
- **Supersedes:** nothing — this is the client half that [ADR 0048](./0048-scanned-pdf-ocr-transcript.md) §6 deliberately left open (transcript contract is unchanged).

## Context

ADR 0048 shipped the server contract: a no-text PDF parks at `needs_ocr`, and `POST /api/attachments/{id}/transcript` resumes normal ingest from client-supplied per-page text. What it did *not* pin is the concrete browser stack — which renderer, which engine, where traineddata comes from on-prem, or how progress/cancel behaves. This ADR pins those.

The deployment reality stays asymmetric compute (0048 Context): the Celeron server must not OCR, the marketing laptop can. But the user never sees "needs_ocr" as an instruction — they see a file that "didn't work". The UX has to make the parked state actionable in one click, show real progress (a 20-page scan takes tens of seconds), and leave the row recoverable when OCR itself fails.

## Decision

1. **`pdfjs-dist` renders, `tesseract.js` recognizes, both behind a seam.** `ocr/run.ts` is a pure orchestration function — `ocrAttachmentToTranscript(blob, { renderPages, engine, onProgress, signal }) → TranscriptPageInput[]` — that never imports pdf.js or tesseract.js itself. `ocr/pdf-pages.ts` (pdf.js → canvas per page) and `ocr/tesseract.ts` (worker lifecycle, `recognize(image) → text`, `terminate()`) are the only files that touch those libs. The engine seam is the eval escape hatch (0048 §6): swapping to onnxruntime-web + PP-OCR CHT is a new engine module, not a rewrite of the flow.
2. **Traineddata is vendored, never CDN.** `chi_tra` int-quantized traineddata (`@tesseract.js-data/chi_tra` `4.0.0_best_int`, ~1.7 MB gz) ships at `web/public/tessdata/chi_tra.traineddata.gz` and `createWorker` gets `langPath` pointing at our own origin. On-prem installs must not phone tessdata.projectnaptha.com. If eval wants the float model or a different lang, the vendored file swaps — the npm package stays out of the dependency tree (the vendored file is self-describing; the package tarball is just transport).
3. **OCR runs on user action, never automatically.** A `needs_ocr` staged row renders its chip with an explicit OCR action (same spirit as the ambiguity chips, 0048 §9); message digests offer it through the existing dropdown. Auto-running would burn the user's CPU on files they may be about to delete.
4. **Whole-document, all-or-nothing transcript.** The client iterates pages 1..N, collects `{page, text}` per page (blank pages included — they keep numbering truthful and the server drops them at block time anyway), then POSTs once. No incremental upload: the endpoint validates the full set against the profile page count, and a partial transcript is indistinguishable from a truncated one. Progress is per-page (`OCR 3/20`); cancel/abandon aborts the run and leaves the row parked at `needs_ocr` — park is the safe state, matching the no-auto-retry posture.
5. **One engine instance per run, pages sequential.** Tesseract internally threads when `SharedArrayBuffer` is available and runs single-threaded without it (no COOP/COEP requirement, 0048 consequence). Rendering is `await`-per-page so peak memory is one canvas (~35 MB at cap) — iOS tab limits drive a ~180 dpi render target with a pixel ceiling rather than 300 dpi. `hardwareConcurrency` is not consulted for a worker pool in v1 — sequential pages keep the state machine and cancel semantics trivial.
6. **Failure is honest and parked, not failed.** Engine load failure, render failure, or a transcript POST rejection restores the row to `needs_ocr` with a readable note — it never flips to `failed` (corrupt-file semantics) and never auto-retries. After a successful POST the row goes back to `pending` and the existing ingest poll (pending/ready_lexical → ready/failed) owns the rest — no second status loop.
7. **Provenance is the engine's own string.** `engine` sent with the transcript is e.g. `"tesseract.js/7 chi_tra"` — recorded into `doc_profile`, never trusted (0048 §5).

## Consequences

- New deps: `pdfjs-dist` (renderer only — no viewer, no text layer use) and `tesseract.js`. Both are `await import()`-ed inside the ocr modules, so they land in lazy chunks — the chat bundle pays nothing until a `needs_ocr` row appears. One vendored asset (`public/tessdata/chi_tra.traineddata.gz`, ~1.7 MB).
- New module `web/src/features/session/ocr/` (`run.ts`, `pdf-pages.ts`, `tesseract.ts`) + `use-attachment-ocr.ts` hook; `apiPostAttachmentTranscript` in `api.ts`; the staged-row chip gains an OCR affordance and per-page progress text; digest dropdown gains the same action. New i18n keys under `chat.attach.*`.
- `StagedAttachment` gains no new fields — OCR progress is hook state keyed by `localId`, not part of the row (the row keeps mirroring server truth).
- Backend is untouched: no new endpoints, no schema, no migration. The poll loop, GC, and transcript persistence all reuse 0048.
- Eval gate unchanged (0048 consequence): real-HK-scan accuracy decides whether `tesseract.js`+`chi_tra` stays default or the seam swaps in onnxruntime-web. That gate gates *enabling the feature in a release*, not this merge.
- Mobile: participates but isn't the target (180 dpi cap, sequential pages — a 3-page receipt is fine, a 60-page scan is a desktop job).
