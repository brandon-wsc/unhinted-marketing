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
| Library | Token swatches (light + dark, renamed `token (mode)`), type scale (IBM Plex Sans / Noto Sans HK), component set: buttons (incl. **primary / loading** = spinner + label, 50% opacity), badges, inputs (incl. **field error** = destructive border + soft ring + inline `destructive-foreground` line under the control; required labels carry a red `*`, optional fields say 選填 — no native browser bubbles; **error copy says what to enter** — 要填X / "Enter a X" per field, never a generic "this field is required"), question cards, agent action trail (voice accent), chat bubbles, tabs, icon buttons (akar send / stop), theme switch, **receipts** (`published` / `failed` / `stubbed`) + `ConfirmGate / image-required`, **AnglePickCard** (ADR 0030 bundled recommend: persona + format chips + angles; voice-border) and **InterruptCard** (ADR 0036: Discard | Execute, format locked). **Accent = voice hover wash**; secondary is the resting gray wash; muted is solid gray — see [TOKENS.md](./TOKENS.md). |
| Login · Register | Orderly centered auth card; exactly ONE corner craft signal (voice ✳ + “Boss yaps. Agent posts.” / 「腦細要Growth 我哋秒Post」). Required labels marked `*`; org name stays 選填. |
| Setup | On-prem first-run wizard (ADR 0026): `0 welcome` · `1 account` (org name is **選填** — backend falls back to “{display name}'s Company”) · `2 instance` · `3 instance smtp` · `4 llm` · `5 done`, plus **`1 account · validation`** — the inline field-error state (destructive border + ring + message under the field, focus moves to first invalid; top `Alert` is API errors only). |
| Session — split | Desktop 1440: `empty` (landing + recommended questions), **`recommend`** (ADR 0030 `angle_gate` park — bundled AnglePickCard; preview pane empty until draft), `preview` (chat + action trail + interrupt card Discard | 出圖, format locked; preview pane with IG mock, revision/dirty badges, Confirm gate with serious copy); `generating` (same desk, interrupt **出圖** becomes spinner + 「出緊圖…」, Discard disabled); composer card stacks textarea then send/stop icon row (not overlaid on the textarea corner); queue tucks above the card. **Real publish (ADR 0022):** `published` (success receipt + 「喺 Instagram 睇」; edit row hidden; badge 已出) and `failed` (destructive receipt + 「再確認」; session stays unconfirmed) |
| Session — paged | Mobile 390: `record` (history), `chat` (same composer stack + queue tuck), **`recommend`** (AnglePickCard in the thread), `preview` (IG mock + Confirm gate), **`published` / `failed`** (same receipt states as split) |
| Dialogs | Edit copy … UserMenu — desktop dropdown / mobile dialog (theme = light/dark switch, no system mode). Order: identity → 語言 → 外觀 → **公司設定** → **系統** (platform only; not 管理後台) → **登出** (destructive). **Remove member** confirm · **Disconnect Instagram** confirm · **Switch to S3** (ink primary) · **Clean local files** (destructive outline) |
| Company settings | Desktop 1440: shell from UserMenu — shipped sidebar **Voice / Products / Members / Approvals / Models / Instagram / Storage**. Frames: Voice; Products Org / Mine; Members; Approvals queue (diff + approve/decline). **Instagram (ADR 0022):** `empty` · `connecting` · `connected` · `expired` · **`needs app`** (BYO Meta app guided card: 3 steps, read-only callback URL + Copy, Standard Access info note, admin CTA) · **`needs app · viewer`** (same card, muted admin note instead of CTA) · **`ready`** (Connect + mode caption — relay disclosure lands here later) · **`manual token`** (Connect + expanded advanced paste-token disclosure). **Storage (ADR 0025):** `local` · `copying` · `ready` · `s3 grace` · `s3`. Editor-only. Spec: [knowledge/UI.md](../knowledge/UI.md). |
| Invite accept | Desktop 1440 AuthLayout card: A logged out · B ready · C email mismatch (destructive Alert: explain signed-in email ≠ invite, no invited address, **Sign out** stays on `/invite/:token`) · D invalid · **E already in org (409)**. Title + body **inside** the card; actions **bottom-right** (outline left · primary right). Footer **left-aligned** outside. Public preview: invited email + company name ([ADR 0014](../adr/0014-invite-public-preview.md)). Spec: [knowledge/UI.md](../knowledge/UI.md). |

Admin console intentionally not designed in Penpot — temporary ops surface. Tenant KB CRUD is **Company settings**, not `/admin`.

**Voice / copy craft:** [VOICE.md](../VOICE.md) — captions, not chrome.

## Change rule

1. Lock intent here (and in Penpot when chrome layout changes).
2. Then patch `web/src/index.css` / fonts / logo to match.
3. Prefer semantic utilities — no parallel palette in JSX.
