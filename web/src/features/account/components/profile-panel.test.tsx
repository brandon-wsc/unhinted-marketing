import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProfilePanel } from "@/features/account/components/profile-panel";

const { updateDisplayName } = vi.hoisted(() => ({
  updateDisplayName: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

const mockUser = {
  id: "u1",
  email: "ada@example.com",
  display_name: "Ada",
  is_active: true,
  platform_level: 3,
  created_at: "2026-01-15T08:30:00Z",
  organizations: [{ id: "o1", name: "Ada Co", slug: "ada-co", role: "owner" }],
};

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: mockUser,
    updateDisplayName,
  }),
}));

describe("ProfilePanel", () => {
  beforeEach(() => {
    updateDisplayName.mockClear();
  });

  it("renders the user profile", () => {
    render(<ProfilePanel />);

    expect(screen.getByLabelText("auth.register.displayName")).toHaveValue("Ada");
    expect(screen.getByLabelText("common.email")).toHaveValue("ada@example.com");
    expect(screen.getByLabelText("common.email")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("account.profile.joined")).toHaveValue("2026-01-15");
    expect(screen.getByText("Ada Co")).toBeInTheDocument();
    expect(screen.getByText("settings.members.roles.owner")).toBeInTheDocument();
  });

  it("saves a new display name", async () => {
    const user = userEvent.setup();
    render(<ProfilePanel />);

    const input = screen.getByLabelText("auth.register.displayName");
    await user.clear(input);
    await user.type(input, "  Ada Lovelace  ");
    await user.click(screen.getByRole("button", { name: "account.profile.save" }));

    expect(updateDisplayName).toHaveBeenCalledWith("Ada Lovelace");
  });

  it("keeps save disabled while the name is unchanged", () => {
    render(<ProfilePanel />);

    expect(screen.getByRole("button", { name: "account.profile.save" })).toBeDisabled();
  });

  it("blocks a blank name before calling the API", async () => {
    const user = userEvent.setup();
    render(<ProfilePanel />);

    const input = screen.getByLabelText("auth.register.displayName");
    await user.clear(input);
    await user.click(screen.getByRole("button", { name: "account.profile.save" }));

    expect(updateDisplayName).not.toHaveBeenCalled();
    expect(screen.getByText("errors.displayNameRequired")).toBeInTheDocument();
  });
});
