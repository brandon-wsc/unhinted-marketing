# Design (in-repo)

> **Format:** docs + tokens inventory + Penpot Core file. **Runtime applied** — [`web/src/index.css`](../../web/src/index.css) carries the harness desk tokens.  
> **Primitives:** [`.cursor/rules/web-ui-system.mdc`](../../.cursor/rules/web-ui-system.mdc)

| Doc / file | Job |
|------------|-----|
| [BRIEF.md](./BRIEF.md) | Positioning + shell vs craft voice |
| [TOKENS.md](./TOKENS.md) | As-shipped vs **proposed** harness desk tokens |
| [`design/penpot/`](../../design/penpot/) | **Penpot Core** visual SSOT for proposed shell — CSS apply still separate |

### Penpot page inventory (2026-08 redesign)

| Page | Contents |
|------|----------|
| Library | Token swatches (light + dark, renamed `token (mode)`), type scale (IBM Plex Sans / Noto Sans HK), component set: buttons, badges, inputs, question cards, agent action trail (voice accent), chat bubbles, tabs, icon buttons (akar send / stop), theme switch |
| Login · Register | Orderly centered auth card; exactly ONE corner craft signal (voice ✳ + “Reliable tools, unleashed copy”) |
| Session — split | Desktop 1440: `empty` (landing + recommended questions) and `preview` (chat + action trail + interrupt card; preview pane with IG mock, revision/dirty badges, Confirm gate with serious copy); composer send/stop are icon buttons |
| Session — paged | Mobile 390: `record` (history), `chat` (trail + preview-ready banner), `preview` (IG mock + Confirm gate) |
| Dialogs | Edit copy … UserMenu — desktop dropdown / mobile dialog (theme = light/dark switch, no system mode); **Company settings** menu item above Admin |
| Company settings | Desktop 1440: shell page from UserMenu — sidebar **Voice / Products / Approvals**; Products has **Org \| Mine** tabs. Frames: Voice form (roast / locale / forbidden / tone), Products Org (import + table), Products Mine (cover badge), Approvals empty (K6 held). Spec: [knowledge/UI.md](../knowledge/UI.md). |

Admin console intentionally not designed in Penpot — temporary ops surface. Tenant KB CRUD is **Company settings**, not `/admin`.

**Voice / copy craft:** [VOICE.md](../VOICE.md) — captions, not chrome.

## Change rule

1. Lock intent here (and in Penpot when chrome layout changes).
2. Then patch `web/src/index.css` / fonts / logo to match.
3. Prefer semantic utilities — no parallel palette in JSX.
