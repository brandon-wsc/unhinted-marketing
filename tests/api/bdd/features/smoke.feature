Feature: BDD smoke — shipped API through Gherkin
  Scaffold proving pytest-bdd drives the existing API surface before
  feature specs (e.g. ADR 0047 attachments) are written against it.

  Scenario: health endpoint answers ok
    When the client requests "GET /api/health"
    Then the response status is 200
    And the response reports status "ok"

  Scenario: registered member logs in and reads own profile
    Given a registered member
    When the member logs in with the seeded password
    Then the response status is 200
    And the member receives a bearer token
    When the member requests "GET /api/auth/me" with the bearer token
    Then the response status is 200
    And the profile email is the registered member's
