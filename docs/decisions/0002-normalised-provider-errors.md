# ADR 0002 — Normalise provider errors before routing sees them

**Status:** accepted · **Date:** 2026-07-29

## Context

Retry, fallback and circuit-breaking all need to answer one question: what kind
of failure was that? Each provider answers differently — different status codes,
different bodies, different wording, changed without notice.

## Decision

Every adapter maps its provider's failures onto six classes in
`nexus/providers/errors.py`: `RateLimitError`, `ProviderTimeoutError`,
`ProviderUnavailableError`, `ContextLengthError`, `ContentFilterError`,
`AuthError`. Each carries `retryable` and `should_fallback`. Nothing outside an
adapter is permitted to inspect a raw provider error.

## Alternatives considered

- **Branch on HTTP status in the router.** Works until a provider returns 400 for
  a context-length problem and 400 for a content filter, which need opposite
  handling.
- **Match on error message strings.** Works until the provider rewords a message,
  at which point fallback silently stops working and nothing fails loudly.

## Consequences

- Adding a provider means writing one `_translate_error` method; routing logic is
  untouched.
- `MockProvider` can raise any of the six on demand, so fallback behaviour is
  testable offline and in CI — the difference between fallback that is tested and
  fallback that is hoped for.
- Mapping mistakes are now concentrated in one method per provider, which is why
  each branch gets its own test.
