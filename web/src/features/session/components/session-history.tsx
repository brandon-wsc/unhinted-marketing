import { ChevronLeft } from "lucide-react";
import {
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { IconButton } from "@/components/icon-button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { SessionListItem } from "@/features/session/types";

type Props = {
  collapsed: boolean;
  onToggle: () => void;
  sessions: SessionListItem[];
  loading: boolean;
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onNewChat: () => void;
  onRename: (sessionId: string, title: string) => Promise<unknown>;
  onPin: (sessionId: string, pinned: boolean) => Promise<unknown>;
  onDelete: (sessionId: string) => Promise<unknown>;
  /** Full-bleed page (mobile) — stretch width; pair with onBack. */
  pageMode?: boolean;
  onBack?: () => void;
};

type HistoryGroup = {
  key: string;
  label: string;
  items: SessionListItem[];
};

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

function groupUnpinned(
  sessions: SessionListItem[],
  labels: { today: string; yesterday: string; week: string; older: string },
): HistoryGroup[] {
  const now = new Date();
  const today = startOfDay(now);
  const yesterday = today - 86_400_000;
  const weekAgo = today - 7 * 86_400_000;

  const buckets: Record<string, SessionListItem[]> = {
    today: [],
    yesterday: [],
    week: [],
    older: [],
  };

  for (const s of sessions) {
    const t = startOfDay(new Date(s.updated_at));
    if (t >= today) buckets.today.push(s);
    else if (t >= yesterday) buckets.yesterday.push(s);
    else if (t >= weekAgo) buckets.week.push(s);
    else buckets.older.push(s);
  }

  return (
    [
      { key: "today", label: labels.today, items: buckets.today },
      { key: "yesterday", label: labels.yesterday, items: buckets.yesterday },
      { key: "week", label: labels.week, items: buckets.week },
      { key: "older", label: labels.older, items: buckets.older },
    ] as const
  ).filter((g) => g.items.length > 0);
}

export function SessionHistorySidebar({
  collapsed,
  onToggle,
  sessions,
  loading,
  activeSessionId,
  onSelect,
  onNewChat,
  onRename,
  onPin,
  onDelete,
  pageMode = false,
  onBack,
}: Props) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((s) => {
      const title = (s.title || "").toLowerCase();
      return title.includes(q) || s.id.toLowerCase().includes(q);
    });
  }, [sessions, query]);

  const pinned = useMemo(() => filtered.filter((s) => !!s.pinned), [filtered]);
  const unpinned = useMemo(() => filtered.filter((s) => !s.pinned), [filtered]);

  const groups = useMemo(
    () =>
      groupUnpinned(unpinned, {
        today: t("chat.history.group.today"),
        yesterday: t("chat.history.group.yesterday"),
        week: t("chat.history.group.week"),
        older: t("chat.history.group.older"),
      }),
    [unpinned, t],
  );

  async function handleRename(id: string, title: string) {
    setBusyId(id);
    try {
      await onRename(id, title);
      setRenamingId(null);
    } finally {
      setBusyId(null);
    }
  }

  async function handlePin(id: string, pinnedNext: boolean) {
    setBusyId(id);
    try {
      await onPin(id, pinnedNext);
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(id: string) {
    setBusyId(id);
    try {
      await onDelete(id);
      setConfirmDeleteId(null);
    } finally {
      setBusyId(null);
    }
  }

  function renderRow(s: SessionListItem) {
    const active = s.id === activeSessionId;
    const title = s.title?.trim() || t("chat.history.untitled");
    const renaming = renamingId === s.id;
    const busy = busyId === s.id;

    return (
      <li key={s.id} className="group relative">
        {renaming ? (
          <RenameField
            initial={s.title?.trim() || ""}
            disabled={busy}
            onCancel={() => setRenamingId(null)}
            onSubmit={(next) => void handleRename(s.id, next)}
          />
        ) : (
          <div
            className={`flex items-center gap-0.5 rounded-full transition ${
              active ? "bg-accent" : "hover:bg-accent"
            }`}
          >
            <button
              type="button"
              onClick={() => onSelect(s.id)}
              className="min-w-0 flex-1 truncate px-3 py-2 text-left text-[13px] leading-snug text-foreground"
              title={title}
            >
              {s.pinned ? (
                <span className="mr-1.5 inline-flex text-muted-foreground" aria-hidden>
                  <PinIcon filled />
                </span>
              ) : null}
              {title}
            </button>
            <div className="relative shrink-0 pr-1">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <IconButton
                    type="button"
                    className="h-7 w-7 rounded-full opacity-0 group-hover:opacity-100 focus:opacity-100 data-[state=open]:opacity-100"
                    aria-label={t("chat.history.more")}
                  >
                    <MoreIcon />
                  </IconButton>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-40">
                  <DropdownMenuItem onSelect={() => void handlePin(s.id, !s.pinned)}>
                    <PinIcon filled={!!s.pinned} />
                    {s.pinned ? t("chat.history.unpin") : t("chat.history.pin")}
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setRenamingId(s.id)}>
                    <RenameIcon />
                    {t("chat.history.rename")}
                  </DropdownMenuItem>
                  <DropdownMenuItem variant="destructive" onSelect={() => setConfirmDeleteId(s.id)}>
                    <TrashIcon />
                    {t("chat.history.delete")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        )}
      </li>
    );
  }

  if (collapsed) {
    return (
      <aside className="flex h-full min-h-0 w-12 shrink-0 flex-col items-center gap-2 overflow-hidden border-r border-border bg-background py-3">
        <IconButton
          type="button"
          onClick={onToggle}
          className="h-8 w-8 rounded-full"
          title={t("chat.history.open")}
          aria-label={t("chat.history.open")}
        >
          <SidebarIcon />
        </IconButton>
        <IconButton
          type="button"
          onClick={onNewChat}
          className="h-8 w-8 rounded-full"
          title={t("chat.history.new")}
          aria-label={t("chat.history.new")}
        >
          <PlusIcon />
        </IconButton>
      </aside>
    );
  }

  return (
    <aside
      className={`flex h-full min-h-0 shrink-0 flex-col overflow-hidden bg-background ${
        pageMode ? "w-full" : "w-[280px] border-r border-border"
      }`}
    >
      <div className="flex shrink-0 items-center gap-1 px-3 pb-1 pt-3">
        {pageMode && onBack ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <IconButton
                type="button"
                className="size-9 rounded-full"
                onClick={onBack}
                aria-label={t("chat.mobile.back")}
              >
                <ChevronLeft />
              </IconButton>
            </TooltipTrigger>
            <TooltipContent side="bottom">{t("chat.mobile.back")}</TooltipContent>
          </Tooltip>
        ) : !pageMode ? (
          <IconButton
            type="button"
            onClick={onToggle}
            className="h-9 w-9 rounded-full"
            title={t("chat.history.collapse")}
            aria-label={t("chat.history.collapse")}
          >
            <SidebarIcon />
          </IconButton>
        ) : null}
        <button
          type="button"
          onClick={onNewChat}
          className="flex h-9 flex-1 items-center justify-center gap-1.5 rounded-full bg-card px-3 text-sm font-medium text-foreground shadow-sm ring-1 ring-border transition hover:bg-accent"
        >
          <PlusIcon />
          {t("chat.history.new")}
        </button>
      </div>

      <div className="shrink-0 px-3 pb-2 pt-2">
        <div className="relative">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">
            <SearchIcon />
          </span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("chat.history.search")}
            className="w-full rounded-full border-0 bg-card py-2 pl-9 pr-3 text-sm outline-none ring-1 ring-border transition placeholder:text-muted-foreground focus:ring-ring"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {loading && sessions.length === 0 ? (
          <p className="px-3 py-8 text-center text-xs text-muted-foreground">
            {t("chat.history.loading")}
          </p>
        ) : pinned.length === 0 && groups.length === 0 ? (
          <p className="px-3 py-8 text-center text-xs text-muted-foreground">
            {t("chat.history.empty")}
          </p>
        ) : (
          <>
            {pinned.length > 0 && (
              <div className="mb-2">
                <p className="px-3 pb-1 pt-2 text-[11px] font-medium text-muted-foreground">
                  {t("chat.history.group.pinned")}
                </p>
                <ul className="flex flex-col gap-0.5">{pinned.map(renderRow)}</ul>
              </div>
            )}
            {groups.map((group) => (
              <div key={group.key} className="mb-2">
                <p className="px-3 pb-1 pt-2 text-[11px] font-medium text-muted-foreground">
                  {group.label}
                </p>
                <ul className="flex flex-col gap-0.5">{group.items.map(renderRow)}</ul>
              </div>
            ))}
          </>
        )}
      </div>

      <AlertDialog
        open={confirmDeleteId !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmDeleteId(null);
        }}
      >
        <AlertDialogContent size="sm">
          <AlertDialogHeader>
            <AlertDialogTitle>{t("chat.history.deleteTitle")}</AlertDialogTitle>
            <AlertDialogDescription>{t("chat.history.deleteBody")}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busyId === confirmDeleteId}>
              {t("chat.history.cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={busyId === confirmDeleteId || !confirmDeleteId}
              onClick={(e) => {
                e.preventDefault();
                if (confirmDeleteId) void handleDelete(confirmDeleteId);
              }}
            >
              {busyId === confirmDeleteId ? t("chat.history.deleting") : t("chat.history.delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </aside>
  );
}

function RenameField({
  initial,
  disabled,
  onCancel,
  onSubmit,
}: {
  initial: string;
  disabled?: boolean;
  onCancel: () => void;
  onSubmit: (title: string) => void;
}) {
  const { t } = useTranslation();
  const [value, setValue] = useState(initial);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    onSubmit(value);
  }

  function onKeyDown(e: ReactKeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      e.preventDefault();
      onCancel();
    }
  }

  return (
    <form onSubmit={submit} className="px-1 py-0.5">
      <input
        ref={inputRef}
        value={value}
        disabled={disabled}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => submit()}
        maxLength={200}
        aria-label={t("chat.history.rename")}
        className="w-full rounded-full bg-card px-3 py-2 text-[13px] outline-none ring-2 ring-ring"
      />
    </form>
  );
}

/** Mobile: left sheet overlay. */
export function SessionHistoryMobileSheet({
  open,
  onClose,
  sessions,
  loading,
  activeSessionId,
  onSelect,
  onNewChat,
  onRename,
  onPin,
  onDelete,
}: {
  open: boolean;
  onClose: () => void;
  sessions: SessionListItem[];
  loading: boolean;
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onNewChat: () => void;
  onRename: (sessionId: string, title: string) => Promise<unknown>;
  onPin: (sessionId: string, pinned: boolean) => Promise<unknown>;
  onDelete: (sessionId: string) => Promise<unknown>;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex md:hidden">
      <button
        type="button"
        className="absolute inset-0 bg-black/40"
        aria-label="Close"
        onClick={onClose}
      />
      <div className="relative h-full w-[280px] max-w-[85vw] shadow-xl [&_aside]:border-r-0">
        <SessionHistorySidebar
          collapsed={false}
          onToggle={onClose}
          sessions={sessions}
          loading={loading}
          activeSessionId={activeSessionId}
          onSelect={(id) => {
            onSelect(id);
            onClose();
          }}
          onNewChat={() => {
            onNewChat();
            onClose();
          }}
          onRename={onRename}
          onPin={onPin}
          onDelete={onDelete}
        />
      </div>
    </div>
  );
}

function SidebarIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden>
      <rect x="2" y="2.5" width="12" height="11" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
      <path d="M6 2.5v11" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.2" />
      <path
        d="M10.5 10.5 13.5 13.5"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
    </svg>
  );
}

function MoreIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <circle cx="8" cy="3.5" r="1.2" />
      <circle cx="8" cy="8" r="1.2" />
      <circle cx="8" cy="12.5" r="1.2" />
    </svg>
  );
}

function PinIcon({ filled }: { filled?: boolean }) {
  if (filled) {
    return (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
        <path d="M9.8 2.2a1 1 0 0 0-1.4 0L6.2 4.4 4.5 3.9a.75.75 0 0 0-.8 1.2l2.1 2.1-.9 3.3a.75.75 0 0 0 1.1.85l2.9-1.5 2.1 2.1a.75.75 0 1 0 1.06-1.06l-.5-1.7 2.2-2.2a1 1 0 0 0 0-1.4L9.8 2.2Z" />
      </svg>
    );
  }
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M9.6 2.6 13.4 6.4M6.3 4.6 4.6 4.1a.6.6 0 0 0-.64.96l2 2-.85 3.15a.6.6 0 0 0 .88.68l2.75-1.42 2 2a.6.6 0 0 0 .85-.85l-.48-1.6 2.05-2.05"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function RenameIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M9.5 3.5 12.5 6.5M3 13l.7-2.8L10.2 3.7a1.2 1.2 0 0 1 1.7 0l.4.4a1.2 1.2 0 0 1 0 1.7L5.8 12.3 3 13Z"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M3.5 4.5h9M6.5 4.5V3.2a.7.7 0 0 1 .7-.7h1.6a.7.7 0 0 1 .7.7v1.3M5 4.5l.5 8.2a.8.8 0 0 0 .8.7h3.4a.8.8 0 0 0 .8-.7L11 4.5"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
