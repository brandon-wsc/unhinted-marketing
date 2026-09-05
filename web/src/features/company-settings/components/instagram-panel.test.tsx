import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { InstagramPanel } from "@/features/company-settings/components/instagram-panel";

const { api } = vi.hoisted(() => ({
  api: {
    apiListSocialAccounts: vi.fn(),
    apiStartInstagramOAuth: vi.fn(),
    apiGetInstagramOAuthStatus: vi.fn(),
    apiCancelInstagramOAuth: vi.fn(),
    apiDisconnectInstagramAccount: vi.fn(),
  },
}));

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t, i18n: { language: "en" } }) };
});

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}));

vi.mock("@/features/company-settings/api", () => ({
  apiListSocialAccounts: api.apiListSocialAccounts,
  apiStartInstagramOAuth: api.apiStartInstagramOAuth,
  apiGetInstagramOAuthStatus: api.apiGetInstagramOAuthStatus,
  apiCancelInstagramOAuth: api.apiCancelInstagramOAuth,
  apiDisconnectInstagramAccount: api.apiDisconnectInstagramAccount,
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

function renderPanel() {
  return render(
    <TooltipProvider>
      <InstagramPanel companyId="c1" />
    </TooltipProvider>,
  );
}

describe("InstagramPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.apiListSocialAccounts.mockReset().mockResolvedValue([]);
    api.apiStartInstagramOAuth.mockReset();
    api.apiGetInstagramOAuthStatus.mockReset();
    api.apiCancelInstagramOAuth.mockReset();
    api.apiDisconnectInstagramAccount.mockReset();
  });

  it("shows the connect button when no account is connected", async () => {
    api.apiListSocialAccounts.mockResolvedValue([]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "not_connected" });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "settings.instagram.connect" })).toBeInTheDocument();
    });
    expect(screen.queryByLabelText("settings.instagram.igUserId")).not.toBeInTheDocument();
  });

  it("does not show connected chrome while oauth is pending with an empty list", async () => {
    api.apiListSocialAccounts.mockResolvedValue([]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "pending" });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("settings.instagram.connectingTitle")).toBeInTheDocument();
    });
    expect(screen.queryByText("settings.instagram.connected")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "settings.instagram.connect" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "settings.instagram.rotate" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "common.cancel" })).toBeInTheDocument();
  });

  it("cancels a pending oauth poll", async () => {
    const user = userEvent.setup();
    api.apiListSocialAccounts.mockResolvedValue([]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "pending" });
    api.apiCancelInstagramOAuth.mockResolvedValue({ status: "not_connected" });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "common.cancel" })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "common.cancel" }));
    await waitFor(() => {
      expect(api.apiCancelInstagramOAuth).toHaveBeenCalledWith("tok", "c1");
    });
    await waitFor(() => {
      expect(screen.getByText("settings.instagram.oauthAborted")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "settings.instagram.connect" })).toBeInTheDocument();
    });
  });

  it("shows last4 only on a connected account", async () => {
    api.apiListSocialAccounts.mockResolvedValue([connected]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "connected" });
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
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "not_connected" });
    api.apiStartInstagramOAuth.mockResolvedValue({
      status: "pending",
      authorization_url: "https://www.facebook.com/v22.0/dialog/oauth?state=x",
      poll_url: "/api/companies/c1/social-accounts/oauth/status",
    });
    const openSpy = vi.spyOn(window, "open").mockReturnValue({ closed: false } as Window);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "settings.instagram.connect" })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "settings.instagram.connect" }));
    await waitFor(() => {
      expect(api.apiStartInstagramOAuth).toHaveBeenCalledWith("tok", "c1");
    });
    expect(openSpy).toHaveBeenCalledWith(
      "https://www.facebook.com/v22.0/dialog/oauth?state=x",
      "_blank",
      "noopener,noreferrer",
    );
    openSpy.mockRestore();
  });

  it("shows the expired alert on an expired connected account", async () => {
    api.apiListSocialAccounts.mockResolvedValue([
      { ...connected, expires_at: "2020-01-01T00:00:00Z" },
    ]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "connected" });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("settings.instagram.expiredTitle")).toBeInTheDocument();
    });
    expect(screen.getByText("settings.instagram.expiredBody")).toBeInTheDocument();
    expect(screen.queryByText("settings.instagram.connected")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.instagram.rotate" })).toBeInTheDocument();
  });

  it("disconnects a connected account", async () => {
    const user = userEvent.setup();
    api.apiListSocialAccounts.mockResolvedValue([connected]);
    api.apiGetInstagramOAuthStatus.mockResolvedValue({ status: "connected" });
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
    await user.click(
      within(dialog).getByRole("button", { name: "settings.instagram.disconnect" }),
    );
    await waitFor(() => {
      expect(api.apiDisconnectInstagramAccount).toHaveBeenCalledWith("tok", "c1");
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "settings.instagram.connect" })).toBeInTheDocument();
    });
  });
});
