import { useState } from "react";
import { useTranslation } from "react-i18next";

type PasswordBoxProps = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete?: string;
  placeholder?: string;
  required?: boolean;
};

function EyeIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      className="h-4 w-4"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178Z"
      />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      className="h-4 w-4"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M3.98 8.223A10.477 10.477 0 0 0 1.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.451 10.451 0 0 1 12 4.5c4.756 0 8.773 3.162 10.065 7.498a10.522 10.522 0 0 1-4.293 5.774M6.228 6.228 3 3m3.228 3.228 3.65 3.65m7.894 7.894L21 21m-3.228-3.228-3.65-3.65m0 0a3 3 0 1 0-4.243-4.243m4.242 4.242L9.88 9.88"
      />
    </svg>
  );
}

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
    <div className="space-y-2">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete}
          placeholder={placeholder}
          required={required}
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] py-2.5 pr-10 pl-3 text-sm outline-none transition focus:border-[var(--color-ring)] focus:ring-2 focus:ring-[var(--color-ring)]/30"
        />
        <button
          type="button"
          onClick={() => setVisible((current) => !current)}
          aria-label={visible ? t("common.hidePassword") : t("common.showPassword")}
          aria-pressed={visible}
          className="absolute top-1/2 right-2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-md text-[var(--color-muted)] transition hover:bg-[var(--color-hover)] hover:text-[var(--color-foreground)]"
        >
          {visible ? <EyeOffIcon /> : <EyeIcon />}
        </button>
      </div>
    </div>
  );
}
