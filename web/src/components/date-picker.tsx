import { format } from "date-fns";
import { Calendar as CalendarIcon, X } from "lucide-react";
import { useState } from "react";
import { enUS, zhHK } from "react-day-picker/locale";
import { useTranslation } from "react-i18next";
import { IconButton } from "@/components/icon-button";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export type DatePickerProps = {
  id?: string;
  value?: Date;
  onChange: (date: Date | undefined) => void;
  placeholder?: string;
  disabled?: boolean;
};

const DROPDOWN_START = new Date(2018, 0);
const DROPDOWN_END = new Date(2100, 11);

/** Local calendar date from an ISO timestamp (avoids UTC date-only shift). */
export function toLocalDate(iso: string | null): Date | undefined {
  if (!iso) return undefined;
  const stamp = new Date(iso);
  if (Number.isNaN(stamp.getTime())) return undefined;
  return new Date(stamp.getFullYear(), stamp.getMonth(), stamp.getDate());
}

/** Persist a local calendar date as ISO at local midnight. */
export function fromLocalDate(date: Date | undefined): string | null {
  if (!date) return null;
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).toISOString();
}

export function DatePicker({ id, value, onChange, placeholder, disabled }: DatePickerProps) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const locale = i18n.language === "en" ? enUS : zhHK;
  const emptyLabel = placeholder ?? t("common.datePlaceholder");

  return (
    <div className="relative">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            id={id}
            type="button"
            variant="outline"
            disabled={disabled}
            data-empty={!value}
            className={cn(
              "h-9 w-full justify-start border-input bg-transparent px-3 font-normal shadow-xs hover:enabled:border-voice-border hover:enabled:bg-transparent hover:enabled:text-foreground focus-visible:border-ring focus-visible:ring-1 data-[state=open]:border-ring data-[state=open]:ring-1 data-[state=open]:ring-ring data-[empty=true]:text-muted-foreground dark:bg-input/30",
              value && "pr-10",
            )}
          >
            <CalendarIcon />
            {value ? format(value, "yyyy-MM-dd") : emptyLabel}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          <Calendar
            mode="single"
            selected={value}
            onSelect={(date) => {
              onChange(date);
              if (date) setOpen(false);
            }}
            captionLayout="dropdown"
            locale={locale}
            defaultMonth={value}
            startMonth={DROPDOWN_START}
            endMonth={DROPDOWN_END}
          />
        </PopoverContent>
      </Popover>
      {value ? (
        <IconButton
          type="button"
          aria-label={t("common.clear")}
          className="absolute top-1/2 right-1 h-7 w-7 -translate-y-1/2"
          onClick={() => {
            onChange(undefined);
            setOpen(false);
          }}
        >
          <X />
        </IconButton>
      ) : null}
    </div>
  );
}
