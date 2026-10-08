import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useHorizontalOverflow } from "./use-horizontal-overflow";

function Row() {
  const o = useHorizontalOverflow('[aria-current="page"]');
  return (
    <>
      <div data-testid="row" ref={o.ref} />
      <output>{`${o.start}/${o.end}/${o.overflowing}`}</output>
    </>
  );
}

function size(el: HTMLElement, clientWidth: number, scrollWidth: number) {
  Object.defineProperty(el, "clientWidth", { configurable: true, value: clientWidth });
  Object.defineProperty(el, "scrollWidth", { configurable: true, value: scrollWidth });
}

describe("useHorizontalOverflow", () => {
  it("reports no edges when content fits", () => {
    render(<Row />);
    expect(screen.getByRole("status").textContent).toBe("false/false/false");
  });

  it("tracks hidden content on each edge as the row scrolls", () => {
    render(<Row />);
    const row = screen.getByTestId("row");
    size(row, 100, 300);

    act(() => {
      fireEvent.scroll(row);
    });
    expect(screen.getByRole("status").textContent).toBe("false/true/true");

    act(() => {
      row.scrollLeft = 200;
      fireEvent.scroll(row);
    });
    expect(screen.getByRole("status").textContent).toBe("true/false/true");
  });
});
