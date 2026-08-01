import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UserMenuDropdown } from "@/components/user-menu-dropdown";

const { changeLanguage, setMode, logout } = vi.hoisted(() => ({
  changeLanguage: vi.fn(),
  setMode: vi.fn(),
  logout: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("@/i18n", () => ({
  default: { changeLanguage },
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: {
      id: "u1",
      email: "ada@example.com",
      display_name: "Ada",
      is_active: true,
      created_at: "",
      organizations: [],
    },
    logout,
  }),
}));

vi.mock("@/context/theme-context", () => ({
  useTheme: () => ({
    mode: "light",
    resolved: "light",
    setMode,
  }),
}));

describe("UserMenuDropdown", () => {
  beforeEach(() => {
    changeLanguage.mockClear();
    setMode.mockClear();
    logout.mockClear();
  });

  it("opens and closes the menu", async () => {
    const user = userEvent.setup();
    render(<UserMenuDropdown />);

    const trigger = screen.getByRole("button", { name: /Ada/i });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await user.click(trigger);
    expect(screen.getByRole("menu")).toBeInTheDocument();

    await user.click(trigger);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("calls setMode when a theme option is selected", async () => {
    const user = userEvent.setup();
    render(<UserMenuDropdown />);

    await user.click(screen.getByRole("button", { name: /Ada/i }));
    await user.click(screen.getByRole("menuitemradio", { name: "theme.dark" }));

    expect(setMode).toHaveBeenCalledWith("dark");
  });

  it("calls changeLanguage when a locale is selected", async () => {
    const user = userEvent.setup();
    render(<UserMenuDropdown />);

    await user.click(screen.getByRole("button", { name: /Ada/i }));
    await user.click(screen.getByRole("menuitemradio", { name: "繁體中文（香港）" }));

    expect(changeLanguage).toHaveBeenCalledWith("zh-HK");
  });
});
