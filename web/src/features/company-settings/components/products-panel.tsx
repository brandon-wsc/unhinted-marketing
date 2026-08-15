import { Archive, CirclePlus, Minus } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FormField } from "@/components/form-field";
import { IconButton } from "@/components/icon-button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
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
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuth } from "@/context/auth-context";
import {
  apiArchiveProduct,
  apiCreateProduct,
  apiImportProducts,
  apiListProducts,
  apiPatchProduct,
  apiProposeProduct,
  ProductSkuConflictError,
  type ProductImportResponse,
  type ProductItem,
  type ProductScope,
} from "@/features/company-settings/api";
import { mapApiError } from "@/lib/map-api-error";
import type { ProductSkuConflict } from "@/lib/parse-api-error";

type ProductsPanelProps = {
  companyId: string;
  scope: "org" | "mine";
  onScopeChange: (scope: "org" | "mine") => void;
};

function extraProfileEntries(profile: Record<string, string>): [string, string][] {
  return Object.entries(profile).filter(
    ([key]) => key !== "name" && key !== "sku" && key !== "notes",
  );
}

function toApiScope(scope: "org" | "mine"): ProductScope {
  return scope === "mine" ? "user" : "org";
}

type ProductEditor = { kind: "add" } | { kind: "edit"; product: ProductItem };

export function ProductsPanel({ companyId, scope, onScopeChange }: ProductsPanelProps) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const fileInputId = useId();
  const fileRef = useRef<HTMLInputElement>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<ProductItem[]>([]);
  const [canEdit, setCanEdit] = useState(false);
  const [importResult, setImportResult] = useState<ProductImportResponse | null>(null);
  const [editor, setEditor] = useState<ProductEditor | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [skuConflict, setSkuConflict] = useState<ProductSkuConflict | null>(null);
  const [newName, setNewName] = useState("");
  const [newSku, setNewSku] = useState("");
  const [newNotes, setNewNotes] = useState("");

  const extraFields =
    editor?.kind === "edit" ? extraProfileEntries(editor.product.profile) : [];
  const formEditable = Boolean(canEdit && editor);

  function resetForm() {
    setNewName("");
    setNewSku("");
    setNewNotes("");
    setFormError(null);
    setSkuConflict(null);
  }

  function openAdd() {
    resetForm();
    setEditor({ kind: "add" });
  }

  function openEdit(product: ProductItem) {
    setFormError(null);
    setSkuConflict(null);
    setNewName(product.name);
    setNewSku(product.sku);
    setNewNotes(product.profile.notes ?? "");
    setEditor({ kind: "edit", product });
  }

  function closeEditor() {
    setEditor(null);
    resetForm();
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setImportResult(null);
    void (async () => {
      try {
        const data = await apiListProducts(accessToken, companyId, toApiScope(scope));
        if (cancelled) return;
        setItems(data.items);
        setCanEdit(data.can_edit);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [accessToken, companyId, scope]);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiListProducts(accessToken, companyId, toApiScope(scope));
      setItems(data.items);
      setCanEdit(data.can_edit);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function onImportFile(file: File | undefined) {
    if (!file || !canEdit) return;
    setBusy(true);
    setError(null);
    try {
      const result = await apiImportProducts(accessToken, companyId, toApiScope(scope), file);
      setImportResult(result);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function onPropose(productId: string) {
    setBusy(true);
    setError(null);
    try {
      await apiProposeProduct(accessToken, companyId, productId);
      await refresh();
    } catch (err) {
      setError(mapApiError(err instanceof Error ? err.message : String(err), t));
    } finally {
      setBusy(false);
    }
  }

  async function onArchive(productId: string) {
    if (!canEdit) return;
    setBusy(true);
    setError(null);
    try {
      await apiArchiveProduct(accessToken, companyId, productId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function submitAddRow() {
    if (!canEdit) return;
    setBusy(true);
    setFormError(null);
    try {
      await apiCreateProduct(accessToken, companyId, toApiScope(scope), {
        name: newName.trim(),
        sku: newSku.trim(),
        notes: newNotes.trim() || undefined,
      });
      closeEditor();
      await refresh();
    } catch (err) {
      if (err instanceof ProductSkuConflictError) {
        setSkuConflict(err.conflict);
        return;
      }
      setFormError(mapApiError(err instanceof Error ? err.message : String(err), t));
    } finally {
      setBusy(false);
    }
  }

  async function submitEditRow(productId: string) {
    if (!canEdit) return;
    setBusy(true);
    setFormError(null);
    try {
      await apiPatchProduct(accessToken, companyId, productId, {
        name: newName.trim(),
        sku: newSku.trim(),
        notes: newNotes.trim() || undefined,
      });
      closeEditor();
      await refresh();
    } catch (err) {
      if (err instanceof ProductSkuConflictError) {
        setSkuConflict(err.conflict);
        return;
      }
      setFormError(mapApiError(err instanceof Error ? err.message : String(err), t));
    } finally {
      setBusy(false);
    }
  }

  function onEditorSave() {
    if (!canEdit || busy || !newName.trim() || !newSku.trim() || !editor) return;
    if (editor.kind === "add") {
      void submitAddRow();
      return;
    }
    void submitEditRow(editor.product.id);
  }

  function applyGeneratedSku() {
    if (!skuConflict) return;
    setNewSku(skuConflict.suggested_sku);
    setSkuConflict(null);
  }

  function confirmOverwrite() {
    if (!skuConflict) return;
    const productId = skuConflict.existing.id;
    setSkuConflict(null);
    void submitEditRow(productId);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {t("settings.products.title")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {scope === "org"
            ? t("settings.products.subtitleOrg")
            : t("settings.products.subtitleMine")}
        </p>
      </div>

      <Tabs value={scope} onValueChange={(v) => onScopeChange(v === "mine" ? "mine" : "org")}>
        <TabsList>
          <TabsTrigger value="org">{t("settings.products.tabs.org")}</TabsTrigger>
          <TabsTrigger value="mine">{t("settings.products.tabs.mine")}</TabsTrigger>
        </TabsList>

        <TabsContent value={scope} className="mt-4 space-y-4">
          <div className="space-y-4 rounded-xl border border-border bg-card p-4 sm:p-6">
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            {!canEdit && scope === "org" && (
              <Alert>
                <AlertDescription>{t("settings.products.readOnlyOrg")}</AlertDescription>
              </Alert>
            )}

            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  ref={fileRef}
                  id={fileInputId}
                  type="file"
                  accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  className="sr-only"
                  disabled={!canEdit || busy}
                  onChange={(e) => void onImportFile(e.target.files?.[0])}
                />
                <Button
                  type="button"
                  disabled={!canEdit || busy}
                  onClick={() => fileRef.current?.click()}
                >
                  {t("settings.products.import")}
                </Button>
                {scope === "mine" && (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={!canEdit || busy}
                    onClick={openAdd}
                  >
                    {t("settings.products.addRow")}
                  </Button>
                )}
                <p className="text-xs text-muted-foreground">{t("settings.products.importHint")}</p>
              </div>
              <Badge variant="secondary">
                {t("settings.products.activeCount", { count: items.length })}
              </Badge>
            </div>

            {importResult && (
              <div className="flex flex-wrap gap-4 rounded-lg bg-accent px-3.5 py-3 text-sm">
                <span>
                  <span className="text-muted-foreground">
                    {t("settings.products.stats.imported")}{" "}
                  </span>
                  <span className="font-semibold">{importResult.imported}</span>
                </span>
                <span>
                  <span className="text-muted-foreground">
                    {t("settings.products.stats.updated")}{" "}
                  </span>
                  <span className="font-semibold">{importResult.updated}</span>
                </span>
                <span>
                  <span className="text-muted-foreground">
                    {t("settings.products.stats.skipped")}{" "}
                  </span>
                  <span className="font-semibold">{importResult.skipped}</span>
                </span>
                <span>
                  <span className="text-muted-foreground">
                    {t("settings.products.stats.errors")}{" "}
                  </span>
                  <span className="font-semibold">{importResult.errors.length}</span>
                </span>
              </div>
            )}

            {importResult && importResult.errors.length > 0 && (
              <Alert>
                <AlertDescription>
                  <ul className="list-disc space-y-1 pl-4 text-sm">
                    {importResult.errors.slice(0, 5).map((msg) => (
                      <li key={msg}>{msg}</li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            )}

            {loading ? (
              <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
            ) : items.length === 0 ? (
              <p className="py-8 text-sm text-muted-foreground">{t("settings.products.empty")}</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("settings.products.columns.name")}</TableHead>
                    {scope === "mine" && (
                      <TableHead>{t("settings.products.columns.draftsUse")}</TableHead>
                    )}
                    <TableHead>{t("settings.products.columns.status")}</TableHead>
                    <TableHead className="text-right">
                      <span className="sr-only">{t("settings.products.columns.action")}</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow
                      key={item.id}
                      className="cursor-pointer"
                      onClick={() => openEdit(item)}
                    >
                      <TableCell className="font-medium">
                        {item.name}
                        <span className="font-normal text-muted-foreground">({item.sku})</span>
                      </TableCell>
                      {scope === "mine" && (
                        <TableCell>
                          {item.covered_by_company ? (
                            <Badge variant="default">
                              {t("settings.products.coveredByCompany")}
                            </Badge>
                          ) : (
                            <Badge variant="secondary">
                              {t("settings.products.personalOnly")}
                            </Badge>
                          )}
                        </TableCell>
                      )}
                      <TableCell>
                        <Badge variant="outline">{t("settings.products.statusActive")}</Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex flex-wrap items-center justify-end gap-2">
                          {scope === "mine" && item.pending_proposal_id ? (
                            <Badge variant="secondary">
                              {t("settings.products.pendingReview")}
                            </Badge>
                          ) : null}
                          {scope === "mine" && canEdit && !item.pending_proposal_id ? (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <IconButton
                                  type="button"
                                  className="size-8"
                                  disabled={busy}
                                  aria-label={t("settings.products.propose")}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    void onPropose(item.id);
                                  }}
                                >
                                  <CirclePlus />
                                </IconButton>
                              </TooltipTrigger>
                              <TooltipContent side="top">
                                {t("settings.products.propose")}
                              </TooltipContent>
                            </Tooltip>
                          ) : null}
                          {canEdit ? (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <IconButton
                                  type="button"
                                  className="size-8"
                                  disabled={busy}
                                  aria-label={t("settings.products.archive")}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    void onArchive(item.id);
                                  }}
                                >
                                  <Archive />
                                </IconButton>
                              </TooltipTrigger>
                              <TooltipContent side="top">
                                {t("settings.products.archive")}
                              </TooltipContent>
                            </Tooltip>
                          ) : (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span className="inline-flex">
                                  <IconButton
                                    type="button"
                                    className="size-8"
                                    disabled
                                    aria-label={t("common.notAvailable")}
                                    onClick={(e) => e.stopPropagation()}
                                  >
                                    <Minus />
                                  </IconButton>
                                </span>
                              </TooltipTrigger>
                              <TooltipContent side="top">{t("common.notAvailable")}</TooltipContent>
                            </Tooltip>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}

            {scope === "mine" && (
              <div className="rounded-lg bg-accent px-3.5 py-3">
                <p className="text-xs font-medium">{t("settings.products.coverTitle")}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("settings.products.coverBody")}
                </p>
              </div>
            )}
          </div>
        </TabsContent>
      </Tabs>

      <Dialog
        open={editor != null}
        onOpenChange={(open) => {
          if (skuConflict) return;
          if (!open) closeEditor();
        }}
      >
        <DialogContent className="flex max-h-[85vh] min-h-0 flex-col gap-4 overflow-hidden sm:max-w-lg">
          <DialogHeader className="shrink-0">
            <DialogTitle>
              {editor?.kind === "edit"
                ? t(
                    formEditable
                      ? "settings.products.detail.editTitle"
                      : "settings.products.detail.title",
                  )
                : t("settings.products.addRow")}
            </DialogTitle>
          </DialogHeader>
          <div className="min-h-0 min-w-0 flex-1 space-y-4 overflow-y-auto p-px">
            {formError && (
              <Alert variant="destructive">
                <AlertDescription>{formError}</AlertDescription>
              </Alert>
            )}
            <FormField id="product-name" label={t("settings.products.fields.name")}>
              <Input
                id="product-name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                autoComplete="off"
                readOnly={!formEditable}
              />
            </FormField>
            <FormField id="product-sku" label={t("settings.products.fields.sku")}>
              <Input
                id="product-sku"
                value={newSku}
                onChange={(e) => setNewSku(e.target.value)}
                autoComplete="off"
                readOnly={!formEditable}
              />
            </FormField>
            <FormField id="product-notes" label={t("settings.products.fields.notes")}>
              <Textarea
                id="product-notes"
                value={newNotes}
                onChange={(e) => setNewNotes(e.target.value)}
                rows={4}
                className="field-sizing-fixed max-h-[min(16rem,40vh)] min-h-24 resize-y overflow-y-auto"
                maxLength={4000}
                readOnly={!formEditable}
              />
              <p className="text-xs text-muted-foreground">
                {t("settings.products.fields.notesHint")}
              </p>
            </FormField>
            {extraFields.map(([key, value]) => (
              <div key={key} className="space-y-1">
                <p className="text-xs font-medium break-all text-muted-foreground">{key}</p>
                <p className="text-sm whitespace-pre-wrap break-words text-foreground">
                  {value.trim() || "—"}
                </p>
              </div>
            ))}
          </div>
          {formEditable ? (
            <DialogFooter className="shrink-0">
              <Button type="button" variant="outline" onClick={closeEditor}>
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                disabled={busy || !newName.trim() || !newSku.trim()}
                onClick={onEditorSave}
              >
                {t("common.save")}
              </Button>
            </DialogFooter>
          ) : null}
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={skuConflict != null}
        onOpenChange={(open) => {
          if (!open) setSkuConflict(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.products.overwrite.title")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("settings.products.overwrite.body", {
                sku: skuConflict?.existing.sku ?? newSku.trim(),
                name: skuConflict?.existing.name ?? "",
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="flex-col sm:flex-row">
            <AlertDialogCancel>{t("settings.products.overwrite.keepEditing")}</AlertDialogCancel>
            <Button type="button" variant="outline" disabled={busy} onClick={applyGeneratedSku}>
              {t("settings.products.overwrite.generate")}
            </Button>
            {editor?.kind === "add" ? (
              <AlertDialogAction disabled={busy} onClick={confirmOverwrite}>
                {t("settings.products.overwrite.confirm")}
              </AlertDialogAction>
            ) : null}
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
