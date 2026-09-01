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
  const hidePair = !isSplit && pagedPane === "record";
  const showPreviewPane = !!previewReady && !!preview;

  return (
    <div ref={shellRef} className="flex min-h-0 flex-1 overflow-hidden">
      {isSplit ? history : null}

      {!isSplit && pagedPane === "record" ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{historyPage}</div>
      ) : null}

      <ResizablePanelGroup
        id="session-split"
        className={cn("min-h-0 min-w-0 flex-1", hidePair && "hidden")}
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
          className={cn("min-h-0 min-w-0", !isSplit && pagedPane !== "chat" && "hidden")}
        >
          <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">{chat}</div>
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
              className={cn("min-h-0 min-w-0", !isSplit && pagedPane !== "preview" && "hidden")}
            >
              <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">{preview}</div>
            </ResizablePanel>
          </>
        ) : null}
      </ResizablePanelGroup>
    </div>
  );
}
