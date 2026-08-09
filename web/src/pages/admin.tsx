import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { AppShell } from "@/components/app-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/context/auth-context";
import { LlmCallRecords } from "@/features/admin/components/llm-call-records";
import { NodeStepsPanel } from "@/features/admin/components/node-steps";
import { ResearchPanel } from "@/features/admin/components/research-panel";
import { SessionTracePanel } from "@/features/admin/components/session-trace";
import { isAdmin } from "@/lib/platform-level";

type AdminTab = "llm" | "steps" | "trace" | "research";

function parseTab(raw: string | null): AdminTab {
  if (raw === "steps" || raw === "trace" || raw === "research") return raw;
  return "llm";
}

export function AdminPage() {
  const { t } = useTranslation();
  const { user, loading } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = parseTab(params.get("tab"));
  const turnId = params.get("turn") ?? "";
  const sessionId = params.get("session") ?? "";

  const setTab = useMemo(
    () => (next: AdminTab, extras?: { turn?: string; session?: string }) => {
      const nextParams = new URLSearchParams(params);
      nextParams.set("tab", next);
      if (extras?.turn !== undefined) {
        if (extras.turn) nextParams.set("turn", extras.turn);
        else nextParams.delete("turn");
      }
      if (extras?.session !== undefined) {
        if (extras.session) nextParams.set("session", extras.session);
        else nextParams.delete("session");
      }
      setParams(nextParams, { replace: true });
    },
    [params, setParams],
  );

  if (loading) {
    return (
      <AppShell mainClassName="flex items-center justify-center overflow-y-auto">
        <p className="text-muted-foreground">{t("common.loading")}</p>
      </AppShell>
    );
  }

  if (!user) return <Navigate to="/login" replace />;

  if (!isAdmin(user.platform_level)) {
    return (
      <AppShell mainClassName="flex items-center justify-center overflow-y-auto">
        <div className="text-center">
          <h1 className="text-lg font-semibold text-foreground">{t("admin.forbidden.title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("admin.forbidden.body")}</p>
          <Link
            to="/"
            className="mt-4 inline-block rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90"
          >
            {t("admin.forbidden.back")}
          </Link>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell mainClassName="overflow-y-auto">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <h1 className="mb-4 text-lg font-semibold text-foreground">{t("admin.title")}</h1>
        <Tabs value={tab} onValueChange={(value) => setTab(parseTab(value))}>
          <TabsList>
            <TabsTrigger value="llm">{t("admin.tabs.llm")}</TabsTrigger>
            <TabsTrigger value="steps">{t("admin.tabs.steps")}</TabsTrigger>
            <TabsTrigger value="research">{t("admin.tabs.research")}</TabsTrigger>
            <TabsTrigger value="trace">{t("admin.tabs.trace")}</TabsTrigger>
          </TabsList>
          <TabsContent value="llm">
            <LlmCallRecords
              onOpenTurn={(id) => setTab("steps", { turn: id })}
              onOpenSession={(id) => setTab("trace", { session: id })}
              onOpenResearch={(id) => setTab("research", { session: id })}
            />
          </TabsContent>
          <TabsContent value="steps">
            <NodeStepsPanel
              initialTurnId={turnId}
              onOpenSession={(id) => setTab("trace", { session: id })}
            />
          </TabsContent>
          <TabsContent value="research">
            <ResearchPanel
              initialSessionId={sessionId}
              onOpenTurn={(id) => setTab("steps", { turn: id })}
            />
          </TabsContent>
          <TabsContent value="trace">
            <SessionTracePanel
              initialSessionId={sessionId}
              onOpenTurn={(id) => setTab("steps", { turn: id })}
              onOpenResearch={(id) => setTab("research", { session: id })}
            />
          </TabsContent>
        </Tabs>
      </div>
    </AppShell>
  );
}
