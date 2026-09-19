import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AnglePickCard } from "@/features/session/components/angle-pick-card";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const ANGLES = ["Angle one", "Angle two", "Angle three"];

describe("AnglePickCard", () => {
  it("renders nothing when no angles are offered", () => {
    const { container } = render(<AnglePickCard angles={[]} sending={false} onPick={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders each offered angle as a pickable option", () => {
    render(<AnglePickCard angles={ANGLES} sending={false} onPick={vi.fn()} />);
    for (const angle of ANGLES) {
      expect(screen.getByRole("button", { name: new RegExp(angle) })).toBeEnabled();
    }
  });

  it("calls onPick with the option index", async () => {
    const onPick = vi.fn();
    const user = userEvent.setup();
    render(<AnglePickCard angles={ANGLES} sending={false} onPick={onPick} />);
    await user.click(screen.getByRole("button", { name: /Angle two/ }));
    expect(onPick).toHaveBeenCalledWith(1);
  });

  it("disables options while a pick is in flight", () => {
    render(<AnglePickCard angles={ANGLES} sending={true} onPick={vi.fn()} />);
    for (const angle of ANGLES) {
      expect(screen.getByRole("button", { name: new RegExp(angle) })).toBeDisabled();
    }
    expect(screen.getByText("chat.agent.anglePick.working")).toBeInTheDocument();
  });

  it("does not pick while sending", async () => {
    const onPick = vi.fn();
    const user = userEvent.setup();
    render(<AnglePickCard angles={ANGLES} sending={true} onPick={onPick} />);
    await user.click(screen.getByRole("button", { name: /Angle one/ }));
    expect(onPick).not.toHaveBeenCalled();
  });

  it("focuses the first option on mount", () => {
    render(<AnglePickCard angles={ANGLES} sending={false} onPick={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Angle one/ })).toHaveFocus();
  });

  it("arrow keys move focus through options and into the other input", async () => {
    const user = userEvent.setup();
    render(<AnglePickCard angles={ANGLES} sending={false} onPick={vi.fn()} />);
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("button", { name: /Angle two/ })).toHaveFocus();
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(screen.getByLabelText("chat.agent.anglePick.otherLabel")).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("button", { name: /Angle three/ })).toHaveFocus();
  });

  it("keeps a single highlight shared by hover and arrow keys", async () => {
    const user = userEvent.setup();
    render(<AnglePickCard angles={ANGLES} sending={false} onPick={vi.fn()} />);
    const one = screen.getByRole("button", { name: /Angle one/ });
    const two = screen.getByRole("button", { name: /Angle two/ });
    const three = screen.getByRole("button", { name: /Angle three/ });
    expect(one.className).toContain("bg-accent");
    expect(two.className).not.toContain("bg-accent");
    await user.hover(two);
    expect(two.className).toContain("bg-accent");
    expect(one.className).not.toContain("bg-accent");
    // Arrows continue from the hovered item, not the focused one.
    await user.keyboard("{ArrowDown}");
    expect(three).toHaveFocus();
    expect(three.className).toContain("bg-accent");
    expect(two.className).not.toContain("bg-accent");
  });

  it("moves the ring with the active row even when DOM focus stays in the input", async () => {
    const user = userEvent.setup();
    render(<AnglePickCard angles={ANGLES} sending={false} onPick={vi.fn()} />);
    const input = screen.getByLabelText("chat.agent.anglePick.otherLabel");
    await user.click(input);
    expect(input).toHaveFocus();
    await user.hover(screen.getByRole("button", { name: /Angle two/ }));
    const two = screen.getByRole("button", { name: /Angle two/ });
    expect(two.className).toContain("bg-accent");
    expect(two.className).toContain("ring-1");
    // Keystrokes still go to the input; only the highlight moved.
    expect(input).toHaveFocus();
  });

  it("does not move the highlight while sending", async () => {
    const user = userEvent.setup();
    render(<AnglePickCard angles={ANGLES} sending={true} onPick={vi.fn()} />);
    const one = screen.getByRole("button", { name: /Angle one/ });
    const two = screen.getByRole("button", { name: /Angle two/ });
    await user.hover(two);
    expect(one.className).toContain("bg-accent");
    expect(two.className).not.toContain("bg-accent");
  });

  it("submits typed custom angle text", async () => {
    const onPick = vi.fn();
    const user = userEvent.setup();
    render(<AnglePickCard angles={ANGLES} sending={false} onPick={onPick} />);
    await user.type(
      screen.getByLabelText("chat.agent.anglePick.otherLabel"),
      "  My own angle  {Enter}",
    );
    expect(onPick).toHaveBeenCalledWith("My own angle");
  });

  const PERSONAS = [
    { slug: "hk_youth", label: "年輕人", hook: "brunch" },
    { slug: "hk_parents", label: "家長", hook: "school run" },
  ];

  it("hides the persona select when the catalog is empty", () => {
    render(<AnglePickCard angles={ANGLES} sending={false} onPick={vi.fn()} />);
    expect(screen.queryByLabelText("chat.agent.anglePick.personaLabel")).not.toBeInTheDocument();
  });

  it("sends the recommended persona with an angle pick", async () => {
    const onPick = vi.fn();
    const user = userEvent.setup();
    render(
      <AnglePickCard
        angles={ANGLES}
        personas={PERSONAS}
        recommendedPersona="hk_youth"
        sending={false}
        onPick={onPick}
      />,
    );
    expect(screen.getByRole("combobox")).toHaveTextContent("年輕人");
    await user.click(screen.getByRole("button", { name: /Angle two/ }));
    expect(onPick).toHaveBeenCalledWith(1, "hk_youth");
  });
});
