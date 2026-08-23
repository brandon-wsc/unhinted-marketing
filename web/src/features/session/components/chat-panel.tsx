import { cjk } from "@streamdown/cjk";
import { Check, Copy, CornerDownRight, Ellipsis, Pencil, Square, Trash2 } from "lucide-react";
import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { Streamdown } from "streamdown";
import { IconButton } from "@/components/icon-button";
import { SendIcon } from "@/components/icons/send-icon";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuth } from "@/context/auth-context";
import { useToast } from "@/context/toast-context";
import { PreviewPanel } from "@/features/session/components/preview-panel";
import { RecommendedQuestions } from "@/features/session/components/recommended-questions";
import { SessionHistorySidebar } from "@/features/session/components/session-history";
import { MAX_QUEUED_SESSION_MESSAGES, QUEUE_TUCK_PX } from "@/features/session/session-helpers";
import { sessionLayoutMode } from "@/features/session/session-layout";
import type {
  AgentActionRecord,
  ChatMessage,
  DraftCopy,
  RecommendedQuestion,
  SessionBrief,
} from "@/features/session/types";
import { useRecommendedQuestions } from "@/features/session/use-recommended-questions";
import { useSession } from "@/features/session/use-session";
import { useContainerWidth } from "@/hooks/use-container-width";
import { useNow } from "@/hooks/use-now";
import { classifyRelativeTime, formatAbsoluteDateTime } from "@/lib/format-relative-time";
import { cn } from "@/lib/utils";

const HISTORY_COLLAPSED_KEY = "unhinted.sessionHistory.collapsed";

type PagedPane = "record" | "chat" | "preview";

/** Border-box plus overflowing descendants (tucked queue). */
function overlayStackHeight(el: HTMLElement): number {
  const wrap = el.getBoundingClientRect();
  let top = wrap.top;
  for (const node of el.querySelectorAll("*")) {
    const r = node.getBoundingClientRect();
    if (r.height > 0) top = Math.min(top, r.top);
  }
  return Math.max(0, Math.round(wrap.bottom - top));
}

export function ChatPanel() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { showError } = useToast();
  const companyId = user?.organizations[0]?.id;
  const canPromoteExemplar =
    user?.organizations[0]?.role === "owner" || user?.organizations[0]?.role === "admin";
  const {
    session,
    messages,
    mode,
    sending,
    stopping,
    queueFull,
    queuedMessages,
    streamingText,
    agentActions,
    brief,
    briefAfterMessageId,
    interruptAfterMessageId,
    previewAfterMessageId,
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
    enqueueQueuedMessage,
    dequeueQueuedMessage,
    resumeImage,
    stopTurn,
    updateDraft,
    saveImagePlan,
    regenImage,
    addImage,
    removeImage,
    uploadImage,
    confirmPost,
    openSession,
    startNewChat,
    renameSession,
    pinSession,
    deleteSession,
  } = useSession(companyId);
  const { questions, loading: questionsLoading, isStale } = useRecommendedQuestions(companyId);
  const now = useNow();
  const [input, setInput] = useState("");
  const [editInsertAt, setEditInsertAt] = useState<number | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [historyCollapsed, setHistoryCollapsed] = useState(() => {
    try {
      return localStorage.getItem(HISTORY_COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [pagedPane, setPagedPane] = useState<PagedPane>("chat");
  const scrollRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLDivElement>(null);
  const [composerH, setComposerH] = useState(0);
  const { ref: shellRef, width: shellWidth } = useContainerWidth();
  const previewMode = mode === "PREVIEW" && !!draft;
  const layoutMode = sessionLayoutMode(shellWidth, {
    historyCollapsed,
    previewReady: previewMode,
  });
  const isSplit = layoutMode === "split";
  const composerCol = `mx-auto w-full px-4 sm:px-6 ${previewMode ? "max-w-none" : "max-w-3xl"}`;

  // Preview page only exists while a draft is ready — fall back to chat.
  useEffect(() => {
    if (!previewMode && pagedPane === "preview") {
      setPagedPane("chat");
    }
  }, [previewMode, pagedPane]);

  function goToChat() {
    setPagedPane("chat");
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
    void startNewChat()
      .then(() => goToChat())
      .catch(() => showError(t("chat.history.createFailed")));
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

  useLayoutEffect(() => {
    const el = composerRef.current;
    if (!el) return;
    const resize = new ResizeObserver(() => setComposerH(overlayStackHeight(el)));
    const observeTree = () => {
      resize.observe(el);
      for (const node of el.querySelectorAll("*")) {
        resize.observe(node);
      }
    };
    observeTree();
    setComposerH(overlayStackHeight(el));
    const mutations = new MutationObserver(() => {
      observeTree();
      setComposerH(overlayStackHeight(el));
    });
    mutations.observe(el, { childList: true, subtree: true });
    return () => {
      resize.disconnect();
      mutations.disconnect();
    };
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [
    messages,
    sending,
    streamingText,
    agentActions,
    brief,
    awaitingImageOk,
    queuedMessages,
    composerH,
  ]);

  async function onSubmit(e?: FormEvent) {
    e?.preventDefault();
    if (stopping) return;
    const text = input.trim();
    if (!text) return;
    const queueIndex = editInsertAt;
    if (sending && queueFull && queueIndex == null) return;
    setInput("");
    setEditInsertAt(null);
    try {
      await sendMessage(text, queueIndex != null ? { queueIndex } : undefined);
    } catch {
      setInput(text);
      setEditInsertAt(queueIndex);
      showError(t("chat.error.sendFailed"));
    }
  }

  function beginEditQueued(id: string) {
    const item = queuedMessages.find((q) => q.id === id);
    if (!item) return;
    if (editInsertAt != null) {
      const pending = input.trim();
      if (pending && !enqueueQueuedMessage(pending, editInsertAt)) return;
    } else if (input.trim()) {
      if (queuedMessages.length >= MAX_QUEUED_SESSION_MESSAGES) return;
      enqueueQueuedMessage(input);
    }
    const removedAt = dequeueQueuedMessage(id);
    if (removedAt < 0) return;
    setInput(item.content);
    setEditInsertAt(removedAt);
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  function cancelQueuedEdit() {
    if (editInsertAt == null) return;
    const text = input.trim();
    if (text) enqueueQueuedMessage(text, editInsertAt);
    setInput("");
    setEditInsertAt(null);
  }

  async function onRetryUserMessage(content: string) {
    if (!content.trim() || stopping) return;
    if (sending && queueFull) return;
    try {
      await sendMessage(content);
    } catch {
      showError(t("chat.error.sendFailed"));
    }
  }

  async function onPickQuestion(question: RecommendedQuestion) {
    if (stopping) return;
    if (sending && queueFull) return;
    try {
      await sendMessage(question.text);
    } catch {
      showError(t("chat.error.sendFailed"));
    }
  }

  async function onResumeImageGen(format?: "single" | "comic_4panel") {
    try {
      await resumeImage(format);
    } catch {
      showError(t("chat.error.sendFailed"));
    }
  }

  async function onStopTurn() {
    try {
      await stopTurn();
    } catch {
      showError(t("chat.error.stopFailed"));
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

  async function onSavePlan(imageId: string, plan: Record<string, unknown>) {
    try {
      return await saveImagePlan(imageId, plan);
    } catch {
      showError(t("preview.error.planFailed"));
      return null;
    }
  }

  async function onRegenImage(imageId: string) {
    try {
      await regenImage(imageId);
    } catch {
      showError(t("preview.error.regenFailed"));
    }
  }

  async function onAddImage(format?: "single" | "comic_4panel") {
    try {
      return await addImage(format);
    } catch {
      showError(t("preview.error.addFailed"));
      return null;
    }
  }

  async function onRemoveImage(imageId: string) {
    try {
      return await removeImage(imageId);
    } catch {
      showError(t("preview.error.removeFailed"));
      return null;
    }
  }

  async function onUploadImage(imageId: string, file: File) {
    try {
      return await uploadImage(imageId, file);
    } catch {
      showError(t("preview.error.uploadFailed"));
      return null;
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // isComposing guard: Enter must not send while a CJK IME candidate is open.
    if (stopping) return;
    if (e.key === "Escape" && editInsertAt != null) {
      e.preventDefault();
      cancelQueuedEdit();
      return;
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void onSubmit();
    }
  }

  const showLanding = messages.length === 0 && !sending && !stopping && streamingText === null;
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
      {!isSplit && (
        <div className="absolute left-4 top-3 z-10">
          <button
            type="button"
            onClick={() => setPagedPane("record")}
            className="pointer-events-auto flex h-9 w-9 items-center justify-center rounded-full border border-border bg-card/90 text-muted-foreground backdrop-blur transition hover:border-voice-border hover:bg-accent hover:text-accent-foreground"
            title={t("chat.history.open")}
            aria-label={t("chat.history.open")}
          >
            <svg width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden>
              <rect
                x="2"
                y="2.5"
                width="12"
                height="11"
                rx="1.5"
                stroke="currentColor"
                strokeWidth="1.2"
              />
              <path d="M6 2.5v11" stroke="currentColor" strokeWidth="1.2" />
            </svg>
          </button>
        </div>
      )}

      <div ref={scrollRef} className="mb-8 min-h-0 flex-1 overflow-y-auto">
        <div
          className={`flex min-h-full w-full flex-col gap-5 ${composerCol} ${
            isSplit ? "pt-6" : "pt-14"
          }`}
          style={{ paddingBottom: composerH }}
        >
          {restoring ? (
            <p className="py-16 text-center text-sm text-muted-foreground">
              {t("chat.history.restoring")}
            </p>
          ) : showLanding ? (
            <div className="flex flex-1 flex-col items-center justify-center py-16 text-center sm:py-24">
              <h1 className="text-2xl font-semibold tracking-tight">
                <span className="mr-1.5 text-voice" aria-hidden="true">
                  ✳
                </span>
                {t("chat.empty.title")}
              </h1>
              <p className="mt-2 max-w-md text-sm text-muted-foreground">
                {t("chat.empty.subtitle")}
              </p>
              <RecommendedQuestions
                questions={questions}
                loading={questionsLoading}
                isStale={isStale}
                disabled={stopping || (sending && queueFull)}
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
                    now={now}
                    retryContent={prevUser}
                    retryDisabled={stopping || (sending && queueFull)}
                    onRetry={prevUser ? () => void onRetryUserMessage(prevUser) : undefined}
                  />
                  {turnActions.length > 0 && <AgentActionList actions={turnActions} />}
                  {brief && briefAfterMessageId === m.id && <BriefCard brief={brief} />}
                  {awaitingImageOk && interruptAfterMessageId === m.id && (
                    <InterruptCard
                      sending={sending || stopping}
                      onResume={(format) => void onResumeImageGen(format)}
                    />
                  )}
                  {previewMode && previewAfterMessageId === m.id && !isSplit && (
                    <PreviewReadyBanner onOpen={() => setPagedPane("preview")} />
                  )}
                </div>
              );
            })
          )}
          {/* Fallback if anchor message was replaced / missing — keep cards visible. */}
          {agentActions.some(
            (a) => !a.afterMessageId || !messages.some((m) => m.id === a.afterMessageId),
          ) && (
            <AgentActionList
              actions={agentActions.filter(
                (a) => !a.afterMessageId || !messages.some((m) => m.id === a.afterMessageId),
              )}
            />
          )}
          {brief && briefAfterMessageId && !messages.some((m) => m.id === briefAfterMessageId) && (
            <BriefCard brief={brief} />
          )}
          {awaitingImageOk &&
            interruptAfterMessageId &&
            !messages.some((m) => m.id === interruptAfterMessageId) && (
              <InterruptCard
                sending={sending || stopping}
                onResume={(format) => void onResumeImageGen(format)}
              />
            )}
          {previewMode &&
            previewAfterMessageId &&
            !messages.some((m) => m.id === previewAfterMessageId) &&
            !isSplit && <PreviewReadyBanner onOpen={() => setPagedPane("preview")} />}
          {brief && !briefAfterMessageId && <BriefCard brief={brief} />}
          {awaitingImageOk && !interruptAfterMessageId && (
            <InterruptCard
              sending={sending || stopping}
              onResume={(format) => void onResumeImageGen(format)}
            />
          )}
          {previewMode && !previewAfterMessageId && !isSplit && (
            <PreviewReadyBanner onOpen={() => setPagedPane("preview")} />
          )}
          {/* Inline LLM error when failed before an assistant row was persisted. */}
          {llmError && !messages.some((m) => isLlmErrorContent(m.content)) && (
            <LlmErrorCard
              message={llmError}
              retryDisabled={stopping || (sending && queueFull)}
              onRetry={
                findLastUserContent(messages)
                  ? () => void onRetryUserMessage(findLastUserContent(messages)!)
                  : undefined
              }
            />
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

      <div ref={composerRef} className="pointer-events-none absolute inset-x-0 bottom-4 z-10">
        <form
          onSubmit={onSubmit}
          className={`pointer-events-auto flex flex-col gap-1.5 ${composerCol}`}
        >
          {(awaitingImageOk && queuedMessages.length > 0) || queueFull ? (
            <div className="space-y-0.5 px-1 text-[11px] leading-snug text-muted-foreground">
              {awaitingImageOk && queuedMessages.length > 0 ? (
                <p>{t("chat.queue.holdForImage")}</p>
              ) : null}
              {queueFull ? <p>{t("chat.queue.full")}</p> : null}
            </div>
          ) : null}
          <div className="relative">
            {queuedMessages.length > 0 ? (
              <div
                className="absolute inset-x-3 z-0 overflow-hidden rounded-2xl border border-voice-border bg-card"
                style={{
                  bottom: `calc(100% - ${QUEUE_TUCK_PX}px)`,
                  paddingBottom: QUEUE_TUCK_PX,
                }}
              >
                <ul className="flex flex-col p-1">
                  {queuedMessages.map((item) => (
                    <li
                      key={item.id}
                      className="group flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12px] leading-tight text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                    >
                      <CornerDownRight className="size-3 shrink-0 text-voice" aria-hidden />
                      <span className="min-w-0 flex-1 truncate">{item.content}</span>
                      <div className="flex shrink-0 items-center gap-0.5 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 has-[[data-state=open]]:opacity-100">
                        <IconButton
                          type="button"
                          className="h-6 w-6"
                          title={t("chat.queue.remove")}
                          aria-label={t("chat.queue.remove")}
                          onClick={() => dequeueQueuedMessage(item.id)}
                        >
                          <Trash2 className="size-3" />
                        </IconButton>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <IconButton
                              type="button"
                              className="h-6 w-6"
                              title={t("chat.queue.more")}
                              aria-label={t("chat.queue.more")}
                            >
                              <Ellipsis className="size-3" />
                            </IconButton>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-40">
                            <DropdownMenuItem onSelect={() => beginEditQueued(item.id)}>
                              <Pencil className="size-3.5" />
                              {t("chat.queue.edit")}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <div className="relative z-10 flex flex-col rounded-2xl border border-border bg-card px-3 py-2 shadow-sm transition-colors hover:border-voice-border focus-within:border-voice focus-within:hover:border-voice">
              <Textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                rows={2}
                placeholder={t("chat.input.placeholder")}
                disabled={stopping}
                className="block max-h-40 min-h-16 w-full resize-none overflow-y-auto border-0 bg-transparent px-2 py-1.5 shadow-none not-read-only:hover:border-0 not-read-only:focus-visible:border-0 not-read-only:focus-visible:ring-0 not-read-only:focus-visible:hover:border-0"
              />
              <div className="flex items-center justify-end gap-1 px-1">
                {(sending || stopping) && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    disabled={stopping}
                    onClick={() => void onStopTurn()}
                    className="h-8 w-8 rounded-full text-foreground"
                    title={stopping ? t("chat.stopping") : t("chat.stop")}
                    aria-label={stopping ? t("chat.stopping") : t("chat.stop")}
                  >
                    <Square className="size-3.5" fill="currentColor" stroke="none" />
                  </Button>
                )}
                <Button
                  type="submit"
                  variant="ghost"
                  size="icon"
                  disabled={
                    stopping || !input.trim() || (sending && queueFull && editInsertAt == null)
                  }
                  className="h-8 w-8 rounded-full text-foreground"
                  title={t("chat.send")}
                  aria-label={t("chat.send")}
                >
                  <SendIcon className="size-[18px]" />
                </Button>
              </div>
            </div>
          </div>
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
      companyId={companyId}
      canPromoteExemplar={canPromoteExemplar}
      onApply={onApplyDraft}
      onConfirm={onConfirmDraft}
      onSavePlan={onSavePlan}
      onRegenImage={onRegenImage}
      onAddImage={onAddImage}
      onRemoveImage={onRemoveImage}
      onUploadImage={onUploadImage}
      paged={!isSplit}
      onBack={goToChat}
    />
  ) : null;

  return (
    <div ref={shellRef} className="flex min-h-0 flex-1 overflow-hidden">
      {isSplit && <div className="flex h-full min-h-0">{historySidebar}</div>}

      {!isSplit && pagedPane === "record" && (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <SessionHistorySidebar
            collapsed={false}
            onToggle={() => undefined}
            pageMode
            onBack={goToChat}
            {...historyProps}
          />
        </div>
      )}

      <div
        className={`min-h-0 min-w-0 flex-col overflow-hidden ${
          isSplit || pagedPane === "chat" ? "flex" : "hidden"
        } ${isSplit && previewMode ? "flex-none basis-[38%]" : "flex-1"}`}
      >
        {chatColumn}
      </div>

      {previewMode && previewPane ? (
        <div
          className={`min-h-0 min-w-0 flex-1 flex-col overflow-hidden ${
            isSplit || pagedPane === "preview" ? "flex" : "hidden"
          }`}
        >
          {previewPane}
        </div>
      ) : null}
    </div>
  );
}

function PreviewReadyBanner({ onOpen }: { onOpen: () => void }) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onOpen}
      className="rounded-xl border border-border bg-card px-3 py-2 text-left text-xs text-muted-foreground transition hover:border-voice-border hover:bg-accent hover:text-accent-foreground"
    >
      {t("preview.readyBanner")}
    </button>
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
        const running = action.status === "running";
        return (
          <li
            key={action.id}
            className={cn(
              "flex items-start gap-2 text-xs leading-snug",
              running
                ? "-mx-1.5 rounded-md bg-voice-soft px-1.5 py-1 text-voice"
                : "text-muted-foreground",
            )}
          >
            <span
              className={cn(
                "mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center",
                running ? "text-voice" : "text-muted-foreground",
              )}
            >
              {running ? (
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-voice" />
              ) : (
                <Check className="size-3.5" aria-hidden />
              )}
            </span>
            <span className="min-w-0">
              <span>{label}</span>
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

function BriefCard({ brief }: { brief: SessionBrief }) {
  const { t } = useTranslation();
  const sections: { title: string; items: string[] }[] = [
    { title: t("chat.agent.brief.canDo"), items: brief.can_do },
    { title: t("chat.agent.brief.cannotDo"), items: brief.cannot_do },
    { title: t("chat.agent.brief.angles"), items: brief.angles },
  ].filter((s) => s.items.length > 0);

  return (
    <div className="rounded-xl border border-border bg-card p-4 text-sm shadow-sm">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("chat.agent.brief.title")}
        </span>
        {brief.persona && (
          <span className="rounded-md border border-border px-1.5 py-0.5 text-[11px] leading-none text-muted-foreground">
            {brief.persona}
          </span>
        )}
      </div>
      {brief.summary && <p className="mb-3 leading-relaxed">{brief.summary}</p>}
      <div className="flex flex-col gap-3">
        {sections.map((section) => (
          <div key={section.title}>
            <p className="mb-1 text-xs font-medium text-muted-foreground">{section.title}</p>
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

function InterruptCard({
  sending,
  onResume,
}: {
  sending: boolean;
  onResume: (format?: "single" | "comic_4panel") => void;
}) {
  const { t } = useTranslation();
  const [format, setFormat] = useState<"single" | "comic_4panel">("single");
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-primary/40 bg-card p-4 text-sm shadow-sm">
      <div>
        <p className="font-medium text-foreground">{t("chat.agent.interrupt.title")}</p>
        <p className="mt-0.5 text-muted-foreground">{t("chat.agent.interrupt.subtitle")}</p>
      </div>
      <div
        className="flex flex-wrap gap-2"
        role="group"
        aria-label={t("chat.agent.interrupt.formatLabel")}
      >
        <Button
          type="button"
          variant={format === "single" ? "default" : "outline"}
          disabled={sending}
          className={
            format === "single" ? "ring-2 ring-primary ring-offset-2 ring-offset-card" : undefined
          }
          onClick={() => setFormat("single")}
          aria-pressed={format === "single"}
        >
          {t("chat.agent.interrupt.formatSingle")}
        </Button>
        <Button
          type="button"
          variant={format === "comic_4panel" ? "default" : "outline"}
          disabled={sending}
          className={
            format === "comic_4panel"
              ? "ring-2 ring-primary ring-offset-2 ring-offset-card"
              : undefined
          }
          onClick={() => setFormat("comic_4panel")}
          aria-pressed={format === "comic_4panel"}
        >
          {t("chat.agent.interrupt.formatComic")}
        </Button>
      </div>
      <Button
        type="button"
        disabled={sending}
        className="shrink-0 self-start"
        onClick={() => onResume(format)}
      >
        {t("chat.agent.interrupt.confirm")}
      </Button>
    </div>
  );
}

function isLlmErrorContent(content: string): boolean {
  return content.startsWith("AI 服務暫時唔可用") || content.startsWith("AI service unavailable");
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
      className="flex flex-col gap-3 rounded-xl border border-destructive/40 bg-destructive-soft px-4 py-3 text-sm text-destructive-foreground shadow-sm sm:flex-row sm:items-start sm:justify-between"
      role="alert"
    >
      <p className="min-w-0 flex-1 whitespace-pre-wrap leading-relaxed">{message}</p>
      {onRetry && (
        <Button
          type="button"
          variant="ghost"
          disabled={retryDisabled}
          onClick={onRetry}
          className="shrink-0 border border-destructive/40 text-destructive-foreground hover:bg-destructive/10"
        >
          {t("chat.error.retry")}
        </Button>
      )}
    </div>
  );
}

function ChatMessageItem({
  message,
  now,
  onRetry,
  retryContent,
  retryDisabled,
}: {
  message: ChatMessage;
  now: Date;
  onRetry?: () => void;
  retryContent?: string | null;
  retryDisabled?: boolean;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="flex max-w-[85%] flex-col sm:max-w-[75%]">
          <div className="whitespace-pre-wrap rounded-2xl bg-primary px-4 py-2.5 text-sm text-primary-foreground">
            {message.content}
          </div>
          <MessageMeta
            align="user"
            content={message.content}
            createdAt={message.created_at}
            now={now}
          />
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
      <MessageMeta
        align="assistant"
        content={message.content}
        createdAt={message.created_at}
        now={now}
      />
    </div>
  );
}

function MessageMeta({
  align,
  content,
  createdAt,
  now,
}: {
  align: "user" | "assistant";
  content: string;
  createdAt: string;
  now: Date;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(id);
  }, [copied]);

  const relative = classifyRelativeTime(createdAt, now);
  const absolute = formatAbsoluteDateTime(createdAt);
  const timeLabel =
    relative.kind === "relative"
      ? t(`chat.message.time.${relative.unit}`, { n: relative.n })
      : relative.kind === "absolute"
        ? relative.text
        : null;

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  const copyButton = (
    <Tooltip>
      <TooltipTrigger asChild>
        <IconButton
          type="button"
          className="h-6 w-6"
          aria-label={copied ? t("chat.message.copied") : t("chat.message.copy")}
          onClick={() => void onCopy()}
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        </IconButton>
      </TooltipTrigger>
      <TooltipContent side="top">
        {copied ? t("chat.message.copied") : t("chat.message.copy")}
      </TooltipContent>
    </Tooltip>
  );

  const timeLabelNode =
    timeLabel && absolute ? (
      <Tooltip>
        <TooltipTrigger asChild>
          <time
            dateTime={createdAt}
            className="cursor-default text-[11px] tabular-nums text-muted-foreground"
          >
            {timeLabel}
          </time>
        </TooltipTrigger>
        <TooltipContent side="top">{absolute}</TooltipContent>
      </Tooltip>
    ) : null;

  return (
    <div
      className={cn(
        "mt-1 flex items-center gap-1 sm:gap-1.5",
        align === "user" ? "justify-end" : "justify-start",
      )}
    >
      {align === "user" ? (
        <>
          {timeLabelNode}
          {copyButton}
        </>
      ) : (
        <>
          {copyButton}
          {timeLabelNode}
        </>
      )}
    </div>
  );
}
