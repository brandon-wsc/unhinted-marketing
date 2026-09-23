# ADR 0031 — Queue Send while parked at image OK

- **Status:** Superseded by [ADR 0036](./0036-image-direction-new-script.md) (explicit Send while image-parked is a new script, not a queue)
- **Date:** 2026-09-19
- **Supersedes:** [ADR 0016](./0016-queue-send-while-turn-in-flight.md) §6 only (explicit Send while image-parked used to `stopTurn` then post a new message)

## Context

ADR 0016 §5 already holds the drain while `awaiting_image_ok` so queued text cannot blind-resume image gen. §6 still treated an **explicit** composer Send at that park as Stop-then-new-turn, which discarded the parked draft (Generate-image CTA gone) and opened a fresh graph turn. UAT at the image park (typed「想睇 4格漫畫」while idle-parked) failed that path: the send was not a queue hold, and it was not a format lock either ([ADR 0030](./0030-image-format-in-bundled-gate.md) §3 — format cues belong on the card or a *non-parked* chat turn).

Angle park is different: a typed send *is* the pick ([ADR 0028](./0028-angle-pick-before-draft.md) §3). That path stays.

## Decision

1. **Image park + explicit Send enqueues** ~~like an in-flight send (ADR 0016 §1). Do **not** `stopTurn`. The parked draft, Generate-image CTA, and `awaiting_image_ok` stay until `POST /resume-image` or Stop.~~ **Superseded by [ADR 0036](./0036-image-direction-new-script.md):** Send while image-parked revises and re-parks (a direction change writes a new script + plan; a caption-only edit keeps the locked plan). Do not `stopTurn` and do not blind-resume image gen.
2. **Drain still holds** ~~while parked (ADR 0016 §5 unchanged). Queued rows wait for unpark; they are never a pick and never a blind image resume.~~ **Image-park hold superseded by [ADR 0036](./0036-image-direction-new-script.md):** a queued line drains as a direction-change turn. The angle park still holds.
3. **Angle park + explicit Send remains a typed pick** (ADR 0028 §3). Do not enqueue at `awaiting_angle_pick`.
4. **Image resume remains `POST /resume-image` only** ([ADR 0004](./0004-stop-discard-and-image-resume.md) §4). ~~Backend `POST /messages` while image-parked still 409.~~ **Superseded by [ADR 0036](./0036-image-direction-new-script.md):** that Send is a new script, not 409 and not `ainvoke(None)`.

## Consequences

- ~~Composer Send at the image park is the same local FIFO as mid-turn (max 3); the hold chrome (`chat.queue.holdForImage`) already covers this.~~ **Superseded by [ADR 0036](./0036-image-direction-new-script.md):** Send while image-parked starts a new script.
- Stop while parked still discards the turn (ADR 0004 §2). After Stop unlocks and the session is not re-parked, the queue drains.
- ~~Format change while image-parked stays on the card toggle / `POST /resume-image`, not via queued chat text.~~ **Superseded by [ADR 0036](./0036-image-direction-new-script.md):** format is locked on the pending version; changing it is another script.
