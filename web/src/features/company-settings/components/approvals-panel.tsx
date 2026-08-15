import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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

function proposalNote(item: ProductProposalItem): string {
  return item.profile?.notes?.trim() ?? "";
}

export function ApprovalsPanel({ companyId }: ApprovalsPanelProps) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<ProductProposalItem[]>([]);
  const [detail, setDetail] = useState<ProductProposalItem | null>(null);

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
      setDetail(null);
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
      setDetail(null);
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
        <div className="rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("settings.approvals.columns.product")}</TableHead>
                <TableHead>{t("settings.approvals.columns.sku")}</TableHead>
                <TableHead>{t("settings.approvals.columns.note")}</TableHead>
                <TableHead className="text-right" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.id} className="cursor-pointer" onClick={() => setDetail(item)}>
                  <TableCell className="max-w-56">
                    <span className="block truncate font-medium">{item.name}</span>
                  </TableCell>
                  <TableCell className="max-w-40">
                    <span className="block truncate text-sm text-muted-foreground">{item.sku}</span>
                  </TableCell>
                  <TableCell className="max-w-72">
                    <span className="block truncate text-sm text-muted-foreground">
                      {proposalNote(item) || "—"}
                    </span>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={busyId === item.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          void onReject(item.id);
                        }}
                      >
                        {t("settings.approvals.reject")}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        loading={busyId === item.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          void onApprove(item.id);
                        }}
                      >
                        {t("settings.approvals.approve")}
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={detail != null} onOpenChange={(open) => !open && setDetail(null)}>
        <DialogContent className="flex max-h-[85vh] flex-col gap-0 overflow-hidden sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("settings.approvals.detailTitle")}</DialogTitle>
            <DialogDescription>
              {detail?.proposed_by_email
                ? t("settings.approvals.proposedBy", { email: detail.proposed_by_email })
                : null}
            </DialogDescription>
          </DialogHeader>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto py-4">
            <div>
              <p className="text-base font-semibold text-foreground">
                {detail?.name}{" "}
                <span className="font-normal text-muted-foreground">({detail?.sku})</span>
              </p>
            </div>

            {detail && proposalNote(detail) && (
              <p className="text-sm whitespace-pre-wrap text-foreground">{proposalNote(detail)}</p>
            )}
          </div>
          {detail && (
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={busyId === detail.id}
                onClick={() => void onReject(detail.id)}
              >
                {t("settings.approvals.reject")}
              </Button>
              <Button
                type="button"
                loading={busyId === detail.id}
                onClick={() => void onApprove(detail.id)}
              >
                {t("settings.approvals.approve")}
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
