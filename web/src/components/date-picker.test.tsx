import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DatePicker, fromLocalDate, toLocalDate } from "@/components/date-picker";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

describe("DatePicker", () => {
  it("shows the empty placeholder", () => {
    render(<DatePicker value={undefined} onChange={() => {}} />);
    expect(screen.getByRole("button", { name: /common.datePlaceholder/ })).toBeInTheDocument();
  });

  it("formats a chosen local date as yyyy-MM-dd", () => {
    render(<DatePicker value={new Date(2027, 0, 15)} onChange={() => {}} />);
    expect(screen.getByRole("button", { name: /2027-01-15/ })).toBeInTheDocument();
  });

  it("calls onChange when a day is picked", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<DatePicker value={undefined} onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: /common.datePlaceholder/ }));
    const today = await waitFor(() => {
      const button = document.querySelector("[data-today] button");
      expect(button).toBeTruthy();
      return button as HTMLElement;
    });
    await user.click(today);

    expect(onChange).toHaveBeenCalledTimes(1);
    const picked = onChange.mock.calls[0]?.[0] as Date;
    expect(picked).toBeInstanceOf(Date);
    expect(Number.isNaN(picked.getTime())).toBe(false);
  });

  it("clears the value", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<DatePicker value={new Date(2027, 0, 15)} onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: "common.clear" }));
    expect(onChange).toHaveBeenCalledWith(undefined);
  });
});

describe("local date ISO helpers", () => {
  it("round-trips a local calendar date without UTC day shift", () => {
    const date = new Date(2027, 5, 1);
    const iso = fromLocalDate(date);
    expect(iso).toBeTruthy();
    const back = toLocalDate(iso);
    expect(back?.getFullYear()).toBe(2027);
    expect(back?.getMonth()).toBe(5);
    expect(back?.getDate()).toBe(1);
  });

  it("returns undefined / null for empty input", () => {
    expect(toLocalDate(null)).toBeUndefined();
    expect(fromLocalDate(undefined)).toBeNull();
  });
});
