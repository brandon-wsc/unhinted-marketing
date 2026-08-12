import { Navigate, useLocation } from "react-router-dom";

/** Preserve query string when redirecting bookmarks from the old `/admin` SPA path. */
export function LegacyAdminRedirect() {
  const { search } = useLocation();
  return <Navigate to={`/system${search}`} replace />;
}
