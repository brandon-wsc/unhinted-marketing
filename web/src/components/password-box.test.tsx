import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PasswordBox } from "@/components/password-box";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

describe("PasswordBox", () => {
  it("renders the label", () => {
    render(<PasswordBox id="password" label="Password" value="" onChange={() => {}} />);
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("toggles input type between password and text", async () => {
    const user = userEvent.setup();
    render(<PasswordBox id="password" label="Password" value="secret" onChange={() => {}} />);

    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");

    const toggle = screen.getByRole("button", { name: "common.showPassword" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");

    await user.click(toggle);
    expect(input).toHaveAttribute("type", "text");
    expect(toggle).toHaveAttribute("aria-label", "common.hidePassword");
    expect(toggle).toHaveAttribute("aria-pressed", "true");

    await user.click(toggle);
    expect(input).toHaveAttribute("type", "password");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
  });
});
