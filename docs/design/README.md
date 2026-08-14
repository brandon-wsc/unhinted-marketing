# Design (in-repo)

> **Format:** docs + tokens inventory + Penpot Core file. **Runtime applied** — [`web/src/index.css`](../../web/src/index.css) carries the harness desk tokens.  
> **Primitives:** [`.cursor/rules/web-ui-system.mdc`](../../.cursor/rules/web-ui-system.mdc)

| Doc / file | Job |
|------------|-----|
| [BRIEF.md](./BRIEF.md) | Positioning + shell vs craft voice |
| [TOKENS.md](./TOKENS.md) | Live harness desk tokens + `muted` vs `accent` wash rules |
| [`design/penpot/`](../../design/penpot/) | **Penpot Core** visual SSOT for proposed shell — CSS apply still separate |

### Penpot page inventory (2026-08 redesign)

| Page | Contents |
|------|----------|
| Library | Token swatches (light + dark, renamed `token (mode)`), type scale (IBM Plex Sans / Noto Sans HK), component set: buttons, badges, inputs, question cards, agent action trail (voice accent), chat bubbles, tabs, icon buttons (akar send / stop), theme switch. **Accent = hover wash**; muted is solid gray — see [TOKENS.md](./TOKENS.md). |
| Login · Register | Orderly centered auth card; exactly ONE corner craft signal (voice ✳ + “Reliable tools, unleashed copy”) |
| Session — split | Desktop 1440: `empty` (landing + recommended questions) and `preview` (chat + action trail + interrupt card; preview pane with IG mock, revision/dirty badges, Confirm gate with serious copy); composer send/stop are icon buttons |
| Session — paged | Mobile 390: `record` (history), `chat` (trail + preview-ready banner), `preview` (IG mock + Confirm gate) |
| Dialogs | Edit copy … UserMenu — desktop dropdown / mobile dialog (theme = light/dark switch, no system mode). Order: identity → 語言 → 外觀 → **公司設定** → **系統** (platform only; not 管理後台) → **登出** (destructive). **Remove member** confirm |
| Company settings | Desktop 1440: shell from UserMenu — shipped sidebar **Voice / Products / Members** (Approvals held, hidden until K6). Frames: Voice; Products Org / Mine; **Members** editor (idle invite form) + invite-sent card + member view; Approvals empty (K6). Spec: [knowledge/UI.md](../knowledge/UI.md). |
| Invite accept | Desktop 1440 AuthLayout card: A logged out · B ready · C email mismatch · D invalid · **E already in org (409)**. Footer **bottom-right**: return/outline left · accept/primary right. No public company-name preview. |

Admin console intentionally not designed in Penpot — temporary ops surface. Tenant KB CRUD is **Company settings**, not `/admin`.

**Voice / copy craft:** [VOICE.md](../VOICE.md) — captions, not chrome.

## Change rule

1. Lock intent here (and in Penpot when chrome layout changes).
2. Then patch `web/src/index.css` / fonts / logo to match.
3. Prefer semantic utilities — no parallel palette in JSX.
