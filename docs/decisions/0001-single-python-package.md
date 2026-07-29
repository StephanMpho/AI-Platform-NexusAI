# ADR 0001 — One Python package, not three services

**Status:** accepted · **Date:** 2026-07-29

## Context

The task list (FOUND-001) describes `/services/api`, `/services/worker` and
`/packages/schemas` as separate trees. Modelled literally in Python that means
three installable packages with three `pyproject.toml` files and a workspace tool
to link them.

The API and the worker share almost everything: settings, models, provider
adapters, schemas. They differ only in entry point.

## Decision

One installable package, `src/nexus/`, with `api/`, `worker/`, `providers/`,
`db/` and `schemas/` as submodules. Two entry points: `nexus.api.main:app` and
`nexus.worker.celery_app`.

## Alternatives considered

- **Three packages with a uv or Poetry workspace.** Correct if the teams or
  release cadences were genuinely separate. They are not — it is one developer
  and one release. The cost is editing three dependency files for every shared
  change, which is friction paid daily for a benefit not yet needed.
- **A single flat module.** Cheaper still, and it stops scaling the moment the
  Knowledge Hub arrives.

## Consequences

- The API and worker deploy as the same image with different commands. Fine while
  they scale together; the day ingestion needs its own scaling profile, the split
  is a Dockerfile change, not a refactor, because the module boundaries already
  exist.
- Shared code cannot drift between services, which removes a class of bug.
- The directory layout differs from the specification. This ADR is the record of
  why; the specification is not wrong, it is just describing a later state.
