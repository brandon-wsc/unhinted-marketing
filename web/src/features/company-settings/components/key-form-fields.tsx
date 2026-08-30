import { useTranslation } from "react-i18next";
import { FormField } from "@/components/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ByokProviderType } from "@/features/company-settings/api";
import {
  BYOK_PROVIDER_TYPES,
  type ByokKeyFormValue,
} from "@/features/company-settings/byok-helpers";

type KeyFormFieldsProps = {
  idPrefix: string;
  value: ByokKeyFormValue;
  onChange: (next: ByokKeyFormValue) => void;
  /** Show the provider-type select. Hidden when editing an existing key (type is fixed). */
  showType?: boolean;
  /** When false the key field is optional and shows the rotate placeholder. */
  keyRequired?: boolean;
};

/** Shared label / type / secret / api_base fields for add-key, edit-key, and wizard step 1. */
export function KeyFormFields({
  idPrefix,
  value,
  onChange,
  showType = true,
  keyRequired = true,
}: KeyFormFieldsProps) {
  const { t } = useTranslation();
  return (
    <>
      <FormField id={`${idPrefix}-label`} label={t("settings.apiKeys.wizard.label")}>
        <Input
          id={`${idPrefix}-label`}
          value={value.label}
          onChange={(e) => onChange({ ...value, label: e.target.value })}
          autoComplete="off"
        />
      </FormField>
      {showType && (
        <FormField id={`${idPrefix}-type`} label={t("settings.apiKeys.wizard.providerType")}>
          <Select
            value={value.providerType}
            onValueChange={(next) => onChange({ ...value, providerType: next as ByokProviderType })}
          >
            <SelectTrigger id={`${idPrefix}-type`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {BYOK_PROVIDER_TYPES.map((type) => (
                <SelectItem key={type} value={type}>
                  {t(`settings.apiKeys.providerType.${type}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      )}
      <FormField id={`${idPrefix}-key`} label={t("settings.apiKeys.wizard.apiKey")}>
        <Input
          id={`${idPrefix}-key`}
          type="password"
          value={value.apiKey}
          onChange={(e) => onChange({ ...value, apiKey: e.target.value })}
          autoComplete="new-password"
          placeholder={keyRequired ? undefined : t("settings.apiKeys.edit.apiKeyPlaceholder")}
        />
      </FormField>
      {value.providerType === "openai_compatible" && (
        <FormField id={`${idPrefix}-base`} label={t("settings.apiKeys.wizard.apiBase")}>
          <Input
            id={`${idPrefix}-base`}
            value={value.apiBase}
            onChange={(e) => onChange({ ...value, apiBase: e.target.value })}
            autoComplete="off"
            placeholder="https://"
          />
          <p className="text-xs text-muted-foreground">
            {t("settings.apiKeys.wizard.apiBaseHint")}
          </p>
        </FormField>
      )}
    </>
  );
}
