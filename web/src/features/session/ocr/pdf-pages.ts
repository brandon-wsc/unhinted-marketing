// pdf.js page renderer for the OCR path (ADR 0049 §1/§5). Dynamic-imported so
// the ~1 MB pdf.js chunk only loads when a needs_ocr row appears.

import type { PdfRenderer } from "./run";

// ~180 dpi balances chi_tra accuracy against canvas memory; the pixel cap
// keeps large page sizes inside iOS tab limits (0049 §5).
const TARGET_SCALE = 180 / 72;
const MAX_CANVAS_PIXELS = 16_000_000;

export async function makePdfjsRenderer(blob: Blob): Promise<PdfRenderer> {
  const [pdfjs, { default: PdfWorker }] = await Promise.all([
    import("pdfjs-dist"),
    import("pdfjs-dist/build/pdf.worker.min.mjs?worker"),
  ]);
  pdfjs.GlobalWorkerOptions.workerPort ??= new PdfWorker();
  const data = new Uint8Array(await blob.arrayBuffer());
  const loading = pdfjs.getDocument({ data });
  const doc = await loading.promise;

  return {
    totalPages: doc.numPages,
    async renderPage(n: number) {
      const page = await doc.getPage(n);
      const base = page.getViewport({ scale: 1 });
      const scale = Math.min(
        TARGET_SCALE,
        Math.sqrt(MAX_CANVAS_PIXELS / (base.width * base.height)),
      );
      const viewport = page.getViewport({ scale });
      const canvas = document.createElement("canvas");
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      await page.render({ canvas, viewport }).promise;
      page.cleanup();
      return canvas;
    },
    async close() {
      await loading.destroy();
    },
  };
}
