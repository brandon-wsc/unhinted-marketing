import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiStatusError } from "@/features/company-settings/api";
import { InviteAcceptPage } from "@/pages/invite-accept";

const { logout, refreshAccessToken, apiAcceptInvite, apiGetInvitePreview } = vi.hoisted(() => ({
  logout: vi.fn().mockResolvedValue(undefined),
  refreshAccessToken: vi.fn().mockResolvedValue("tok"),
  apiAcceptInvite: vi.fn(),
  apiGetInvitePreview: vi.fn(),
}));

const auth = vi.hoisted(() => ({
  user: null as { email: string; organizations?: { id: string; role?: string }[] } | null,
  loading: false,
  accessToken: "tok" as string | null,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("@/components/auth-layout", () => ({
  AuthLayout: ({
    title,
    children,
    footer,
  }: {
    title: string;
    children: ReactNode;
    footer?: ReactNode;
  }) => (
    <div>
      <h1>{title}</h1>
      <div>{children}</div>
      {footer ? <p>{footer}</p> : null}
    </div>
  ),
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: auth.user,
    loading: auth.loading,
    accessToken: auth.accessToken,
    logout,
    refreshAccessToken,
  }),
}));

vi.mock("@/features/company-settings/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/features/company-settings/api")>();
  return { ...actual, apiAcceptInvite, apiGetInvitePreview };
});

function renderInvite(token = "abc") {
  return render(
    <MemoryRouter initialEntries={[`/invite/${token}`]}>
      <Routes>
        <Route path="/invite/:token" element={<InviteAcceptPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function expectBefore(earlier: HTMLElement, later: HTMLElement) {
  expect(earlier.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
}

describe("InviteAcceptPage", () => {
  beforeEach(() => {
    auth.user = null;
    auth.loading = false;
    logout.mockClear();
    refreshAccessToken.mockClear();
    apiAcceptInvite.mockReset();
    apiGetInvitePreview.mockReset();
    apiGetInvitePreview.mockResolvedValue({
      email: "ada@example.com",
      company_name: "Test Co",
    });
  });

  it("logged out: register then login, both with next=", async () => {
    renderInvite("tok-1");
    const register = await screen.findByRole("link", { name: "invite.register" });
    const login = screen.getByRole("link", { name: "invite.login" });
    expect(register).toHaveAttribute("href", "/register?next=%2Finvite%2Ftok-1");
    expect(login).toHaveAttribute("href", "/login?next=%2Finvite%2Ftok-1");
    expectBefore(register, login);
  });

  it("invalid preview: show invalid copy", async () => {
    apiGetInvitePreview.mockRejectedValue(new ApiStatusError(400, "expired"));
    renderInvite();
    expect(await screen.findByRole("heading", { name: "invite.invalidTitle" })).toBeInTheDocument();
  });

  it("logged in: warn replace, return home then join", async () => {
    auth.user = { email: "ada@example.com", organizations: [{ id: "solo", role: "owner" }] };
    renderInvite();
    expect(await screen.findByRole("alert")).toHaveTextContent("invite.replaceWarning");
    const email = screen.getByDisplayValue("ada@example.com");
    expect(email).toHaveAttribute("readOnly");
    expect(email).not.toBeDisabled();
    const home = screen.getByRole("link", { name: "invite.home" });
    const join = screen.getByRole("button", { name: "invite.join" });
    expectBefore(home, join);
  });

  it("logged in member of a team: no replace warning", async () => {
    auth.user = { email: "ada@example.com", organizations: [{ id: "team", role: "member" }] };
    renderInvite();
    expect(await screen.findByDisplayValue("ada@example.com")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("logged in with matching email ignoring case: Join, not mismatch", async () => {
    auth.user = { email: "Ada@Example.com" };
    renderInvite();
    expect(await screen.findByRole("button", { name: "invite.join" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "invite.mismatchTitle" })).not.toBeInTheDocument();
  });

  it("join 409: already in a company", async () => {
    auth.user = { email: "ada@example.com", organizations: [{ id: "team", role: "member" }] };
    apiAcceptInvite.mockRejectedValue(new ApiStatusError(409, "conflict"));
    renderInvite();
    await userEvent.click(await screen.findByRole("button", { name: "invite.join" }));
    expect(await screen.findByRole("heading", { name: "invite.conflictTitle" })).toBeInTheDocument();
    expect(apiAcceptInvite).toHaveBeenCalled();
  });

  it("join 400: invite no longer valid", async () => {
    auth.user = { email: "ada@example.com" };
    apiAcceptInvite.mockRejectedValue(new ApiStatusError(400, "expired"));
    renderInvite();
    await userEvent.click(await screen.findByRole("button", { name: "invite.join" }));
    expect(await screen.findByRole("heading", { name: "invite.invalidTitle" })).toBeInTheDocument();
  });

  it("logged in with a different email: mismatch without Join", async () => {
    auth.user = { email: "other@example.com" };
    const { unmount } = renderInvite();
    expect(await screen.findByRole("heading", { name: "invite.mismatchTitle" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("invite.mismatchBody");
    expect(screen.queryByDisplayValue("other@example.com")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "invite.join" })).not.toBeInTheDocument();
    const home = screen.getByRole("link", { name: "invite.home" });
    const signOut = screen.getByRole("button", { name: "auth.logout" });
    expectBefore(home, signOut);

    logout.mockImplementation(async () => {
      auth.user = null;
    });
    await userEvent.click(signOut);
    expect(logout).toHaveBeenCalled();
    unmount();
    renderInvite();
    expect(await screen.findByRole("heading", { name: "invite.loggedOutTitle" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "invite.login" })).toBeInTheDocument();
  });
});
