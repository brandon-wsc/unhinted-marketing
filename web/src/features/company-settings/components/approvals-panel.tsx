import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/context/auth-context";
import {
  apiApproveProposal,
  apiListProposals,
  apiRejectProposal,
  type ProductProposalItem,
} from "@/features/company-settings/api";

type ApprovalsPanelProps = {
  companyId: string;
};

export function ApprovalsPanel({ companyId }: ApprovalsPanelProps) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<ProductProposalItem[]>([]);

  async function refresh() {
    const data = await apiListProposals(accessToken, companyId);
    setItems(data.items);
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const data = await apiListProposals(accessToken, companyId);
        if (!cancelled) setItems(data.items);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [accessToken, companyId]);

  async function onApprove(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await apiApproveProposal(accessToken, companyId, id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function onReject(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await apiRejectProposal(accessToken, companyId, id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {t("settings.approvals.title")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("settings.approvals.subtitle")}</p>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-border bg-card px-8 py-16 text-center">
          <p className="text-base font-medium text-foreground">
            {t("settings.approvals.emptyTitle")}
          </p>
          <p className="max-w-sm text-sm text-muted-foreground">
            {t("settings.approvals.emptyBody")}
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {items.map((item) => {
            const visible = item.fields.filter((f) => f.change !== "same");
            return (
              <div key={item.id} className="space-y-4 rounded-xl border border-border bg-card p-6">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-semibold">{item.name}</h2>
                    <p className="text-xs text-muted-foreground">{item.sku}</p>
                    {item.proposed_by_email && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {t("settings.approvals.proposedBy", { email: item.proposed_by_email })}
                      </p>
                    )}
                  </div>
                  <Badge variant="secondary">
                    {item.current_name
                      ? t("settings.approvals.replace")
                      : t("settings.approvals.newSku")}
                  </Badge>
                </div>

                {visible.length > 0 && (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t("settings.approvals.columns.field")}</TableHead>
                        <TableHead>{t("settings.approvals.columns.current")}</TableHead>
                        <TableHead>{t("settings.approvals.columns.proposed")}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {visible.map((field) => (
                        <TableRow key={field.key} className="hover:bg-accent">
                          <TableCell className="font-medium">{field.key}</TableCell>
                          <TableCell className="text-muted-foreground">
                            {field.current ?? t("common.notAvailable")}
                          </TableCell>
                          <TableCell>{field.proposed ?? t("common.notAvailable")}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}

                <div className="flex justify-end gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busyId === item.id}
                    onClick={() => void onReject(item.id)}
                  >
                    {t("settings.approvals.reject")}
                  </Button>
                  <Button
                    type="button"
                    loading={busyId === item.id}
                    onClick={() => void onApprove(item.id)}
                  >
                    {t("settings.approvals.approve")}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
