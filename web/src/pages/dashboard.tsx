import { useTranslation } from "react-i18next";
import { Navigate, useParams } from "react-router-dom";
import { AppShell } from "@/components/app-header";
import { useAuth } from "@/context/auth-context";
import { ChatPanel } from "@/features/session/components/chat-panel";

export function DashboardPage() {
  const { t } = useTranslation();
  const { user, loading } = useAuth();
  // ADR 0051 §12 — /sessions/:id is the Confirm deep link an MCP client returns.
  const { sessionId } = useParams();

  if (loading) {
    return (
      <AppShell mainClassName="flex items-center justify-center overflow-y-auto">
        <p className="text-muted-foreground">{t("common.loading")}</p>
      </AppShell>
    );
  }

  if (!user) return <Navigate to="/login" replace />;

  return (
    <AppShell mainClassName="flex min-h-0 flex-col overflow-hidden">
      <ChatPanel requestedSessionId={sessionId} />
    </AppShell>
  );
}
