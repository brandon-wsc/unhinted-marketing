import { describe, expect, it, vi } from "vitest";
import type { OcrEngine, PdfRenderer } from "./run";
import { OcrAbortError, ocrAttachmentToTranscript } from "./run";

const fakeEngine = (texts: Record<number, string> = {}): OcrEngine => ({
  id: "fake-engine/1",
  recognize: vi.fn(async (image: unknown) => texts[(image as { page: number }).page] ?? ""),
  terminate: vi.fn(async () => {}),
});

const fakeRenderer = (pageNums: number[] = [1, 2, 3]): PdfRenderer => ({
  totalPages: pageNums.length,
  renderPage: vi.fn(async (page: number) => ({ page })),
  close: vi.fn(async () => {}),
});

describe("ocrAttachmentToTranscript (ADR 0049 §1)", () => {
  it("returns transcript pages in order, keeping blank pages for truthful numbering", async () => {
    const engine = fakeEngine({ 1: "第一頁", 3: "第三頁" });
    const renderer = fakeRenderer([1, 2, 3]);

    const pages = await ocrAttachmentToTranscript(new Blob(), {
      engine,
      makeRenderer: async () => renderer,
    });

    expect(pages).toEqual([
      { page: 1, text: "第一頁" },
      { page: 2, text: "" },
      { page: 3, text: "第三頁" },
    ]);
    expect(engine.recognize).toHaveBeenCalledTimes(3);
    expect(renderer.renderPage).toHaveBeenNthCalledWith(2, 2);
  });

  it("reports per-page progress with the renderer's total", async () => {
    const onProgress = vi.fn();
    await ocrAttachmentToTranscript(new Blob(), {
      engine: fakeEngine(),
      makeRenderer: async () => fakeRenderer([1, 2]),
      onProgress,
    });
    expect(onProgress).toHaveBeenNthCalledWith(1, { page: 1, total: 2 });
    expect(onProgress).toHaveBeenNthCalledWith(2, { page: 2, total: 2 });
  });

  it("terminates the engine and closes the renderer on success", async () => {
    const engine = fakeEngine();
    const renderer = fakeRenderer([1]);
    await ocrAttachmentToTranscript(new Blob(), {
      engine,
      makeRenderer: async () => renderer,
    });
    expect(engine.terminate).toHaveBeenCalledOnce();
    expect(renderer.close).toHaveBeenCalledOnce();
  });

  it("aborts between pages without finishing the document", async () => {
    const engine = fakeEngine({ 1: "第一頁" });
    const renderer = fakeRenderer([1, 2, 3]);
    const controller = new AbortController();
    const onProgress = vi.fn(() => controller.abort());

    await expect(
      ocrAttachmentToTranscript(new Blob(), {
        engine,
        makeRenderer: async () => renderer,
        onProgress,
        signal: controller.signal,
      }),
    ).rejects.toBeInstanceOf(OcrAbortError);
    expect(engine.recognize).toHaveBeenCalledTimes(1);
    expect(engine.terminate).toHaveBeenCalledOnce();
    expect(renderer.close).toHaveBeenCalledOnce();
  });

  it("propagates engine failures and still tears down", async () => {
    const engine = fakeEngine();
    (engine.recognize as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("wasm oom"));
    const renderer = fakeRenderer([1, 2]);

    await expect(
      ocrAttachmentToTranscript(new Blob(), {
        engine,
        makeRenderer: async () => renderer,
      }),
    ).rejects.toThrow("wasm oom");
    expect(engine.terminate).toHaveBeenCalledOnce();
    expect(renderer.close).toHaveBeenCalledOnce();
  });
});
