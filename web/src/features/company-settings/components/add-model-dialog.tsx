import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FormField } from "@/components/form-field";
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
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/context/auth-context";
import {
  apiCreateByokModel,
  apiListByokProviderCatalog,
  type ByokCapability,
  type ByokListedModel,
  type ByokModelListProxy,
  type ByokProviderItem,
} from "@/features/company-settings/api";
import { capabilityFromListedModel } from "@/features/company-settings/byok-helpers";
import { mapApiError } from "@/lib/map-api-error";

type AddModelDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  companyId: string;
  providers: ByokProviderItem[];
  onChanged: () => Promise<void>;
};

function listedFor(
  catalog: ByokModelListProxy | null,
  modelId: string,
): ByokListedModel | undefined {
  return catalog?.models.find((item) => item.id === modelId);
}

export function AddModelDialog({
  open,
  onOpenChange,
  companyId,
  providers,
  onChanged,
}: AddModelDialogProps) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const providersRef = useRef(providers);
  providersRef.current = providers;

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [providerId, setProviderId] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<ByokModelListProxy | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [modelId, setModelId] = useState("");
  const [capabilityOverride, setCapabilityOverride] = useState<ByokCapability | null>(null);

  const loadCatalog = useCallback(
    async (id: string) => {
      setCatalogLoading(true);
      setCatalog(null);
      try {
        const next = await apiListByokProviderCatalog(accessToken, companyId, id);
        setCatalog(next);
      } catch {
        setCatalog({ fetchable: false, models: [] });
      } finally {
        setCatalogLoading(false);
      }
    },
    [accessToken, companyId],
  );

  useEffect(() => {
    if (!open) return;
    const nextId = providersRef.current[0]?.id ?? null;
    setBusy(false);
    setError(null);
    setProviderId(nextId);
    setCatalog(null);
    setCatalogLoading(false);
    setModelId("");
    setCapabilityOverride(null);
    if (nextId) void loadCatalog(nextId);
  }, [open, loadCatalog]);

  const suggested = capabilityFromListedModel(modelId, listedFor(catalog, modelId));
  const capability = capabilityOverride ?? suggested.capability;
  const capabilitySource =
    capabilityOverride && capabilityOverride !== suggested.capability ? "manual" : suggested.source;
  const useCatalogSelect = Boolean(catalog?.fetchable && catalog.models.length > 0);
  const showKeySelect = providers.length > 1;

  function onProviderChange(id: string) {
    setProviderId(id);
    setModelId("");
    setCapabilityOverride(null);
    void loadCatalog(id);
  }

  async function onSave() {
    if (!providerId || !modelId.trim()) {
      setError(t("settings.apiKeys.errors.modelRequired"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiCreateByokModel(accessToken, companyId, {
        provider_id: providerId,
        model_id: modelId.trim(),
        capability,
        capability_source: capabilitySource,
      });
      await onChanged();
      onOpenChange(false);
    } catch (err) {
      setError(mapApiError(err instanceof Error ? err.message : String(err), t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-lg"
        onPointerDownOutside={(event) => event.preventDefault()}
        onInteractOutside={(event) => event.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>{t("settings.apiKeys.addModel")}</DialogTitle>
          <DialogDescription>{t("settings.apiKeys.addModelHint")}</DialogDescription>
        </DialogHeader>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-4">
          {showKeySelect && (
            <FormField id="byok-model-key" label={t("settings.apiKeys.wizard.keyExisting")}>
              <Select value={providerId ?? undefined} onValueChange={onProviderChange}>
                <SelectTrigger id="byok-model-key" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {providers.map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.label} · ••••{item.key_last4}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          )}
          {catalogLoading ? (
            <p className="text-sm text-muted-foreground">
              {t("settings.apiKeys.wizard.modelFetching")}
            </p>
          ) : useCatalogSelect ? (
            <FormField id="byok-model-id" label={t("settings.apiKeys.wizard.modelId")}>
              <Select
                value={modelId || undefined}
                onValueChange={(value) => {
                  setModelId(value);
                  setCapabilityOverride(null);
                }}
              >
                <SelectTrigger id="byok-model-id" className="w-full">
                  <SelectValue placeholder={t("settings.apiKeys.wizard.modelId")} />
                </SelectTrigger>
                <SelectContent>
                  {catalog?.models.map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          ) : (
            <FormField id="byok-model-id" label={t("settings.apiKeys.wizard.modelId")}>
              <Input
                id="byok-model-id"
                value={modelId}
                onChange={(e) => {
                  setModelId(e.target.value);
                  setCapabilityOverride(null);
                }}
                autoComplete="off"
              />
              <p className="text-xs text-muted-foreground">
                {t("settings.apiKeys.wizard.modelFreeText")}
              </p>
            </FormField>
          )}
          <FormField id="byok-model-capability" label={t("settings.apiKeys.wizard.capability")}>
            <Select
              value={capability}
              onValueChange={(value) => setCapabilityOverride(value as ByokCapability)}
            >
              <SelectTrigger id="byok-model-capability" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="chat">{t("settings.apiKeys.capability.chat")}</SelectItem>
                <SelectItem value="image">{t("settings.apiKeys.capability.image")}</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button type="button" disabled={busy || !providerId} onClick={() => void onSave()}>
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
