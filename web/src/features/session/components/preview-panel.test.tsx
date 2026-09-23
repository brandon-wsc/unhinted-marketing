import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { captionBesideAccount } from "@/features/session/components/ig-preview-mock";
import { PreviewPanel } from "@/features/session/components/preview-panel";
import type { ConfirmSessionResponse, PreviewDraft } from "@/features/session/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}));

vi.mock("@/features/session/components/edit-copy-dialog", () => ({
  EditCopyDialog: () => null,
}));
vi.mock("@/features/session/components/edit-image-dialog", () => ({
  EditImageDialog: () => null,
}));

const noop = async () => undefined;

function draft(overrides: Partial<PreviewDraft> = {}): PreviewDraft {
  return {
    revision: 1,
    approval_token: "tok-ok-12",
    image_url: "https://cdn.example/a.png",
    media: [
      {
        id: "m1",
        url: "https://cdn.example/a.png",
        plan: {},
        format: "single",
        role: "primary",
        seq: 0,
        status: "ready",
      },
    ],
    copy: { caption: "hi", hashtags: [], cta: "" },
    platform: "instagram",
    ...overrides,
  };
}

function renderPanel(opts: {
  draft: PreviewDraft;
  confirmed?: boolean;
  confirmReceipt?: ConfirmSessionResponse | null;
  confirmError?: string | null;
  awaitingImage?: boolean;
  imageGenerating?: boolean;
}) {
  return render(
    <MemoryRouter>
      <TooltipProvider>
        <PreviewPanel
          draft={opts.draft}
          confirmed={opts.confirmed ?? false}
          confirmReceipt={opts.confirmReceipt ?? null}
          draftSaving={false}
          confirming={false}
          confirmError={opts.confirmError ?? null}
          awaitingImage={opts.awaitingImage}
          imageGenerating={opts.imageGenerating}
          onApply={noop}
          onConfirm={noop}
          onSavePlan={noop}
          onRegenImage={noop}
          onAddImage={noop}
          onRemoveImage={noop}
          onUploadImage={noop}
        />
      </TooltipProvider>
    </MemoryRouter>,
  );
}

describe("PreviewPanel receipts", () => {
  it("disables Confirm and shows the image-required hint for copy-only drafts", () => {
    renderPanel({
      draft: draft({ image_url: null, media: [] }),
    });
    expect(screen.getByRole("button", { name: "preview.confirm" })).toBeDisabled();
    expect(screen.getByText("preview.gate.imageRequired")).toBeInTheDocument();
    expect(screen.queryByText("preview.receipt.publishedBadge")).not.toBeInTheDocument();
  });

  it("treats a leftover placeholder image_url as copy-only", () => {
    renderPanel({
      draft: draft({ image_url: "placeholder://seed", media: [] }),
    });
    expect(screen.getByRole("button", { name: "preview.confirm" })).toBeDisabled();
    expect(screen.getByText("preview.gate.imageRequired")).toBeInTheDocument();
  });

  it("shows a failed receipt instead of a success wash", () => {
    renderPanel({
      draft: draft(),
      confirmReceipt: {
        receipt_id: "r-fail",
        status: "failed",
        tool_name: "publish_social_post",
        idempotency_key: "idem-fail",
        error_kind: "platform_error",
      },
    });
    expect(screen.getByText("preview.receipt.failedTitle")).toBeInTheDocument();
    expect(screen.getByText("preview.receipt.error.platform_error")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "preview.receipt.retry" })).toBeInTheDocument();
    expect(screen.queryByText("preview.receipt.publishedBadge")).not.toBeInTheDocument();
    expect(screen.queryByText("preview.confirmDone")).not.toBeInTheDocument();
  });

  it("shows the Instagram permalink on a published receipt", () => {
    renderPanel({
      draft: draft(),
      confirmed: true,
      confirmReceipt: {
        receipt_id: "r-pub",
        status: "published",
        tool_name: "publish_social_post",
        idempotency_key: "idem-pub",
        permalink: "https://www.instagram.com/p/ABC/",
      },
    });
    expect(screen.getByText("preview.receipt.publishedTitle")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "preview.receipt.viewOnInstagram" });
    expect(link).toHaveAttribute("href", "https://www.instagram.com/p/ABC/");
    expect(screen.getByText("preview.receipt.publishedBadge")).toBeInTheDocument();
  });

  it("keeps the stubbed success receipt", () => {
    renderPanel({
      draft: draft(),
      confirmed: true,
      confirmReceipt: {
        receipt_id: "r-stub",
        status: "stubbed",
        tool_name: "publish_social_post",
        idempotency_key: "idem-stub",
      },
    });
    expect(screen.getByText("preview.confirmDone")).toBeInTheDocument();
    expect(screen.getByText("preview.confirmReceipt")).toBeInTheDocument();
  });

  it("keeps the IG shell with a waiting image slot when image-parked", () => {
    renderPanel({
      draft: draft({
        image_url: null,
        copy: { caption: "手沖未出街", hashtags: ["#hkcoffee"], cta: "去試" },
        media: [
          {
            id: "pending-1",
            url: null,
            plan: {
              format: "single",
              prompt: "Harbour pour-over, morning light",
              panels: [{ beat: "kettle" }],
            },
            format: "single",
            role: "primary",
            seq: 0,
            status: "pending",
          },
        ],
      }),
      awaitingImage: true,
    });
    expect(screen.getAllByText("preview.awaiting.title")).toHaveLength(1);
    expect(screen.getByText("preview.mock.sponsored")).toBeInTheDocument();
    expect(screen.getAllByText("unhinted").length).toBeGreaterThan(0);
    const slot = document.querySelector("[data-preview-state='pending']");
    expect(slot).toBeTruthy();
    expect(slot).toHaveTextContent("preview.awaiting.slotEmpty");
    expect(screen.getAllByText("preview.awaiting.slotEmpty")).toHaveLength(1);
    expect(screen.queryByRole("status", { name: "Loading" })).not.toBeInTheDocument();
    expect(screen.getByText(/手沖未出街/)).toBeInTheDocument();
    expect(screen.getByText(/#hkcoffee/)).toBeInTheDocument();
    const plan = screen.getByText("preview.awaiting.plan").closest("details");
    expect(plan).toBeTruthy();
    expect(plan).not.toHaveAttribute("open");
    expect(plan).toHaveTextContent("Harbour pour-over, morning light");
    expect(plan).toHaveTextContent("kettle");
    expect(plan).toHaveTextContent("preview.awaiting.formatSingle");
    expect(screen.queryByText("preview.mock.placeholder")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "preview.apply" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "preview.confirm" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "preview.copy.edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "preview.media.edit" })).not.toBeInTheDocument();
    expect(screen.getAllByText("preview.awaiting.status")).toHaveLength(1);
    expect(screen.queryByText("chat.agent.interrupt.subtitle")).not.toBeInTheDocument();
    expect(screen.queryByText("preview.gate.imageRequired")).not.toBeInTheDocument();
    expect(screen.queryByText("preview.awaiting.badge")).not.toBeInTheDocument();
    expect(slot).toHaveClass("bg-card", "text-foreground", "border-dashed", "border-foreground/40");
    expect(slot).not.toHaveClass("bg-secondary");
    expect(slot?.querySelector("p")).toHaveClass("text-foreground");
    expect(slot?.querySelector("p")).not.toHaveClass("text-muted-foreground");
  });

  it("shows the spinner inside the IG image slot only while generating", () => {
    renderPanel({
      draft: draft({ image_url: null, media: [] }),
      awaitingImage: true,
      imageGenerating: true,
    });
    const slot = document.querySelector("[data-preview-state='generating']");
    expect(slot).toBeTruthy();
    expect(slot).toHaveAttribute("aria-busy", "true");
    const spinner = screen.getByRole("status", { name: "Loading" });
    expect(spinner.closest("[data-preview-state]")).toBe(slot);
    expect(spinner).toHaveClass("text-foreground");
    expect(spinner).not.toHaveClass("text-muted-foreground");
    expect(slot).toHaveClass("bg-card", "text-foreground", "border-dashed");
    expect(screen.getAllByText("preview.awaiting.slotGenerating")).toHaveLength(1);
    expect(screen.getAllByText("preview.awaiting.generatingTitle")).toHaveLength(1);
    expect(screen.getByText("preview.mock.sponsored")).toBeInTheDocument();
    expect(screen.queryByText("preview.awaiting.slotEmpty")).not.toBeInTheDocument();
    expect(screen.queryByText("preview.awaiting.plan")).not.toBeInTheDocument();
    expect(screen.queryByText("preview.mock.placeholder")).not.toBeInTheDocument();
    expect(screen.getAllByText("preview.awaiting.status")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "preview.confirm" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "preview.apply" })).not.toBeInTheDocument();
  });

  it("keeps the accepted IG preview when a parked session still has a ready image", () => {
    renderPanel({
      draft: draft(),
      awaitingImage: true,
    });
    expect(screen.getByText("preview.mock.sponsored")).toBeInTheDocument();
    expect(screen.queryByText("preview.awaiting.slotEmpty")).not.toBeInTheDocument();
    expect(screen.queryByText("preview.awaiting.title")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "preview.confirm" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "preview.apply" })).toBeInTheDocument();
  });

  it("keeps the copy-only IG gate when the session is not image-parked", () => {
    renderPanel({
      draft: draft({ image_url: null, media: [] }),
      awaitingImage: false,
    });
    expect(screen.getByText("preview.mock.sponsored")).toBeInTheDocument();
    expect(screen.getByText("preview.mock.placeholder")).toBeInTheDocument();
    expect(screen.getByText("preview.gate.imageRequired")).toBeInTheDocument();
    expect(screen.queryByText("preview.awaiting.slotEmpty")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "preview.confirm" })).toBeDisabled();
  });

  it("keeps the locked footer as a short chat pointer, not the lock essay", async () => {
    const en = (await import("@/i18n/locales/en.json")).default;
    const zh = (await import("@/i18n/locales/zh-HK.json")).default;
    expect(zh.preview.awaiting.status).not.toBe(zh.chat.agent.interrupt.subtitle);
    expect(en.preview.awaiting.status).not.toBe(en.chat.agent.interrupt.subtitle);
    expect(zh.preview.awaiting.status.length).toBeLessThan(
      zh.chat.agent.interrupt.subtitle.length / 2,
    );
    expect(en.preview.awaiting.status.length).toBeLessThan(en.chat.agent.interrupt.subtitle.length);
    expect(zh.preview.awaiting.status).toMatch(/棄置/);
    expect(zh.preview.awaiting.status).toMatch(/出圖/);
    expect(en.preview.awaiting.status.toLowerCase()).toMatch(/chat/);
  });

  it("bolds the account name and does not repeat a leading handle in the caption", () => {
    expect(captionBesideAccount("unhinted 清晨六點", "unhinted")).toBe("清晨六點");
    expect(captionBesideAccount("Unhinted：清晨", "unhinted")).toBe("清晨");
    expect(captionBesideAccount("清晨六點", "unhinted")).toBe("清晨六點");
    expect(captionBesideAccount("unhintedcoffee 呀", "unhinted")).toBe("unhintedcoffee 呀");

    renderPanel({
      draft: draft({
        copy: { caption: "unhinted 清晨六點，海邊未有人", hashtags: [], cta: "" },
      }),
    });
    const names = screen.getAllByText("unhinted");
    expect(names).toHaveLength(2);
    const captionLead = names.find((el) => el.tagName === "SPAN");
    expect(captionLead).toHaveClass("font-bold");
    const body = screen.getByText(/清晨六點，海邊未有人/);
    expect(body.tagName).toBe("SPAN");
    expect(body).toHaveClass("whitespace-pre-wrap");
    expect(body.textContent).not.toMatch(/unhinted/i);
  });

  it("links to Instagram settings when the account is not connected", () => {
    renderPanel({
      draft: draft(),
      confirmError: "social_account_not_connected",
    });
    expect(screen.getByText("preview.gate.notConnected")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "preview.gate.openSettings" });
    expect(link).toHaveAttribute("href", "/settings?tab=instagram");
  });
});
