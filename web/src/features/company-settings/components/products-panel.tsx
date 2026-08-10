import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FormField } from "@/components/form-field";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
import { useAuth } from "@/context/auth-context";
import {
  apiArchiveProduct,
  apiCreateProduct,
  apiImportProducts,
  apiListProducts,
  type ProductImportResponse,
  type ProductItem,
  type ProductScope,
} from "@/features/company-settings/api";

type ProductsPanelProps = {
  companyId: string;
  scope: "org" | "mine";
  onScopeChange: (scope: "org" | "mine") => void;
};

function toApiScope(scope: "org" | "mine"): ProductScope {
  return scope === "mine" ? "user" : "org";
}

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
  const [addOpen, setAddOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newSku, setNewSku] = useState("");
  const [newNotes, setNewNotes] = useState("");

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

  async function onAddRow() {
    if (!canEdit) return;
    setBusy(true);
    setError(null);
    try {
      await apiCreateProduct(accessToken, companyId, toApiScope(scope), {
        name: newName.trim(),
        sku: newSku.trim(),
        notes: newNotes.trim() || undefined,
      });
      setAddOpen(false);
      setNewName("");
      setNewSku("");
      setNewNotes("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
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
                    onClick={() => setAddOpen(true)}
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
                      <TableHead>{t("settings.products.columns.note")}</TableHead>
                    )}
                    <TableHead>{t("settings.products.columns.status")}</TableHead>
                    <TableHead className="text-right">
                      {t("settings.products.columns.action")}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell>
                        <div className="font-medium">{item.name}</div>
                        <div className="text-xs text-muted-foreground">{item.sku}</div>
                      </TableCell>
                      {scope === "mine" && (
                        <TableCell>
                          {item.covered_by_company ? (
                            <Badge variant="secondary">
                              {t("settings.products.coveredByCompany")}
                            </Badge>
                          ) : (
                            <span className="text-muted-foreground">
                              {t("settings.products.personalOnly")}
                            </span>
                          )}
                        </TableCell>
                      )}
                      <TableCell>
                        <Badge variant="outline">{t("settings.products.statusActive")}</Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        {canEdit ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={busy}
                            onClick={() => void onArchive(item.id)}
                          >
                            {t("settings.products.archive")}
                          </Button>
                        ) : (
                          <span className="text-muted-foreground">{t("common.notAvailable")}</span>
                        )}
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
        open={addOpen}
        onOpenChange={(open) => {
          setAddOpen(open);
          if (!open) {
            setNewName("");
            setNewSku("");
            setNewNotes("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("settings.products.addRow")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <FormField id="product-name" label={t("settings.products.fields.name")}>
              <Input
                id="product-name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                autoComplete="off"
              />
            </FormField>
            <FormField id="product-sku" label={t("settings.products.fields.sku")}>
              <Input
                id="product-sku"
                value={newSku}
                onChange={(e) => setNewSku(e.target.value)}
                autoComplete="off"
              />
            </FormField>
            <FormField id="product-notes" label={t("settings.products.fields.notes")}>
              <Textarea
                id="product-notes"
                value={newNotes}
                onChange={(e) => setNewNotes(e.target.value)}
                rows={4}
                className="min-h-24"
                maxLength={4000}
              />
              <p className="text-xs text-muted-foreground">
                {t("settings.products.fields.notesHint")}
              </p>
            </FormField>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setAddOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              type="button"
              disabled={busy || !newName.trim() || !newSku.trim()}
              onClick={() => void onAddRow()}
            >
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
