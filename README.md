# NexusAI — Enterprise AI Operations Platform

A governed front door for AI inside an organisation: model routing with cost control,
RAG over internal documents with citations, evaluation you can defend, controlled
agent workflows, and an audit trail across all of it.

Specifications live in `docs/`:
- `NexusAI_Task_List.pdf` — 53 tasks across 7 phases
- `NexusAI_Database_Schema.pdf` — 55 tables across 8 domains

---

## Quickstart

You need Docker, Python 3.12 and Node 20.

```bash
cp .env.example .env      # defaults work for local development
make up                   # postgres+pgvector, redis, minio, mlflow, otel, grafana
make install              # python deps into .venv, plus console deps
make migrate              # create the schema
make dev                  # API on :8000, console on :3000
```

Check it is alive:

```bash
curl localhost:8000/health | jq

curl -X POST localhost:8000/v1/chat \
  -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"hello"}],"model":"mock-fast"}' | jq
```

The `mock` provider needs no API key and no network, so the whole request path is
testable before you have spent a cent. Add real providers to `.env` when you want them.

## Layout

```
src/nexus/
  config.py          typed settings — the only place environment is read
  db/                SQLAlchemy models and session factory
  providers/         provider abstraction: mock, openai, anthropic
  api/               FastAPI app, routers, dependencies
  schemas/           request and response models shared by api and worker
  worker/            Celery tasks — ingestion, rollups, evaluation runs
  telemetry.py       OpenTelemetry setup
apps/console/        Next.js 14 console
infra/               compose service configs — otel, prometheus, grafana
migrations/          Alembic
docs/decisions/      one ADR per significant choice
tests/
```

## Where to start

Phase 0 of the task list is largely done by this scaffold. The first real work is
**GW-001 — provider abstraction** (`src/nexus/providers/`), then
**GW-002 — the `/v1/chat` pipeline** (`src/nexus/api/routers/chat.py`).

Both carry `TODO(GW-00x)` markers where the work goes. Search the repo for `TODO(` to
see everything the scaffold has deliberately left open.

## Commands

| Command | What it does |
|---|---|
| `make up` / `make down` | start / stop backing services |
| `make install` | create `.venv`, install Python and console deps |
| `make dev` | run API and console together |
| `make api` / `make console` / `make worker` | run one process |
| `make migrate` | apply migrations |
| `make revision m="add x"` | autogenerate a migration |
| `make test` | pytest |
| `make lint` | ruff + mypy |
| `make fmt` | format and autofix |

## Service ports

| Service | Port |
|---|---|
| API | 8000 |
| Console | 3000 |
| Postgres | 5432 |
| Redis | 6379 |
| MinIO (console) | 9000 (9001) |
| MLflow | 5000 |
| Grafana | 3001 |
| Prometheus | 9090 |
