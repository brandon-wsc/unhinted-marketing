import { CheckIcon, ChevronDownIcon } from "lucide-react";
import { type KeyboardEvent, useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export type ComboboxOption = {
  value: string;
  label: string;
  disabled?: boolean;
};

export type ComboboxProps = {
  id?: string;
  value: string;
  onValueChange: (value: string) => void;
  options: ComboboxOption[];
  placeholder?: string;
  emptyText?: string;
  disabled?: boolean;
  className?: string;
};

function optionMatches(option: ComboboxOption, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return option.label.toLowerCase().includes(needle) || option.value.toLowerCase().includes(needle);
}

/** Input-first combobox: typing is the value; the list below filters as you type. */
export function Combobox({
  id,
  value,
  onValueChange,
  options,
  placeholder,
  emptyText,
  disabled,
  className,
}: ComboboxProps) {
  const { t } = useTranslation();
  const listId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);

  const filtered = useMemo(
    () => options.filter((option) => optionMatches(option, value)),
    [options, value],
  );
  const showList = options.length > 0 && open && !disabled;
  const active = filtered[activeIndex];

  function openList() {
    if (!options.length || disabled) return;
    setOpen(true);
    setActiveIndex(0);
  }

  function selectOption(option: ComboboxOption) {
    if (option.disabled) return;
    onValueChange(option.value);
    setOpen(false);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!options.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) {
        openList();
        return;
      }
      setActiveIndex((current) => (current + 1) % Math.max(filtered.length, 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        openList();
        return;
      }
      setActiveIndex((current) => (current <= 0 ? Math.max(filtered.length - 1, 0) : current - 1));
      return;
    }
    if (event.key === "Enter" && open && active && !active.disabled) {
      event.preventDefault();
      selectOption(active);
      return;
    }
    if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
    }
  }

  useEffect(() => {
    if (!showList) return;
    function onPointerDown(event: PointerEvent) {
      if (rootRef.current?.contains(event.target as Node)) return;
      setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [showList]);

  return (
    <div ref={rootRef} className={cn("relative", showList && "z-10", className)}>
      <Input
        id={id}
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showList && active ? `${listId}-opt-${active.value}` : undefined}
        disabled={disabled}
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        className="pr-8"
        onFocus={openList}
        onChange={(event) => {
          onValueChange(event.target.value);
          setActiveIndex(0);
          if (options.length && !disabled) setOpen(true);
        }}
        onKeyDown={onKeyDown}
      />
      {options.length > 0 ? (
        <ChevronDownIcon
          aria-hidden
          className="pointer-events-none absolute top-1/2 right-2 size-4 -translate-y-1/2 text-muted-foreground opacity-50"
        />
      ) : null}
      {showList ? (
        <div
          id={listId}
          role="listbox"
          className="absolute z-50 mt-1 max-h-60 w-full overflow-y-auto overscroll-contain rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-md dark:border-white/10"
        >
          {filtered.length === 0 ? (
            <div className="px-2 py-1.5 text-sm text-muted-foreground">
              {emptyText ?? t("common.noMatches")}
            </div>
          ) : (
            filtered.map((option, index) => {
              const selected = option.value === value;
              const highlighted = index === activeIndex;
              return (
                <div
                  key={option.value}
                  ref={
                    highlighted
                      ? (node) => {
                          node?.scrollIntoView?.({ block: "nearest" });
                        }
                      : undefined
                  }
                  id={`${listId}-opt-${option.value}`}
                  role="option"
                  tabIndex={-1}
                  aria-selected={selected}
                  aria-disabled={option.disabled || undefined}
                  className={cn(
                    "relative flex cursor-default items-center gap-2 rounded-sm py-1.5 pr-8 pl-2 text-sm outline-hidden select-none",
                    option.disabled && "pointer-events-none opacity-50",
                    highlighted && "bg-accent text-accent-foreground",
                  )}
                  onMouseEnter={() => setActiveIndex(index)}
                  onPointerDown={(event) => event.preventDefault()}
                  onClick={() => selectOption(option)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      selectOption(option);
                    }
                  }}
                >
                  <span className="min-w-0 flex-1 truncate">{option.label}</span>
                  {selected ? (
                    <CheckIcon className="absolute right-2 size-4 text-muted-foreground" />
                  ) : null}
                </div>
              );
            })
          )}
        </div>
      ) : null}
    </div>
  );
}
