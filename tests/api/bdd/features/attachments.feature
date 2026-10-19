Feature: Session file attachments (ADR 0047; OCR transcript path per ADR 0048)
  Chat file import + document retrieve. Uploads land as session
  scratch (User x New); committing to a library is an explicit HTTP
  action — never a chat phrase and never an LLM decision. The LLM
  only ever sees digests; document content is fetched as slices.

  Background:
    Given a member with a session

  Scenario: upload becomes lexical-ready before vectors
    When they upload "catalog2026.pdf" with extractable text
    Then the attachment status becomes "ready_lexical"
    And the digest shows a title, a page count and an outline

  Scenario: an attached file rides on the next message
    Given the member has a ready attachment in the session
    When they send a message with the attachment
    Then the message references the attachment
    And the session carries the attachment digest

  Scenario: zero-instruction upload asks instead of pretending
    Given the member has a ready attachment in the session
    When they send a message with only the attachment
    Then the assistant reply carries the document digest
    And the reply offers actions for drafting, saving and summarizing

  Scenario: document slices answer a query
    Given the member has a ready attachment with an offer section
    When document slices are requested for "優惠期"
    Then at most 5 slices are returned
    And every slice carries a chunk id, a page or section ref and text

  Scenario: section slices work while embeddings are pending
    Given an attachment whose embeddings are still running
    When document slices are requested for the section "優惠詳情"
    Then the slices come from that heading path
    And the result is marked partial

  Scenario: a cold embedder never marks an attachment ready
    Given the worker embedder has not finished loading
    When they upload "catalog2026.pdf" with extractable text
    Then the attachment status is "ready_lexical"
    And no chunk is stored without a vector under status "ready"

  Scenario: scanned PDF parks for OCR
    When they upload "menu-scan.pdf" with no extractable text
    Then the attachment status is "needs_ocr"
    And the error says the file has no readable text
    And the digest says how many pages need OCR

  Scenario: a browser OCR transcript resumes ingest
    Given a scanned attachment parked for OCR
    When they post an OCR transcript for it
    Then the attachment status is "ready_lexical"
    And the digest marks the document as OCR-sourced
    And the transcript is stored for re-ingest

  Scenario: transcript for a healthy attachment is refused
    Given the member has a ready attachment in the session
    When they post an OCR transcript for it
    Then the transcript post is refused with a conflict

  Scenario: oversized file ingests a capped prefix and says so
    When they upload a file exceeding the chunk cap
    Then only the first capped chunks are ingested
    And the digest marks the document partial

  Scenario: spreadsheet upload is steered to product import
    When they upload "pricelist.csv" as an attachment
    Then the upload is refused with a pointer to product import

  Scenario: save to library is an HTTP action
    Given the member has a ready attachment in the session
    When they post the attachment to their library
    Then a committed user-scope document exists
    And the document survives the session

  Scenario: a chat phrase cannot save to library
    Given the member has a ready attachment in the session
    When they send a message asking to save it
    Then no committed document exists for the member

  Scenario: scratch dies with the session
    Given the member has a session-scoped attachment
    When the session is deleted
    Then the attachment rows and the stored object are removed

  Scenario: documents never leak across companies
    Given a member of another company has an attachment
    When the first member requests that attachment
    Then the request is refused
