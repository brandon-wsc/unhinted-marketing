import { describe, expect, it } from "vitest";
import {
  SESSION_PANE,
  sessionLayoutMode,
  sessionSplitMinWidth,
} from "@/features/session/session-layout";

describe("sessionSplitMinWidth", () => {
  it("sums history + chat when preview is not ready", () => {
    expect(
      sessionSplitMinWidth({ historyCollapsed: false, previewReady: false }),
    ).toBe(SESSION_PANE.historyExpanded + SESSION_PANE.chatMin);
    expect(
      sessionSplitMinWidth({ historyCollapsed: true, previewReady: false }),
    ).toBe(SESSION_PANE.historyCollapsed + SESSION_PANE.chatMin);
  });

  it("adds preview min when a draft is ready", () => {
    expect(
      sessionSplitMinWidth({ historyCollapsed: false, previewReady: true }),
    ).toBe(
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
