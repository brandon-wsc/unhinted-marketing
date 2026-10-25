import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PasswordPanel } from "@/features/account/components/password-panel";

const { apiChangePassword, apiVerifyPassword } = vi.hoisted(() => ({
  apiChangePassword: vi.fn().mockResolvedValue(undefined),
  apiVerifyPassword: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ accessToken: "tok-access" }),
}));

vi.mock("@/lib/api", () => ({
  apiVerifyPassword,
  apiChangePassword,
}));

async function typeCurrent(user: ReturnType<typeof userEvent.setup>, password = "password123") {
  await user.type(screen.getByLabelText("account.password.currentLabel"), password);
  await user.click(screen.getByRole("button", { name: "account.password.verify" }));
}

async function verifyCurrent(user: ReturnType<typeof userEvent.setup>, password = "password123") {
  await typeCurrent(user, password);
  await screen.findByLabelText("account.password.newLabel");
}

describe("PasswordPanel", () => {
  beforeEach(() => {
    apiVerifyPassword.mockClear().mockResolvedValue(undefined);
    apiChangePassword.mockClear().mockResolvedValue(undefined);
  });

  it("starts on step 1 with only the current password", () => {
    render(<PasswordPanel />);

    expect(screen.getByLabelText("account.password.currentLabel")).toBeInTheDocument();
    expect(screen.queryByLabelText("account.password.newLabel")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "account.password.verify" })).toBeInTheDocument();
  });

  it("blocks an empty current password before calling the API", async () => {
    const user = userEvent.setup();
    render(<PasswordPanel />);

    await user.click(screen.getByRole("button", { name: "account.password.verify" }));

    expect(apiVerifyPassword).not.toHaveBeenCalled();
    expect(screen.getByText("errors.currentPasswordRequired")).toBeInTheDocument();
  });

  it("shows a field error when the current password is wrong", async () => {
    const user = userEvent.setup();
    apiVerifyPassword.mockRejectedValueOnce(new Error("Current password is incorrect"));
    render(<PasswordPanel />);

    await typeCurrent(user, "wrong-password");

    expect(apiVerifyPassword).toHaveBeenCalledWith("tok-access", "wrong-password");
    expect(await screen.findByText("errors.currentPasswordIncorrect")).toBeInTheDocument();
    expect(screen.queryByLabelText("account.password.newLabel")).not.toBeInTheDocument();
  });

  it("unlocks step 2 after a successful verify", async () => {
    const user = userEvent.setup();
    render(<PasswordPanel />);

    await verifyCurrent(user);

    expect(apiVerifyPassword).toHaveBeenCalledWith("tok-access", "password123");
    expect(screen.getByLabelText("account.password.newLabel")).toBeInTheDocument();
    expect(screen.getByLabelText("account.password.confirmLabel")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "account.password.submit" })).toBeInTheDocument();
  });

  it("rejects a too-short new password without calling the API", async () => {
    const user = userEvent.setup();
    render(<PasswordPanel />);

    await verifyCurrent(user);
    await user.type(screen.getByLabelText("account.password.newLabel"), "short");
    await user.type(screen.getByLabelText("account.password.confirmLabel"), "short");
    await user.click(screen.getByRole("button", { name: "account.password.submit" }));

    expect(apiChangePassword).not.toHaveBeenCalled();
    expect(screen.getByText("errors.passwordTooShort")).toBeInTheDocument();
  });

  it("rejects mismatched confirmation without calling the API", async () => {
    const user = userEvent.setup();
    render(<PasswordPanel />);

    await verifyCurrent(user);
    await user.type(screen.getByLabelText("account.password.newLabel"), "newpassword456");
    await user.type(screen.getByLabelText("account.password.confirmLabel"), "different789");
    await user.click(screen.getByRole("button", { name: "account.password.submit" }));

    expect(apiChangePassword).not.toHaveBeenCalled();
    expect(screen.getByText("errors.passwordMismatch")).toBeInTheDocument();
  });

  it("submits current + new passwords and returns to step 1 on success", async () => {
    const user = userEvent.setup();
    render(<PasswordPanel />);

    await verifyCurrent(user);
    await user.type(screen.getByLabelText("account.password.newLabel"), "newpassword456");
    await user.type(screen.getByLabelText("account.password.confirmLabel"), "newpassword456");
    await user.click(screen.getByRole("button", { name: "account.password.submit" }));

    expect(apiChangePassword).toHaveBeenCalledWith("tok-access", {
      current_password: "password123",
      new_password: "newpassword456",
    });
    expect(screen.getByText("account.password.saved")).toBeInTheDocument();
    expect(screen.getByLabelText("account.password.currentLabel")).toBeInTheDocument();
    expect(screen.queryByLabelText("account.password.newLabel")).not.toBeInTheDocument();
  });

  it("returns to step 1 with a field error when the server re-check fails", async () => {
    const user = userEvent.setup();
    apiChangePassword.mockRejectedValueOnce(new Error("Current password is incorrect"));
    render(<PasswordPanel />);

    await verifyCurrent(user);
    await user.type(screen.getByLabelText("account.password.newLabel"), "newpassword456");
    await user.type(screen.getByLabelText("account.password.confirmLabel"), "newpassword456");
    await user.click(screen.getByRole("button", { name: "account.password.submit" }));

    expect(apiChangePassword).toHaveBeenCalledWith("tok-access", {
      current_password: "password123",
      new_password: "newpassword456",
    });
    expect(screen.getByText("errors.currentPasswordIncorrect")).toBeInTheDocument();
    expect(screen.getByLabelText("account.password.currentLabel")).toBeInTheDocument();
    expect(screen.queryByLabelText("account.password.newLabel")).not.toBeInTheDocument();
  });

  it("keeps the typed current password when verify fails", async () => {
    const user = userEvent.setup();
    apiVerifyPassword.mockRejectedValueOnce(new Error("Current password is incorrect"));
    render(<PasswordPanel />);

    await typeCurrent(user, "wrong-password");

    expect(screen.getByLabelText("account.password.currentLabel")).toHaveValue("wrong-password");
    expect(await screen.findByText("errors.currentPasswordIncorrect")).toBeInTheDocument();
  });
});
