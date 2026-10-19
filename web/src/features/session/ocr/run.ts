// OCR orchestration seam (ADR 0049 §1): pure TS, no pdf.js/tesseract imports —
// the engine and renderer are injected so tests and a future engine swap need
// no WASM/browser machinery.

import type { components } from "../generated/api";

export type TranscriptPage = components["schemas"]["TranscriptPageInput"];

export type OcrProgress = { page: number; total: number };

export interface OcrEngine {
  /** Provenance string recorded in doc_profile, e.g. "tesseract.js/7 chi_tra". */
  id: string;
  recognize(image: unknown): Promise<string>;
  terminate(): Promise<void>;
}

export interface PdfRenderer {
  totalPages: number;
  /** Returns the engine-consumable image for a 1-based page number. */
  renderPage(page: number): Promise<unknown>;
  close(): Promise<void>;
}

export type PdfRendererFactory = (blob: Blob) => Promise<PdfRenderer>;

/** Thrown when the AbortSignal fires; callers treat it as user cancel, not failure. */
export class OcrAbortError extends Error {
  constructor() {
    super("ocr_aborted");
    this.name = "OcrAbortError";
  }
}

const throwIfAborted = (signal?: AbortSignal) => {
  if (signal?.aborted) throw new OcrAbortError();
};

/**
 * Render every page and recognize it sequentially (0049 §4/§5): pages stay in
 * order, blanks are kept so numbering stays truthful, and the transcript is
 * submitted all-or-nothing by the caller. Owns teardown of both the renderer
 * and the engine.
 */
export async function ocrAttachmentToTranscript(
  blob: Blob,
  deps: {
    engine: OcrEngine;
    makeRenderer: (blob: Blob) => Promise<PdfRenderer>;
    onProgress?: (p: OcrProgress) => void;
    signal?: AbortSignal;
  },
): Promise<TranscriptPage[]> {
  const { engine, makeRenderer, onProgress, signal } = deps;
  throwIfAborted(signal);
  const renderer = await makeRenderer(blob);
  try {
    const pages: TranscriptPage[] = [];
    for (let page = 1; page <= renderer.totalPages; page++) {
      throwIfAborted(signal);
      const image = await renderer.renderPage(page);
      throwIfAborted(signal);
      const text = await engine.recognize(image);
      pages.push({ page, text });
      onProgress?.({ page, total: renderer.totalPages });
    }
    return pages;
  } finally {
    await Promise.allSettled([renderer.close(), engine.terminate()]);
  }
}
