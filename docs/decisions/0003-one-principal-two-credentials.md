# ADR 0003 — One Principal, two credential types

**Status:** accepted · **Date:** 2026-07-29

## Context

Two things authenticate against this platform: people in a browser, via OIDC and
a session cookie, and applications, via an API key. They need the same
permission checks, the same workspace scoping and the same audit trail.

## Decision

Both resolve to a single frozen `Principal` in `nexus/auth/principal.py`, built
in exactly one place — `get_principal` in `nexus/api/deps.py`. Routers depend on
`Principal` and are not given any way to tell which credential produced it.

An explicit `Authorization` header beats an ambient cookie when both are
present.

## Alternatives considered

- **Separate dependencies per credential type** (`get_user`, `get_api_client`).
  Every endpoint then has to decide which it supports, and the answer is almost
  always "both", so the decision gets duplicated 40 times and diverges.
- **Session-only, with API keys exchanged for sessions.** Tidy in theory; it
  makes every service call stateful and gives a machine client a token that
  expires for reasons it cannot act on.

## Consequences

- A handler that branches on credential type is a smell, and now an obvious one.
- Header-beats-cookie closes a real hole: a script running in an authenticated
  browser context cannot silently borrow the user's session by omitting a header.
- `DelegatedPrincipal` extends the same idea to agents: a tool executes with the
  delegating user's permissions, never the agent's own and never a service
  account's. An agent able to retrieve more than the person it acts for is a hole
  through every permission check in the platform, so the delegation is modelled
  rather than assumed.
- Both credential types are stored as SHA-256 hashes, so an API key is shown
  exactly once and the endpoint says so rather than pretending it can be
  recovered.
