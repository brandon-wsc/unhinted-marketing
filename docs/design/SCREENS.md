# Screen inventory (as-shipped)

Reverse-engineer target for docs+tokens: map **what exists** before restyle. Routes from `web/src/pages/` + session features.

| Screen | Route | Composition (today) | Notes |
|--------|-------|---------------------|-------|
| Login | `/login` | `AppShell` → `AuthLayout` card | Centered form; Inter + indigo primary |
| Register | `/register` | same | Org + account fields |
| Chat workspace | `/` | Header + history + chat (+ preview) | `split` \| `paged` via container width (`session-layout.ts`) |
| Admin | `/admin` | Header + tabs | Platform level ≥ 6; restyle **after** session/auth |

## Session chrome (primary product surface)

| Region | Code | Job |
|--------|------|-----|
| App header | `components/app-header.tsx` | Logo + name; user menu (lang / theme / logout) |
| History | `features/session/components/session-history.tsx` | Session list; collapsed in split |
| Chat | `features/session/components/chat-panel.tsx` | Messages, Streamdown, composer, agent trail |
| Recommended questions | `…/recommended-questions.tsx` | Empty-state interactive cards |
| Brief / interrupt | inside chat panel | Agent brief + Generate-image CTA |
| Preview | `…/preview-panel.tsx` + `ig-preview-mock.tsx` | Canonical draft + Confirm |
| Edit copy / image | dialogs under `features/session/components/` | Manual revise without LLM publish path |

## Brand assets

| Asset | Path |
|-------|------|
| Mark | `web/public/logo.svg` |
| App title | i18n `app.name` / `app.title` → Unhinted / Unhinted Marketing |

When BRIEF direction locks, restyle order: **tokens + logo + type** → auth → session chrome → admin.
