/** Content-based session shell panes — not viewport/device breakpoints. */
export const SESSION_PANE = {
  historyExpanded: 280,
  historyCollapsed: 48,
  chatMin: 360,
  previewMin: 360,
} as const;

export type SessionLayoutMode = "split" | "paged";

export type SessionLayoutInput = {
  historyCollapsed: boolean;
  previewReady: boolean;
};

/** Minimum container width before history + chat (+ preview) can sit side-by-side. */
export function sessionSplitMinWidth({
  historyCollapsed,
  previewReady,
}: SessionLayoutInput): number {
  const history = historyCollapsed
    ? SESSION_PANE.historyCollapsed
    : SESSION_PANE.historyExpanded;
  const preview = previewReady ? SESSION_PANE.previewMin : 0;
  return history + SESSION_PANE.chatMin + preview;
}

export function sessionLayoutMode(
  containerWidth: number,
  input: SessionLayoutInput,
): SessionLayoutMode {
  return containerWidth >= sessionSplitMinWidth(input) ? "split" : "paged";
}
