# Security review checklist

Status labels: **Implemented**, **Verify each release**, or **Pending human sign-off**.

## OWASP API Top 10

- [ ] **Pending human sign-off — API1 Broken Object Level Authorization:** penetration tester must attempt cross-user export, deletion, credential, QA, and escalation access using two valid JWTs.
- [x] **Implemented — API2 Broken Authentication:** paid-source and privacy routes require verified, expiring HS256 bearer JWTs; signing key is a secret.
- [ ] **Pending human sign-off — API3 Broken Object Property Level Authorization:** penetration test mass-assignment and response-field exposure, especially credentials and legal-hold fields.
- [x] **Implemented — API4 Unrestricted Resource Consumption:** `/ask` is limited to 30/minute/IP and `/retrieve` to 60/minute/IP by default; limits are configurable. Verify production uses a shared/distributed limiter across Cloud Run instances.
- [ ] **Verify each release — API5 Broken Function Level Authorization:** review admin routes and restrict `/admin/review-queue` with the production authorization layer before release.
- [ ] **Pending human sign-off — API6 Unrestricted Access to Sensitive Business Flows:** test automated consent, paid-search, export, and deletion abuse.
- [x] **Implemented — API7 SSRF:** connector stub accepts only query text; any future connector must use an allowlisted provider base URL and be security-reviewed.
- [ ] **Verify each release — API8 Security Misconfiguration:** run deployment configuration review, ensure debug is off, and validate CORS, secrets IAM, and HTTPS.
- [x] **Implemented — API9 Improper Inventory Management:** CI scans Python and JavaScript dependencies; API routes are version-controlled and documented.
- [ ] **Pending human sign-off — API10 Unsafe Consumption of APIs:** penetration test paid-provider responses, malformed tool results, and prompt-injection paths.

## Credential storage

- [x] Envelope encryption uses a random AES-256-GCM data key per credential; Postgres stores ciphertext, nonces, encrypted data key, and KEK version only.
- [x] KEK is loaded from Google Secret Manager at runtime; plaintext credential is not logged, exported, or persisted.
- [ ] **Pending human sign-off:** validate Secret Manager IAM, key rotation execution, backup handling, and forensic log redaction in the deployed environment.

## Dependency scanning

- [x] PR and deployment CI run `pip-audit` and `npm audit --audit-level=high`.
- [ ] **Verify each release:** triage/patch scan findings or record a time-bound approved exception.
