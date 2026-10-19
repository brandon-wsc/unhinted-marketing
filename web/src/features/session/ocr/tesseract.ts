// tesseract.js engine for the OCR path (ADR 0049 §1/§2). Dynamic-imported so
// the WASM stack only loads when a needs_ocr row triggers it. Everything the
// worker needs — script, wasm core, traineddata — is served from our own
// origin; the library's CDN defaults (jsdelivr) are all overridden for on-prem.

import type { OcrEngine } from "./run";

const LANG = "chi_tra";
// Vendored in public/ — langPath is a directory prefix, so a hashed ?url asset
// would not resolve; public/ keeps the filename verbatim.
const LANG_PATH = "/tessdata";

const pickCorePath = async (): Promise<string> => {
  const [{ simd, relaxedSimd }, relaxedUrl, simdUrl, plainUrl] = await Promise.all([
    import("wasm-feature-detect"),
    import("tesseract.js-core/tesseract-core-relaxedsimd-lstm.wasm.js?url"),
    import("tesseract.js-core/tesseract-core-simd-lstm.wasm.js?url"),
    import("tesseract.js-core/tesseract-core-lstm.wasm.js?url"),
  ]);
  if (await relaxedSimd()) return relaxedUrl.default;
  if (await simd()) return simdUrl.default;
  return plainUrl.default;
};

export async function createTesseractEngine(): Promise<OcrEngine> {
  const [{ createWorker }, { default: workerPath }, corePath] = await Promise.all([
    import("tesseract.js"),
    import("tesseract.js/dist/worker.min.js?url"),
    pickCorePath(),
  ]);
  const worker = await createWorker(LANG, undefined, {
    workerPath,
    corePath,
    langPath: LANG_PATH,
    gzip: true,
  });
  return {
    id: `tesseract.js/7 ${LANG}`,
    async recognize(image) {
      const { data } = await worker.recognize(image as HTMLCanvasElement);
      return data.text;
    },
    async terminate() {
      await worker.terminate();
    },
  };
}
