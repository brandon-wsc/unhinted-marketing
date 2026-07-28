import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Streamdown } from "streamdown";
import { cjk } from "@streamdown/cjk";
import { Button } from "@/components/auth-layout";
import { useAuth } from "@/context/auth-context";
import { useToast } from "@/context/toast-context";
import { useSession } from "@/features/session/use-session";
import type { ChatMessage } from "@/features/session/types";

export function ChatPanel() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { showError } = useToast();
  const companyId = user?.organizations[0]?.id;
  const { messages, sending, sseConnected, streamingText, sendMessage } = useSession(companyId);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, sending, streamingText]);

  async function onSubmit(e?: FormEvent) {
    e?.preventDefault();
    const text = input.trim();
    if (!text || sending) return;
    try {
      await sendMessage(text);
      setInput("");
    } catch {
      showError(t("chat.error.sendFailed"));
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // isComposing guard: Enter must not send while a CJK IME candidate is open.
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void onSubmit();
    }
  }

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div className="pointer-events-none absolute right-4 top-3 z-10 flex items-center gap-1.5 text-xs text-[var(--color-muted)]">
        <span
          className={`h-1.5 w-1.5 rounded-full ${sseConnected ? "bg-emerald-500" : "bg-zinc-400"}`}
        />
        {sseConnected ? t("chat.live") : t("chat.offline")}
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-6 sm:px-6">
          {messages.length === 0 && !sending ? (
            <div className="flex flex-col items-center justify-center py-24 text-center">
              <h1 className="text-2xl font-semibold tracking-tight">{t("chat.empty.title")}</h1>
              <p className="mt-2 max-w-md text-sm text-[var(--color-muted)]">
                {t("chat.empty.subtitle")}
              </p>
            </div>
          ) : (
            messages.map((m) => <ChatMessageItem key={m.id} message={m} />)
          )}
          {streamingText !== null && (
            <div className="text-sm leading-relaxed">
              <Streamdown mode="streaming" plugins={{ cjk }}>
                {streamingText}
              </Streamdown>
            </div>
          )}
          {sending && streamingText === null && (
            <div className="flex items-center gap-2 text-sm text-[var(--color-muted)]">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--color-primary)]" />
              {t("chat.thinking")}
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-[var(--color-border)] bg-[var(--color-card)]">
        <form
          onSubmit={onSubmit}
          className="mx-auto flex w-full max-w-3xl items-end gap-3 px-4 py-4 sm:px-6"
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={2}
            placeholder={t("chat.input.placeholder")}
            className="flex-1 resize-none rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-4 py-3 text-sm outline-none transition focus:border-[var(--color-ring)] focus:ring-2 focus:ring-[var(--color-ring)]/30"
          />
          <Button type="submit" disabled={sending || !input.trim()} className="shrink-0">
            {t("chat.send")}
          </Button>
        </form>
      </div>
    </div>
  );
}

function ChatMessageItem({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-[var(--color-primary)] px-4 py-2.5 text-sm text-white sm:max-w-[75%]">
          {message.content}
        </div>
      </div>
    );
  }
  return (
    <div className="text-sm leading-relaxed">
      <Streamdown mode="static" plugins={{ cjk }}>
        {message.content}
      </Streamdown>
    </div>
  );
}
