import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Streamdown } from "streamdown";
import { cjk } from "@streamdown/cjk";
import { Button } from "@/components/auth-layout";
import { useAuth } from "@/context/auth-context";
import { useToast } from "@/context/toast-context";
import { PreviewPanel } from "@/features/session/components/preview-panel";
import { RecommendedQuestions } from "@/features/session/components/recommended-questions";
import { SessionHistorySidebar } from "@/features/session/components/session-history";
import { useRecommendedQuestions } from "@/features/session/use-recommended-questions";
import { useSession } from "@/features/session/use-session";
import type {
  AgentActionRecord,
  ChatMessage,
  DraftCopy,
  RecommendedQuestion,
  SessionBrief,
} from "@/features/session/types";

const HISTORY_COLLAPSED_KEY = "unhinted.sessionHistory.collapsed";

type MobileTab = "record" | "chat" | "preview";

export function ChatPanel() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { showError } = useToast();
  const companyId = user?.organizations[0]?.id;
  const {
    session,
    messages,
    mode,
    sending,
    streamingText,
    agentActions,
    brief,
    briefAfterMessageId,
    interruptAfterMessageId,
    awaitingImageOk,
    draft,
    confirmReceipt,
    draftSaving,
    confirming,
    llmError,
    history,
    historyLoading,
    restoring,
    sendMessage,
    updateDraft,
    confirmPost,
    openSession,
    startNewChat,
    renameSession,
    pinSession,
    deleteSession,
  } = useSession(companyId);
  const {
    questions,
    loading: questionsLoading,
    isStale,
  } = useRecommendedQuestions(companyId);
  const [input, setInput] = useState("");
  const [historyCollapsed, setHistoryCollapsed] = useState(() => {
    try {
      return localStorage.getItem(HISTORY_COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [mobileTab, setMobileTab] = useState<MobileTab>("chat");
  const scrollRef = useRef<HTMLDivElement>(null);
  const previewMode = mode === "PREVIEW" && !!draft;

  // Preview page only exists while a draft is ready — fall back to chat.
  useEffect(() => {
    if (!previewMode && mobileTab === "preview") {
      setMobileTab("chat");
    }
  }, [previewMode, mobileTab]);

  function goToChat() {
    setMobileTab("chat");
  }

  function toggleHistoryCollapsed() {
    setHistoryCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(HISTORY_COLLAPSED_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }

  function handleSelectSession(id: string) {
    void openSession(id).catch(() => showError(t("chat.history.openFailed")));
    goToChat();
  }

  function handleNewChat() {
    startNewChat();
    goToChat();
  }

  async function handleRenameSession(id: string, title: string) {
    try {
      await renameSession(id, title);
    } catch {
      showError(t("chat.history.renameFailed"));
    }
  }

  async function handlePinSession(id: string, pinned: boolean) {
    try {
      await pinSession(id, pinned);
    } catch {
      showError(t("chat.history.pinFailed"));
    }
  }

  async function handleDeleteSession(id: string) {
    try {
      await deleteSession(id);
    } catch {
      showError(t("chat.history.deleteFailed"));
    }
  }

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, sending, streamingText, agentActions, brief, awaitingImageOk]);

  async function onSubmit(e?: FormEvent) {
    e?.preventDefault();
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    try {
      await sendMessage(text);
    } catch {
      setInput(text);
      showError(t("chat.error.sendFailed"));
    }
  }

  async function onRetryUserMessage(content: string) {
    if (!content.trim() || sending) return;
    try {
      await sendMessage(content);
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

  async function onApplyDraft(copy: DraftCopy) {
    try {
      await updateDraft(copy);
    } catch {
      showError(t("preview.error.saveFailed"));
    }
  }

  async function onConfirmDraft(copy: DraftCopy) {
    try {
      await confirmPost(copy);
    } catch {
      showError(t("preview.error.confirmFailed"));
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
  const confirmed = session?.status === "confirmed" || !!confirmReceipt;

  const historyProps = {
    sessions: history,
    loading: historyLoading,
    activeSessionId: session?.id ?? null,
    onSelect: handleSelectSession,
    onNewChat: handleNewChat,
    onRename: handleRenameSession,
    onPin: handlePinSession,
    onDelete: handleDeleteSession,
  };

  const historySidebar = (
    <SessionHistorySidebar
      collapsed={historyCollapsed}
      onToggle={toggleHistoryCollapsed}
      {...historyProps}
    />
  );

  const chatColumn = (
    <div className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      <div className="absolute left-4 top-3 z-10 lg:hidden">
        <button
          type="button"
          onClick={() => setMobileTab("record")}
          className="pointer-events-auto flex h-9 w-9 items-center justify-center rounded-full border border-[var(--color-border)] bg-[var(--color-card)]/90 text-[var(--color-muted)] backdrop-blur transition hover:bg-[var(--color-hover)] hover:text-[var(--color-foreground)]"
          title={t("chat.history.open")}
          aria-label={t("chat.history.open")}
        >
          <svg width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden>
            <rect x="2" y="2.5" width="12" height="11" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
            <path d="M6 2.5v11" stroke="currentColor" strokeWidth="1.2" />
          </svg>
        </button>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        <div
          className={`mx-auto flex w-full flex-col gap-5 px-4 pb-6 pt-14 sm:px-6 lg:pt-6 ${
            previewMode ? "max-w-none" : "max-w-3xl"
          }`}
        >
          {restoring ? (
            <p className="py-16 text-center text-sm text-[var(--color-muted)]">
              {t("chat.history.restoring")}
            </p>
          ) : showLanding ? (
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
            messages.map((m, index) => {
              const prevUser = findPreviousUserContent(messages, index);
              const turnActions = agentActions.filter((a) => a.afterMessageId === m.id);
              return (
              <div key={m.id} className="flex flex-col gap-5">
                <ChatMessageItem
                  message={m}
                  retryContent={prevUser}
                  retryDisabled={sending}
                  onRetry={
                    prevUser
                      ? () => void onRetryUserMessage(prevUser)
                      : undefined
                  }
                />
                {turnActions.length > 0 && <AgentActionList actions={turnActions} />}
                {brief && briefAfterMessageId === m.id && <BriefCard brief={brief} />}
                {awaitingImageOk && interruptAfterMessageId === m.id && (
                  <InterruptCard sending={sending} onResume={() => void onResumeImageGen()} />
                )}
              </div>
              );
            })
          )}
          {/* Fallback if anchor message was replaced / missing — keep cards visible. */}
          {agentActions.some((a) => !a.afterMessageId || !messages.some((m) => m.id === a.afterMessageId)) && (
            <AgentActionList
              actions={agentActions.filter(
                (a) => !a.afterMessageId || !messages.some((m) => m.id === a.afterMessageId),
              )}
            />
          )}
          {brief &&
            briefAfterMessageId &&
            !messages.some((m) => m.id === briefAfterMessageId) && (
              <BriefCard brief={brief} />
            )}
          {awaitingImageOk &&
            interruptAfterMessageId &&
            !messages.some((m) => m.id === interruptAfterMessageId) && (
              <InterruptCard sending={sending} onResume={() => void onResumeImageGen()} />
            )}
          {brief && !briefAfterMessageId && <BriefCard brief={brief} />}
          {awaitingImageOk && !interruptAfterMessageId && (
            <InterruptCard sending={sending} onResume={() => void onResumeImageGen()} />
          )}
          {/* Inline LLM error when failed before an assistant row was persisted. */}
          {llmError && !messages.some((m) => isLlmErrorContent(m.content)) && (
            <LlmErrorCard
              message={llmError}
              retryDisabled={sending}
              onRetry={
                findLastUserContent(messages)
                  ? () => void onRetryUserMessage(findLastUserContent(messages)!)
                  : undefined
              }
            />
          )}
          {previewMode && (
            <button
              type="button"
              onClick={() => setMobileTab("preview")}
              className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] px-3 py-2 text-left text-xs text-[var(--color-muted)] transition hover:border-[var(--color-ring)] hover:text-[var(--color-foreground)] lg:hidden"
            >
              {t("preview.readyBanner")}
            </button>
          )}
          {streamingText !== null && (
            <div className="text-sm leading-relaxed">
              <Streamdown mode="streaming" plugins={{ cjk }}>
                {streamingText}
              </Streamdown>
            </div>
          )}
        </div>
      </div>

      <div className="shrink-0 border-t border-[var(--color-border)] bg-[var(--color-card)]">
        <form
          onSubmit={onSubmit}
          className={`mx-auto flex w-full items-end gap-3 px-4 py-4 sm:px-6 ${
            previewMode ? "max-w-none" : "max-w-3xl"
          }`}
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

  const previewPane = previewMode ? (
    <PreviewPanel
      draft={draft}
      confirmed={confirmed}
      confirmReceipt={confirmReceipt}
      draftSaving={draftSaving}
      confirming={confirming}
      onApply={onApplyDraft}
      onConfirm={onConfirmDraft}
      onBack={goToChat}
    />
  ) : null;

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden">
      <div className="hidden h-full min-h-0 lg:flex">{historySidebar}</div>

      {/* Mobile record page */}
      {mobileTab === "record" && (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden lg:hidden">
          <SessionHistorySidebar
            collapsed={false}
            onToggle={() => undefined}
            pageMode
            onBack={goToChat}
            {...historyProps}
          />
        </div>
      )}

      {/* Chat — primary on mobile; always visible on desktop */}
      <div
        className={`min-h-0 min-w-0 flex-col overflow-hidden ${
          mobileTab === "chat" ? "flex" : "hidden"
        } ${
          previewMode
            ? "flex-1 lg:flex lg:flex-none lg:basis-[38%]"
            : "flex-1 lg:flex"
        }`}
      >
        {chatColumn}
      </div>

      {/* Preview — push page on mobile; side pane on desktop */}
      {previewMode && previewPane ? (
        <div
          className={`min-h-0 min-w-0 flex-1 flex-col overflow-hidden ${
            mobileTab === "preview" ? "flex" : "hidden"
          } lg:flex`}
        >
          {previewPane}
        </div>
      ) : null}
    </div>
  );
}

function AgentActionList({ actions }: { actions: AgentActionRecord[] }) {
  const { t } = useTranslation();
  if (actions.length === 0) return null;
  return (
    <ul className="flex flex-col gap-1.5 py-0.5" aria-label={t("chat.agent.actions")}>
      {actions.map((action) => {
        const nodeKey = `chat.agent.nodes.${action.node}`;
        const label = t(nodeKey, { defaultValue: t("chat.agent.nodes.working") });
        return (
          <li
            key={action.id}
            className="flex items-start gap-2 text-xs leading-snug text-[var(--color-muted)]"
          >
            <span className="mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center">
              {action.status === "running" ? (
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--color-primary)]" />
              ) : (
                <CheckIcon />
              )}
            </span>
            <span className="min-w-0">
              <span className={action.status === "running" ? "text-[var(--color-foreground)]" : ""}>
                {label}
              </span>
              {action.model && (
                <span className="ml-1.5 opacity-70">
                  {action.model_tier ? `${action.model_tier} · ` : ""}
                  {action.model}
                </span>
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function CheckIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M3.5 8.5 6.5 11.5 12.5 4.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
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

function isLlmErrorContent(content: string): boolean {
  return (
    content.startsWith("AI 服務暫時唔可用") ||
    content.startsWith("AI service unavailable")
  );
}

function findPreviousUserContent(messages: ChatMessage[], index: number): string | null {
  for (let i = index - 1; i >= 0; i -= 1) {
    if (messages[i]?.role === "user") return messages[i]!.content;
  }
  return null;
}

function findLastUserContent(messages: ChatMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i]?.role === "user") return messages[i]!.content;
  }
  return null;
}

function LlmErrorCard({
  message,
  onRetry,
  retryDisabled,
}: {
  message: string;
  onRetry?: () => void;
  retryDisabled?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="flex flex-col gap-3 rounded-xl border border-[var(--color-destructive)]/40 px-4 py-3 text-sm shadow-sm sm:flex-row sm:items-start sm:justify-between"
      style={{
        backgroundColor: "var(--color-destructive-soft)",
        color: "var(--color-destructive-text)",
      }}
      role="alert"
    >
      <p className="min-w-0 flex-1 whitespace-pre-wrap leading-relaxed">{message}</p>
      {onRetry && (
        <Button
          type="button"
          variant="ghost"
          disabled={retryDisabled}
          onClick={onRetry}
          className="shrink-0 border border-[var(--color-destructive)]/40 text-[var(--color-destructive-text)] hover:bg-[var(--color-destructive)]/10"
        >
          {t("chat.error.retry")}
        </Button>
      )}
    </div>
  );
}

function ChatMessageItem({
  message,
  onRetry,
  retryContent,
  retryDisabled,
}: {
  message: ChatMessage;
  onRetry?: () => void;
  retryContent?: string | null;
  retryDisabled?: boolean;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-[var(--color-primary)] px-4 py-2.5 text-sm text-white sm:max-w-[75%]">
          {message.content}
        </div>
      </div>
    );
  }
  if (isLlmErrorContent(message.content)) {
    return (
      <LlmErrorCard
        message={message.content}
        onRetry={retryContent ? onRetry : undefined}
        retryDisabled={retryDisabled}
      />
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
