import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { useTranslation } from "react-i18next";
import { FormField } from "@/components/form-field";
import { IconButton } from "@/components/icon-button";
import { Input } from "@/components/ui/input";

type PasswordBoxProps = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete?: string;
  placeholder?: string;
  required?: boolean;
};

export function PasswordBox({
  id,
  label,
  value,
  onChange,
  autoComplete,
  placeholder,
  required,
}: PasswordBoxProps) {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(false);

  return (
    <FormField id={id} label={label}>
      <div className="relative">
        <Input
          id={id}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete}
          placeholder={placeholder}
          required={required}
          className="pr-10"
        />
        <IconButton
          type="button"
          onClick={() => setVisible((current) => !current)}
          aria-label={visible ? t("common.hidePassword") : t("common.showPassword")}
          aria-pressed={visible}
          className="absolute top-1/2 right-1 h-7 w-7 -translate-y-1/2"
        >
          {visible ? <EyeOff /> : <Eye />}
        </IconButton>
      </div>
    </FormField>
  );
}
