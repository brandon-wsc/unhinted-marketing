import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useTheme } from "@/context/theme-context";

type AppLogoProps = {
  className?: string;
  showName?: boolean;
};

export function AppLogo({ className = "", showName = true }: AppLogoProps) {
  const { t } = useTranslation();
  const { mode } = useTheme();
  const name = t("app.name");

  return (
    <Link
      to="/"
      className={`inline-flex items-center gap-2.5 min-w-0 ${className}`}
      aria-label={showName ? undefined : name}
    >
      <img
        src={mode === "dark" ? "/logo-dark.svg" : "/logo-light.svg"}
        alt=""
        width={32}
        height={32}
        className="h-8 w-8 shrink-0"
      />
      {showName && <span className="font-semibold text-base tracking-tight truncate">{name}</span>}
    </Link>
  );
}
