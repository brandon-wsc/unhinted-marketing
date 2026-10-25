import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CopyField } from "@/components/copy-field";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { API_BASE } from "@/lib/api-base";

/**
 * ADR 0051 — the MCP URL is the whole install story: the client discovers
 * OAuth itself via `/.well-known`, then our consent page binds one company.
 * Prefer the configured web_base_url (token audiences bind to it); the page
 * origin is only a fallback for when /api/meta is unreachable.
 */
export function ConnectAppCard() {
  const { t } = useTranslation();
  const [base, setBase] = useState(window.location.origin);
  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/meta`)
      .then((r) => (r.ok ? r.json() : null))
      .then((meta: { web_base_url?: string } | null) => {
        if (!cancelled && meta?.web_base_url) setBase(meta.web_base_url.replace(/\/+$/, ""));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);
  const mcpUrl = `${base}/api/mcp`;

  return (
    <section className="space-y-4 rounded-lg border border-border bg-card p-4">
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-foreground">{t("account.connectAi.title")}</h2>
        <p className="text-sm text-muted-foreground">{t("account.connectAi.description")}</p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="mcp-server-url">{t("account.connectAi.urlLabel")}</Label>
        <CopyField id="mcp-server-url" value={mcpUrl} className="flex-row" />
      </div>
      <Tabs defaultValue="claude">
        <TabsList>
          <TabsTrigger value="claude">Claude</TabsTrigger>
          <TabsTrigger value="chatgpt">ChatGPT</TabsTrigger>
          <TabsTrigger value="agents">{t("account.connectAi.agentsTab")}</TabsTrigger>
        </TabsList>
        {(["claude", "chatgpt"] as const).map((app) => (
          <TabsContent key={app} value={app}>
            <ol className="list-decimal space-y-1.5 pl-5 text-sm text-muted-foreground">
              <li>{t(`account.connectAi.steps.${app}.1`)}</li>
              <li>{t(`account.connectAi.steps.${app}.2`)}</li>
              <li>{t(`account.connectAi.steps.${app}.3`)}</li>
            </ol>
          </TabsContent>
        ))}
        <TabsContent value="agents" className="space-y-2">
          <ol className="list-decimal space-y-1.5 pl-5 text-sm text-muted-foreground">
            <li>{t("account.connectAi.steps.agents.1")}</li>
            <li>{t("account.connectAi.steps.agents.2")}</li>
          </ol>
          <pre className="overflow-x-auto rounded-md bg-secondary p-3 text-xs text-foreground">{`{
  "url": "${mcpUrl}",
  "headers": { "Authorization": "Bearer unh_…" }
}`}</pre>
        </TabsContent>
      </Tabs>
      <p className="text-xs text-muted-foreground">{t("account.connectAi.geminiNote")}</p>
      <p className="text-xs text-muted-foreground">{t("account.connectAi.footer")}</p>
    </section>
  );
}
