import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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
  apiApprovePublishRequest,
  apiListProposals,
  apiListPublishApprovals,
  apiRejectProposal,
  apiRejectPublishRequest,
  type ProductProposalItem,
  type PublishApprovalItem,
} from "@/features/company-settings/api";
import { useAsyncData } from "@/hooks/use-async-data";
import { errorMessage } from "@/lib/utils";

type ApprovalsPanelProps = {
  companyId: string;
};

function proposalNote(item: ProductProposalItem): string {
  return item.profile?.notes?.trim() ?? "";
}

function requesterLabel(item: PublishApprovalItem): string {
  return item.requested_by_email || item.requested_by_name || "—";
}

export function ApprovalsPanel({ companyId }: ApprovalsPanelProps) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [items, setItems] = useState<ProductProposalItem[]>([]);
  const [detail, setDetail] = useState<ProductProposalItem | null>(null);
  const [publishItems, setPublishItems] = useState<PublishApprovalItem[]>([]);
  const [publishDetail, setPublishDetail] = useState<PublishApprovalItem | null>(null);
  const [publishNotice, setPublishNotice] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    const [proposals, publish] = await Promise.all([
      apiListProposals(accessToken, companyId),
      apiListPublishApprovals(accessToken, companyId),
    ]);
    return { proposals: proposals.items, publish: publish.items };
  }, [accessToken, companyId]);
  const { loading, error, setError } = useAsyncData(
    fetchAll,
    (data) => {
      setItems(data.proposals);
      setPublishItems(data.publish);
    },
    [fetchAll],
  );

  // Silent refresh after approve/reject — keeps the list visible (no loading flip).
  async function refresh() {
    const data = await fetchAll();
    setItems(data.proposals);
    setPublishItems(data.publish);
  }

  async function onApprove(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await apiApproveProposal(accessToken, companyId, id);
      setDetail(null);
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
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
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  async function onApprovePublish(id: string) {
    setBusyId(id);
    setError(null);
    setPublishNotice(null);
    try {
      const updated = await apiApprovePublishRequest(accessToken, companyId, id);
      if (updated.status === "failed") {
        setPublishNotice(
          t("settings.approvals.publish.approveFailed", {
            kind: updated.error_kind ?? "platform_error",
          }),
        );
      }
      setPublishDetail(null);
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  async function onRejectPublish(id: string) {
    setBusyId(id);
    setError(null);
    setPublishNotice(null);
    try {
      await apiRejectPublishRequest(accessToken, companyId, id);
      setPublishDetail(null);
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  const empty = items.length === 0 && publishItems.length === 0;

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
      {publishNotice && (
        <Alert variant="destructive">
          <AlertDescription>{publishNotice}</AlertDescription>
        </Alert>
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
      ) : (
        <div className="space-y-8">
          <section className="space-y-3">
            <h2 className="text-sm font-semibold">{t("settings.approvals.products")}</h2>
            {items.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t("settings.approvals.productsEmpty")}
              </p>
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
                      <TableRow
                        key={item.id}
                        className="cursor-pointer"
                        onClick={() => setDetail(item)}
                      >
                        <TableCell className="max-w-56">
                          <span className="block truncate font-medium">{item.name}</span>
                        </TableCell>
                        <TableCell className="max-w-40">
                          <span className="block truncate text-sm text-muted-foreground">
                            {item.sku}
                          </span>
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
          </section>

          <section className="space-y-3">
            <h2 className="text-sm font-semibold">{t("settings.approvals.publish.title")}</h2>
            {publishItems.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t("settings.approvals.publish.empty")}
              </p>
            ) : (
              <div className="rounded-xl border border-border bg-card">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("settings.approvals.publish.columns.caption")}</TableHead>
                      <TableHead>{t("settings.approvals.publish.columns.requester")}</TableHead>
                      <TableHead>{t("settings.approvals.publish.columns.platform")}</TableHead>
                      <TableHead className="text-right" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {publishItems.map((item) => (
                      <TableRow
                        key={item.id}
                        className="cursor-pointer"
                        onClick={() => setPublishDetail(item)}
                      >
                        <TableCell className="max-w-72">
                          <span className="block truncate font-medium">
                            {item.draft_copy.caption.trim() || "—"}
                          </span>
                        </TableCell>
                        <TableCell className="max-w-56">
                          <span className="block truncate text-sm text-muted-foreground">
                            {requesterLabel(item)}
                          </span>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">{item.platform}</Badge>
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
                                void onRejectPublish(item.id);
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
                                void onApprovePublish(item.id);
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
          </section>

          {empty && (
            <div className="flex flex-col items-center gap-3 rounded-xl border border-border bg-card px-8 py-16 text-center">
              <p className="text-base font-medium text-foreground">
                {t("settings.approvals.emptyTitle")}
              </p>
              <p className="max-w-sm text-sm text-muted-foreground">
                {t("settings.approvals.emptyBody")}
              </p>
            </div>
          )}
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

      <Dialog open={publishDetail != null} onOpenChange={(open) => !open && setPublishDetail(null)}>
        <DialogContent className="flex max-h-[85vh] flex-col gap-0 overflow-hidden sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("settings.approvals.publish.detailTitle")}</DialogTitle>
            <DialogDescription>
              {publishDetail ? requesterLabel(publishDetail) : null}
            </DialogDescription>
          </DialogHeader>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto py-4">
            {publishDetail?.image_url && (
              <img
                src={publishDetail.image_url}
                alt=""
                className="w-full rounded-lg border border-border object-cover"
              />
            )}
            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground">
                {t("settings.approvals.publish.columns.caption")}
              </p>
              <p className="text-sm whitespace-pre-wrap text-foreground">
                {publishDetail?.draft_copy.caption || "—"}
              </p>
            </div>
            {(publishDetail?.draft_copy.hashtags.length ?? 0) > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">
                  {t("settings.approvals.publish.hashtags")}
                </p>
                <p className="text-sm text-foreground">
                  {publishDetail?.draft_copy.hashtags.join(" ")}
                </p>
              </div>
            )}
            {publishDetail?.draft_copy.cta.trim() && (
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">CTA</p>
                <p className="text-sm text-foreground">{publishDetail.draft_copy.cta}</p>
              </div>
            )}
            {publishDetail && (
              <p className="text-xs text-muted-foreground">
                {t("settings.approvals.publish.meta", {
                  platform: publishDetail.platform,
                  revision: publishDetail.revision,
                })}
              </p>
            )}
          </div>
          {publishDetail && (
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={busyId === publishDetail.id}
                onClick={() => void onRejectPublish(publishDetail.id)}
              >
                {t("settings.approvals.reject")}
              </Button>
              <Button
                type="button"
                loading={busyId === publishDetail.id}
                onClick={() => void onApprovePublish(publishDetail.id)}
              >
                {t("settings.approvals.publish.approvePublish")}
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
