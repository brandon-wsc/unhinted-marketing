import type { ReactNode, Ref } from "react";
import { useTranslation } from "react-i18next";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import {
  type PagedPane,
  SESSION_PANE,
  SESSION_SPLIT_PANEL,
  type SessionLayoutMode,
  sessionChatRatioFromLayout,
  sessionLeftoverWidth,
  sessionSplitSizes,
} from "@/features/session/session-layout";
import { cn } from "@/lib/utils";

const SPLIT_HIT_TARGET = { coarse: 7, fine: 7 } as const;

const PAGED_PANE = "min-h-0 min-w-0 flex-col overflow-hidden";

type Props = {
  shellRef: Ref<HTMLDivElement | null>;
  layoutMode: SessionLayoutMode;
  pagedPane: PagedPane;
  previewReady: boolean;
  historyCollapsed: boolean;
  shellWidth: number;
  chatRatio: number;
  onChatRatioChange: (ratio: number) => void;
  history: ReactNode;
  historyPage: ReactNode;
  chat: ReactNode;
  preview: ReactNode | null;
};

function pagedPaneClass(active: boolean): string {
  // Real `hidden` (display:none) on a normal div — not on ResizablePanel.
  // react-resizable-panels puts className on an inner wrapper and keeps the
  // outer flex item, so Tailwind `hidden` there still occupies split width.
  return cn(PAGED_PANE, active ? "flex flex-1" : "hidden");
}

function PaneFill({ children }: { children: ReactNode }) {
  return <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">{children}</div>;
}

export function SessionShell({
  shellRef,
  layoutMode,
  pagedPane,
  previewReady,
  historyCollapsed,
  shellWidth,
  chatRatio,
  onChatRatioChange,
  history,
  historyPage,
  chat,
  preview,
}: Props) {
  const { t } = useTranslation();
  const isSplit = layoutMode === "split";
  const leftover = sessionLeftoverWidth(shellWidth, historyCollapsed);
  const sizes = sessionSplitSizes(leftover, chatRatio, previewReady);
  const canResize = isSplit && previewReady && leftover > 0;
  const showPreviewPane = !!previewReady && !!preview;

  return (
    <div ref={shellRef} className="flex min-h-0 flex-1 overflow-hidden">
      {isSplit ? history : null}

      {!isSplit && pagedPane === "record" ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{historyPage}</div>
      ) : null}

      {isSplit ? (
        <ResizablePanelGroup
          id="session-split"
          className="min-h-0 min-w-0 flex-1"
          orientation="horizontal"
          disabled={!canResize}
          resizeTargetMinimumSize={SPLIT_HIT_TARGET}
          onLayoutChanged={(layout, meta) => {
            if (!meta.isUserInteraction) return;
            onChatRatioChange(sessionChatRatioFromLayout(layout));
          }}
        >
          <ResizablePanel
            id={SESSION_SPLIT_PANEL.chat}
            minSize={canResize ? SESSION_PANE.chatMin : 0}
            defaultSize={canResize ? sizes.chatPx : "100%"}
            className="min-h-0 min-w-0"
          >
            <PaneFill>{chat}</PaneFill>
          </ResizablePanel>
          {showPreviewPane ? (
            <>
              <ResizableHandle
                disabled={!canResize}
                aria-label={t("chat.shell.resize")}
                className={cn(!canResize && "hidden")}
              />
              <ResizablePanel
                id={SESSION_SPLIT_PANEL.preview}
                minSize={canResize ? SESSION_PANE.previewMin : 0}
                defaultSize={canResize ? sizes.previewPx : "100%"}
                className="min-h-0 min-w-0"
              >
                <PaneFill>{preview}</PaneFill>
              </ResizablePanel>
            </>
          ) : null}
        </ResizablePanelGroup>
      ) : (
        <div
          data-testid="session-paged"
          className={cn(
            "flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden",
            pagedPane === "record" && "hidden",
          )}
        >
          <div data-testid="session-paged-chat" className={pagedPaneClass(pagedPane === "chat")}>
            <PaneFill>{chat}</PaneFill>
          </div>
          {showPreviewPane ? (
            <div
              data-testid="session-paged-preview"
              className={pagedPaneClass(pagedPane === "preview")}
            >
              <PaneFill>{preview}</PaneFill>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
