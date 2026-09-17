# {{PROJECT_NAME}}

{{SUMMARY}}

## Target and scope

- In scope: `{{TARGET}}` — registration, verification, activation, and account-setup endpoints
- Out of scope: accounts and data not created for this assessment; any traffic that would degrade the service for other users

## Engagement

- Authorized assessment of the flow above: automation resistance, rate limiting, verification strength, and API boundary behavior.
- Authorization basis: {{AUTHORIZATION}}
- Rules of engagement:
  - Use dedicated test accounts and modest request rates; do not impact other users
  - Stop and document if a test causes visible service impact
  - Captured data stays in this workspace; redact credentials in shared output

## Deliverables

1. Endpoint map: methods, parameters, headers, tokens, and sequence
2. Control inventory: rate limits, challenge/CAPTCHA, device and email verification behavior
3. Reproduction harness under `tools/` with configurable rate, request/response logging, and cleanup of test accounts
4. Findings write-up: observed behavior, evidence, impact, and remediation

## Working conventions

- Keep scripts under `tools/`, raw captures under `evidence/`
- Log every request/response pair; change one variable at a time when probing controls
- Prefer the documented API surface over browser automation where it covers the flow
- Update this file whenever scope or authorization changes
