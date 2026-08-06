import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { draftEquals } from "@/features/session/components/ig-preview-mock";
import type { DraftCopy } from "@/features/session/types";

function parseHashtags(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((h) => h.trim())
    .filter(Boolean)
    .map((h) => (h.startsWith("#") ? h : `#${h}`));
}

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  copy: DraftCopy;
  busy: boolean;
  onSave: (copy: DraftCopy) => Promise<unknown>;
};

export function EditCopyDialog({ open, onOpenChange, copy, busy, onSave }: Props) {
  const { t } = useTranslation();
  const [caption, setCaption] = useState(copy.caption);
  const [cta, setCta] = useState(copy.cta);
  const [hashtagsText, setHashtagsText] = useState(copy.hashtags.join(" "));

  useEffect(() => {
    if (!open) return;
    setCaption(copy.caption);
    setCta(copy.cta);
    setHashtagsText(copy.hashtags.join(" "));
  }, [open, copy.caption, copy.cta, copy.hashtags]);

  const working: DraftCopy = useMemo(
    () => ({
      caption,
      cta,
      hashtags: parseHashtags(hashtagsText),
    }),
    [caption, cta, hashtagsText],
  );
  const dirty = !draftEquals(working, copy);
  const canSave = dirty && working.caption.trim().length > 0 && !busy;

  async function handleSave() {
    if (!canSave) return;
    await onSave(working);
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[min(90dvh,640px)] flex-col gap-0 overflow-hidden p-0 sm:max-w-md">
        <DialogHeader className="shrink-0 border-b border-border px-6 py-4 pr-12 text-left">
          <DialogTitle>{t("preview.copy.editTitle")}</DialogTitle>
          <DialogDescription>{t("preview.copy.editHint")}</DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-copy-caption">{t("preview.fields.caption")}</Label>
            <Textarea
              id="edit-copy-caption"
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
              disabled={busy}
              rows={6}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-copy-cta">{t("preview.fields.cta")}</Label>
            <Input
              id="edit-copy-cta"
              value={cta}
              onChange={(e) => setCta(e.target.value)}
              disabled={busy}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-copy-hashtags">{t("preview.fields.hashtags")}</Label>
            <Input
              id="edit-copy-hashtags"
              value={hashtagsText}
              onChange={(e) => setHashtagsText(e.target.value)}
              disabled={busy}
              placeholder="#HongKong #Marketing"
            />
          </div>
        </div>

        <DialogFooter className="shrink-0 border-t border-border px-6 py-4">
          <div className="flex w-full flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => onOpenChange(false)}
            >
              {t("preview.media.cancel")}
            </Button>
            <Button type="button" size="sm" disabled={!canSave} onClick={() => void handleSave()}>
              {busy ? t("preview.applySaving") : t("preview.apply")}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
