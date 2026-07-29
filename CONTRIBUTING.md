# Working on NexusAI

## Loop

```bash
make up          # backing services, once per session
make dev         # api + console with reload
make test        # before every commit
make lint        # ruff + mypy, matches CI
```

## Conventions

- **Settings** are read only in `nexus/config.py`. No `os.environ` anywhere else.
- **Workspace scoping** belongs in the repository layer, not the router. Every
  repository method takes `workspace_id` and puts it in the WHERE clause.
- **Provider specifics** stay inside the adapter. If routing logic needs to know
  which provider it is talking to, something has leaked.
- **Migrations** are generated (`make revision m="..."`) and then read before
  committing. Autogenerate is a first draft, not an answer.
- **Every task from the spec** gets a branch named for its ID: `gw-002-chat-pipeline`.
- **TODO markers** carry the task ID: `TODO(GW-004)`. `grep -rn "TODO(" src` is
  the live backlog.

## Definition of done

A task is done when every statement in its DONE WHEN section is verifiable, not
when the code is written. If the acceptance test needs a fixture that does not
exist, building the fixture is part of the task.

## Tests worth writing first

The negative ones. Cross-workspace reads, ungranted tool calls, permission
bypasses in retrieval — these are the failures that matter and the ones that
never get written if left until later.
