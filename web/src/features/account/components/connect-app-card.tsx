import { useTranslation } from "react-i18next";
import { CopyField } from "@/components/copy-field";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

/**
 * ADR 0051 — the MCP URL is the whole install story: the client discovers
 * OAuth itself via `/.well-known`, then our consent page binds one company.
 * Derived from the SPA origin, which is the install's public web_base_url.
 */
export function ConnectAppCard() {
  const { t } = useTranslation();
  const mcpUrl = `${window.location.origin}/api/mcp`;

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
          <TabsTrigger value="gemini">Gemini</TabsTrigger>
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
        <TabsContent value="gemini">
          <p className="text-sm text-muted-foreground">{t("account.connectAi.geminiNote")}</p>
        </TabsContent>
      </Tabs>
      <p className="text-xs text-muted-foreground">{t("account.connectAi.footer")}</p>
    </section>
  );
}
