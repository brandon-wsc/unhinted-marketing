import { CirclePlay, Pencil, Trash2 } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FormField } from "@/components/form-field";
import { IconButton } from "@/components/icon-button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuth } from "@/context/auth-context";
import {
  apiCreateByokProvider,
  apiDeleteByokModel,
  apiDeleteByokProvider,
  apiGetByokRouting,
  apiListByokModels,
  apiListByokProviders,
  apiPatchByokProvider,
  apiPutByokRouting,
  apiTestByokModel,
  apiTestByokProvider,
  ByokDependentsError,
  type ByokHasDependents,
  type ByokModelItem,
  type ByokProviderItem,
  type ByokRoutingSlot,
  type ByokRoutingSlotName,
} from "@/features/company-settings/api";
import {
  type ByokKeyFormValue,
  EMPTY_BYOK_KEY_FORM,
  isByokPending,
  PLATFORM_SLOT_VALUE,
  routingToUpdate,
  slotUpdateField,
  validateByokKeyForm,
} from "@/features/company-settings/byok-helpers";
import { AddModelDialog } from "@/features/company-settings/components/add-model-dialog";
import { KeyFormFields } from "@/features/company-settings/components/key-form-fields";
import { mapApiError } from "@/lib/map-api-error";

const ROUTING_SLOTS: ByokRoutingSlotName[] = ["cheap", "medium", "strong", "image"];
const POLL_ATTEMPTS = 4;
const POLL_DELAY_MS = 1500;

type ApiKeysPanelProps = {
  companyId: string;
};

type PendingDelete =
  | { kind: "provider"; item: ByokProviderItem; conflict: ByokHasDependents | null }
  | { kind: "model"; item: ByokModelItem; conflict: ByokHasDependents | null };

type EditKeyState = {
  item: ByokProviderItem;
  value: ByokKeyFormValue;
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function VerifiedBadge({
  item,
}: {
  item: { verified: boolean; last_verified_at: string | null; last_error_kind: string | null };
}) {
  const { t } = useTranslation();
  if (item.verified) {
    return <Badge>{t("settings.apiKeys.status.verified")}</Badge>;
  }
  if (item.last_error_kind) {
    return <Badge variant="destructive">{t("settings.apiKeys.status.error")}</Badge>;
  }
  return <Badge variant="secondary">{t("settings.apiKeys.status.pending")}</Badge>;
}

function RowIconAction({
  label,
  onClick,
  disabled,
  loading,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <IconButton
          type="button"
          className="size-8"
          disabled={disabled}
          loading={loading}
          aria-label={label}
          onClick={onClick}
        >
          {loading ? null : children}
        </IconButton>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );
}

function dependentsSummary(
  conflict: ByokHasDependents,
  t: (key: string, opts: { list: string }) => string,
): string[] {
  const lines: string[] = [];
  if (conflict.models.length > 0) {
    lines.push(
      t("settings.apiKeys.delete.modelsLabel", {
        list: conflict.models.map((row) => row.model_id).join("、"),
      }),
    );
  }
  if (conflict.slots.length > 0) {
    lines.push(t("settings.apiKeys.delete.slotsLabel", { list: conflict.slots.join("、") }));
  }
  return lines;
}

export function ApiKeysPanel({ companyId }: ApiKeysPanelProps) {
  const { t } = useTranslation();
  const tRef = useRef(t);
  tRef.current = t;
  const { accessToken } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [providers, setProviders] = useState<ByokProviderItem[]>([]);
  const [models, setModels] = useState<ByokModelItem[]>([]);
  const [routing, setRouting] = useState<ByokRoutingSlot[]>([]);
  const [addModelOpen, setAddModelOpen] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const [editKey, setEditKey] = useState<EditKeyState | null>(null);
  const [addKey, setAddKey] = useState<ByokKeyFormValue | null>(null);
  const [imageTest, setImageTest] = useState<ByokModelItem | null>(null);

  const apply = useCallback(
    (next: {
      providers: ByokProviderItem[];
      models: ByokModelItem[];
      routing: ByokRoutingSlot[];
    }) => {
      setProviders(next.providers);
      setModels(next.models);
      setRouting(next.routing);
    },
    [],
  );

  const fetchAll = useCallback(async () => {
    const [nextProviders, nextModels, nextRouting] = await Promise.all([
      apiListByokProviders(accessToken, companyId),
      apiListByokModels(accessToken, companyId),
      apiGetByokRouting(accessToken, companyId),
    ]);
    return { providers: nextProviders, models: nextModels, routing: nextRouting.slots };
  }, [accessToken, companyId]);

  const refresh = useCallback(
    async (opts?: { poll?: boolean }) => {
      let data = await fetchAll();
      apply(data);
      if (!opts?.poll) return;
      for (let attempt = 0; attempt < POLL_ATTEMPTS; attempt += 1) {
        const pending = [...data.providers, ...data.models].some(isByokPending);
        if (!pending) return;
        await sleep(POLL_DELAY_MS);
        data = await fetchAll();
        apply(data);
      }
    },
    [apply, fetchAll],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        let data = await fetchAll();
        if (cancelled) return;
        apply(data);
        setLoading(false);
        for (let attempt = 0; attempt < POLL_ATTEMPTS; attempt += 1) {
          if (cancelled) return;
          if (![...data.providers, ...data.models].some(isByokPending)) return;
          await sleep(POLL_DELAY_MS);
          if (cancelled) return;
          data = await fetchAll();
          if (cancelled) return;
          apply(data);
        }
      } catch (err) {
        if (cancelled) return;
        setError(mapApiError(err instanceof Error ? err.message : String(err), tRef.current));
        setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [apply, fetchAll]);

  async function onTestProvider(item: ByokProviderItem) {
    setBusyId(item.id);
    setError(null);
    try {
      await apiTestByokProvider(accessToken, companyId, item.id);
      await refresh();
    } catch (err) {
      setError(mapApiError(err instanceof Error ? err.message : String(err), t));
    } finally {
      setBusyId(null);
    }
  }

  async function onTestModel(item: ByokModelItem, confirmPaid = false) {
    setBusyId(item.id);
    setError(null);
    try {
      await apiTestByokModel(accessToken, companyId, item.id, confirmPaid);
      setImageTest(null);
      await refresh();
    } catch (err) {
      setError(mapApiError(err instanceof Error ? err.message : String(err), t));
    } finally {
      setBusyId(null);
    }
  }

  function closeAddKey() {
    setAddKey(null);
    setDialogError(null);
  }

  function openAddKey() {
    setDialogError(null);
    setAddKey(EMPTY_BYOK_KEY_FORM);
  }

  async function onSaveAddKey() {
    if (!addKey) return;
    const invalid = validateByokKeyForm(addKey, { requireKey: true });
    if (invalid) {
      setDialogError(t(`settings.apiKeys.errors.${invalid}`));
      return;
    }
    setBusyId("add-key");
    setDialogError(null);
    try {
      await apiCreateByokProvider(accessToken, companyId, {
        label: addKey.label.trim(),
        provider_type: addKey.providerType,
        api_key: addKey.apiKey.trim(),
        api_base: addKey.providerType === "openai_compatible" ? addKey.apiBase.trim() : null,
      });
      setAddKey(null);
      await refresh({ poll: true });
    } catch (err) {
      setDialogError(mapApiError(err instanceof Error ? err.message : String(err), t));
    } finally {
      setBusyId(null);
    }
  }

  async function onSaveEdit() {
    if (!editKey) return;
    const invalid = validateByokKeyForm(editKey.value, { requireKey: false });
    if (invalid) {
      setDialogError(t(`settings.apiKeys.errors.${invalid}`));
      return;
    }
    setBusyId(editKey.item.id);
    setDialogError(null);
    try {
      const patch: { label: string; api_key?: string; api_base?: string | null } = {
        label: editKey.value.label.trim(),
      };
      if (editKey.value.apiKey.trim()) patch.api_key = editKey.value.apiKey.trim();
      if (editKey.item.provider_type === "openai_compatible") {
        patch.api_base = editKey.value.apiBase.trim() || null;
      }
      await apiPatchByokProvider(accessToken, companyId, editKey.item.id, patch);
      setEditKey(null);
      await refresh({ poll: true });
    } catch (err) {
      setDialogError(mapApiError(err instanceof Error ? err.message : String(err), t));
    } finally {
      setBusyId(null);
    }
  }

  async function onConfirmDelete() {
    if (!pendingDelete) return;
    const force = pendingDelete.conflict != null;
    setBusyId(pendingDelete.item.id);
    setError(null);
    try {
      if (pendingDelete.kind === "provider") {
        await apiDeleteByokProvider(accessToken, companyId, pendingDelete.item.id, force);
      } else {
        await apiDeleteByokModel(accessToken, companyId, pendingDelete.item.id, force);
      }
      setPendingDelete(null);
      await refresh();
    } catch (err) {
      if (err instanceof ByokDependentsError) {
        setPendingDelete({ ...pendingDelete, conflict: err.conflict });
      } else {
        setError(mapApiError(err instanceof Error ? err.message : String(err), t));
        setPendingDelete(null);
      }
    } finally {
      setBusyId(null);
    }
  }

  async function onRoutingChange(slot: ByokRoutingSlotName, value: string) {
    setBusyId(`routing-${slot}`);
    setError(null);
    try {
      const update = routingToUpdate(routing);
      update[slotUpdateField(slot)] = value === PLATFORM_SLOT_VALUE ? null : value;
      const next = await apiPutByokRouting(accessToken, companyId, update);
      setRouting(next.slots);
    } catch (err) {
      setError(mapApiError(err instanceof Error ? err.message : String(err), t));
    } finally {
      setBusyId(null);
    }
  }

  const deleteTitle =
    pendingDelete?.kind === "provider"
      ? t("settings.apiKeys.delete.titleKey")
      : t("settings.apiKeys.delete.titleModel");
  const deleteBody =
    pendingDelete?.kind === "provider"
      ? t("settings.apiKeys.delete.bodyKey", { label: pendingDelete.item.label })
      : pendingDelete
        ? t("settings.apiKeys.delete.bodyModel", { modelId: pendingDelete.item.model_id })
        : "";
  const conflictLines = pendingDelete?.conflict ? dependentsSummary(pendingDelete.conflict, t) : [];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {t("settings.apiKeys.title")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("settings.apiKeys.subtitle")}</p>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
      ) : (
        <>
          <section className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-foreground">
                {t("settings.apiKeys.keys.title")}
              </h2>
              <Button type="button" size="sm" onClick={openAddKey}>
                {t("settings.apiKeys.addKey")}
              </Button>
            </div>
            {providers.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("settings.apiKeys.keys.empty")}</p>
            ) : (
              <div className="rounded-xl border border-border bg-card">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("settings.apiKeys.keys.columns.label")}</TableHead>
                      <TableHead>{t("settings.apiKeys.keys.columns.key")}</TableHead>
                      <TableHead>{t("settings.apiKeys.keys.columns.type")}</TableHead>
                      <TableHead>{t("settings.apiKeys.keys.columns.status")}</TableHead>
                      <TableHead className="text-right" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {providers.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell className="font-medium">{item.label}</TableCell>
                        <TableCell className="text-muted-foreground">
                          {t("settings.apiKeys.keys.masked", { last4: item.key_last4 })}
                        </TableCell>
                        <TableCell>
                          {t(`settings.apiKeys.providerType.${item.provider_type}`)}
                        </TableCell>
                        <TableCell>
                          <VerifiedBadge item={item} />
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-2">
                            <RowIconAction
                              label={t("settings.apiKeys.actions.test")}
                              loading={busyId === item.id}
                              onClick={() => void onTestProvider(item)}
                            >
                              <CirclePlay />
                            </RowIconAction>
                            <RowIconAction
                              label={t("settings.apiKeys.actions.edit")}
                              onClick={() => {
                                setDialogError(null);
                                setEditKey({
                                  item,
                                  value: {
                                    label: item.label,
                                    providerType: item.provider_type,
                                    apiKey: "",
                                    apiBase: item.api_base ?? "",
                                  },
                                });
                              }}
                            >
                              <Pencil />
                            </RowIconAction>
                            <RowIconAction
                              label={t("settings.apiKeys.actions.delete")}
                              onClick={() =>
                                setPendingDelete({ kind: "provider", item, conflict: null })
                              }
                            >
                              <Trash2 />
                            </RowIconAction>
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
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-foreground">
                {t("settings.apiKeys.models.title")}
              </h2>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={providers.length === 0}
                onClick={() => setAddModelOpen(true)}
              >
                {t("settings.apiKeys.addModel")}
              </Button>
            </div>
            {models.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t(
                  providers.length === 0
                    ? "settings.apiKeys.models.emptyNeedsKey"
                    : "settings.apiKeys.models.empty",
                )}
              </p>
            ) : (
              <div className="rounded-xl border border-border bg-card">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("settings.apiKeys.models.columns.model")}</TableHead>
                      <TableHead>{t("settings.apiKeys.models.columns.key")}</TableHead>
                      <TableHead>{t("settings.apiKeys.models.columns.capability")}</TableHead>
                      <TableHead>{t("settings.apiKeys.models.columns.status")}</TableHead>
                      <TableHead className="text-right" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {models.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell className="font-medium">{item.model_id}</TableCell>
                        <TableCell className="text-muted-foreground">
                          {item.provider_label} ·{" "}
                          {t("settings.apiKeys.keys.masked", { last4: item.provider_key_last4 })}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">
                            {t(`settings.apiKeys.capability.${item.capability}`)}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <VerifiedBadge item={item} />
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-2">
                            <RowIconAction
                              label={t("settings.apiKeys.actions.test")}
                              loading={busyId === item.id}
                              onClick={() => {
                                if (item.capability === "image") setImageTest(item);
                                else void onTestModel(item);
                              }}
                            >
                              <CirclePlay />
                            </RowIconAction>
                            <RowIconAction
                              label={t("settings.apiKeys.actions.delete")}
                              onClick={() =>
                                setPendingDelete({ kind: "model", item, conflict: null })
                              }
                            >
                              <Trash2 />
                            </RowIconAction>
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
            <div>
              <h2 className="text-sm font-semibold text-foreground">
                {t("settings.apiKeys.routing.title")}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {t("settings.apiKeys.routing.subtitle")}
              </p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {ROUTING_SLOTS.map((slot) => {
                const current = routing.find((row) => row.slot === slot);
                const expected = slot === "image" ? "image" : "chat";
                const options = models.filter((item) => item.capability === expected);
                const selectValue =
                  current?.source === "org" && current.registry_id
                    ? current.registry_id
                    : PLATFORM_SLOT_VALUE;
                const helper =
                  current?.source === "org" && current.model_id
                    ? t("settings.apiKeys.routing.helperOrg", { modelId: current.model_id })
                    : t("settings.apiKeys.routing.helperEnv");
                return (
                  <FormField
                    key={slot}
                    id={`byok-slot-${slot}`}
                    label={t(`settings.apiKeys.routing.slots.${slot}`)}
                  >
                    <Select
                      value={selectValue}
                      onValueChange={(value) => void onRoutingChange(slot, value)}
                      disabled={busyId === `routing-${slot}`}
                    >
                      <SelectTrigger id={`byok-slot-${slot}`} className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={PLATFORM_SLOT_VALUE}>
                          {t("settings.apiKeys.routing.platformDefault")}
                        </SelectItem>
                        {options.map((item) => (
                          <SelectItem key={item.id} value={item.id}>
                            {item.model_id}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">{helper}</p>
                  </FormField>
                );
              })}
            </div>
          </section>
        </>
      )}

      <AddModelDialog
        open={addModelOpen}
        onOpenChange={setAddModelOpen}
        companyId={companyId}
        providers={providers}
        onChanged={async () => {
          try {
            await refresh({ poll: true });
          } catch (err) {
            setError(mapApiError(err instanceof Error ? err.message : String(err), t));
            throw err;
          }
        }}
      />

      <Dialog open={addKey != null} onOpenChange={(open) => !open && closeAddKey()}>
        <DialogContent
          onPointerDownOutside={(event) => event.preventDefault()}
          onInteractOutside={(event) => event.preventDefault()}
        >
          <DialogHeader>
            <DialogTitle>{t("settings.apiKeys.addKey")}</DialogTitle>
            <DialogDescription>{t("settings.apiKeys.addKeyHint")}</DialogDescription>
          </DialogHeader>
          {addKey != null && dialogError && (
            <Alert variant="destructive">
              <AlertDescription>{dialogError}</AlertDescription>
            </Alert>
          )}
          {addKey != null && (
            <div className="space-y-4">
              <KeyFormFields idPrefix="byok-add" value={addKey} onChange={setAddKey} />
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={closeAddKey}>
              {t("common.cancel")}
            </Button>
            <Button
              type="button"
              disabled={busyId === "add-key"}
              onClick={() => void onSaveAddKey()}
            >
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={editKey != null}
        onOpenChange={(open) => {
          if (!open) {
            setEditKey(null);
            setDialogError(null);
          }
        }}
      >
        <DialogContent
          onPointerDownOutside={(event) => event.preventDefault()}
          onInteractOutside={(event) => event.preventDefault()}
        >
          <DialogHeader>
            <DialogTitle>{t("settings.apiKeys.edit.title")}</DialogTitle>
            <DialogDescription>{t("settings.apiKeys.edit.apiKeyRotate")}</DialogDescription>
          </DialogHeader>
          {editKey != null && dialogError && (
            <Alert variant="destructive">
              <AlertDescription>{dialogError}</AlertDescription>
            </Alert>
          )}
          {editKey && (
            <div className="space-y-4">
              <KeyFormFields
                idPrefix="byok-edit"
                value={editKey.value}
                onChange={(value) => setEditKey({ ...editKey, value })}
                showType={false}
                keyRequired={false}
              />
            </div>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setEditKey(null);
                setDialogError(null);
              }}
            >
              {t("common.cancel")}
            </Button>
            <Button
              type="button"
              disabled={busyId === editKey?.item.id}
              onClick={() => void onSaveEdit()}
            >
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={pendingDelete != null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{deleteTitle}</AlertDialogTitle>
            <AlertDialogDescription>{deleteBody}</AlertDialogDescription>
          </AlertDialogHeader>
          {conflictLines.length > 0 && (
            <div className="space-y-1 text-sm text-muted-foreground">
              <p>{t("settings.apiKeys.delete.dependents")}</p>
              {conflictLines.map((line) => (
                <p key={line}>{line}</p>
              ))}
            </div>
          )}
          <AlertDialogFooter>
            <Button type="button" variant="outline" onClick={() => setPendingDelete(null)}>
              {t("common.cancel")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={busyId === pendingDelete?.item.id}
              onClick={() => void onConfirmDelete()}
            >
              {pendingDelete?.conflict
                ? t("settings.apiKeys.delete.force")
                : t("settings.apiKeys.actions.delete")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={imageTest != null} onOpenChange={(open) => !open && setImageTest(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.apiKeys.models.imageTestTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("settings.apiKeys.models.imageTestBody")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button type="button" variant="outline" onClick={() => setImageTest(null)}>
              {t("common.cancel")}
            </Button>
            <Button
              type="button"
              loading={busyId === imageTest?.id}
              onClick={() => imageTest && void onTestModel(imageTest, true)}
            >
              {t("settings.apiKeys.models.imageTestConfirm")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
