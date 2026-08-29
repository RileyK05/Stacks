# Auth boundary and ingestion runs

**Status:** accepted, 2026-08-25

## Authentication boundary

`User` is the public API-safe identity. `UserAccount` is internal state and may
contain a password hash and deletion marker. Internal account records must be
converted to `User` before an API response is returned.

Registration normalizes email addresses and validates passwords before bcrypt.
JWTs require subject, issued-at, not-before, expiry, issuer, and audience claims.
Production configuration rejects the development signing secret.

## Ingestion execution

Ingestion is a persisted ordered run with versioned stage handlers and
configuration. The order is text extraction, locator creation, chunk creation,
cascading TOC update, and memory extraction. A stage cannot run before its
dependency succeeds. A failed stage is retried up to the configured total
attempt count; exhaustion fails the run and prevents later stages from running.
Stage handlers must be idempotent.
