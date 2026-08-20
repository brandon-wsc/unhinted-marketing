# Knowledge collect UI

> **Status:** Locked for K1–K6 shell · **Penpot drawn** · Voice **shipped** (incl. exemplars) · Products **shipped** (K3/K3b import + list + archive + propose) · Approvals **shipped**  
> **Parent:** [README.md](./README.md) · **Data rules:** [COLLECT.md](./COLLECT.md) · **Shell vs craft:** [design/BRIEF.md](../design/BRIEF.md)

Shell settings collect human-provided knowledge. Session craft does **not** silently write org catalog. **System** (`/system`) is platform ops (LLM / Trace) — not tenant KB CRUD; `/admin` redirects there.

---

## Locked decisions (2026-08-10)

1. **Entry:** UserMenu → **公司設定** (`/settings`; no separate dashboard nav). English locale: Company settings.
2. **Products:** one Products page with two tabs — **Org** | **Mine**.
3. **Docs first**, then Penpot Company settings pages, then code. **Penpot:** page `Company settings` in *Unhinted — Harness Desk (Core)* (2026-08-10).

**Locked decisions (2026-08-13) — Team + invite UI (slice 4; ships with session isolation audit slice 5 on same branch):**

1. **One settings shell** — `/settings?tab=members` shares the Voice / Products page; **no** separate admin route for tenant team management (contrast: **System** = platform ops only).
2. **Security** — UI hides management controls for plain members; **API is SSOT** (`require_company_settings_editor` → 403). No route-level split for MVP; optional `canManageTeam` helper mirrors Voice `can_edit`. Shared values stay visible as **read-only** (not disabled-tease). Voice: one muted line to ask an admin for changes. Products: no tab descriptions. Members: no extra banner — hide Invite / role actions. Approvals tab stays hidden.
3. **Invite link** — `{WEB_BASE_URL}/invite/{token}`; create response always includes `invite_url` for copy (WhatsApp / email optional via SMTP).
4. **Invite accept** — dedicated SPA `/invite/:token`; not anonymous; user must **register or log in with the invited email**, then accept. Copy must **not** imply one-click join without an account. Public `GET /api/invites/{token}` returns `{ email, company_name }` so login/register can **lock** that email ([ADR 0014](../adr/0014-invite-public-preview.md)).
5. **Register + invite (MVP)** — Register still auto-creates a solo company today; **accept** replaces a **sole-owner single-member** org ([ADR 0013](../adr/0013-invite-accept-replaces-bootstrap-org.md)). Products **rehome to Mine** on the invited org; **voice is not copied**; sessions/drafts stay. Warn on the join card. Any other existing membership → 409. [ADR 0015](../adr/0015-invite-rehome-solo-products.md).
6. **Sessions** — teammates do **not** browse each other's chats (slice 5: audit `sessions` routes stay `user_id`-scoped; add API tests). Products + voice remain the only shared assets.

---

## Penpot frames (drawn)

| Frame | Contents |
|-------|----------|
| `Company settings · Voice` | Sidebar Voice active · roast 0–3 · locale · forbidden · tone · **exemplar slots** · Save |
| `Company settings · Products · Org` | Org tab · Import CSV/Excel · import stats · table + Archive |
| `Company settings · Products · Mine` | Mine tab · Import + Add row · **Drafts use** (Company / Yours) · cover rule note |
| `Company settings · Members` | ✅ Drawn — editor (idle invite form) + **invite-sent** card + member read-only; sidebar Voice / Products / Members / Approvals |
| `Invite accept` | ✅ Drawn — A logged out · B ready · C email mismatch · D invalid · **E already in org (409)** |
| `Company settings · Approvals` | Pending proposals · field diff · Approve / Decline — owner/admin |

Entry: UserMenu → **公司設定** (desktop dropdown + mobile dialog; above **系統** when platform level ≥ 6). Penpot frames are desktop 1440 only; mobile uses same `/settings` routes (layout follows shell). UserMenu copy is zh-HK; only **登出** is destructive red.

---

## Information architecture

```text
UserMenu
  ├─ 語言 / 外觀               ← chrome only (not routes)
  ├─ 公司設定                  ← SPA `/settings`  (en: Company settings)
  │     ├─ Voice               ← K1 + K5 exemplars
  │     ├─ Products            ← K3 / K3b  (tabs: Org | Mine)
  │     ├─ Members             ← org team (slice 4)
  │     └─ Approvals           ← K6 — owner/admin queue
  ├─ 系統                      ← SPA `/system` (platform ops; API `/api/admin/*`; en: System)
  └─ 登出                      ← destructive

/invite/:token                 ← invite accept page (public); POST accept requires auth
```

| Surface | Job | Shell / craft |
|---------|-----|----------------|
| Company settings | Persist voice + catalogs + team + approve | **Shell** — serious, scannable |
| Session chat | Turn-local product facts only | **Craft** — User × New scratch; no org upsert |
| Confirm / draft action | Manual exemplar pick (K5) | **Shell** gate-adjacent — short accurate copy |
| **System** | Platform ops (LLM trace, research) | Out of scope for COLLECT UI (`/admin` → redirect) |
| **Invite accept** | Join org after auth | **Shell** — short, guided; links to login/register |

---

## UI → data map

| UI | Collects / shows | Scope | Who | Phase |
|----|------------------|-------|-----|-------|
| **Voice** | `roast_level` (0–3), `forbidden_phrases[]` (≤15), `tone_notes`, `locale` (default `zh-HK`), `exemplar_captions` (≤3 × ≤150) | Org × Old → `entities.profile` | owner/admin edit; member read | **K1 + K5** ✅ |
| **Products → Org** | CSV/xlsx import → `sku` / `name` / …; list + archive | Org × Old | owner/admin | **K3** ✅ |
| **Products → Mine** | Personal import / save | User × Old | any member | **K3b** ✅ |
| **Members → Company** | Company `name` (rename) | Org | owner/admin | **org UI slice 4** |
| **Members → Roster** | `GET …/members` — display name, email, role, joined | Org | any member read | **slice 4** |
| **Members → Manage** | role change (`admin` ↔ `member`), remove, self-leave | Org | owner/admin (not self-leave for owner) | **slice 4** |
| **Members → Invite** | `POST …/invites` · copy `invite_url` · list/revoke pending | Org | owner/admin | **slice 4** |
| **Invite accept** | `GET /api/invites/{token}` preview · `POST /api/invites/{token}/accept` | Join org | preview public; accept authed, email must match | **slice 4** |
| Session chat | Spoken SKU/price (no form) | User × New | current user | shipped; **private** per user |
| Confirm / draft promote | Save caption → prepend `exemplar_captions` | Org (manual) | owner/admin | **K5** ✅ |
| **Approvals** | Proposal diff → approve / reject | Org × New → Old | owner/admin | **K6** ✅ |

**Not collected in UI (MVP):** per-company persona CRUD, offer-snippet dedicated page, brand PDF upload, pain points, market signals, platform craft ([VOICE.md](../VOICE.md)).

---

## Screen contracts (minimal)

### Voice (K1 + K5)

- Controls only — no cards for decoration; one purpose: brand knobs + optional exemplars.
- Persist on company `entities.profile`; compress to `voice_pack` in `load_context` ([MODEL.md](./MODEL.md#brand-voice-voice_pack)).
- Member (non-admin): **read-only** (`can_edit=false`); hide Save; fields `readOnly` not greyed-out disabled. One muted line under the subtitle — no info Alert. Owner/admin edit + Confirm promote.
- Exemplars: ≤3 × ≤150 chars in Voice form; or Confirm → **Save caption as voice example**.

### Products (K3 / K3b)

| Tab | Content |
|-----|---------|
| **Org** | Upload CSV/xlsx · result summary (`imported` / `updated` / `skipped` / `errors[]`) · table (name + `sku`, status, trailing **Archive** icon + tooltip) · **row click → same form as Add row** (name / product code / notes; extra import columns read-only). Editors can save (`PATCH`). Members: hide import / archive; row opens read-only detail. No tab descriptions. Cover rule stays on Mine. Count badge sits above the table (left), not as a right-aligned toolbar orphan. Upsert **replace by SKU** on import — no merge-conflict UI ([COLLECT §2](./COLLECT.md#2-ownership-org--user-new--old)). |
| **Mine** | Same form for personal library (Add row + row click to edit). Org covers user on SKU clash at retrieve — **Drafts use** column: Company vs Yours. **Add to company** / **Cancel request** (icon + tooltip) → Approvals queue ([ADR 0011](../adr/0011-knowledge-commit-without-llm.md)). |

Flexible headers: no required column names; store raw row in `profile`. **Import hard limit: 50 columns** — reject whole file ([COLLECT §4](./COLLECT.md#4-product-import-k3)). No content column in the table (unknown CSV shapes).

### Approvals (K6)

- List pending Mine→org proposals; show field diff vs current org row; **Approve** / **Decline** HTTP, zero LLM ([ADR 0011](../adr/0011-knowledge-commit-without-llm.md)).
- **UI:** `/settings?tab=approvals` in sidebar for owner/admin only. Members propose from Products → Mine; they can **cancel** a pending request from Mine.
- Chat still must not write org catalog.

### Members (org team — slice 4)

**Route:** `/settings?tab=members` · sidebar label **Members** (i18n `settings.nav.members`; zh-HK **成員** — same English-nav pattern as Voice / Products).

**Layout (top → bottom):**

1. **Company name** — single field + Save; owner/admin edit; members see the name as text (no Save). `PATCH /api/companies/{id}` `{ name }`.
2. **Member roster** — table: display name, email, role badge, joined date. `GET …/members`. All members can view. Members do **not** get a permission banner.
3. **Manage row** (owner/admin only) — role `Select` in the Role column (`admin` | `member` only). Trailing **icon + tooltip** (same 32px `IconButton` as Products archive): **Remove member** with confirm. Owner row never demotable/removable from UI (API 409). Members cannot manage others.
4. **Invite** (owner/admin only) — email + role (`admin` | `member`) + **Send invite**. Idle: form only. On success: show **copy link** (`invite_url`) + short hint (WhatsApp / paste to colleague) — do not show the URL before send. Reject emails already on the roster (409). No in-app email required (`EMAIL_BACKEND=link`).
5. **Pending invites** (owner/admin only) — table: email, role, expires; trailing **icon + tooltip** **Revoke invite** → `DELETE …/invites/{id}`.

**Permissions helper:** `canManageTeam = role ∈ { owner, admin }` from `user.organizations[0]` (future: API `can_manage` on members list).

**Empty states:** sole owner alone → still show roster; pending invites empty → hide section or “No pending invites”.

### Invite accept (slice 4)

**Route:** `/invite/:token` · **not** under `/settings`. The page is public (logged-out CTA is a real state). **Accept** (`POST`) requires a session; login/register return via `?next=`.

Title + body sit **inside** the AuthLayout card (Penpot AuthCard), left-aligned. Actions **bottom-right**: outline/return **left**, primary/accept **right**. Not full-width stacked. Footer (login/register switcher · invite once-note) stays **outside** the card, **left-aligned**.

| Auth state | UI |
|------------|-----|
| Logged out | Show invited **email** + **company name** from `GET /api/invites/{token}`; footer → **Create account** (outline) · **Log in** (primary) with `?next=/invite/:token`. Login/register **lock** that email (`readOnly`); register **hides** company-name (bootstrap org still created, replaced on accept). |
| Logged in, accept OK | Warning (info Alert) only if the user is **sole owner** of their current org (bootstrap replace — ADR 0013): products → Mine in the invited company; voice not copied; chats/drafts stay. Members/admins of a real team do **not** see replace copy (join → 409). Footer: **Back to home** (outline, left) · **Join company** (primary, right) → `POST /api/invites/{token}/accept` → toast + redirect `/`. |
| 403 email mismatch | Detected from preview vs signed-in email (before Join) as well as POST 403. Title **Email mismatch**. Destructive Alert **explains**, does not command, and **does not interpolate** the invited address: “You're signed in with a different email than this invite.” Actions: **Back to home** (outline) · **Sign out** (primary, `auth.logout`). After logout, stay on `/invite/:token` (logged-out invite card — not `/login`). |
| 409 already in org | “You already belong to a company” + **Back to home** (right-aligned outline; bootstrap replace handled server-side for sole-owner solo org — see locked decision above). |
| 400 expired / revoked / used | Static error + contact your admin; **Back to home** right-aligned. |

**Login / register:** honor `?next=` after success (preserve path + query). When `next` is `/invite/:token`, wait for preview before submit (email `readOnly`, submit disabled while loading). On success, email is pre-filled and locked; register hides company-name.

---

## Design system notes

- Reuse existing shell primitives ([`web/src/components/ui/`](../../web/src/components/ui/)) — tabs, table, input, textarea, button, dialog, **Select**.
- **Select** — `SelectContent` is **`popper`** (list below trigger, not `item-aligned` overlay). Border is `border-border` (+ `dark:border-white/10`), same as dropdown menus.
- Table row hover/selected → `bg-accent` (voice-soft, not `muted`) — [TOKENS.md](../design/TOKENS.md) `muted` vs `accent` vs `secondary`.
- Voice is the interaction pulse: hover / focus / queued / selected use `text-voice` / `bg-accent` (`voice-soft`) / `border-voice-border` / `ring` (voice). Craft copy still uses the same family (action trail, recommended questions, login corner, filled exemplars, save-as-example). Settings **resting** chrome stays neutral. Save stays ink. **Tone strength** is a form **choice** (neutral `secondary` wash + ink selected border, `radiogroup`) — not a tab track, not voice. **Products Org | Mine** is a **line tab** (ink underline; hover `secondary`). `info` is status alerts only — not field focus.
- Penpot: **Company settings** drawn under [design/penpot](../../design/penpot/); CSS follows tokens in `web/src/index.css`.
- **UI copy:** user-facing only (what the person sees/does). Avoid internal jargon in subtitles (no “K6”, “owner/admin”, “upsert”, “Zero LLM”).

---

## Phase checklist (UI)

| Phase | UI deliverable |
|-------|----------------|
| **K1** | Company settings → Voice form | ✅ |
| **K3** | Products → Org tab (import + table) | ✅ |
| **K3b** | Products → Mine tab | ✅ |
| **K5** | Exemplar promote from Confirm / draft + Voice settings slots | ✅ |
| **Org team** | Members tab + invite accept page + login `next` | ✅ |
| **Session isolation** | Cross-member session API tests; routes stay `user_id`-scoped | ✅ CI `backend-api` |
| **K6** | Approvals tab + Mine propose + HTTP approve/reject | ✅ |

---

## References

- [COLLECT.md](./COLLECT.md) — ownership, cover rules, import API
- [MODEL.md](./MODEL.md) — `voice_pack` fields
- [design/BRIEF.md](../design/BRIEF.md) — shell vs craft
- [design/README.md](../design/README.md) — Penpot inventory
