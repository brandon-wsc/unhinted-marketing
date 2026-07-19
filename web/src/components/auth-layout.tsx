import type { ReactNode } from "react";
import { AppShell } from "@/components/app-header";

type AuthLayoutProps = {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer?: ReactNode;
};

export function AuthLayout({ title, subtitle, children, footer }: AuthLayoutProps) {
  return (
    <AppShell mainClassName="flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="text-[var(--color-muted)] mt-2 text-sm">{subtitle}</p>
        </div>

        <div
          className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-6 shadow-xl"
          style={{ boxShadow: `0 20px 40px var(--shadow-color)` }}
        >
          {children}
        </div>

        {footer && (
          <div className="mt-6 text-center text-sm text-[var(--color-muted)]">{footer}</div>
        )}
      </div>
    </AppShell>
  );
}

type FieldProps = {
  id: string;
  label: string;
  type?: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete?: string;
  placeholder?: string;
  required?: boolean;
};

export function Field({
  id,
  label,
  type = "text",
  value,
  onChange,
  autoComplete,
  placeholder,
  required,
}: FieldProps) {
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        placeholder={placeholder}
        required={required}
        className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm outline-none transition focus:border-[var(--color-ring)] focus:ring-2 focus:ring-[var(--color-ring)]/30"
      />
    </div>
  );
}

type ButtonProps = {
  children: ReactNode;
  type?: "button" | "submit";
  disabled?: boolean;
  variant?: "primary" | "ghost";
  onClick?: () => void;
  className?: string;
};

export function Button({
  children,
  type = "button",
  disabled,
  variant = "primary",
  onClick,
  className = "",
}: ButtonProps) {
  const base =
    "rounded-lg px-4 py-2.5 text-sm font-medium transition disabled:opacity-50 disabled:cursor-not-allowed";
  const styles =
    variant === "primary"
      ? "bg-[var(--color-primary)] hover:bg-[var(--color-primary-hover)] text-white"
      : "bg-transparent hover:bg-[var(--color-hover)] text-[var(--color-muted)] hover:text-[var(--color-foreground)]";

  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={`${base} ${styles} ${className}`}
    >
      {children}
    </button>
  );
}

export function ErrorAlert({ message }: { message: string }) {
  return (
    <div
      className="rounded-lg border border-[var(--color-destructive)]/30 px-3 py-2 text-sm"
      style={{
        backgroundColor: "var(--color-destructive-soft)",
        color: "var(--color-destructive-text)",
      }}
    >
      {message}
    </div>
  );
}
