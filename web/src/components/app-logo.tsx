import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

type AppLogoProps = {
  className?: string;
  showName?: boolean;
};

export function AppLogo({ className = "", showName = true }: AppLogoProps) {
  const { t } = useTranslation();

  return (
    <Link to="/" className={`inline-flex items-center gap-2.5 min-w-0 ${className}`}>
      <img src="/logo.svg" alt="" className="h-8 w-8 shrink-0 rounded-lg" width={32} height={32} />
      {showName && (
        <span className="font-semibold text-base tracking-tight truncate">{t("app.name")}</span>
      )}
    </Link>
  );
}
