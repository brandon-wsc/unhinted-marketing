/** Content-based session shell panes — not viewport/device breakpoints. */
export const SESSION_PANE = {
  historyExpanded: 280,
  historyCollapsed: 48,
  chatMin: 360,
  previewMin: 360,
  /** Share of leftover (after history) for chat; preview takes the rest. */
  chatDefaultRatio: 0.4,
} as const;

export const SESSION_CHAT_RATIO_KEY = "unhinted.sessionSplit.chatRatio";

export const SESSION_SPLIT_PANEL = {
  chat: "session-chat",
  preview: "session-preview",
} as const;

export type SessionLayoutMode = "split" | "paged";

export type PagedPane = "record" | "chat" | "preview";

export type SessionLayoutInput = {
  historyCollapsed: boolean;
  previewReady: boolean;
};

export type SessionSplitSizes = {
  chatPx: number;
  previewPx: number;
};

export type SessionSplitPercents = {
  chatPct: number;
  previewPct: number;
  chatMinPct: number;
  previewMinPct: number;
};

export function sessionHistoryWidth(collapsed: boolean): number {
  return collapsed ? SESSION_PANE.historyCollapsed : SESSION_PANE.historyExpanded;
}

/** Width left for chat (+ preview) after the history pane. */
export function sessionLeftoverWidth(containerWidth: number, historyCollapsed: boolean): number {
  return Math.max(0, containerWidth - sessionHistoryWidth(historyCollapsed));
}

/** Minimum container width before history + chat (+ preview) can sit side-by-side. */
export function sessionSplitMinWidth({
  historyCollapsed,
  previewReady,
}: SessionLayoutInput): number {
  const preview = previewReady ? SESSION_PANE.previewMin : 0;
  return sessionHistoryWidth(historyCollapsed) + SESSION_PANE.chatMin + preview;
}

export function sessionLayoutMode(
  containerWidth: number,
  input: SessionLayoutInput,
): SessionLayoutMode {
  return containerWidth >= sessionSplitMinWidth(input) ? "split" : "paged";
}

function clamp(n: number, lo: number, hi: number): number {
  if (lo > hi) return hi;
  return Math.min(hi, Math.max(lo, n));
}

function finiteRatio(ratio: number): number {
  if (!Number.isFinite(ratio) || ratio <= 0 || ratio >= 1) {
    return SESSION_PANE.chatDefaultRatio;
  }
  return ratio;
}

/**
 * Chat / preview pixel widths from leftover after history.
 * When preview is on, chat is clamped so both panes keep their mins.
 */
export function sessionSplitSizes(
  leftoverPx: number,
  chatRatio: number,
  previewReady: boolean,
): SessionSplitSizes {
  if (leftoverPx <= 0) {
    return { chatPx: 0, previewPx: 0 };
  }
  if (!previewReady) {
    return { chatPx: leftoverPx, previewPx: 0 };
  }
  const preferred = leftoverPx * finiteRatio(chatRatio);
  const chatPx = clamp(preferred, SESSION_PANE.chatMin, leftoverPx - SESSION_PANE.previewMin);
  return { chatPx, previewPx: leftoverPx - chatPx };
}

/** Percent of leftover (chat / preview / mins). */
export function sessionSplitPercents(
  leftoverPx: number,
  chatRatio: number,
  previewReady: boolean,
): SessionSplitPercents {
  if (leftoverPx <= 0) {
    return { chatPct: 100, previewPct: 0, chatMinPct: 0, previewMinPct: 0 };
  }
  const { chatPx, previewPx } = sessionSplitSizes(leftoverPx, chatRatio, previewReady);
  const chatMinPct = Math.min(100, (SESSION_PANE.chatMin / leftoverPx) * 100);
  const previewMinPct = previewReady
    ? Math.min(100, (SESSION_PANE.previewMin / leftoverPx) * 100)
    : 0;
  return {
    chatPct: (chatPx / leftoverPx) * 100,
    previewPct: (previewPx / leftoverPx) * 100,
    chatMinPct,
    previewMinPct,
  };
}

export function sessionChatRatioFromPx(chatPx: number, leftoverPx: number): number {
  if (leftoverPx <= 0) return SESSION_PANE.chatDefaultRatio;
  return finiteRatio(chatPx / leftoverPx);
}

/** Map a resizable-panels Group layout (panel id → flexGrow) to leftover chat ratio. */
export function sessionChatRatioFromLayout(layout: Record<string, number>): number {
  const chat = layout[SESSION_SPLIT_PANEL.chat] ?? 0;
  const preview = layout[SESSION_SPLIT_PANEL.preview] ?? 0;
  const sum = chat + preview;
  if (sum <= 0) return SESSION_PANE.chatDefaultRatio;
  return finiteRatio(chat / sum);
}

export function getSessionChatRatio(): number {
  if (typeof localStorage === "undefined") return SESSION_PANE.chatDefaultRatio;
  try {
    const raw = localStorage.getItem(SESSION_CHAT_RATIO_KEY);
    if (raw == null) return SESSION_PANE.chatDefaultRatio;
    return finiteRatio(Number(raw));
  } catch {
    return SESSION_PANE.chatDefaultRatio;
  }
}

export function setSessionChatRatio(ratio: number): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(SESSION_CHAT_RATIO_KEY, String(finiteRatio(ratio)));
  } catch {
    /* ignore quota / private mode */
  }
}
