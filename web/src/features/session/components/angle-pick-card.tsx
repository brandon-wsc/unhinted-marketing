import { CornerDownLeft } from "lucide-react";
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { IconButton } from "@/components/icon-button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { FormatToggle, type ImageFormat } from "@/features/session/components/format-toggle";
import type { AudiencePersonaOption } from "@/features/session/types";
import { cn } from "@/lib/utils";

type Props = {
  angles: string[];
  personas?: AudiencePersonaOption[];
  recommendedPersona?: string | null;
  recommendedImageFormat?: ImageFormat | null;
  sending: boolean;
  onPick: (angle: number | string, persona?: string, imageFormat?: ImageFormat) => void;
};

// Highlight follows `active` (hover/arrow/focus all move it), not DOM focus —
// one row shows border + wash + ring at a time, like a listbox activedescendant.
const ACTIVE_CLASS = "border-voice-border bg-accent ring-1 ring-ring";

function fallbackPersona(
  personas: AudiencePersonaOption[],
  recommended: string | null | undefined,
): string {
  if (recommended && personas.some((p) => p.slug === recommended)) return recommended;
  return personas[0]?.slug ?? "";
}

function fallbackFormat(recommended: ImageFormat | null | undefined): ImageFormat {
  return recommended === "comic_4panel" ? "comic_4panel" : "single";
}

const EMPTY_PERSONAS: AudiencePersonaOption[] = [];

export function AnglePickCard({
  angles,
  personas = EMPTY_PERSONAS,
  recommendedPersona = null,
  recommendedImageFormat = null,
  sending,
  onPick,
}: Props) {
  const { t } = useTranslation();
  const [other, setOther] = useState("");
  // 0..angles.length-1 = options; angles.length = the "other" input row.
  const [active, setActive] = useState(0);
  const [persona, setPersona] = useState(() => fallbackPersona(personas, recommendedPersona));
  const [imageFormat, setImageFormat] = useState<ImageFormat>(() =>
    fallbackFormat(recommendedImageFormat),
  );
  const listRef = useRef<HTMLUListElement>(null);
  const otherInputRef = useRef<HTMLInputElement>(null);

  // Focus the first option when the card appears with fresh angles.
  useEffect(() => {
    setActive(0);
    setPersona(fallbackPersona(personas, recommendedPersona));
    setImageFormat(fallbackFormat(recommendedImageFormat));
    if (angles.length > 0) listRef.current?.querySelector("button")?.focus();
  }, [angles, personas, recommendedPersona, recommendedImageFormat]);

  if (angles.length === 0) return null;

  const itemCount = angles.length + 1;
  const selectedPersona = personas.length > 0 ? persona || undefined : undefined;

  function emitPick(angle: number | string) {
    onPick(angle, selectedPersona, imageFormat);
  }

  // disabled 擋 click/focus 但 pointerenter 仲會 fire — sending 時唔郁 highlight。
  function activate(idx: number) {
    if (!sending) setActive(idx);
  }

  function focusAt(idx: number) {
    const items = [
      ...Array.from(listRef.current?.querySelectorAll<HTMLElement>(":scope > li > button") ?? []),
      ...(otherInputRef.current ? [otherInputRef.current] : []),
    ];
    items[idx]?.focus();
  }

  function moveActive(delta: number) {
    const next = (active + delta + itemCount) % itemCount;
    setActive(next);
    focusAt(next);
  }

  function onNavKeyDown(e: KeyboardEvent<HTMLElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      moveActive(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      moveActive(-1);
    } else if (e.key === "Escape" && e.target === otherInputRef.current) {
      const last = angles.length - 1;
      setActive(last);
      focusAt(last);
    }
  }

  function onSubmitOther(e: FormEvent) {
    e.preventDefault();
    const text = other.trim();
    if (text) emitPick(text);
  }

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-voice-border bg-card p-4 text-sm shadow-sm">
      <div>
        <p className="font-medium text-foreground">{t("chat.agent.anglePick.title")}</p>
        <p className="mt-0.5 text-muted-foreground">{t("chat.agent.anglePick.subtitle")}</p>
      </div>
      {personas.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="angle-pick-persona">{t("chat.agent.anglePick.personaLabel")}</Label>
          <Select value={persona} onValueChange={setPersona} disabled={sending}>
            <SelectTrigger id="angle-pick-persona" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {personas.map((row) => (
                <SelectItem key={row.slug} value={row.slug}>
                  {row.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      <div className="flex flex-col gap-1.5">
        <Label>{t("chat.agent.anglePick.formatLabel")}</Label>
        <FormatToggle
          value={imageFormat}
          onChange={setImageFormat}
          disabled={sending}
          groupLabel={t("chat.agent.anglePick.formatLabel")}
        />
      </div>
      <ul
        ref={listRef}
        className="flex flex-col gap-2"
        aria-label={t("chat.agent.anglePick.optionsLabel")}
      >
        {angles.map((angle, i) => (
          <li key={angle}>
            {/* Native row: the shared Button's own hover wash would fight the
                single `active` highlight — the ring already marks focus. */}
            <button
              type="button"
              disabled={sending}
              onClick={() => emitPick(i)}
              onKeyDown={onNavKeyDown}
              onPointerEnter={() => activate(i)}
              onFocus={() => activate(i)}
              className={cn(
                "flex w-full items-baseline gap-2 rounded-lg border border-input px-3 py-3 text-left text-foreground transition focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50",
                i === active && ACTIVE_CLASS,
              )}
            >
              <span className="font-medium text-muted-foreground">{i + 1}.</span>
              {angle}
            </button>
          </li>
        ))}
        <li>
          {/* Field chrome lives on the row (composer pattern): rest border-input,
              hover border-voice-border, active/focus ring via ACTIVE_CLASS. */}
          <form
            onSubmit={onSubmitOther}
            onPointerEnter={() => activate(angles.length)}
            className={cn(
              "flex items-center gap-1.5 rounded-lg border bg-card transition",
              active === angles.length ? ACTIVE_CLASS : "border-input hover:border-voice-border",
            )}
          >
            <input
              ref={otherInputRef}
              type="text"
              value={other}
              onChange={(e) => setOther(e.target.value)}
              onKeyDown={onNavKeyDown}
              onFocus={() => activate(angles.length)}
              disabled={sending}
              placeholder={t("chat.agent.anglePick.otherPlaceholder")}
              aria-label={t("chat.agent.anglePick.otherLabel")}
              className="h-11 flex-1 bg-transparent px-3 text-foreground outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
            />
            <IconButton
              type="submit"
              className="mr-1.5 h-7 w-7"
              disabled={sending || !other.trim()}
              onFocus={() => activate(angles.length)}
              title={t("chat.agent.anglePick.otherSubmit")}
              aria-label={t("chat.agent.anglePick.otherSubmit")}
            >
              <CornerDownLeft className="size-3.5" />
            </IconButton>
          </form>
        </li>
      </ul>
      {sending && (
        <p role="status" className="text-xs text-muted-foreground">
          {t("chat.agent.anglePick.working")}
        </p>
      )}
    </div>
  );
}
