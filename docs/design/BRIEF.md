# Unhinted — Visual brief

> **Status:** Proposed — style direction **not locked**.  
> **Product name:** Unhinted Marketing (shipped).  
> **Personality target:** “unhinged” as **character** (港式抽水小編), not a rename.

Align the **tool UI** with [VOICE.md](../VOICE.md): sharp, spoken HK Cantonese energy, scene-first, soft sell — not corporate dashboard PR.

---

## Tension (today)

| Layer | Today | Desired |
|-------|-------|---------|
| Brand mark | Indigo `#6366F1` rounded square + Inter | Personality-first mark + expressive type |
| Surfaces | Zinc / off-white SaaS shell | Atmosphere that feels like chatting with a 小編, not an admin console |
| Session | Functional chat + IG preview | Same IA; stronger brand signal without landing-page clutter |

Shipped shell (header → chat → agent trail → preview → confirm) stays. Personality lands in **tokens, type, logo, empty/interrupt moments** — not a second product IA.

---

## Hard constraints (product)

- **Confirm ≠ chat** — publish only via Confirm + `approval_token` ([ADR 0003](../adr/0003-confirm-without-llm.md)).
- Session workspace is a **tool**, not a marketing landing: no hero budget of stats / promo strips in the first viewport of `/`.
- Cards only for **interactive** units (brief, interrupt, recommended questions, auth form) — see web UI system rule.
- Avoid default AI-look clusters: purple→indigo glow themes; warm cream + terracotta serif; broadsheet dense columns; emoji-as-UI; multi-layer neon shadows.

---

## Direction options (pick one primary)

### A — 茶餐廳夜檔 *(recommended draft)*

Cool fluorescent white, ink black, one hot accent (curry yellow **or** chilli red — not both as primaries). Bold / slightly industrial sans for English brand; solid CJK for body. Feels like after-OT IG scroll with a friend who writes copy.

### B — 街招 × 工具

High-contrast black/white base; single fluorescent accent (cyan **or** magenta). Dense but dry; agent trail / preview read like a clipping board.

### C — Soft meme studio

Light workbench chrome; personality in illustration + 2–3 intentional motions on empty / interrupt / confirm. Quiet shell, loud moments.

**Working proposal until locked:** start from **A**, keep dual light/dark themes, expose “unhinged” only as craft attitude (VOICE), not as chrome wordmark.

---

## Open decisions

| # | Question | Default until locked |
|---|----------|----------------------|
| 1 | Primary direction A / B / C? | **A** |
| 2 | Show “unhinged” in UI copy? | **No** — product stays Unhinted |
| 3 | Scope of first visual pass | Session chrome + auth; admin later |
| 4 | Keep light + dark? | **Yes** |
| 5 | Accent hue for A | TBD (yellow vs red) |

---

## Motion (when restyling)

Ship **2–3** intentional motions max for the first pass, e.g.: composer send affordance, preview ready affordance, interrupt card entrance. No decorative particle / glow noise.
