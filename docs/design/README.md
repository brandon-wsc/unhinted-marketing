# Design (in-repo)

> **Format:** docs + tokens inventory + Penpot Core file. **Runtime applied** — [`web/src/index.css`](../../web/src/index.css) carries the harness desk tokens.  
> **Primitives:** [`AGENTS.md`](../../AGENTS.md) (Web UI system)

| Doc / file | Job |
|------------|-----|
| [BRIEF.md](./BRIEF.md) | Positioning + shell vs craft voice |
| [TOKENS.md](./TOKENS.md) | Live harness desk tokens + `muted` / `accent` / `secondary` wash rules |
| [`design/penpot/`](../../design/penpot/) | **Penpot Core** layout reference — token/CSS truth is runtime (`index.css` + docs here); sync Penpot when chrome layout changes |

### Penpot page inventory (2026-08 redesign)

| Page | Contents |
|------|----------|
| Library | Token swatches (light + dark, renamed `token (mode)`), type scale (IBM Plex Sans / Noto Sans HK), component set: buttons (incl. **primary / loading** = spinner + label, 50% opacity), badges, inputs, question cards, agent action trail (voice accent), chat bubbles, tabs, icon buttons (akar send / stop), theme switch, **receipts** (`published` / `failed` / `stubbed`) + `ConfirmGate / image-required`. **Accent = voice hover wash**; secondary is the resting gray wash; muted is solid gray — see [TOKENS.md](./TOKENS.md). |
| Login · Register | Orderly centered auth card; exactly ONE corner craft signal (voice ✳ + “Boss yaps. Agent posts.” / 「腦細要Growth 我哋秒Post」) |
| Session — split | Desktop 1440: `empty` (landing + recommended questions) and `preview` (chat + action trail + interrupt card; preview pane with IG mock, revision/dirty badges, Confirm gate with serious copy); `generating` (same desk, interrupt **出圖** becomes spinner + 「出緊圖…」, format chips disabled); composer card stacks textarea then send/stop icon row (not overlaid on the textarea corner); queue tucks above the card. **Real publish (ADR 0022):** `published` (success receipt + 「喺 Instagram 睇」; edit row hidden; badge 已出) and `failed` (destructive receipt + 「再確認」; session stays unconfirmed) |
| Session — paged | Mobile 390: `record` (history), `chat` (same composer stack + queue tuck), `preview` (IG mock + Confirm gate), **`published` / `failed`** (same receipt states as split) |
| Dialogs | Edit copy … UserMenu — desktop dropdown / mobile dialog (theme = light/dark switch, no system mode). Order: identity → 語言 → 外觀 → **公司設定** → **系統** (platform only; not 管理後台) → **登出** (destructive). **Remove member** confirm · **Disconnect Instagram** confirm |
| Company settings | Desktop 1440: shell from UserMenu — shipped sidebar **Voice / Products / Members / Approvals / Models / Instagram**. Frames: Voice; Products Org / Mine; Members; Approvals queue (diff + approve/decline). **Instagram (ADR 0022, drawn):** `empty` (Connect Instagram → Instagram Login popup) · `connecting` (voice-soft cluster + Cancel inside; Connect/Reconnect hidden) · `connected` (last4, expires, Reconnect / Disconnect) · `expired` (destructive badge + Reconnect). Editor-only. Spec: [knowledge/UI.md](../knowledge/UI.md). |
| Invite accept | Desktop 1440 AuthLayout card: A logged out · B ready · C email mismatch (destructive Alert: explain signed-in email ≠ invite, no invited address, **Sign out** stays on `/invite/:token`) · D invalid · **E already in org (409)**. Title + body **inside** the card; actions **bottom-right** (outline left · primary right). Footer **left-aligned** outside. Public preview: invited email + company name ([ADR 0014](../adr/0014-invite-public-preview.md)). Spec: [knowledge/UI.md](../knowledge/UI.md). |

Admin console intentionally not designed in Penpot — temporary ops surface. Tenant KB CRUD is **Company settings**, not `/admin`.

**Voice / copy craft:** [VOICE.md](../VOICE.md) — captions, not chrome.

## Change rule

1. Lock intent here (and in Penpot when chrome layout changes).
2. Then patch `web/src/index.css` / fonts / logo to match.
3. Prefer semantic utilities — no parallel palette in JSX.
