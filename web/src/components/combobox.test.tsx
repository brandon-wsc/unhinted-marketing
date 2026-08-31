import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Combobox, type ComboboxOption } from "@/components/combobox";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

const OPTIONS: ComboboxOption[] = [
  { value: "gpt-4o", label: "gpt-4o" },
  { value: "gpt-4o-mini", label: "gpt-4o-mini" },
  { value: "seedream", label: "seedream" },
];

function Harness({
  options = OPTIONS,
  initial = "",
}: {
  options?: ComboboxOption[];
  initial?: string;
}) {
  const [value, setValue] = useState(initial);
  return (
    <Combobox
      id="model"
      value={value}
      onValueChange={setValue}
      options={options}
      placeholder="pick"
    />
  );
}

describe("Combobox", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
  });

  it("keeps typed text as the value", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByRole("combobox");
    await user.type(input, "my-custom-id");
    expect(input).toHaveValue("my-custom-id");
  });

  it("filters options as you type", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByRole("combobox");
    await user.click(input);
    const list = await screen.findByRole("listbox");
    expect(within(list).getByRole("option", { name: /^gpt-4o$/ })).toBeInTheDocument();
    expect(within(list).getByRole("option", { name: "seedream" })).toBeInTheDocument();
    await user.type(input, "seed");
    const filtered = await screen.findByRole("listbox");
    expect(within(filtered).getByRole("option", { name: "seedream" })).toBeInTheDocument();
    expect(within(filtered).queryByRole("option", { name: /^gpt-4o$/ })).not.toBeInTheDocument();
  });

  it("fills the input when an option is chosen", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: "gpt-4o-mini" }));
    expect(screen.getByRole("combobox")).toHaveValue("gpt-4o-mini");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("shows empty copy when nothing matches, without clearing the typed value", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByRole("combobox");
    await user.type(input, "not-a-model");
    expect(input).toHaveValue("not-a-model");
    expect(await screen.findByText("common.noMatches")).toBeInTheDocument();
  });

  it("is a plain input when there are no options", async () => {
    const user = userEvent.setup();
    render(<Harness options={[]} />);
    const input = screen.getByRole("combobox");
    await user.type(input, "typed-id");
    expect(input).toHaveValue("typed-id");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("keeps the list in the field so dialog scroll lock cannot swallow wheel", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByRole("combobox");
    await user.click(input);
    const list = await screen.findByRole("listbox");
    expect(input.parentElement).toContainElement(list);
    expect(list.className).toMatch(/overflow-y-auto/);
  });

  it("closes the list on outside pointer down", async () => {
    const user = userEvent.setup();
    render(
      <div>
        <Harness />
        <button type="button">outside</button>
      </div>,
    );
    await user.click(screen.getByRole("combobox"));
    expect(await screen.findByRole("listbox")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "outside" }));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
