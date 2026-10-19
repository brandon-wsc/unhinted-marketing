// Default production deps for the OCR run (ADR 0049 §1). Kept in one module so
// tests can vi.mock a single seam and exercise the real orchestration in run.ts
// against fake engines/renderers — no WASM or pdf.js in unit tests.

import { makePdfjsRenderer } from "./pdf-pages";
import type { OcrEngine, PdfRendererFactory } from "./run";
import { createTesseractEngine } from "./tesseract";

export type OcrDeps = {
  makeEngine: () => Promise<OcrEngine>;
  makeRenderer: PdfRendererFactory;
};

export const defaultOcrDeps: OcrDeps = {
  makeEngine: createTesseractEngine,
  makeRenderer: makePdfjsRenderer,
};
