# Knowledge collect UI

> **Status:** Locked for K1–K5 shell · **Penpot drawn** · Voice **shipped** · Products **shipped** (K3/K3b import + list + archive) · Approvals held  
> **Parent:** [README.md](./README.md) · **Data rules:** [COLLECT.md](./COLLECT.md) · **Shell vs craft:** [design/BRIEF.md](../design/BRIEF.md)

Shell settings collect human-provided knowledge. Session craft does **not** silently write org catalog. `/admin` stays ops-only (LLM / Trace) — not tenant KB CRUD.

---

## Locked decisions (2026-08-10)

1. **Entry:** UserMenu → **Company settings** (no separate dashboard nav).
2. **Products:** one Products page with two tabs — **Org** | **Mine**.
3. **Docs first**, then Penpot Company settings pages, then code. **Penpot:** page `Company settings` in *Unhinted — Harness Desk (Core)* (2026-08-10).

---

## Penpot frames (drawn)

| Frame | Contents |
|-------|----------|
| `Company settings · Voice` | Sidebar Voice active · roast 0–3 · locale · forbidden phrases · tone notes · Save |
| `Company settings · Products · Org` | Org tab · Import CSV/Excel · import stats · table + Archive |
| `Company settings · Products · Mine` | Mine tab · Import + Add row · `covered by company` badge · cover rule note |
| `Company settings · Approvals` | Empty state · K6 held badge |

Entry: UserMenu → **Company settings** (desktop + mobile, above Admin). Penpot frames are desktop 1440 only; **mobile 390 layout TBD** when settings pages are implemented.

---

## Information architecture

```text
UserMenu
  └─ Company settings          ← shell page (SPA route TBD, not /admin)
        ├─ Voice               ← K1
        ├─ Products            ← K3 / K3b  (tabs: Org | Mine)
        └─ Approvals           ← K6 held — **hidden from UI until promote ships**
```

| Surface | Job | Shell / craft |
|---------|-----|----------------|
| Company settings | Persist voice + catalogs + approve | **Shell** — serious, scannable |
| Session chat | Turn-local product facts only | **Craft** — User × New scratch; no org upsert |
| Confirm / draft action | Manual exemplar pick (K5) | **Shell** gate-adjacent — short accurate copy |
| `/admin` | Platform ops | Out of scope for COLLECT UI |

---

## UI → data map

| UI | Collects | Scope | Who | Phase |
|----|----------|-------|-----|-------|
| **Voice** | `roast_level` (0–3), `forbidden_phrases[]` (≤15), `tone_notes`, `locale` (default `zh-HK`) | Org × Old → `entities.profile` | owner/admin | **K1** |
| **Products → Org** | CSV/xlsx import → `sku` / `name` / `search_document` / `profile` JSONB; list + archive | Org × Old | owner/admin | **K3** |
| **Products → Mine** | Same row shape; personal import / save | User × Old | any member | **K3b** |
| Session chat | Spoken SKU/price (no form) | User × New | current user | shipped behavior; **not** PG catalog |
| Confirm / draft promote | ≤3 captions × ≤150 chars → `exemplar_captions` | Org (manual) | owner/admin or promote | **K5** |
| **Approvals** | Proposal diff → approve / reject | Org × New → Old | owner/admin | **K6 held** |

**Not collected in UI (MVP):** per-company persona CRUD, offer-snippet dedicated page, brand PDF upload, pain points, market signals, platform craft ([VOICE.md](../VOICE.md)).

---

## Screen contracts (minimal)

### Voice (K1)

- Controls only — no cards for decoration; one purpose: brand knobs.
- Persist on company `entities.profile`; compress to `voice_pack` in `load_context` ([MODEL.md](./MODEL.md#brand-voice-voice_pack)).
- Member (non-admin): read-only or hide edit — policy TBD at implement time (default: owner/admin edit).

### Products (K3 / K3b)

| Tab | Content |
|-----|---------|
| **Org** | Upload CSV/xlsx · result summary (`imported` / `updated` / `skipped` / `errors[]`) · table (name with `sku` subtitle, status, actions) · archive. Upsert **replace by SKU** — no merge-conflict UI ([COLLECT §2](./COLLECT.md#2-ownership-org--user-new--old)). |
| **Mine** | Same pattern for personal library. Org covers user on SKU clash at retrieve — UI may show badge “covered by company” when org has same SKU. |

Flexible headers: no required column names; store raw row in `profile` ([COLLECT §4](./COLLECT.md#4-product-import-k3)).

### Approvals (K6 — hidden)

- List pending promote proposals; show diff vs org row; Approve / Reject HTTP, zero LLM.
- **UI:** nav entry + page **hidden** until K6 UX is ready (`approvals-panel.tsx` kept for later).
- Until K6: do not implement silent chat→org writes.

---

## Design system notes

- Reuse existing shell primitives ([`web/src/components/ui/`](../../web/src/components/ui/)) — tabs, table, input, textarea, button, dialog.
- Voice accent (`text-voice`) only if showing craft exemplars preview; settings chrome stays neutral primary.
- Penpot: add **Company settings** pages (Voice / Products tabs / Approvals empty) under [design/penpot](../../design/penpot/) after this doc; CSS follows tokens already in `web/src/index.css`.
- **UI copy:** user-facing only (what the person sees/does). Avoid internal jargon in subtitles (no “K6”, “owner/admin”, “upsert”, “Zero LLM”).

---

## Phase checklist (UI)

| Phase | UI deliverable |
|-------|----------------|
| **K1** | Company settings → Voice form |
| **K3** | Products → Org tab (import + table) |
| **K3b** | Products → Mine tab |
| **K5** | Exemplar promote from Confirm / draft |
| **K6** | Approvals tab/page + Penpot when UX locked |

---

## References

- [COLLECT.md](./COLLECT.md) — ownership, cover rules, import API
- [MODEL.md](./MODEL.md) — `voice_pack` fields
- [design/BRIEF.md](../design/BRIEF.md) — shell vs craft
- [design/README.md](../design/README.md) — Penpot inventory
