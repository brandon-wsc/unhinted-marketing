import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  InstagramPanel,
  OAUTH_POLL_TIMEOUT_MS,
} from "@/features/company-settings/components/instagram-panel";

const { api, authState } = vi.hoisted(() => ({
  api: {
    apiListSocialAccounts: vi.fn(),
    apiStartInstagramOAuth: vi.fn(),
    apiGetInstagramOAuthStatus: vi.fn(),
    apiCancelInstagramOAuth: vi.fn(),
    apiDisconnectInstagramAccount: vi.fn(),
    apiUpsertSocialAccount: vi.fn(),
  },
  authState: { platformLevel: 9 },
}));

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t, i18n: { language: "en" } }) };
});

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    accessToken: "tok",
    user: { platform_level: authState.platformLevel },
  }),
}));

vi.mock("@/features/company-settings/api", () => ({
  apiListSocialAccounts: api.apiListSocialAccounts,
  apiStartInstagramOAuth: api.apiStartInstagramOAuth,
  apiGetInstagramOAuthStatus: api.apiGetInstagramOAuthStatus,
  apiCancelInstagramOAuth: api.apiCancelInstagramOAuth,
  apiDisconnectInstagramAccount: api.apiDisconnectInstagramAccount,
  apiUpsertSocialAccount: api.apiUpsertSocialAccount,
}));

const connected = {
  id: "sa-1",
  company_id: "c1",
  platform: "instagram" as const,
  ig_user_id: "17841400000000000",
  token_last4: "ab12",
  expires_at: "2099-01-01T00:00:00Z",
  last_verified_at: null,
  last_error_kind: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderPanel(path = "/settings?tab=instagram") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <TooltipProvider>
        <InstagramPanel companyId="c1" />
      </TooltipProvider>
    </MemoryRouter>,
  );
}

const OAUTH_CALLBACK = "https://acme.example/api/social/oauth/callback";

describe("InstagramPanel", () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
    authState.platformLevel = 9;
    api.apiListSocialAccounts.mockReset().mockResolvedValue([]);
    api.apiStartInstagramOAuth.mockReset();
    api.apiGetInstagramOAuthStatus.mockReset();
    api.apiCancelInstagramOAuth.mockReset();
    api.apiDisconnectInstagramAccount.mockReset();
    api.apiUpsertSocialAccount.mockReset();
  });

  it("shows the connect button when no account is connected", async () => {
    api.apiListSocialAccounts.mockResolvedValue([]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({
      status: "not_connected",
      configured: true,
      callback_url: OAUTH_CALLBACK,
    });
    renderPanel();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "settings.instagram.connect" }),
      ).toBeInTheDocument();
    });
    // The paste-token disclosure stays collapsed (its fields are inside <details>).
    expect(
      screen.getByText("settings.instagram.manualToggle").closest("details"),
    ).not.toHaveAttribute("open");
  });

  it("does not show connected chrome while oauth is pending with an empty list", async () => {
    api.apiListSocialAccounts.mockResolvedValue([]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "pending", configured: true });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("settings.instagram.connectingTitle")).toBeInTheDocument();
    });
    expect(screen.queryByText("settings.instagram.connected")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "settings.instagram.connect" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "settings.instagram.rotate" }),
    ).not.toBeInTheDocument();
    const status = screen.getByRole("status");
    expect(within(status).getByText("settings.instagram.connectingTitle")).toBeInTheDocument();
    expect(within(status).getByText("settings.instagram.connectingBody")).toBeInTheDocument();
    expect(within(status).getByRole("button", { name: "common.cancel" })).toBeInTheDocument();
  });

  it("cancels a pending oauth poll", async () => {
    const user = userEvent.setup();
    api.apiListSocialAccounts.mockResolvedValue([]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "pending", configured: true });
    api.apiCancelInstagramOAuth.mockResolvedValue({ status: "not_connected", configured: true });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "common.cancel" })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "common.cancel" }));
    await waitFor(() => {
      expect(api.apiCancelInstagramOAuth).toHaveBeenCalledWith("tok", "c1");
    });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "settings.instagram.connect" }),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText("settings.instagram.oauthAborted")).not.toBeInTheDocument();
  });

  it("shows the aborted error when the oauth poll times out", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.apiListSocialAccounts.mockResolvedValue([]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "pending", configured: true });
    api.apiCancelInstagramOAuth.mockResolvedValue({ status: "not_connected", configured: true });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "common.cancel" })).toBeInTheDocument();
    });
    await vi.advanceTimersByTimeAsync(OAUTH_POLL_TIMEOUT_MS);
    await waitFor(() => {
      expect(screen.getByText("settings.instagram.oauthAborted")).toBeInTheDocument();
    });
    vi.useRealTimers();
  });

  it("surfaces a failed oauth callback from the redirect query", async () => {
    api.apiListSocialAccounts.mockResolvedValue([]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "not_connected", configured: true });
    renderPanel("/settings?tab=instagram&oauth=done&status=meta_oauth_not_professional");
    await waitFor(() => {
      expect(screen.getByText("settings.instagram.oauthNotProfessional")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "settings.instagram.connect" })).toBeInTheDocument();
  });

  it("surfaces a no-pages oauth callback from the redirect query", async () => {
    api.apiListSocialAccounts.mockResolvedValue([]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "not_connected", configured: true });
    renderPanel("/settings?tab=instagram&oauth=done&status=meta_oauth_missing_publish");
    await waitFor(() => {
      expect(screen.getByText("settings.instagram.oauthMissingPublish")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "settings.instagram.connect" })).toBeInTheDocument();
  });

  it("does not flash a connected alert after a successful oauth callback", async () => {
    api.apiListSocialAccounts.mockResolvedValue([connected]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "connected", configured: true });
    renderPanel("/settings?tab=instagram&oauth=done&status=ok");
    await waitFor(() => {
      expect(screen.getByText("settings.instagram.connected")).toBeInTheDocument();
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows last4 only on a connected account", async () => {
    api.apiListSocialAccounts.mockResolvedValue([connected]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "connected", configured: true });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("••••ab12")).toBeInTheDocument();
    });
    expect(screen.getByText("settings.instagram.connected")).toBeInTheDocument();
    expect(screen.getByText(connected.ig_user_id)).toBeInTheDocument();
    expect(screen.queryByDisplayValue(/IGQ|secret-token/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.instagram.rotate" })).toBeInTheDocument();
  });

  it("starts OAuth and opens a popup when connect is clicked", async () => {
    const user = userEvent.setup();
    api.apiListSocialAccounts.mockResolvedValue([]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "not_connected", configured: true });
    api.apiStartInstagramOAuth.mockResolvedValue({
      status: "pending",
      authorization_url: "https://www.instagram.com/oauth/authorize?state=x",
      poll_url: "/api/companies/c1/social-accounts/oauth/status",
    });
    const openSpy = vi.spyOn(window, "open").mockReturnValue({ closed: false } as Window);
    renderPanel();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "settings.instagram.connect" }),
      ).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "settings.instagram.connect" }));
    await waitFor(() => {
      expect(api.apiStartInstagramOAuth).toHaveBeenCalledWith("tok", "c1");
    });
    expect(openSpy).toHaveBeenCalledWith(
      "https://www.instagram.com/oauth/authorize?state=x",
      "_blank",
      "noopener,noreferrer",
    );
    openSpy.mockRestore();
  });

  it("shows an expired badge instead of the connected badge", async () => {
    api.apiListSocialAccounts.mockResolvedValue([
      { ...connected, expires_at: "2020-01-01T00:00:00Z" },
    ]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "connected", configured: true });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("settings.instagram.expiredTitle")).toBeInTheDocument();
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("settings.instagram.connected")).not.toBeInTheDocument();
    expect(screen.getByText(connected.ig_user_id)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.instagram.rotate" })).toBeInTheDocument();
  });

  it("disconnects a connected account", async () => {
    const user = userEvent.setup();
    api.apiListSocialAccounts.mockResolvedValue([connected]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "connected", configured: true });
    api.apiDisconnectInstagramAccount.mockResolvedValue(undefined);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "settings.instagram.rotate" })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "settings.instagram.disconnect" }));
    await waitFor(() => {
      expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    });
    // The destructive action inside the AlertDialog carries the same label; grab it from the dialog.
    const dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "settings.instagram.disconnect" }));
    await waitFor(() => {
      expect(api.apiDisconnectInstagramAccount).toHaveBeenCalledWith("tok", "c1");
    });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "settings.instagram.connect" }),
      ).toBeInTheDocument();
    });
    expect(screen.getByText("settings.instagram.disconnected")).toBeInTheDocument();
  });

  it("shows the guided BYO card with an admin CTA when unconfigured", async () => {
    api.apiListSocialAccounts.mockResolvedValue([]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({
      status: "not_connected",
      configured: false,
      callback_url: OAUTH_CALLBACK,
    });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("settings.instagram.needsAppTitle")).toBeInTheDocument();
    });
    expect(screen.getByText("settings.instagram.needsAppStep1")).toBeInTheDocument();
    expect(screen.getByText("settings.instagram.standardAccessNote")).toBeInTheDocument();
    expect(screen.getByDisplayValue(OAUTH_CALLBACK)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "settings.instagram.openInstanceSettings" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "settings.instagram.connect" }),
    ).not.toBeInTheDocument();
  });

  it("shows the muted viewer note instead of the CTA for non-superadmins", async () => {
    authState.platformLevel = 3;
    api.apiListSocialAccounts.mockResolvedValue([]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({
      status: "not_connected",
      configured: false,
      callback_url: OAUTH_CALLBACK,
    });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("settings.instagram.needsAppViewerNote")).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("button", { name: "settings.instagram.openInstanceSettings" }),
    ).not.toBeInTheDocument();
  });

  it("flips to the guided card when start reports meta_oauth_not_configured", async () => {
    const user = userEvent.setup();
    api.apiListSocialAccounts.mockResolvedValue([]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({
      status: "not_connected",
      configured: true,
      callback_url: OAUTH_CALLBACK,
    });
    api.apiStartInstagramOAuth.mockRejectedValue(new Error("meta_oauth_not_configured"));
    renderPanel();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "settings.instagram.connect" }),
      ).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "settings.instagram.connect" }));
    await waitFor(() => {
      expect(screen.getByText("settings.instagram.needsAppTitle")).toBeInTheDocument();
    });
  });

  it("saves a manually pasted token", async () => {
    const user = userEvent.setup();
    api.apiListSocialAccounts.mockResolvedValueOnce([]).mockResolvedValue([connected]);
    api.apiGetInstagramOAuthStatus
      .mockResolvedValueOnce({ status: "not_connected", configured: true })
      .mockResolvedValue({ status: "connected", configured: true });
    api.apiUpsertSocialAccount.mockResolvedValue(connected);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("settings.instagram.manualToggle")).toBeInTheDocument();
    });
    await user.click(screen.getByText("settings.instagram.manualToggle"));
    await user.type(screen.getByLabelText("settings.instagram.igUserId"), "17841");
    await user.type(screen.getByLabelText("settings.instagram.accessToken"), "tok-abc");
    await user.click(screen.getByRole("button", { name: "common.save" }));
    await waitFor(() => {
      expect(api.apiUpsertSocialAccount).toHaveBeenCalledWith("tok", "c1", "instagram", {
        ig_user_id: "17841",
        access_token: "tok-abc",
        expires_at: null,
      });
    });
    await waitFor(() => {
      expect(screen.getByText("settings.instagram.connected")).toBeInTheDocument();
    });
  });
});
