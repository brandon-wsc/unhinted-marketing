import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { SessionShell } from "@/features/session/components/session-shell";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/components/ui/resizable", () => ({
  ResizablePanelGroup: ({
    children,
    className,
    id,
  }: {
    children?: ReactNode;
    className?: string;
    id?: string;
  }) => (
    <div data-testid="panel-group" id={id} className={className}>
      {children}
    </div>
  ),
  ResizablePanel: ({
    children,
    className,
    id,
  }: {
    children?: ReactNode;
    className?: string;
    id?: string;
  }) => (
    <div data-testid={`panel-${id}`} id={id}>
      <div className={className}>{children}</div>
    </div>
  ),
  ResizableHandle: ({
    className,
    "aria-label": label,
  }: {
    className?: string;
    "aria-label"?: string;
  }) => (
    <button type="button" data-testid="resize-handle" aria-label={label} className={className} />
  ),
}));

const slots = {
  history: <div>history-slot</div>,
  historyPage: <div>history-page-slot</div>,
  chat: <div>chat-slot</div>,
  preview: <div>preview-slot</div>,
};

function renderShell(
  props: Partial<{
    layoutMode: "split" | "paged";
    pagedPane: "record" | "chat" | "preview";
    previewReady: boolean;
    historyCollapsed: boolean;
    shellWidth: number;
    preview: typeof slots.preview | null;
  }> = {},
) {
  const { preview = slots.preview, ...rest } = props;
  return render(
    <SessionShell
      shellRef={{ current: null }}
      layoutMode="split"
      pagedPane="chat"
      previewReady={false}
      historyCollapsed={false}
      shellWidth={1440}
      chatRatio={0.4}
      onChatRatioChange={() => undefined}
      {...slots}
      preview={preview}
      {...rest}
    />,
  );
}

describe("SessionShell", () => {
  it("shows history + chat and no resize handle when split without preview", () => {
    renderShell({ previewReady: false, preview: null });
    expect(screen.getByText("history-slot")).toBeInTheDocument();
    expect(screen.getByText("chat-slot")).toBeInTheDocument();
    expect(screen.queryByText("preview-slot")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("chat.shell.resize")).not.toBeInTheDocument();
    expect(document.getElementById("session-split")).toBeInTheDocument();
    expect(screen.queryByTestId("session-paged")).not.toBeInTheDocument();
  });

  it("shows a resize handle when split and preview are ready", () => {
    renderShell({ previewReady: true });
    expect(screen.getByText("chat-slot")).toBeInTheDocument();
    expect(screen.getByText("preview-slot")).toBeInTheDocument();
    expect(screen.getByLabelText("chat.shell.resize")).toBeInTheDocument();
    expect(screen.getByLabelText("chat.shell.resize")).not.toHaveClass("hidden");
  });

  it("keeps preview mounted in paged chat without a split group", () => {
    renderShell({
      layoutMode: "paged",
      pagedPane: "chat",
      previewReady: true,
      shellWidth: 390,
    });
    expect(screen.queryByText("history-page-slot")).not.toBeInTheDocument();
    expect(screen.getByText("chat-slot")).toBeInTheDocument();
    expect(screen.getByText("preview-slot")).toBeInTheDocument();
    expect(document.getElementById("session-split")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("chat.shell.resize")).not.toBeInTheDocument();
    expect(screen.getByTestId("session-paged")).not.toHaveClass("hidden");
    expect(screen.getByTestId("session-paged-chat")).not.toHaveClass("hidden");
    expect(screen.getByTestId("session-paged-preview")).toHaveClass("hidden");
  });

  it("shows preview full-page in paged preview and hides chat", () => {
    renderShell({
      layoutMode: "paged",
      pagedPane: "preview",
      previewReady: true,
      shellWidth: 390,
    });
    expect(screen.getByText("preview-slot")).toBeInTheDocument();
    expect(screen.getByText("chat-slot")).toBeInTheDocument();
    expect(document.getElementById("session-split")).not.toBeInTheDocument();
    expect(screen.getByTestId("session-paged-chat")).toHaveClass("hidden");
    expect(screen.getByTestId("session-paged-preview")).not.toHaveClass("hidden");
  });

  it("shows the record page in paged record mode and hides the pair", () => {
    renderShell({
      layoutMode: "paged",
      pagedPane: "record",
      previewReady: false,
      shellWidth: 390,
      preview: null,
    });
    expect(screen.getByText("history-page-slot")).toBeInTheDocument();
    expect(screen.queryByText("history-slot")).not.toBeInTheDocument();
    expect(document.getElementById("session-split")).not.toBeInTheDocument();
    expect(screen.getByTestId("session-paged")).toHaveClass("hidden");
    expect(screen.getByText("chat-slot")).toBeInTheDocument();
  });
});
