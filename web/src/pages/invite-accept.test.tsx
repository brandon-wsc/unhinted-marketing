import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiStatusError } from "@/features/company-settings/api";
import { InviteAcceptPage } from "@/pages/invite-accept";

const { logout, refreshAccessToken, apiAcceptInvite } = vi.hoisted(() => ({
  logout: vi.fn().mockResolvedValue(undefined),
  refreshAccessToken: vi.fn().mockResolvedValue("tok"),
  apiAcceptInvite: vi.fn(),
}));

const auth = vi.hoisted(() => ({
  user: null as { email: string } | null,
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
  return { ...actual, apiAcceptInvite };
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
  });

  it("logged out: register then login, both with next=", () => {
    renderInvite("tok-1");
    const register = screen.getByRole("link", { name: "invite.register" });
    const login = screen.getByRole("link", { name: "invite.login" });
    expect(register).toHaveAttribute("href", "/register?next=%2Finvite%2Ftok-1");
    expect(login).toHaveAttribute("href", "/login?next=%2Finvite%2Ftok-1");
    expectBefore(register, login);
  });

  it("logged in: return home then join", () => {
    auth.user = { email: "ada@example.com" };
    renderInvite();
    expect(screen.getByDisplayValue("ada@example.com")).toHaveAttribute("readOnly");
    expect(screen.getByDisplayValue("ada@example.com")).not.toBeDisabled();
    const home = screen.getByRole("link", { name: "invite.home" });
    const join = screen.getByRole("button", { name: "invite.join" });
    expectBefore(home, join);
  });

  it("403 mismatch: return home then switch account", async () => {
    auth.user = { email: "other@example.com" };
    apiAcceptInvite.mockRejectedValue(new ApiStatusError(403, "mismatch"));
    const user = userEvent.setup();
    renderInvite();
    await user.click(screen.getByRole("button", { name: "invite.join" }));
    const home = screen.getByRole("link", { name: "invite.home" });
    const switchAccount = screen.getByRole("button", { name: "invite.logoutRelogin" });
    expectBefore(home, switchAccount);
  });
});
