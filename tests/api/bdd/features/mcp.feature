Feature: Remote MCP server for consumer AI apps (ADR 0051)
  An external AI app drafts posts through a per-user OAuth grant bound to
  one company. Identity comes from the token only. Session gates can be
  answered by the client — or by the adapter in auto mode — but no tool
  publishes, confirms or approves: Confirm stays a click in our UI.

  # --- transport + discovery (§1, §2) -------------------------------------

  Scenario: an MCP call without a token is challenged
    When an MCP client lists tools without a token
    Then the response status is 401
    And the challenge points at the protected resource metadata

  Scenario: protected resource metadata advertises only the default scopes
    When the client fetches the protected resource metadata
    Then the response status is 200
    And the metadata names the MCP endpoint as the resource
    And the metadata names an authorization server
    And the default scopes are "knowledge:read drafts:write"

  # --- token isolation + revocation (§4) ----------------------------------

  Scenario: a web session token cannot call the MCP endpoint
    Given a member with a web session
    When the member lists MCP tools with the web token
    Then the response status is 401

  Scenario: an MCP token cannot call the web API
    Given a member with an MCP grant for "drafts:write"
    When the MCP token requests "GET /api/sessions"
    Then the response status is 401

  Scenario: revoking the connected app cuts the next call
    Given a member with an MCP grant for "drafts:write"
    When the member revokes the connected app on the web
    Then the revoke response status is 204
    When the client lists MCP tools
    Then the response status is 401

  # --- tool surface (§5, §7, §12) -----------------------------------------

  Scenario: the tool surface has no publish-class tool
    Given a member with an MCP grant for "knowledge:read drafts:write images:generate"
    When the client lists MCP tools
    Then the response status is 200
    And the tools are exactly the ADR 0051 surface
    And no tool name mentions publish or confirm

  Scenario: approving an image needs the images:generate scope
    Given a member with an MCP grant for "drafts:write"
    And the member has a session parked at image OK
    When the client approves the image
    Then the response status is 403
    And the challenge asks for scope "images:generate"

  # --- identity from the token only (§6) ----------------------------------

  Scenario: a draft started over MCP belongs to the grant's user and company
    Given a member with an MCP grant for "drafts:write"
    And the session graph parks at both gates
    When the client starts a post draft "中秋月餅推廣"
    Then the tool result has a session id and status "running"
    And the session belongs to the member and the granted company
    And the session origin records the MCP client

  Scenario: a teammate's session is refused
    Given a member with an MCP grant for "drafts:write"
    And a teammate in the same company has a session
    When the client gets the teammate's post draft
    Then the tool call is refused with reason "access_denied"

  Scenario: the grant never reaches the user's other company
    Given a member with an MCP grant for "drafts:write"
    And the member also owns a session in a second company
    When the client gets that second-company post draft
    Then the tool call is refused with reason "access_denied"

  Scenario: a member over the monthly token cap is refused over MCP
    Given a capped member who has used their monthly tokens
    And the member holds an MCP grant for "drafts:write"
    When the client starts a post draft "中秋月餅推廣"
    Then the tool call is refused with reason "usage_limit_exceeded"

  # --- gates: client-answered and auto (§8, §9, §10) ----------------------

  Scenario: a draft settles at the angle park with a recommendation
    Given a member with an MCP grant for "drafts:write"
    And the session graph parks at both gates
    When the client starts a post draft "中秋月餅推廣"
    And the client polls the draft until it settles
    Then the draft status is "awaiting_angle_pick"
    And the result offers the angles with a recommended angle index

  Scenario: auto mode without images:generate stops at the image park
    Given a member with an MCP grant for "drafts:write"
    And the session graph parks at both gates
    When the client starts an auto post draft "中秋月餅推廣"
    And the client polls the draft until it settles
    Then the draft status is "awaiting_image_ok"
    And the graph never resumed past the image park
    And the session origin records the recommended angle as an auto pick

  # --- Confirm stays in our UI (§12) --------------------------------------

  Scenario: a ready draft links to Confirm and never leaks the approval token
    Given a member with an MCP grant for "drafts:write"
    And the member has a preview-ready session
    When the client gets that post draft
    Then the draft status is "ready"
    And the result carries a confirm url for the session
    And the reply never contains the approval token
