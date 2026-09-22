# ADR 0036 — Image direction change is a new script, then Discard or Execute

- **Status:** Accepted
- **Date:** 2026-09-22
- **Supersedes:** [ADR 0030](./0030-image-format-in-bundled-gate.md) §6 (late format switch regenerates the image only); [ADR 0031](./0031-queue-send-while-image-parked.md) §1 (explicit Send while image-parked enqueues); the image-park half of [ADR 0016](./0016-queue-send-while-turn-in-flight.md) §5 (drain holds while `awaiting_image_ok`)

## Context

可以反悔＝創作方向變咗. A change of picture or creative direction is a new version of the post, not a redraw of the old caption.

ADR 0030 locked format on the bundled angle card, then left an image-park toggle that re-generated the image only and left the caption alone. The edit-image dialog did the same: save a new plan (or flip single ↔ comic) and regenerate pixels without rewriting the script. After a chat revise that needed a new image, the 出圖 card still offered format chips, so Execute could paint a different vehicle against the script that was just written. ADR 0031 queued composer Send at the first image park, so a direction change before the first Execute could not become a new script at all.

The pending caption also lived only in the graph checkpoint until image generation finished. A reload while parked still showed the previous preview row.

Execute stays a human click. A chat message must not generate the image by itself.

## Decision

1. **Direction change writes a new script and a new image plan.** Chat that changes what the picture shows (including 「唔要…改成…」 of a visual, and an explicit format cue) and an edit-image plan/format/prompt change both produce a new `{ caption, hashtags, cta }` plus a matching `image_plan`. Caption-only edits (shorter, tone, hashtags, CTA) do not.

2. **That version is pending until Execute or Discard.** The graph parks **after** `executor_image_plan` and **before** `executor_image_gen` (`interrupt_before` includes `executor_image_gen`, not `executor_image_plan`). The pending copy and plan are inserted as a new `preview_drafts` revision **before** Execute, so a reload shows the new caption. The card offers only **Discard** (Stop while parked — restores the last accepted revision) or **Execute** (`POST /resume-image`, which generates the image from the locked plan). No format chips.

3. **Format is locked for that version.** `POST /resume-image` rejects an `image_format` that differs from the locked plan. Changing format is another regret cycle (new script + plan) and then Execute. There is no image-only late switch.

4. **Edit image dialog uses the same pending version.** Saving a changed prompt, format, or plan rewrites the script to match, stores the plan, and parks for Discard | Execute. It does not generate pixels in that request.

5. **`POST .../media/{id}/regen` only re-samples the current locked plan.** It does not change format or direction, and it refuses while a version is pending Execute. Direction changes go through decision 1.

6. **Chat while image-parked is the regret cycle, not a queue.** Explicit Send does not `stopTurn` and does not `ainvoke(None)`. It runs a revise turn from the pending script, writes another script + plan, and re-parks. A line queued during the in-flight turn drains into that same revise once the park lands. Angle-park Send stays a typed pick ([ADR 0028](./0028-angle-pick-before-draft.md)). The angle-park queue hold is unchanged.

7. **Discard restores the last accepted version.** Stop while parked deletes preview revisions above the pre-turn revision and restores `sessions.state` (and mode) from the discard anchor. Stop mid-Execute still re-parks ([ADR 0004](./0004-stop-discard-and-image-resume.md) §2). Confirm / publish stays [ADR 0003](./0003-confirm-without-llm.md).

## Consequences

- The first image park and a later regret park share one card: Discard | 出圖, format already chosen. Reload at that park shows the pending caption from `preview_drafts`, not the previous accepted row.
- `executor_image_plan` runs before the human click. Execute only runs `executor_image_gen`.
- Clients that still POST a different `image_format` on resume get 400. Matching or omitted format is a no-op.
- Same-plan Regenerate remains for “draw this locked plan again” after a version has been executed. It is not the path for a direction or format change.
