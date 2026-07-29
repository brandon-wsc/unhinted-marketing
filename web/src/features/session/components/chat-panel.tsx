import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Streamdown } from "streamdown";
import { cjk } from "@streamdown/cjk";
import { Button } from "@/components/auth-layout";
import { useAuth } from "@/context/auth-context";
import { useToast } from "@/context/toast-context";
import { RecommendedQuestions } from "@/features/session/components/recommended-questions";
import { useRecommendedQuestions } from "@/features/session/use-recommended-questions";
import { useSession } from "@/features/session/use-session";
import type {
  AgentProgress,
  ChatMessage,
  RecommendedQuestion,
  SessionBrief,
} from "@/features/session/types";

export function ChatPanel() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { showError } = useToast();
  const companyId = user?.organizations[0]?.id;
  const {
    messages,
    sending,
    sseConnected,
    streamingText,
    agentProgress,
    brief,
    awaitingImageOk,
    sendMessage,
  } = useSession(companyId);
  const {
    questions,
    loading: questionsLoading,
    isStale,
  } = useRecommendedQuestions(companyId);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, sending, streamingText, agentProgress, brief, awaitingImageOk]);

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

  async function onPickQuestion(question: RecommendedQuestion) {
    if (sending) return;
    try {
      await sendMessage(question.text);
    } catch {
      showError(t("chat.error.sendFailed"));
    }
  }

  async function onResumeImageGen() {
    try {
      await sendMessage(t("chat.agent.imageOkMessage"));
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

  const showLanding = messages.length === 0 && !sending && streamingText === null;

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
          {showLanding ? (
            <div className="flex flex-col items-center justify-center py-16 text-center sm:py-24">
              <h1 className="text-2xl font-semibold tracking-tight">{t("chat.empty.title")}</h1>
              <p className="mt-2 max-w-md text-sm text-[var(--color-muted)]">
                {t("chat.empty.subtitle")}
              </p>
              <RecommendedQuestions
                questions={questions}
                loading={questionsLoading}
                isStale={isStale}
                disabled={sending}
                onSelect={(q) => void onPickQuestion(q)}
              />
            </div>
          ) : (
            messages.map((m) => <ChatMessageItem key={m.id} message={m} />)
          )}
          {brief && <BriefCard brief={brief} />}
          {awaitingImageOk && (
            <InterruptCard sending={sending} onResume={() => void onResumeImageGen()} />
          )}
          {streamingText !== null && (
            <div className="text-sm leading-relaxed">
              <Streamdown mode="streaming" plugins={{ cjk }}>
                {streamingText}
              </Streamdown>
            </div>
          )}
          {sending && streamingText === null && <AgentStatusLine progress={agentProgress} />}
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

function AgentStatusLine({ progress }: { progress: AgentProgress | null }) {
  const { t } = useTranslation();
  const nodeKey = `chat.agent.nodes.${progress?.node ?? "working"}`;
  return (
    <div className="flex items-center gap-2 text-sm text-[var(--color-muted)]">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--color-primary)]" />
      <span>{t(nodeKey, { defaultValue: t("chat.agent.nodes.working") })}</span>
      {progress?.model && (
        <span className="rounded-md border border-[var(--color-border)] px-1.5 py-0.5 text-[11px] leading-none">
          {progress.model_tier ? `${progress.model_tier} · ` : ""}
          {progress.model}
        </span>
      )}
    </div>
  );
}

function BriefCard({ brief }: { brief: SessionBrief }) {
  const { t } = useTranslation();
  const sections: { title: string; items: string[] }[] = [
    { title: t("chat.agent.brief.canDo"), items: brief.can_do },
    { title: t("chat.agent.brief.cannotDo"), items: brief.cannot_do },
    { title: t("chat.agent.brief.angles"), items: brief.angles },
  ].filter((s) => s.items.length > 0);

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4 text-sm shadow-sm">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-[var(--color-muted)]">
          {t("chat.agent.brief.title")}
        </span>
        {brief.persona && (
          <span className="rounded-md border border-[var(--color-border)] px-1.5 py-0.5 text-[11px] leading-none text-[var(--color-muted)]">
            {brief.persona}
          </span>
        )}
      </div>
      {brief.summary && <p className="mb-3 leading-relaxed">{brief.summary}</p>}
      <div className="flex flex-col gap-3">
        {sections.map((section) => (
          <div key={section.title}>
            <p className="mb-1 text-xs font-medium text-[var(--color-muted)]">{section.title}</p>
            <ul className="list-disc space-y-0.5 pl-5 leading-relaxed">
              {section.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

function InterruptCard({ sending, onResume }: { sending: boolean; onResume: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-[var(--color-primary)]/40 bg-[var(--color-card)] p-4 text-sm shadow-sm sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="font-medium">{t("chat.agent.interrupt.title")}</p>
        <p className="mt-0.5 text-[var(--color-muted)]">{t("chat.agent.interrupt.subtitle")}</p>
      </div>
      <Button onClick={onResume} disabled={sending} className="shrink-0">
        {t("chat.agent.interrupt.confirm")}
      </Button>
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
