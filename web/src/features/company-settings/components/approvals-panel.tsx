import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";

export function ApprovalsPanel() {
  const { t } = useTranslation();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {t("settings.approvals.title")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("settings.approvals.subtitle")}</p>
      </div>

      <div className="flex flex-col items-center gap-3 rounded-xl border border-border bg-card px-8 py-16 text-center">
        <p className="text-base font-medium text-foreground">
          {t("settings.approvals.emptyTitle")}
        </p>
        <p className="max-w-sm text-sm text-muted-foreground">
          {t("settings.approvals.emptyBody")}
        </p>
        <Badge variant="secondary">{t("settings.approvals.emptyBadge")}</Badge>
      </div>
    </div>
  );
}
