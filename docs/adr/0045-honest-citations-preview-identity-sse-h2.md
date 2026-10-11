# ADR 0045 — Honest citations, org preview identity, SSE HTTP/2 hardening

- **Status:** Accepted
- **Date:** 2026-10-12
- **Supersedes:** — (amends [ADR 0038](./0038-preview-source-signals.md) Sources semantics; hardens [ADR 0002](./0002-rest-source-of-truth-sse-enhancement.md) recovery)

## Context

Demo review on the Azure Container Apps deploy surfaced three honesty gaps:

1. **Ghost identity.** `IgPreviewMock` hard-coded `unhinted` as the account
   name and the copy prompt never told the executor which brand it was
   writing as, so a configured 公司名稱 (e.g. 港護康) appeared nowhere in the
   draft or preview.
2. **Stuffed citations.** `executor_post` fell back to `signal_ids[:3]` when
   the model returned no usable `source_signal_ids`, and `grounding_check`
   *required* citations whenever any HK signal existed in the DB. A creative
   draft that correctly used no market fact was therefore forced to list
   unrelated trend items under 出處 — the opposite of grounding.
3. **Silent hang.** `/sessions/{id}/events` sent `Connection: keep-alive`, a
   hop-by-hop header that is a protocol violation on HTTP/2
   (RFC 9113 §8.2.2). ACA ingress negotiates h2 with browsers; if a wedged
   h2 stream also swallows the in-flight turn POST's response, the UI pinned
   on 寫緊稿 until a manual reload.

## Decision

1. **Citations mean "actually used".** `executor_post` no longer pads empty
   `source_signal_ids` with the top ranked ids; the executor/edit prompts
   state that an empty list is correct for posts that use no market fact.
   `grounding_check` drops the "signals exist in DB ⇒ citations required"
   rule — it still rejects cited ids that do not resolve and invented
   product numbers; whether a *claim* needs a citation is the reviewer's
   call. `edit_copy` may cite from the ranked pool, not only previously
   used ids, so a reviewer ask for a citation is satisfiable.
2. **Sources block states "none" honestly.** The preview renders
   出處 · 今次未用市場出處 when `source_signals` is empty instead of
   hiding the block (extending ADR 0038 §6).
3. **Preview identity = org name.** `PreviewPanel` resolves the org matching
   `companyId` from the signed-in user's organizations and passes it as the
   IG mock `accountName`; `unhinted` remains only the no-org fallback. The
   executor/edit prompts tell the model the post is published under
   `company.name`, and the payload now carries `company` to `edit_copy`.
4. **SSE stream headers are h2-legal.** The events response drops
   `Connection: keep-alive` (`Cache-Control: no-cache` +
   `X-Accel-Buffering: no` stay).
5. **Reconnect resyncs the transcript.** On a post-failure reconnect the
   client now runs the same REST catch-up as the visibility/online handler
   — the snapshot carries no messages. If resync finds an assistant row the
   client never saw while a turn POST is still in flight, that POST is a
   zombie: it is aborted and the transcript hydrates from REST, so running
   agent pills finish. While the stream is down the chat header shows
   未連線 so the state is visible instead of a silent hang.

## Consequences

- A draft's 出處 can legitimately be empty; reviewers still gate invented
  market claims (`signals_trusted` rules unchanged).
- Demo sessions show the configured company name on the preview without any
  new backend field; a dedicated IG handle field can supersede this later.
- The HTTP/2 protocol error's infra root cause (ingress stream reset) is not
  locally reproducible; the header fix removes one known trigger and the
  client recovery covers the rest. If resets persist, investigate ACA
  ingress `stream_idle_timeout` / `max_stream_duration` next.
