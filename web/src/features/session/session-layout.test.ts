import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getSessionChatRatio,
  SESSION_CHAT_RATIO_KEY,
  SESSION_PANE,
  SESSION_SPLIT_PANEL,
  sessionChatRatioFromLayout,
  sessionChatRatioFromPx,
  sessionHistoryWidth,
  sessionLayoutMode,
  sessionLeftoverWidth,
  sessionSplitMinWidth,
  sessionSplitPercents,
  sessionSplitSizes,
  setSessionChatRatio,
} from "@/features/session/session-layout";

describe("sessionSplitMinWidth", () => {
  it("sums history + chat when preview is not ready", () => {
    expect(sessionSplitMinWidth({ historyCollapsed: false, previewReady: false })).toBe(
      SESSION_PANE.historyExpanded + SESSION_PANE.chatMin,
    );
    expect(sessionSplitMinWidth({ historyCollapsed: true, previewReady: false })).toBe(
      SESSION_PANE.historyCollapsed + SESSION_PANE.chatMin,
    );
  });

  it("adds preview min when a draft is ready", () => {
    expect(sessionSplitMinWidth({ historyCollapsed: false, previewReady: true })).toBe(
      SESSION_PANE.historyExpanded + SESSION_PANE.chatMin + SESSION_PANE.previewMin,
    );
  });
});

describe("sessionLayoutMode", () => {
  it("returns split at or above the content threshold", () => {
    const input = { historyCollapsed: false, previewReady: true };
    const min = sessionSplitMinWidth(input);
    expect(sessionLayoutMode(min, input)).toBe("split");
    expect(sessionLayoutMode(min - 1, input)).toBe("paged");
  });
});

describe("sessionHistoryWidth / leftover", () => {
  it("maps collapse to pane constants", () => {
    expect(sessionHistoryWidth(false)).toBe(SESSION_PANE.historyExpanded);
    expect(sessionHistoryWidth(true)).toBe(SESSION_PANE.historyCollapsed);
  });

  it("subtracts history from the shell", () => {
    expect(sessionLeftoverWidth(1440, false)).toBe(1440 - SESSION_PANE.historyExpanded);
    expect(sessionLeftoverWidth(1440, true)).toBe(1440 - SESSION_PANE.historyCollapsed);
    expect(sessionLeftoverWidth(10, false)).toBe(0);
  });
});

describe("sessionSplitSizes", () => {
  it("gives leftover to chat when preview is off", () => {
    expect(sessionSplitSizes(800, 0.4, false)).toEqual({ chatPx: 800, previewPx: 0 });
  });

  it("clamps both panes to mins at the split threshold leftover", () => {
    const leftover =
      sessionSplitMinWidth({ historyCollapsed: false, previewReady: true }) -
      SESSION_PANE.historyExpanded;
    expect(leftover).toBe(SESSION_PANE.chatMin + SESSION_PANE.previewMin);
    expect(sessionSplitSizes(leftover, SESSION_PANE.chatDefaultRatio, true)).toEqual({
      chatPx: SESSION_PANE.chatMin,
      previewPx: SESSION_PANE.previewMin,
    });
  });

  it("uses 0.4 of leftover when both mins already fit", () => {
    const leftover = 1160;
    const sizes = sessionSplitSizes(leftover, SESSION_PANE.chatDefaultRatio, true);
    expect(sizes.chatPx).toBe(leftover * SESSION_PANE.chatDefaultRatio);
    expect(sizes.previewPx).toBe(leftover - sizes.chatPx);
    expect(sizes.chatPx).toBeGreaterThanOrEqual(SESSION_PANE.chatMin);
    expect(sizes.previewPx).toBeGreaterThanOrEqual(SESSION_PANE.previewMin);
  });

  it("falls back to the default ratio when the stored value is unusable", () => {
    const leftover = 1160;
    expect(sessionSplitSizes(leftover, Number.NaN, true)).toEqual(
      sessionSplitSizes(leftover, SESSION_PANE.chatDefaultRatio, true),
    );
    expect(sessionSplitSizes(leftover, 0, true)).toEqual(
      sessionSplitSizes(leftover, SESSION_PANE.chatDefaultRatio, true),
    );
    expect(sessionSplitSizes(leftover, 1, true)).toEqual(
      sessionSplitSizes(leftover, SESSION_PANE.chatDefaultRatio, true),
    );
  });
});

describe("sessionSplitPercents", () => {
  it("is 50/50 at the exact min leftover", () => {
    const leftover = SESSION_PANE.chatMin + SESSION_PANE.previewMin;
    const pct = sessionSplitPercents(leftover, 0.4, true);
    expect(pct.chatPct).toBe(50);
    expect(pct.previewPct).toBe(50);
    expect(pct.chatMinPct).toBe(50);
    expect(pct.previewMinPct).toBe(50);
  });
});

describe("sessionChatRatioFromLayout", () => {
  it("uses chat share of chat+preview flexGrow", () => {
    expect(
      sessionChatRatioFromLayout({
        [SESSION_SPLIT_PANEL.chat]: 40,
        [SESSION_SPLIT_PANEL.preview]: 60,
      }),
    ).toBeCloseTo(0.4);
  });

  it("falls back when both grows are empty", () => {
    expect(sessionChatRatioFromLayout({})).toBe(SESSION_PANE.chatDefaultRatio);
  });
});

describe("sessionChatRatioFromPx", () => {
  it("returns chat / leftover", () => {
    expect(sessionChatRatioFromPx(464, 1160)).toBeCloseTo(0.4);
  });

  it("falls back when leftover is empty", () => {
    expect(sessionChatRatioFromPx(100, 0)).toBe(SESSION_PANE.chatDefaultRatio);
  });
});

describe("chatRatio persist", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("defaults when unset", () => {
    expect(getSessionChatRatio()).toBe(SESSION_PANE.chatDefaultRatio);
  });

  it("round-trips a valid ratio", () => {
    setSessionChatRatio(0.35);
    expect(localStorage.getItem(SESSION_CHAT_RATIO_KEY)).toBe("0.35");
    expect(getSessionChatRatio()).toBe(0.35);
  });

  it("rejects 0, 1, and non-finite stored values", () => {
    localStorage.setItem(SESSION_CHAT_RATIO_KEY, "0");
    expect(getSessionChatRatio()).toBe(SESSION_PANE.chatDefaultRatio);
    localStorage.setItem(SESSION_CHAT_RATIO_KEY, "1");
    expect(getSessionChatRatio()).toBe(SESSION_PANE.chatDefaultRatio);
    localStorage.setItem(SESSION_CHAT_RATIO_KEY, "nope");
    expect(getSessionChatRatio()).toBe(SESSION_PANE.chatDefaultRatio);
  });

  it("swallows localStorage errors", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(getSessionChatRatio()).toBe(SESSION_PANE.chatDefaultRatio);

    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => setSessionChatRatio(0.5)).not.toThrow();
  });
});
