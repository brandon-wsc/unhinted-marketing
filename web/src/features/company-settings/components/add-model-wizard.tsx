import { useEffect, useRef, useState } from "react";
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
  apiCreateByokProvider,
  apiListByokProviderCatalog,
  apiPutByokRouting,
  type ByokCapability,
  type ByokListedModel,
  type ByokModelListProxy,
  type ByokProviderItem,
  type ByokProviderType,
  type ByokRoutingSlot,
  type ByokRoutingSlotName,
} from "@/features/company-settings/api";
import {
  capabilityFromListedModel,
  NEW_PROVIDER_VALUE,
  routingToUpdate,
  slotUpdateField,
} from "@/features/company-settings/byok-helpers";
import { mapApiError } from "@/lib/map-api-error";
import { cn } from "@/lib/utils";

type AddModelWizardProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  companyId: string;
  providers: ByokProviderItem[];
  routing: ByokRoutingSlot[];
  onChanged: () => Promise<void>;
};

type WizardStep = 1 | 2 | 3;

const CHAT_SLOTS: ByokRoutingSlotName[] = ["cheap", "medium", "strong"];
const PROVIDER_TYPES: ByokProviderType[] = ["openai", "anthropic", "openai_compatible"];

function listedFor(
  catalog: ByokModelListProxy | null,
  modelId: string,
): ByokListedModel | undefined {
  return catalog?.models.find((item) => item.id === modelId);
}

export function AddModelWizard({
  open,
  onOpenChange,
  companyId,
  providers,
  routing,
  onChanged,
}: AddModelWizardProps) {
  const { t } = useTranslation();
  const { accessToken } = useAuth();
  const providersRef = useRef(providers);
  providersRef.current = providers;
  const [step, setStep] = useState<WizardStep>(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [keyChoice, setKeyChoice] = useState(NEW_PROVIDER_VALUE);
  const [label, setLabel] = useState("");
  const [providerType, setProviderType] = useState<ByokProviderType>("openai");
  const [apiKey, setApiKey] = useState("");
  const [apiBase, setApiBase] = useState("");
  const [providerId, setProviderId] = useState<string | null>(null);

  const [catalog, setCatalog] = useState<ByokModelListProxy | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [modelId, setModelId] = useState("");
  const [capabilityOverride, setCapabilityOverride] = useState<ByokCapability | null>(null);

  const [slots, setSlots] = useState<Set<ByokRoutingSlotName>>(new Set());

  useEffect(() => {
    const nextProviders = providersRef.current;
    setStep(1);
    setBusy(false);
    setError(null);
    setKeyChoice(open ? (nextProviders[0]?.id ?? NEW_PROVIDER_VALUE) : NEW_PROVIDER_VALUE);
    setLabel("");
    setProviderType("openai");
    setApiKey("");
    setApiBase("");
    setProviderId(null);
    setCatalog(null);
    setCatalogLoading(false);
    setModelId("");
    setCapabilityOverride(null);
    setSlots(new Set());
  }, [open]);

  const addingKey =
    providerId == null && (keyChoice === NEW_PROVIDER_VALUE || providers.length === 0);
  const suggested = capabilityFromListedModel(modelId, listedFor(catalog, modelId));
  const capability = capabilityOverride ?? suggested.capability;
  const capabilitySource =
    capabilityOverride && capabilityOverride !== suggested.capability ? "manual" : suggested.source;
  const slotChoices: ByokRoutingSlotName[] = capability === "image" ? ["image"] : CHAT_SLOTS;
  const useCatalogSelect = Boolean(catalog?.fetchable && catalog.models.length > 0);

  async function loadCatalog(id: string) {
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
  }

  function validateStep1(): string | null {
    if (!addingKey) return keyChoice ? null : t("settings.apiKeys.errors.keyRequired");
    if (!label.trim()) return t("settings.apiKeys.errors.labelRequired");
    if (!apiKey.trim()) return t("settings.apiKeys.errors.keyRequired");
    if (providerType === "openai_compatible" && !apiBase.trim()) {
      return t("settings.apiKeys.errors.apiBaseRequired");
    }
    return null;
  }

  async function onNext() {
    setError(null);
    if (step === 1) {
      const invalid = validateStep1();
      if (invalid) {
        setError(invalid);
        return;
      }
      setBusy(true);
      try {
        let nextId = keyChoice;
        if (addingKey) {
          const created = await apiCreateByokProvider(accessToken, companyId, {
            label: label.trim(),
            provider_type: providerType,
            api_key: apiKey.trim(),
            api_base: providerType === "openai_compatible" ? apiBase.trim() : null,
          });
          nextId = created.id;
          setApiKey("");
          setKeyChoice(created.id);
          try {
            await onChanged();
          } catch {
            // Key is already stored; continue so retry does not POST again.
          }
        }
        setProviderId(nextId);
        setStep(2);
        await loadCatalog(nextId);
      } catch (err) {
        setError(mapApiError(err instanceof Error ? err.message : String(err), t));
      } finally {
        setBusy(false);
      }
      return;
    }
    if (step === 2) {
      if (!modelId.trim()) {
        setError(t("settings.apiKeys.errors.modelRequired"));
        return;
      }
      setSlots(new Set());
      setStep(3);
    }
  }

  async function onSave() {
    if (!providerId || !modelId.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const created = await apiCreateByokModel(accessToken, companyId, {
        provider_id: providerId,
        model_id: modelId.trim(),
        capability,
        capability_source: capabilitySource,
      });
      if (slots.size > 0) {
        const update = routingToUpdate(routing);
        for (const slot of slots) {
          update[slotUpdateField(slot)] = created.id;
        }
        await apiPutByokRouting(accessToken, companyId, update);
      }
      await onChanged();
      onOpenChange(false);
    } catch (err) {
      setError(mapApiError(err instanceof Error ? err.message : String(err), t));
    } finally {
      setBusy(false);
    }
  }

  function toggleSlot(slot: ByokRoutingSlotName) {
    setSlots((current) => {
      const next = new Set(current);
      if (next.has(slot)) next.delete(slot);
      else next.add(slot);
      return next;
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("settings.apiKeys.wizard.title")}</DialogTitle>
          <DialogDescription>
            {step === 1
              ? t("settings.apiKeys.wizard.stepKey")
              : step === 2
                ? t("settings.apiKeys.wizard.stepModel")
                : t("settings.apiKeys.wizard.stepSlots")}
          </DialogDescription>
        </DialogHeader>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {step === 1 && (
          <div className="space-y-4">
            {providers.length > 0 && (
              <FormField id="byok-wizard-key" label={t("settings.apiKeys.wizard.keyExisting")}>
                <Select value={keyChoice} onValueChange={setKeyChoice}>
                  <SelectTrigger id="byok-wizard-key" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {providers.map((item) => (
                      <SelectItem key={item.id} value={item.id}>
                        {item.label} · ••••{item.key_last4}
                      </SelectItem>
                    ))}
                    <SelectItem value={NEW_PROVIDER_VALUE}>
                      {t("settings.apiKeys.wizard.keyNew")}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </FormField>
            )}
            {addingKey && (
              <>
                <FormField id="byok-wizard-label" label={t("settings.apiKeys.wizard.label")}>
                  <Input
                    id="byok-wizard-label"
                    value={label}
                    onChange={(e) => setLabel(e.target.value)}
                    autoComplete="off"
                  />
                </FormField>
                <FormField id="byok-wizard-type" label={t("settings.apiKeys.wizard.providerType")}>
                  <Select
                    value={providerType}
                    onValueChange={(value) => setProviderType(value as ByokProviderType)}
                  >
                    <SelectTrigger id="byok-wizard-type" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PROVIDER_TYPES.map((type) => (
                        <SelectItem key={type} value={type}>
                          {t(`settings.apiKeys.providerType.${type}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FormField>
                <FormField id="byok-wizard-api-key" label={t("settings.apiKeys.wizard.apiKey")}>
                  <Input
                    id="byok-wizard-api-key"
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    autoComplete="new-password"
                  />
                </FormField>
                {providerType === "openai_compatible" && (
                  <FormField id="byok-wizard-api-base" label={t("settings.apiKeys.wizard.apiBase")}>
                    <Input
                      id="byok-wizard-api-base"
                      value={apiBase}
                      onChange={(e) => setApiBase(e.target.value)}
                      autoComplete="off"
                      placeholder="https://"
                    />
                    <p className="text-xs text-muted-foreground">
                      {t("settings.apiKeys.wizard.apiBaseHint")}
                    </p>
                  </FormField>
                )}
              </>
            )}
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            {catalogLoading ? (
              <p className="text-sm text-muted-foreground">
                {t("settings.apiKeys.wizard.modelFetching")}
              </p>
            ) : useCatalogSelect ? (
              <FormField id="byok-wizard-model" label={t("settings.apiKeys.wizard.modelId")}>
                <Select
                  value={modelId || undefined}
                  onValueChange={(value) => {
                    setModelId(value);
                    setCapabilityOverride(null);
                  }}
                >
                  <SelectTrigger id="byok-wizard-model" className="w-full">
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
              <FormField id="byok-wizard-model" label={t("settings.apiKeys.wizard.modelId")}>
                <Input
                  id="byok-wizard-model"
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
            <FormField id="byok-wizard-capability" label={t("settings.apiKeys.wizard.capability")}>
              <Select
                value={capability}
                onValueChange={(value) => setCapabilityOverride(value as ByokCapability)}
              >
                <SelectTrigger id="byok-wizard-capability" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="chat">{t("settings.apiKeys.capability.chat")}</SelectItem>
                  <SelectItem value="image">{t("settings.apiKeys.capability.image")}</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              {t("settings.apiKeys.wizard.slotsHint")}
            </p>
            <div className="flex flex-wrap gap-2">
              {slotChoices.map((slot) => {
                const selected = slots.has(slot);
                return (
                  <Button
                    key={slot}
                    type="button"
                    size="sm"
                    variant="outline"
                    className={cn(selected && "bg-accent text-accent-foreground")}
                    onClick={() => toggleSlot(slot)}
                    aria-pressed={selected}
                  >
                    {t(`settings.apiKeys.routing.slots.${slot}`)}
                  </Button>
                );
              })}
            </div>
          </div>
        )}

        <DialogFooter>
          {step > 1 && (
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => {
                setError(null);
                setStep((current) => (current === 3 ? 2 : 1));
              }}
            >
              {t("settings.apiKeys.wizard.back")}
            </Button>
          )}
          {step < 3 ? (
            <Button type="button" disabled={busy} onClick={() => void onNext()}>
              {t("settings.apiKeys.wizard.next")}
            </Button>
          ) : (
            <Button type="button" disabled={busy} onClick={() => void onSave()}>
              {t("settings.apiKeys.wizard.save")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
