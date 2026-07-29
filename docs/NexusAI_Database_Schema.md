# NexusAI — Enterprise AI Operations Platform
## Database Schema Specification · v1.0

**PostgreSQL 16 · pgvector · SQLAlchemy 2.0 + Alembic**
**55 tables · 8 domains · Multi-tenant · Append-only audit · Effective-dated pricing**

---

## Design principles & global conventions

- **UUID primary keys everywhere** — `gen_random_uuid()` via pgcrypto. Prevents enumeration and lets a client generate an ID before insert. The two exceptions are `audit_log` and `spans`, which use `BIGSERIAL` because insertion order carries meaning and volume is high.
- **All timestamps `TIMESTAMPTZ`** — stored in UTC without exception. Local time conversion happens in the UI layer only, never in a query.
- **Workspace scoping on every business table** — `workspace_id` is present and indexed on every table a user can reach, including denormalised onto hot child tables. Multi-tenancy enforced by a mandatory predicate in the repository layer; a query without it is a bug caught by test, not by review.
- **Immutable tables** — `audit_log`, `cost_entries`, `policy_violations`, `agent_steps`, `eval_results`, `pii_detections`, `fallback_events` are append-only. Enforced by Postgres row-level security, not application convention.
- **Soft deletes on configuration, hard deletes on nothing user-facing** — `deleted_at` on definitional tables (agents, prompts, collections, policies). Historical runs must still resolve their configuration after it is retired.
- **`VARCHAR` + `CHECK`, never native `ENUM`** — `ALTER TYPE` takes a table lock; adding a value to a CHECK constraint does not. SQLAlchemy generates Python enums from the same constants.
- **`NUMERIC` for money, never float** — `NUMERIC(14,8)` for per-request cost, `NUMERIC(14,4)` for aggregates, `NUMERIC(12,6)` for per-million-token rates. Individual request costs are fractions of a cent and float error accumulates visibly across a month.
- **Effective-dated pricing** — `pricing_rates` is versioned by `effective_from`. Cost is computed against the rate live at request time, so historical reports never change when a provider updates prices.
- **JSONB for open shapes, columns for anything queried** — configuration, tool arguments and decision factors are JSONB. Anything filtered, grouped or aggregated gets a real column.
- **`updated_at` by trigger** — one shared `set_updated_at()` function applied to every table with the column. Correct even for direct SQL and migrations.
- **Vectors are versioned** — `chunk_embeddings` carries the model and embedding version on every row, which is what makes an embedding-model migration possible without downtime.
- **Partitioning where volume demands it** — `audit_log` and `traces` by month, `spans` and `gateway_requests` by day. Partition creation is a scheduled job, not a manual chore.

### Column flag legend

| Flag | Meaning | Flag | Meaning |
|---|---|---|---|
| **PK** | Primary key | **FK** | Foreign key, referenced table in description |
| **NN** | NOT NULL | **UQ** | UNIQUE constraint |
| **IDX** | Indexed, non-unique | **DEF** | Has a default, stated in description |

---

## Schema summary — 55 tables across 8 domains

| Domain | # | Tables |
|---|---|---|
| 1. Identity & Access | 7 | users, workspaces, workspace_memberships, roles, role_assignments, api_keys, user_sessions |
| 2. Gateway & Routing | 8 | providers, models, model_deployments, routing_policies, routing_rules, gateway_requests, gateway_messages, fallback_events |
| 3. Cost & Quotas | 5 | pricing_rates, cost_entries, budgets, quota_windows, rate_limit_buckets |
| 4. Knowledge Hub | 9 | collections, collection_grants, documents, document_versions, chunks, chunk_embeddings, ingestion_jobs, retrieval_queries, retrieval_citations |
| 5. Agents & Workflows | 7 | agent_definitions, agent_versions, tools, agent_tool_grants, agent_runs, agent_steps, approval_requests |
| 6. Evaluation | 7 | prompt_templates, prompt_versions, eval_datasets, eval_items, scorers, eval_runs, eval_results |
| 7. Observability | 5 | traces, spans, span_events, metric_rollups, alert_rules |
| 8. Governance & Audit | 7 | audit_log, policies, policy_violations, pii_detections, redaction_rules, feature_flags, data_retention_schedules |

---

# 1. Identity & Access

### users
*Platform identities, provisioned on first SSO login.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | `gen_random_uuid()` |
| email | VARCHAR(320) | UQ NN IDX | Lowercased and trimmed on insert |
| external_subject | VARCHAR(255) | UQ IDX | OIDC `sub` claim. Stable across email changes — match on this, not email |
| issuer | VARCHAR(255) | NN | OIDC issuer URL. Same subject from a different issuer is a different person |
| display_name | VARCHAR(200) | NN | |
| avatar_url | VARCHAR(500) | | |
| default_workspace_id | UUID | FK | → workspaces.id. Landing workspace after login |
| clearance | VARCHAR(20) | NN | `public` \| `internal` \| `confidential` \| `restricted`. Matched against document sensitivity in retrieval. DEF `internal` |
| is_active | BOOLEAN | NN | Deactivated users cannot authenticate. Never hard-delete. DEF true |
| last_login_at | TIMESTAMPTZ | | |
| created_at | TIMESTAMPTZ | NN | |
| updated_at | TIMESTAMPTZ | NN | Trigger-maintained |

**Indexes** `uq_users_email (email)` · `uq_users_subject (issuer, external_subject)` · `idx_users_active (is_active) PARTIAL WHERE is_active`

---

### workspaces
*The tenancy boundary. Every business record belongs to exactly one.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| slug | VARCHAR(60) | UQ NN | URL-safe identifier |
| name | VARCHAR(200) | NN | |
| description | TEXT | | |
| logging_mode | VARCHAR(20) | NN | `full` \| `redacted` \| `metadata_only`. Governs what `gateway_messages` stores. DEF `redacted` |
| default_routing_policy_id | UUID | FK | → routing_policies.id. Used when a request specifies neither model nor policy |
| monthly_budget_usd | NUMERIC(12,2) | | NULL = unlimited. Enforced by GW-007 |
| data_residency | VARCHAR(20) | | `any` \| `eu` \| `us` \| `local_only`. Constrains which provider deployments are eligible |
| allow_external_providers | BOOLEAN | NN | FALSE forces routing to self-hosted deployments only. DEF true |
| settings | JSONB | | Open configuration bag for module-level defaults |
| is_active | BOOLEAN | NN | DEF true |
| created_at | TIMESTAMPTZ | NN | |
| updated_at | TIMESTAMPTZ | NN | |

---

### workspace_memberships
*Which users belong to which workspaces.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | → workspaces.id ON DELETE CASCADE |
| user_id | UUID | FK NN IDX | → users.id ON DELETE CASCADE |
| invited_by | UUID | FK | → users.id |
| joined_at | TIMESTAMPTZ | NN | |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_membership (workspace_id, user_id) UNIQUE`

---

### roles
*Named permission bundles. Permissions live in JSONB so a role extends without a migration.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK IDX | → workspaces.id. NULL = system role available to all workspaces |
| name | VARCHAR(50) | NN | `owner` \| `admin` \| `engineer` \| `analyst` \| `viewer`, or custom |
| description | TEXT | | |
| permissions | JSONB | NN | Array of permission strings, e.g. `["gateway.route.write","knowledge.collection.read"]` |
| is_system | BOOLEAN | NN | System roles cannot be edited or deleted. DEF false |
| created_at | TIMESTAMPTZ | NN | |
| updated_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_role_name (workspace_id, name) UNIQUE NULLS NOT DISTINCT`

---

### role_assignments
*Binds a user to a role within a workspace.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | → workspaces.id |
| user_id | UUID | FK NN IDX | → users.id |
| role_id | UUID | FK NN | → roles.id |
| granted_by | UUID | FK NN | → users.id. Audited |
| expires_at | TIMESTAMPTZ | | Time-bounded elevation. NULL = permanent |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_role_assignment (workspace_id, user_id, role_id) UNIQUE` · `idx_role_expiry (expires_at) PARTIAL WHERE expires_at IS NOT NULL`

---

### api_keys
*Service credentials. Scoped to one workspace, hashed at rest, shown once.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | → workspaces.id ON DELETE CASCADE |
| key_prefix | VARCHAR(16) | NN | First 12 chars for display, e.g. `nx_live_A7f2`. Identifies a key without exposing it |
| key_hash | VARCHAR(64) | UQ NN | SHA-256 of the full key. Plaintext never stored |
| environment | VARCHAR(10) | NN | `live` \| `test` ✓ CHECK |
| label | VARCHAR(100) | NN | Human name, e.g. `support-bot-prod` |
| scopes | TEXT[] | | Permission scopes. NULL = the workspace's default service scope |
| created_by | UUID | FK NN | → users.id |
| last_used_at | TIMESTAMPTZ | | Written at most once per minute to limit write amplification |
| last_used_ip | INET | | Anomaly detection |
| request_count | BIGINT | NN | DEF 0 |
| expires_at | TIMESTAMPTZ | | NULL = never. Set to force rotation |
| revoked_at | TIMESTAMPTZ | IDX | NULL = active |
| revoked_by | UUID | FK | → users.id |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `idx_apikey_hash (key_hash) UNIQUE` · `idx_apikey_ws (workspace_id, revoked_at)`

---

### user_sessions
*Browser sessions with revocation state.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK NN IDX | → users.id |
| token_hash | VARCHAR(64) | UQ NN | SHA-256 of the opaque session token |
| workspace_id | UUID | FK | Active workspace at last request |
| ip_address | INET | | |
| user_agent | TEXT | | |
| status | VARCHAR(20) | NN IDX | `active` \| `expired` \| `revoked` \| `logged_out` |
| revoke_reason | VARCHAR(50) | | `user_logout` \| `admin_force` \| `suspicious_activity` \| `password_change` |
| expires_at | TIMESTAMPTZ | NN IDX | 8h default, sliding refresh capped at 24h |
| last_active_at | TIMESTAMPTZ | | |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `idx_session_token (token_hash) UNIQUE` · `idx_session_expiry (expires_at)` — cleanup job

---

# 2. Gateway & Routing

### providers
*Upstream model providers. Adding one is configuration, not code.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| slug | VARCHAR(50) | UQ NN | `openai` \| `anthropic` \| `azure_openai` \| `vertex` \| `local` \| `mock` |
| name | VARCHAR(100) | NN | |
| adapter_class | VARCHAR(200) | NN | Import path of the `LLMProvider` implementation |
| base_url | VARCHAR(500) | | Override for self-hosted or regional endpoints |
| credential_ref | VARCHAR(200) | | Key into the secret resolver. Never the credential itself |
| is_external | BOOLEAN | NN | FALSE for self-hosted. Data policies gate on this. DEF true |
| region | VARCHAR(20) | | Residency enforcement |
| default_timeout_ms | INTEGER | NN | DEF 60000 |
| max_concurrency | SMALLINT | NN | Connection pool ceiling. DEF 20 |
| health_status | VARCHAR(20) | NN | `healthy` \| `degraded` \| `unavailable` \| `unknown`. Written by the health probe |
| health_checked_at | TIMESTAMPTZ | | |
| is_active | BOOLEAN | NN | DEF true |
| created_at | TIMESTAMPTZ | NN | |
| updated_at | TIMESTAMPTZ | NN | |

---

### models
*A model as the platform knows it, independent of where it is deployed.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| slug | VARCHAR(100) | UQ NN IDX | Platform-wide name used in API requests, e.g. `fast-general`, `strong-reasoning` |
| provider_id | UUID | FK NN IDX | → providers.id |
| provider_model_name | VARCHAR(200) | NN | The name the provider expects on the wire |
| family | VARCHAR(50) | | Groups variants for comparison in the Evaluation Lab |
| tier | VARCHAR(20) | NN IDX | `cheap` \| `standard` \| `strong` \| `embedding`. Routing rules reference this |
| modality | VARCHAR(20) | NN | `text` \| `multimodal` \| `embedding` |
| context_window | INTEGER | NN | Max input tokens. Used for context-length fallback decisions |
| max_output_tokens | INTEGER | | |
| supports_tools | BOOLEAN | NN | DEF false |
| supports_streaming | BOOLEAN | NN | DEF true |
| supports_json_mode | BOOLEAN | NN | DEF false |
| embedding_dimensions | SMALLINT | | Only for embedding models. Must match the vector column width |
| is_active | BOOLEAN | NN | Inactive models cannot be selected by new requests but remain resolvable for history |
| deprecated_at | TIMESTAMPTZ | | Warning surfaced on routing policies still referencing it |
| created_at | TIMESTAMPTZ | NN | |
| updated_at | TIMESTAMPTZ | NN | |

**Indexes** `idx_models_slug (slug) UNIQUE` · `idx_models_tier (tier, is_active)`

---

### model_deployments
*The same model in different regions or on different endpoints. Residency policies select here.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| model_id | UUID | FK NN IDX | → models.id |
| region | VARCHAR(20) | NN | `eu` \| `us` \| `local` |
| endpoint_url | VARCHAR(500) | | Overrides the provider base URL |
| deployment_name | VARCHAR(200) | | Azure deployment name or equivalent |
| priority | SMALLINT | NN | Lower is preferred among eligible deployments. DEF 100 |
| is_active | BOOLEAN | NN | DEF true |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `idx_deploy_model_region (model_id, region, is_active)`

---

### routing_policies
*A named, versioned routing configuration.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | → workspaces.id |
| name | VARCHAR(100) | NN | |
| version | INTEGER | NN | Incremented on change; prior versions retained |
| is_current | BOOLEAN | NN | One current version per name per workspace |
| default_model_id | UUID | FK NN | → models.id. Used when no rule matches |
| fallback_model_ids | UUID[] | | Ordered preference list for GW-004 |
| max_cost_per_request_usd | NUMERIC(10,6) | | Hard ceiling. Requests estimated above it are rejected |
| total_timeout_ms | INTEGER | NN | Wall-clock budget across all retries and fallbacks. DEF 60000 |
| description | TEXT | | |
| created_by | UUID | FK NN | → users.id |
| deleted_at | TIMESTAMPTZ | | |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_policy_current (workspace_id, name, version) UNIQUE` · `idx_policy_current (workspace_id, name, is_current) PARTIAL WHERE is_current`

---

### routing_rules
*Ordered conditions within a policy. First match wins.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| routing_policy_id | UUID | FK NN IDX | → routing_policies.id ON DELETE CASCADE |
| sequence | SMALLINT | NN | Evaluation order, 1-indexed |
| name | VARCHAR(100) | NN | Shown in the request record so a routing decision is self-explaining |
| condition | JSONB | NN | e.g. `{"all":[{"field":"metadata.task_type","op":"in","value":["summarise"]},{"field":"estimated_input_tokens","op":"lt","value":4000}]}` |
| action | VARCHAR(20) | NN | `route` \| `route_preference_list` \| `reject` ✓ CHECK |
| target_model_id | UUID | FK | → models.id. Required when action = `route` |
| target_model_ids | UUID[] | | Ordered list when action = `route_preference_list` |
| reject_reason | VARCHAR(200) | | Returned to the caller when action = `reject` |
| is_active | BOOLEAN | NN | DEF true |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_rule_seq (routing_policy_id, sequence) UNIQUE`

---

### gateway_requests
*Every request through the gateway. Partitioned by day.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | Also the public `x-nexus-request-id` |
| workspace_id | UUID | FK NN IDX | → workspaces.id |
| user_id | UUID | FK IDX | → users.id. NULL for service-key requests |
| api_key_id | UUID | FK IDX | → api_keys.id. NULL for user requests |
| agent_run_id | UUID | FK IDX | → agent_runs.id when the caller was an agent |
| eval_run_id | UUID | FK IDX | → eval_runs.id when the caller was an evaluation |
| routing_policy_id | UUID | FK | → routing_policies.id. NULL when the model was pinned |
| routing_rule_id | UUID | FK | → routing_rules.id. Which rule decided, for explainability |
| requested_model_id | UUID | FK | → models.id. What the caller asked for, if anything |
| resolved_model_id | UUID | FK IDX | → models.id. What actually served the request |
| prompt_version_id | UUID | FK | → prompt_versions.id when a registered prompt was used |
| status | VARCHAR(20) | NN IDX | `in_flight` \| `success` \| `error` \| `rejected` \| `cancelled` |
| error_class | VARCHAR(40) | IDX | Normalised: `rate_limit` \| `timeout` \| `context_length` \| `content_filter` \| `auth` \| `unavailable` \| `policy_denied` \| `quota_exceeded` |
| error_detail | TEXT | | |
| input_tokens | INTEGER | | |
| output_tokens | INTEGER | | |
| cached_tokens | INTEGER | | Prompt-cache hits, priced differently |
| estimated_input_tokens | INTEGER | | Pre-call estimate used for routing. Kept to measure estimator drift |
| fallback_count | SMALLINT | NN | DEF 0 |
| retry_count | SMALLINT | NN | DEF 0 |
| duration_ms | INTEGER | | Total, including retries and fallbacks |
| provider_duration_ms | INTEGER | | Provider time only. The difference is gateway overhead |
| trace_id | VARCHAR(32) | IDX | OTel trace ID — joins to `traces` |
| idempotency_key | VARCHAR(255) | IDX | Replay key, 24h validity |
| metadata | JSONB | | Caller-supplied tags used by routing rules and reporting |
| is_streaming | BOOLEAN | NN | DEF false |
| created_at | TIMESTAMPTZ | NN IDX | Partition key, by day |
| completed_at | TIMESTAMPTZ | | |

**Indexes** `idx_gwreq_ws_time (workspace_id, created_at DESC)` · `idx_gwreq_model (resolved_model_id, created_at DESC)` · `idx_gwreq_status (status, error_class) PARTIAL WHERE status <> 'success'` · `idx_gwreq_idem (idempotency_key, workspace_id) UNIQUE PARTIAL WHERE idempotency_key IS NOT NULL`

---

### gateway_messages
*Prompt and completion content, subject to the workspace logging mode.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| gateway_request_id | UUID | FK NN IDX | → gateway_requests.id ON DELETE CASCADE |
| workspace_id | UUID | FK NN IDX | Denormalised for retention sweeps |
| sequence | SMALLINT | NN | Message order within the request |
| role | VARCHAR(20) | NN | `system` \| `user` \| `assistant` \| `tool` ✓ CHECK |
| content | TEXT | | NULL in `metadata_only` mode, redacted in `redacted` mode |
| content_ref | VARCHAR(500) | | Object storage key when content exceeds 8KB |
| content_hash | VARCHAR(64) | | SHA-256 of the original, retained even when content is not |
| token_count | INTEGER | | |
| tool_calls | JSONB | | Structured tool calls emitted by the assistant |
| redaction_applied | BOOLEAN | NN | DEF false |
| purge_after | DATE | IDX | Set from `data_retention_schedules`. Content nulled after this date |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_msg_seq (gateway_request_id, sequence) UNIQUE` · `idx_msg_purge (purge_after) PARTIAL WHERE content IS NOT NULL`

---

### fallback_events
*Every time routing moved a request to a different model. Append-only.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| gateway_request_id | UUID | FK NN IDX | → gateway_requests.id |
| workspace_id | UUID | FK NN IDX | Denormalised |
| attempt_number | SMALLINT | NN | 1-indexed |
| from_model_id | UUID | FK NN | → models.id |
| to_model_id | UUID | FK | → models.id. NULL when the fallback chain was exhausted |
| trigger_error_class | VARCHAR(40) | NN IDX | Normalised error that caused it |
| provider_status_code | SMALLINT | | |
| circuit_breaker_open | BOOLEAN | NN | TRUE when the source model was skipped by an open breaker rather than tried. DEF false |
| latency_before_fallback_ms | INTEGER | | Time wasted on the failed attempt |
| created_at | TIMESTAMPTZ | NN IDX | IMMUTABLE |

**Indexes** `idx_fallback_models (from_model_id, to_model_id, created_at DESC)`

---

# 3. Cost & Quotas

### pricing_rates
*Effective-dated model pricing. The reason historical cost reports stay correct.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| model_id | UUID | FK NN IDX | → models.id |
| input_per_million_usd | NUMERIC(12,6) | NN | |
| output_per_million_usd | NUMERIC(12,6) | NN | |
| cached_input_per_million_usd | NUMERIC(12,6) | | Prompt-cache rate. NULL = same as input |
| currency | CHAR(3) | NN | DEF `USD` |
| effective_from | TIMESTAMPTZ | NN IDX | |
| effective_to | TIMESTAMPTZ | | NULL = currently in force |
| source | VARCHAR(50) | NN | `provider_published` \| `negotiated` \| `estimated` |
| notes | TEXT | | |
| created_by | UUID | FK | → users.id |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `idx_rate_lookup (model_id, effective_from DESC)` · EXCLUDE constraint preventing overlapping `[effective_from, effective_to)` ranges per model — overlapping rates make cost ambiguous and the database should refuse them.

---

### cost_entries
*One row per billable operation. Append-only.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | → workspaces.id |
| gateway_request_id | UUID | FK IDX | → gateway_requests.id |
| user_id | UUID | FK IDX | → users.id |
| api_key_id | UUID | FK IDX | → api_keys.id |
| agent_run_id | UUID | FK IDX | → agent_runs.id |
| eval_run_id | UUID | FK IDX | → eval_runs.id |
| ingestion_job_id | UUID | FK IDX | → ingestion_jobs.id. Populated for embedding cost |
| model_id | UUID | FK NN IDX | → models.id |
| pricing_rate_id | UUID | FK NN | → pricing_rates.id. The exact rate applied |
| operation | VARCHAR(20) | NN IDX | `completion` \| `embedding` \| `rerank` \| `judge`. Keeps ingestion cost separable from query cost |
| input_tokens | INTEGER | NN | DEF 0 |
| output_tokens | INTEGER | NN | DEF 0 |
| cached_tokens | INTEGER | NN | DEF 0 |
| cost_usd | NUMERIC(14,8) | NN | Computed at write time, never recomputed |
| accounting_period | CHAR(7) | NN IDX | `YYYY-MM`. Monthly aggregation key |
| created_at | TIMESTAMPTZ | NN IDX | IMMUTABLE |

**Indexes** `idx_cost_ws_period (workspace_id, accounting_period, operation)` · `idx_cost_model_time (model_id, created_at DESC)`

---

### budgets
*Spend ceilings per workspace per period.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | → workspaces.id |
| period_type | VARCHAR(10) | NN | `monthly` \| `daily` ✓ CHECK |
| amount_usd | NUMERIC(12,2) | NN | |
| soft_threshold_pct | SMALLINT | NN | Warning point. DEF 80 |
| hard_stop | BOOLEAN | NN | TRUE rejects requests at 100%; FALSE only alerts. DEF true |
| alert_channel_ids | UUID[] | | → alert_rules.id for notification routing |
| effective_from | DATE | NN | |
| effective_to | DATE | | |
| is_active | BOOLEAN | NN | DEF true |
| created_at | TIMESTAMPTZ | NN | |
| updated_at | TIMESTAMPTZ | NN | |

---

### quota_windows
*Usage counters per workspace per window. Survives a Redis flush.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | → workspaces.id |
| window_type | VARCHAR(10) | NN | `minute` \| `hour` \| `day` \| `month` |
| window_start | TIMESTAMPTZ | NN IDX | |
| request_count | INTEGER | NN | DEF 0 |
| input_tokens | BIGINT | NN | DEF 0 |
| output_tokens | BIGINT | NN | DEF 0 |
| cost_usd | NUMERIC(14,6) | NN | DEF 0 |
| rejected_rate_limit | INTEGER | NN | DEF 0 |
| rejected_budget | INTEGER | NN | DEF 0 |
| updated_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_quota_window (workspace_id, window_type, window_start) UNIQUE`

---

### rate_limit_buckets
*Configured limits. Live counters are in Redis; this table is the configuration and the console's view of it.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | → workspaces.id |
| api_key_id | UUID | FK IDX | → api_keys.id. NULL = workspace-wide limit |
| scope | VARCHAR(20) | NN | `workspace` \| `api_key` \| `user` |
| requests_per_minute | INTEGER | | NULL = unlimited |
| tokens_per_minute | INTEGER | | |
| concurrent_requests | SMALLINT | | |
| is_active | BOOLEAN | NN | DEF true |
| created_at | TIMESTAMPTZ | NN | |
| updated_at | TIMESTAMPTZ | NN | |

---

# 4. Knowledge Hub

### collections
*A governed set of documents with one embedding configuration.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | → workspaces.id |
| slug | VARCHAR(80) | NN | |
| name | VARCHAR(200) | NN | |
| description | TEXT | | |
| embedding_model_id | UUID | FK NN | → models.id. Must be an embedding model |
| embedding_version | SMALLINT | NN | Incremented on re-embed. `chunk_embeddings` filters on it. DEF 1 |
| active_embedding_version | SMALLINT | NN | Flipped atomically after a re-embed completes. Zero-downtime migration hinges on these being separate |
| chunking_strategy | VARCHAR(20) | NN | `recursive` \| `semantic` \| `structural` ✓ CHECK |
| chunk_size_tokens | SMALLINT | NN | DEF 800 |
| chunk_overlap_tokens | SMALLINT | NN | DEF 120 |
| rerank_enabled | BOOLEAN | NN | Cross-encoder rerank. Costs latency, so it is a decision. DEF false |
| default_sensitivity | VARCHAR(20) | NN | Applied to documents that do not set their own. DEF `internal` |
| freshness_window_days | SMALLINT | | NULL = documents never go stale |
| exclude_stale | BOOLEAN | NN | Remove stale documents from retrieval entirely. DEF false |
| document_count | INTEGER | NN | Denormalised. DEF 0 |
| chunk_count | INTEGER | NN | Denormalised. DEF 0 |
| last_indexed_at | TIMESTAMPTZ | | |
| deleted_at | TIMESTAMPTZ | | |
| created_at | TIMESTAMPTZ | NN | |
| updated_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_collection_slug (workspace_id, slug) UNIQUE`

---

### collection_grants
*Who may read or manage a collection. Retrieval joins against this table — it is a hot path, not an afterthought.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| collection_id | UUID | FK NN IDX | → collections.id ON DELETE CASCADE |
| workspace_id | UUID | FK NN IDX | Denormalised for the retrieval predicate |
| grantee_type | VARCHAR(10) | NN | `role` \| `user` ✓ CHECK |
| role_id | UUID | FK | → roles.id |
| user_id | UUID | FK | → users.id |
| access_level | VARCHAR(10) | NN | `read` \| `manage` ✓ CHECK |
| granted_by | UUID | FK NN | → users.id. Every grant change is audited |
| expires_at | TIMESTAMPTZ | | |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `idx_grant_lookup (collection_id, grantee_type, role_id, user_id)` · `idx_grant_user (user_id, collection_id)` — the index the retrieval predicate uses

---

### documents
*A logical document. Content lives in `document_versions`.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| collection_id | UUID | FK NN IDX | → collections.id ON DELETE CASCADE |
| workspace_id | UUID | FK NN IDX | Denormalised |
| title | VARCHAR(500) | NN | |
| source_type | VARCHAR(20) | NN | `upload` \| `url` \| `connector` |
| source_uri | VARCHAR(1000) | | Original location, for re-fetch and freshness checks |
| sensitivity | VARCHAR(20) | NN | `public` \| `internal` \| `confidential` \| `restricted`. Matched against `users.clearance` |
| current_version_id | UUID | FK | → document_versions.id |
| author | VARCHAR(200) | | |
| document_date | DATE | | Business date of the content, distinct from upload date. Freshness uses this |
| metadata | JSONB | | Arbitrary filterable attributes: department, doc_type, product |
| is_stale | BOOLEAN | NN | Set by the freshness job. DEF false |
| stale_reason | VARCHAR(50) | | `source_changed` \| `past_freshness_window` |
| deleted_at | TIMESTAMPTZ | | |
| created_at | TIMESTAMPTZ | NN | |
| updated_at | TIMESTAMPTZ | NN | |

**Indexes** `idx_docs_collection (collection_id, deleted_at)` · `idx_docs_metadata (metadata) USING GIN` · `idx_docs_stale (is_stale) PARTIAL WHERE is_stale`

---

### document_versions
*Immutable content revisions. A re-upload versions rather than overwrites.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| document_id | UUID | FK NN IDX | → documents.id ON DELETE CASCADE |
| version_number | SMALLINT | NN | 1-indexed |
| storage_key | VARCHAR(500) | NN | Object storage key. Never a public URL; signed URLs generated on demand |
| content_hash | VARCHAR(64) | NN IDX | SHA-256. Deduplication and change detection |
| mime_type | VARCHAR(100) | NN | |
| size_bytes | BIGINT | NN | |
| page_count | SMALLINT | | |
| extracted_text_key | VARCHAR(500) | | Parsed plain text, cached to avoid reparsing on re-chunk |
| uploaded_by | UUID | FK NN | → users.id |
| is_current | BOOLEAN | NN | DEF true |
| created_at | TIMESTAMPTZ | NN | IMMUTABLE |

**Indexes** `uq_docver (document_id, version_number) UNIQUE` · `idx_docver_hash (content_hash)`

---

### chunks
*Retrievable units with full provenance. Provenance quality is citation quality.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| document_version_id | UUID | FK NN IDX | → document_versions.id ON DELETE CASCADE |
| document_id | UUID | FK NN IDX | Denormalised |
| collection_id | UUID | FK NN IDX | Denormalised — retrieval filters on it before any join |
| workspace_id | UUID | FK NN IDX | Denormalised |
| sequence | INTEGER | NN | Order within the document |
| content | TEXT | NN | Raw chunk text, displayed in citations |
| embedded_text | TEXT | NN | Content prefixed with title and heading path. This is what was embedded, and it differs from `content` deliberately |
| token_count | SMALLINT | NN | |
| page_number | SMALLINT | | |
| section_path | TEXT[] | | Heading hierarchy, e.g. `{Policies, Leave, Approval}` |
| char_start | INTEGER | | Offset in the source text, for highlighting |
| char_end | INTEGER | | |
| chunking_strategy | VARCHAR(20) | NN | The strategy that produced this chunk |
| content_tsv | TSVECTOR | IDX | Generated column for full-text search |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_chunk_seq (document_version_id, sequence) UNIQUE` · `idx_chunk_fts (content_tsv) USING GIN` · `idx_chunk_trgm (content gin_trgm_ops) USING GIN` · `idx_chunk_collection (collection_id, document_id)`

---

### chunk_embeddings
*Vectors, versioned by model so an embedding migration is possible.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| chunk_id | UUID | FK NN IDX | → chunks.id ON DELETE CASCADE |
| collection_id | UUID | FK NN IDX | Denormalised — the vector query filters on it first |
| embedding_model_id | UUID | FK NN | → models.id |
| embedding_version | SMALLINT | NN IDX | Matched against `collections.active_embedding_version` at query time |
| embedding | VECTOR(1536) | NN | Normalised on write; cosine distance at query time |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_chunk_emb (chunk_id, embedding_version) UNIQUE` · `idx_emb_hnsw (embedding vector_cosine_ops) USING hnsw WITH (m=16, ef_construction=64)` · `idx_emb_filter (collection_id, embedding_version)`

---

### ingestion_jobs
*One job per document version through the pipeline.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| document_version_id | UUID | FK NN IDX | → document_versions.id |
| collection_id | UUID | FK NN IDX | |
| workspace_id | UUID | FK NN IDX | |
| status | VARCHAR(20) | NN IDX | `queued` \| `parsing` \| `chunking` \| `embedding` \| `indexed` \| `failed` \| `cancelled` |
| stage_failed | VARCHAR(20) | | Which stage threw. Diagnosis starts here |
| error_message | TEXT | | |
| chunks_created | INTEGER | | |
| embeddings_created | INTEGER | | |
| tokens_embedded | INTEGER | | Feeds the embedding cost entry |
| attempt_count | SMALLINT | NN | Max 3 then parked as failed. DEF 0 |
| trace_id | VARCHAR(32) | | |
| queued_at | TIMESTAMPTZ | NN | |
| started_at | TIMESTAMPTZ | | |
| completed_at | TIMESTAMPTZ | | |
| duration_ms | INTEGER | | |

**Indexes** `idx_ingest_status (status, queued_at)` — worker polling query

---

### retrieval_queries
*Every retrieval, with its results and scores. The raw material for retrieval evaluation.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | |
| user_id | UUID | FK IDX | The principal whose permissions were applied — for an agent, the delegating user |
| agent_run_id | UUID | FK IDX | → agent_runs.id when retrieval was a tool call |
| gateway_request_id | UUID | FK IDX | → gateway_requests.id for the generation step |
| query_text | TEXT | NN | |
| collection_ids | UUID[] | NN | Collections searched |
| filters | JSONB | | Metadata filters applied |
| top_k | SMALLINT | NN | |
| rerank_applied | BOOLEAN | NN | DEF false |
| chunks_returned | SMALLINT | NN | |
| chunks_excluded_by_permission | SMALLINT | NN | A rising number here means permissions are misconfigured. DEF 0 |
| top_score | NUMERIC(6,4) | | Fused score of the best result. A low top score is the signal for a no-answer response |
| keyword_latency_ms | INTEGER | | |
| vector_latency_ms | INTEGER | | |
| rerank_latency_ms | INTEGER | | |
| total_latency_ms | INTEGER | | |
| feedback_rating | VARCHAR(20) | IDX | `helpful` \| `unhelpful` \| `incorrect`. NULL until a user responds |
| feedback_reason | TEXT | | |
| expected_answer | TEXT | | Supplied on `incorrect` feedback. Promotion source for eval datasets |
| promoted_to_eval_item_id | UUID | FK | → eval_items.id once promoted |
| created_at | TIMESTAMPTZ | NN IDX | |

**Indexes** `idx_rq_feedback (feedback_rating, created_at DESC) PARTIAL WHERE feedback_rating IS NOT NULL`

---

### retrieval_citations
*Which chunks were cited in which answer. Enables citation-validity scoring.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| retrieval_query_id | UUID | FK NN IDX | → retrieval_queries.id ON DELETE CASCADE |
| chunk_id | UUID | FK NN IDX | → chunks.id |
| document_id | UUID | FK NN | Denormalised — a chunk may be deleted while a citation record must survive |
| marker | SMALLINT | NN | The `[n]` the model emitted |
| rank_keyword | SMALLINT | | Rank in the BM25 leg. NULL = not returned by keyword search |
| rank_vector | SMALLINT | | Rank in the vector leg |
| fused_score | NUMERIC(6,4) | NN | RRF result |
| included_in_context | BOOLEAN | NN | FALSE when dropped by the context window budget |
| was_cited | BOOLEAN | NN | Whether the model actually referenced it. DEF false |
| citation_valid | BOOLEAN | | NULL until scored. FALSE = the model cited a chunk that does not support the claim |
| flagged_bad_by_user | BOOLEAN | NN | From KB-008 feedback. Distinguishes retrieval failure from generation failure. DEF false |
| created_at | TIMESTAMPTZ | NN | |

---

# 5. Agents & Workflows

### agent_definitions
*A named agent. Behaviour lives in versions.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | → workspaces.id |
| slug | VARCHAR(80) | NN | |
| name | VARCHAR(200) | NN | |
| description | TEXT | | |
| owner_user_id | UUID | FK NN | → users.id. Accountable person, surfaced in the approval queue |
| production_version_id | UUID | FK | → agent_versions.id |
| staging_version_id | UUID | FK | → agent_versions.id |
| is_active | BOOLEAN | NN | DEF true |
| deleted_at | TIMESTAMPTZ | | |
| created_at | TIMESTAMPTZ | NN | |
| updated_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_agent_slug (workspace_id, slug) UNIQUE`

---

### agent_versions
*An immutable agent configuration. Deployable and rollback-able.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| agent_definition_id | UUID | FK NN IDX | → agent_definitions.id ON DELETE CASCADE |
| version_number | INTEGER | NN | |
| graph_definition | JSONB | NN | Nodes and edges. Node types: `llm`, `tool`, `condition`, `approval`, `parallel`, `end` |
| system_prompt_version_id | UUID | FK | → prompt_versions.id |
| model_id | UUID | FK | → models.id. Mutually exclusive with routing_policy_id |
| routing_policy_id | UUID | FK | → routing_policies.id |
| max_steps | SMALLINT | NN | DEF 25 |
| max_tool_calls | SMALLINT | NN | DEF 15 |
| max_cost_usd | NUMERIC(10,4) | NN | Hard stop. An agent without a cost cap is an open invoice. DEF 1.0000 |
| timeout_seconds | SMALLINT | NN | DEF 300 |
| changelog | TEXT | | |
| validation_status | VARCHAR(20) | NN | `valid` \| `invalid`. Set on save; invalid versions cannot be promoted |
| validation_errors | JSONB | | Per-node errors for inline display |
| created_by | UUID | FK NN | → users.id |
| created_at | TIMESTAMPTZ | NN | IMMUTABLE |

**Indexes** `uq_agentver (agent_definition_id, version_number) UNIQUE`

---

### tools
*The registry of what agents can do.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK IDX | NULL = built-in tool available to all workspaces |
| slug | VARCHAR(80) | NN | `knowledge_search` \| `sql_query` \| `http_request` \| `create_ticket` \| `send_notification` |
| name | VARCHAR(200) | NN | |
| description | TEXT | NN | Shown to the model. Its quality directly affects tool-selection accuracy |
| args_schema | JSONB | NN | JSON Schema. Arguments validated before the handler runs |
| handler_ref | VARCHAR(200) | NN | Import path |
| side_effect_class | VARCHAR(20) | NN IDX | `read` \| `write` \| `external` \| `destructive` ✓ CHECK. Drives default approval requirements |
| requires_approval_default | BOOLEAN | NN | Overridable per grant. DEF true for write and destructive |
| runs_as_principal | BOOLEAN | NN | TRUE = executes with the delegating user's permissions. Must be TRUE for any data-access tool. DEF true |
| domain_allowlist | TEXT[] | | For `http_request`. Empty array = no external access |
| timeout_seconds | SMALLINT | NN | DEF 30 |
| is_active | BOOLEAN | NN | DEF true |
| created_at | TIMESTAMPTZ | NN | |
| updated_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_tool_slug (workspace_id, slug) UNIQUE NULLS NOT DISTINCT`

---

### agent_tool_grants
*Default deny. An agent with no grants has no tools.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| agent_version_id | UUID | FK NN IDX | → agent_versions.id ON DELETE CASCADE |
| tool_id | UUID | FK NN IDX | → tools.id |
| workspace_id | UUID | FK NN | Denormalised |
| max_calls_per_run | SMALLINT | | NULL = the agent-level tool-call limit applies |
| requires_approval | BOOLEAN | NN | Overrides the tool default for this agent |
| argument_constraints | JSONB | | e.g. `{"schema":{"enum":["analytics_read"]}}` — restricts values, not just presence |
| granted_by | UUID | FK NN | → users.id. Every grant writes to audit_log |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_grant (agent_version_id, tool_id) UNIQUE`

---

### agent_runs
*One invocation of an agent version.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | |
| agent_definition_id | UUID | FK NN IDX | → agent_definitions.id |
| agent_version_id | UUID | FK NN | → agent_versions.id. Pinned, so history survives a version change |
| thread_id | UUID | NN IDX | LangGraph checkpoint thread. Groups resumed runs |
| parent_run_id | UUID | FK | → agent_runs.id when an agent spawned a sub-agent |
| delegating_user_id | UUID | FK NN IDX | → users.id. Whose permissions tools execute with — the security-critical field on this table |
| triggered_by | VARCHAR(20) | NN | `user` \| `schedule` \| `webhook` \| `agent` \| `evaluation` |
| trigger_ref | VARCHAR(255) | | |
| input | JSONB | NN | |
| output | JSONB | | |
| status | VARCHAR(20) | NN IDX | `running` \| `awaiting_approval` \| `completed` \| `failed` \| `cancelled` \| `limit_exceeded` \| `timeout` |
| termination_reason | VARCHAR(50) | | `max_steps` \| `max_cost` \| `max_tool_calls` \| `timeout` \| `rejected` \| `error` |
| step_count | SMALLINT | NN | DEF 0 |
| tool_call_count | SMALLINT | NN | DEF 0 |
| input_tokens | INTEGER | NN | DEF 0 |
| output_tokens | INTEGER | NN | DEF 0 |
| cost_usd | NUMERIC(12,6) | NN | DEF 0. Checked against the version's cap after every step |
| trace_id | VARCHAR(32) | IDX | |
| error_message | TEXT | | |
| started_at | TIMESTAMPTZ | NN IDX | |
| completed_at | TIMESTAMPTZ | | |
| duration_ms | INTEGER | | |

**Indexes** `idx_run_agent_time (agent_definition_id, started_at DESC)` · `idx_run_status (status) PARTIAL WHERE status IN ('running','awaiting_approval')`

---

### agent_steps
*Every node execution. Append-only. This is the evidence that the platform is governable.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| agent_run_id | UUID | FK NN IDX | → agent_runs.id ON DELETE CASCADE |
| workspace_id | UUID | FK NN | Denormalised |
| step_number | SMALLINT | NN | 1-indexed |
| node_name | VARCHAR(100) | NN | Node in the graph definition |
| step_type | VARCHAR(20) | NN IDX | `thought` \| `tool_call` \| `tool_result` \| `approval` \| `output` \| `error` ✓ CHECK |
| tool_id | UUID | FK | → tools.id |
| tool_arguments | JSONB | | Post-validation arguments. Sensitive values redacted per GOV-001 |
| tool_result | JSONB | | Truncated above 32KB with a reference to full storage |
| tool_error | TEXT | | |
| thought_text | TEXT | | Model reasoning |
| gateway_request_id | UUID | FK | → gateway_requests.id for the LLM call behind this step |
| approval_request_id | UUID | FK | → approval_requests.id |
| input_tokens | INTEGER | | |
| output_tokens | INTEGER | | |
| cost_usd | NUMERIC(12,6) | | |
| duration_ms | INTEGER | | |
| created_at | TIMESTAMPTZ | NN | IMMUTABLE |

**Indexes** `uq_step (agent_run_id, step_number) UNIQUE`

---

### approval_requests
*A paused run waiting on a person.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| agent_run_id | UUID | FK NN IDX | → agent_runs.id |
| workspace_id | UUID | FK NN IDX | |
| step_number | SMALLINT | NN | The step that triggered the pause |
| checkpoint_id | VARCHAR(200) | NN | LangGraph checkpoint to resume from |
| requested_action | VARCHAR(200) | NN | Human-readable summary, e.g. "Create ticket in OPS project" |
| tool_id | UUID | FK | → tools.id |
| proposed_arguments | JSONB | NN | What the agent wants to do |
| agent_reasoning | TEXT | NN | Why. A reviewer cannot approve what they cannot evaluate |
| trigger_reason | VARCHAR(50) | NN | `approval_node` \| `side_effect_class` \| `grant_requires` \| `policy_requires` |
| status | VARCHAR(20) | NN IDX | `pending` \| `approved` \| `rejected` \| `modified_approved` \| `timed_out` |
| decided_by | UUID | FK | → users.id |
| decided_at | TIMESTAMPTZ | | |
| decision_note | TEXT | | |
| modified_arguments | JSONB | | Reviewer-edited arguments when status = `modified_approved` |
| expires_at | TIMESTAMPTZ | NN IDX | Auto-reject deadline. DEF now() + 24h |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `idx_approval_pending (workspace_id, status, expires_at) PARTIAL WHERE status = 'pending'`

---

# 6. Evaluation

### prompt_templates
*A named prompt. Content lives in versions.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | |
| slug | VARCHAR(80) | NN | |
| name | VARCHAR(200) | NN | |
| description | TEXT | | |
| production_version_id | UUID | FK | → prompt_versions.id. Label pointer; rollback is a pointer move |
| staging_version_id | UUID | FK | → prompt_versions.id |
| owner_user_id | UUID | FK NN | → users.id |
| deleted_at | TIMESTAMPTZ | | |
| created_at | TIMESTAMPTZ | NN | |
| updated_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_prompt_slug (workspace_id, slug) UNIQUE`

---

### prompt_versions
*Immutable prompt revisions.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| prompt_template_id | UUID | FK NN IDX | → prompt_templates.id ON DELETE CASCADE |
| version_number | INTEGER | NN | |
| content | TEXT | NN | With `{{variable}}` placeholders |
| variables_schema | JSONB | NN | JSON Schema. Rendering fails loudly on a missing variable rather than emitting the placeholder |
| default_model_id | UUID | FK | → models.id |
| default_temperature | NUMERIC(3,2) | | |
| default_max_tokens | INTEGER | | |
| changelog | TEXT | | |
| created_by | UUID | FK NN | → users.id |
| created_at | TIMESTAMPTZ | NN | IMMUTABLE |

**Indexes** `uq_promptver (prompt_template_id, version_number) UNIQUE`

---

### eval_datasets
*A versioned test set. Immutable once referenced by a run.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | |
| slug | VARCHAR(80) | NN | |
| name | VARCHAR(200) | NN | |
| description | TEXT | | |
| version | INTEGER | NN | New version on any edit after first use. Historical scores must stay comparable |
| target_type | VARCHAR(20) | NN | `prompt` \| `rag` \| `agent` \| `routing` |
| item_count | INTEGER | NN | DEF 0 |
| is_locked | BOOLEAN | NN | TRUE once an eval run references it. DEF false |
| created_by | UUID | FK NN | → users.id |
| created_at | TIMESTAMPTZ | NN | |
| updated_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_dataset (workspace_id, slug, version) UNIQUE`

---

### eval_items
*One test case.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| eval_dataset_id | UUID | FK NN IDX | → eval_datasets.id ON DELETE CASCADE |
| workspace_id | UUID | FK NN | |
| external_ref | VARCHAR(100) | | Stable ID from import, for cross-version comparison |
| input | JSONB | NN | Variables or question |
| expected_output | TEXT | | |
| expected_behaviour | VARCHAR(50) | | `answer` \| `no_answer` \| `escalate` \| `refuse`. Lets a no-answer be a correct result |
| expected_chunk_ids | UUID[] | | Ground truth for retrieval metrics |
| expected_model_slug | VARCHAR(100) | | Ground truth for routing evaluation |
| split | VARCHAR(10) | NN | `train` \| `dev` \| `test`. Reporting on the set used for iteration hides overfitting. DEF `test` |
| tags | TEXT[] | | |
| difficulty | VARCHAR(10) | | `easy` \| `medium` \| `hard` |
| source | VARCHAR(20) | NN | `manual` \| `import` \| `production`. Production-sourced items are the valuable ones |
| source_query_id | UUID | FK | → retrieval_queries.id when promoted from feedback |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `idx_item_dataset (eval_dataset_id, split)`

---

### scorers
*A scoring function with its calibration record.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK IDX | NULL = built-in |
| slug | VARCHAR(80) | NN | `exact_match` \| `faithfulness` \| `precision_at_k` \| `citation_validity` |
| name | VARCHAR(200) | NN | |
| scorer_type | VARCHAR(20) | NN IDX | `deterministic` \| `retrieval` \| `llm_judge` ✓ CHECK |
| handler_ref | VARCHAR(200) | NN | |
| config | JSONB | | k for precision@k, thresholds, normalisation options |
| judge_model_id | UUID | FK | → models.id. Pinned — an unpinned judge makes historical scores incomparable |
| judge_prompt_version_id | UUID | FK | → prompt_versions.id. Also pinned |
| human_agreement_rate | NUMERIC(4,3) | | Agreement with hand labels. An uncalibrated judge is a random number with good manners |
| calibration_sample_size | SMALLINT | | |
| calibrated_at | TIMESTAMPTZ | | |
| passing_threshold | NUMERIC(4,3) | | Score at or above which `passed` is TRUE |
| version | INTEGER | NN | Pinned on runs. DEF 1 |
| is_active | BOOLEAN | NN | DEF true |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_scorer (workspace_id, slug, version) UNIQUE NULLS NOT DISTINCT`

---

### eval_runs
*One dataset executed against one configuration.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | |
| name | VARCHAR(200) | | |
| eval_dataset_id | UUID | FK NN IDX | → eval_datasets.id |
| dataset_version | INTEGER | NN | Pinned |
| split | VARCHAR(10) | NN | Which split was run |
| target_type | VARCHAR(20) | NN | `prompt` \| `rag` \| `agent` \| `routing` |
| prompt_version_id | UUID | FK | → prompt_versions.id |
| agent_version_id | UUID | FK | → agent_versions.id |
| collection_id | UUID | FK | → collections.id for RAG runs |
| model_id | UUID | FK | → models.id |
| retrieval_config | JSONB | | top_k, rerank, filters — pinned for reproducibility |
| scorer_ids | UUID[] | NN | |
| sample_size | SMALLINT | | NULL = full split |
| status | VARCHAR(20) | NN IDX | `queued` \| `running` \| `completed` \| `failed` \| `cancelled` |
| items_total | SMALLINT | NN | |
| items_completed | SMALLINT | NN | DEF 0 |
| items_failed | SMALLINT | NN | DEF 0 |
| aggregate_scores | JSONB | | Mean per scorer, pass rate, latency percentiles |
| total_cost_usd | NUMERIC(12,6) | NN | Visible live so an expensive sweep can be stopped. DEF 0 |
| mlflow_run_id | VARCHAR(64) | IDX | Links to the MLflow experiment |
| triggered_by | UUID | FK | → users.id |
| started_at | TIMESTAMPTZ | | |
| completed_at | TIMESTAMPTZ | | |
| created_at | TIMESTAMPTZ | NN IDX | |

**Indexes** `idx_evalrun_dataset (eval_dataset_id, created_at DESC)`

---

### eval_results
*Per-item, per-scorer outcome. Append-only.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| eval_run_id | UUID | FK NN IDX | → eval_runs.id ON DELETE CASCADE |
| eval_item_id | UUID | FK NN IDX | → eval_items.id |
| scorer_id | UUID | FK NN IDX | → scorers.id |
| scorer_version | INTEGER | NN | Pinned |
| score | NUMERIC(6,4) | | NULL when the scorer errored |
| passed | BOOLEAN | | |
| reason | TEXT | | Why this score. A bare number tells you nothing when it drops |
| actual_output | TEXT | | |
| retrieved_chunk_ids | UUID[] | | For retrieval metric recomputation without a re-run |
| gateway_request_id | UUID | FK | → gateway_requests.id |
| agent_run_id | UUID | FK | → agent_runs.id |
| trace_id | VARCHAR(32) | | A failing item opens straight into its trace |
| input_tokens | INTEGER | | |
| output_tokens | INTEGER | | |
| cost_usd | NUMERIC(12,6) | | |
| latency_ms | INTEGER | | |
| error_message | TEXT | | |
| created_at | TIMESTAMPTZ | NN | IMMUTABLE |

**Indexes** `uq_result (eval_run_id, eval_item_id, scorer_id) UNIQUE` · `idx_result_failures (eval_run_id, passed) PARTIAL WHERE passed = false`

---

# 7. Observability

### traces
*Trace headers, partitioned by month. Spans hold the detail.*

| Column | Type | Flags | Description |
|---|---|---|---|
| trace_id | VARCHAR(32) | PK | W3C trace ID |
| workspace_id | UUID | FK IDX | From OTel baggage |
| root_span_name | VARCHAR(200) | NN | |
| service_name | VARCHAR(100) | NN | `api` \| `worker` |
| status | VARCHAR(20) | NN IDX | `ok` \| `error` |
| duration_ms | INTEGER | NN IDX | |
| span_count | SMALLINT | NN | |
| gateway_request_id | UUID | FK IDX | Correlation anchor across gateway, cost, agent and trace |
| agent_run_id | UUID | FK IDX | |
| started_at | TIMESTAMPTZ | NN IDX | Partition key, monthly |
| ended_at | TIMESTAMPTZ | | |

**Indexes** `idx_trace_ws_time (workspace_id, started_at DESC)` · `idx_trace_slow (duration_ms DESC, started_at DESC)`

---

### spans
*Individual operations. High volume, partitioned by day, 30-day retention.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | BIGSERIAL | PK | Insertion order matters and volume is high |
| trace_id | VARCHAR(32) | NN IDX | → traces.trace_id |
| span_id | VARCHAR(16) | NN | |
| parent_span_id | VARCHAR(16) | IDX | NULL for the root |
| name | VARCHAR(200) | NN IDX | `gateway.route`, `gateway.provider_call`, `knowledge.retrieve`, `agent.step` |
| kind | VARCHAR(20) | NN | `server` \| `client` \| `internal` \| `producer` \| `consumer` |
| status | VARCHAR(20) | NN | `ok` \| `error` \| `unset` |
| status_message | TEXT | | |
| attributes | JSONB | | GenAI semantic conventions plus `nexus.*` namespace |
| gen_ai_system | VARCHAR(50) | IDX | Promoted from attributes for query performance |
| gen_ai_request_model | VARCHAR(100) | IDX | Promoted |
| gen_ai_input_tokens | INTEGER | | Promoted |
| gen_ai_output_tokens | INTEGER | | Promoted |
| duration_ms | INTEGER | NN IDX | |
| started_at | TIMESTAMPTZ | NN IDX | Partition key, daily |
| ended_at | TIMESTAMPTZ | NN | |

**Indexes** `idx_span_trace (trace_id, started_at)` · `idx_span_name_time (name, started_at DESC)`

---

### span_events
*Point-in-time events on a span: retries, fallbacks, breaker transitions.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | BIGSERIAL | PK | |
| trace_id | VARCHAR(32) | NN IDX | |
| span_id | VARCHAR(16) | NN IDX | |
| name | VARCHAR(100) | NN | `retry.attempted` \| `fallback.triggered` \| `circuit.opened` \| `approval.requested` |
| attributes | JSONB | | |
| occurred_at | TIMESTAMPTZ | NN IDX | |

---

### metric_rollups
*Pre-aggregated metrics. Every dashboard reads here, never from raw request tables.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | |
| grain | VARCHAR(10) | NN IDX | `hour` \| `day` ✓ CHECK |
| period_start | TIMESTAMPTZ | NN IDX | |
| dimension | VARCHAR(20) | NN | `workspace` \| `model` \| `user` \| `api_key` \| `agent` \| `collection` |
| dimension_id | UUID | IDX | NULL when dimension = `workspace` |
| request_count | INTEGER | NN | DEF 0 |
| success_count | INTEGER | NN | DEF 0 |
| error_count | INTEGER | NN | DEF 0 |
| errors_by_class | JSONB | | Counts keyed by normalised error class |
| input_tokens | BIGINT | NN | DEF 0 |
| output_tokens | BIGINT | NN | DEF 0 |
| cached_tokens | BIGINT | NN | DEF 0 |
| cost_usd | NUMERIC(14,6) | NN | DEF 0 |
| latency_digest | BYTEA | | Serialised t-digest. Merged across buckets to compute correct percentiles — averaging stored percentiles produces a plausible wrong number |
| latency_p50_ms | INTEGER | | Materialised for fast reads |
| latency_p95_ms | INTEGER | | |
| latency_p99_ms | INTEGER | | |
| fallback_count | INTEGER | NN | DEF 0 |
| retrieval_hit_rate | NUMERIC(5,4) | | Share of retrievals returning above the score threshold |
| tool_success_rate | NUMERIC(5,4) | | |
| approval_rate | NUMERIC(5,4) | | Share of approval requests approved |
| dimension_hash | VARCHAR(64) | NN | Idempotency key for re-runs |
| computed_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_rollup (workspace_id, grain, period_start, dimension, dimension_id) UNIQUE NULLS NOT DISTINCT` · `idx_rollup_query (workspace_id, grain, period_start DESC)`

---

### alert_rules
*Threshold rules and their notification routing.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | |
| name | VARCHAR(200) | NN | |
| metric | VARCHAR(50) | NN | `error_rate` \| `latency_p95` \| `cost_burn_pct` \| `circuit_open` \| `ingestion_failure_rate` \| `zero_result_rate` |
| dimension | VARCHAR(20) | | Scope the rule to a model, agent or collection |
| dimension_id | UUID | | |
| comparison | VARCHAR(5) | NN | `gt` \| `lt` \| `gte` \| `lte` ✓ CHECK |
| threshold | NUMERIC(12,4) | NN | |
| window_minutes | SMALLINT | NN | DEF 5 |
| consecutive_breaches | SMALLINT | NN | Suppresses single-datapoint noise. DEF 2 |
| channel_type | VARCHAR(20) | NN | `webhook` \| `email` \| `slack` |
| channel_config | JSONB | NN | URL or address. Secrets referenced, not stored |
| is_active | BOOLEAN | NN | DEF true |
| last_fired_at | TIMESTAMPTZ | | |
| last_resolved_at | TIMESTAMPTZ | | |
| current_state | VARCHAR(20) | NN | `ok` \| `breaching` \| `firing`. DEF `ok` |
| created_at | TIMESTAMPTZ | NN | |
| updated_at | TIMESTAMPTZ | NN | |

---

# 8. Governance & Audit

### audit_log
*Append-only, hash-chained, partitioned by month. The record the platform's argument rests on.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | BIGSERIAL | PK | Sequential — insertion order is part of the evidence |
| workspace_id | UUID | FK IDX | NULL for platform-level events |
| event_type | VARCHAR(50) | NN IDX | `record.mutation` \| `auth.login` \| `auth.failed` \| `apikey.created` \| `apikey.revoked` \| `permission.granted` \| `policy.changed` \| `approval.decided` \| `pii.revealed` \| `data.exported` |
| table_name | VARCHAR(100) | IDX | For record mutations |
| record_id | UUID | IDX | |
| operation | VARCHAR(10) | | `INSERT` \| `UPDATE` \| `DELETE` ✓ CHECK |
| changed_fields | TEXT[] | | UPDATE only |
| old_values | JSONB | | NULL on INSERT |
| new_values | JSONB | | NULL on DELETE |
| actor_type | VARCHAR(20) | NN | `user` \| `api_key` \| `agent` \| `system` |
| actor_id | UUID | IDX | |
| impersonated_by | UUID | FK | Set when an admin acted on a user's behalf |
| request_id | UUID | IDX | Correlates every mutation within one HTTP request |
| trace_id | VARCHAR(32) | | |
| ip_address | INET | | |
| user_agent | TEXT | | |
| prev_hash | VARCHAR(64) | | SHA-256 of the previous row in this partition |
| row_hash | VARCHAR(64) | NN | SHA-256 over this row's content plus prev_hash. Breaks detectably if a row is altered |
| created_at | TIMESTAMPTZ | NN IDX | Partition key, monthly. IMMUTABLE |

**Indexes** `idx_audit_record (table_name, record_id, created_at DESC)` · `idx_audit_actor (actor_id, created_at DESC)` · `idx_audit_event (event_type, created_at DESC)`
**RLS** `USING (false) WITH CHECK (true)` — INSERT and SELECT permitted, UPDATE and DELETE rejected by the database rather than by convention.

---

### policies
*Governance rules evaluated at gateway, tool and retrieval boundaries.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | |
| name | VARCHAR(200) | NN | |
| policy_type | VARCHAR(20) | NN IDX | `model` \| `tool` \| `data` \| `content` ✓ CHECK |
| version | INTEGER | NN | |
| is_current | BOOLEAN | NN | |
| mode | VARCHAR(10) | NN | `monitor` \| `enforce` ✓ CHECK. Never deploy straight to enforce on live traffic. DEF `monitor` |
| priority | SMALLINT | NN | Lower evaluates first. DEF 100 |
| rules | JSONB | NN | Type-specific: allowed/blocked model IDs, blocked tool IDs, collection-to-provider constraints, content patterns |
| applies_to | JSONB | | Scope: all, specific API keys, specific users, specific agents |
| deny_message | VARCHAR(300) | NN | Returned to the caller. Must name the policy — an unattributable denial is undebuggable |
| created_by | UUID | FK NN | → users.id |
| deleted_at | TIMESTAMPTZ | | |
| created_at | TIMESTAMPTZ | NN | |

**Indexes** `uq_policy_ver (workspace_id, name, version) UNIQUE` · `idx_policy_eval (workspace_id, policy_type, is_current, priority) PARTIAL WHERE is_current`

---

### policy_violations
*Every denial, and every would-be denial in monitor mode. Append-only.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | |
| policy_id | UUID | FK NN IDX | → policies.id |
| policy_version | INTEGER | NN | |
| enforcement_point | VARCHAR(20) | NN | `gateway` \| `tool` \| `retrieval` |
| action_taken | VARCHAR(20) | NN IDX | `blocked` \| `would_block` \| `approval_required`. `would_block` is the monitor-mode record |
| matched_rule | VARCHAR(200) | NN | |
| actor_type | VARCHAR(20) | NN | |
| actor_id | UUID | IDX | |
| gateway_request_id | UUID | FK IDX | |
| agent_run_id | UUID | FK IDX | |
| requested_resource | VARCHAR(300) | | Model slug, tool slug or collection name |
| context | JSONB | | Enough to reconstruct the decision, without the payload itself |
| created_at | TIMESTAMPTZ | NN IDX | IMMUTABLE |

**Indexes** `idx_violation_policy (policy_id, created_at DESC)`

---

### pii_detections
*What was found and what was done. Never what it was. Append-only.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | |
| gateway_request_id | UUID | FK IDX | |
| gateway_message_id | UUID | FK IDX | |
| document_id | UUID | FK IDX | Detection during ingestion |
| entity_type | VARCHAR(40) | NN IDX | `national_id` \| `bank_account` \| `phone` \| `email` \| `person_name` \| `address` \| `credential` |
| char_start | INTEGER | NN | Offsets only. Storing the detected value would defeat the purpose |
| char_end | INTEGER | NN | |
| confidence | NUMERIC(4,3) | NN | |
| detector | VARCHAR(50) | NN | `presidio` \| `regex` \| `custom_rule` |
| redaction_rule_id | UUID | FK | → redaction_rules.id when a custom rule matched |
| action_taken | VARCHAR(20) | NN | `redacted_pre_provider` \| `redacted_pre_storage` \| `flagged_only` \| `allowlisted` |
| vault_token | VARCHAR(64) | | Reference for reversible redaction. Resolvable only with `governance.pii.reveal` |
| created_at | TIMESTAMPTZ | NN IDX | IMMUTABLE |

**Indexes** `idx_pii_type_time (workspace_id, entity_type, created_at DESC)`

---

### redaction_rules
*Custom patterns and false-positive allow-lists.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| workspace_id | UUID | FK NN IDX | |
| name | VARCHAR(200) | NN | |
| rule_type | VARCHAR(20) | NN | `detect` \| `allowlist` ✓ CHECK. Allowlist stops a product code being flagged as an ID number |
| entity_type | VARCHAR(40) | NN | |
| pattern | TEXT | NN | Regex, validated and length-bounded at save to prevent catastrophic backtracking |
| replacement | VARCHAR(100) | | e.g. `[REDACTED_ID]`. DEF `[REDACTED]` |
| reversible | BOOLEAN | NN | Store a vault token for authorised reveal. DEF false |
| is_active | BOOLEAN | NN | DEF true |
| created_by | UUID | FK NN | → users.id |
| created_at | TIMESTAMPTZ | NN | |
| updated_at | TIMESTAMPTZ | NN | |

---

### feature_flags
*Runtime toggles with targeting.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| key | VARCHAR(100) | UQ NN | `HYBRID_RERANK_ENABLED` \| `AGENT_STUDIO_ENABLED` \| `PII_PRE_PROVIDER_REDACTION` \| `EVAL_JUDGE_SCORERS` |
| enabled | BOOLEAN | NN | Global state. DEF false |
| rollout_percentage | SMALLINT | | 0–100. NULL = all or none |
| workspace_ids | UUID[] | | Restrict to specific workspaces. NULL = all |
| user_ids | UUID[] | | Internal testing |
| description | TEXT | NN | What this controls and what to expect when it flips |
| updated_by | UUID | FK | → users.id |
| created_at | TIMESTAMPTZ | NN | |
| updated_at | TIMESTAMPTZ | NN | |

---

### data_retention_schedules
*Retention policy and legal basis, per table.*

| Column | Type | Flags | Description |
|---|---|---|---|
| id | UUID | PK | |
| table_name | VARCHAR(100) | UQ NN | |
| workspace_id | UUID | FK IDX | NULL = platform default; a row with a workspace overrides it |
| retention_days | INTEGER | NN | |
| strategy | VARCHAR(30) | NN | `delete_row` \| `null_columns` \| `hash_identifiers` \| `aggregate_only` ✓ CHECK |
| target_columns | TEXT[] | | Columns cleared under `null_columns` |
| legal_basis | VARCHAR(100) | NN | e.g. `contract_performance`, `legitimate_interest`, `regulatory_7yr` |
| last_run_at | TIMESTAMPTZ | | |
| next_run_at | TIMESTAMPTZ | IDX | |
| rows_affected_last_run | INTEGER | | |
| approved_by | UUID | FK | → users.id |
| updated_at | TIMESTAMPTZ | NN | |

---

## Alembic migration order

Later migrations reference foreign keys from earlier ones. Run in strict order.

| # | Name | Tables / objects | Task |
|---|---|---|---|
| 000 | Extensions | `vector`, `pgcrypto`, `pg_trgm` | INFRA-001 |
| 001 | Identity & access | users, workspaces, workspace_memberships, roles, role_assignments, api_keys, user_sessions | INFRA-002 |
| 002 | Gateway & routing | providers, models, model_deployments, routing_policies, routing_rules, gateway_requests, gateway_messages, fallback_events | INFRA-002 |
| 003 | Cost & quotas | pricing_rates, cost_entries, budgets, quota_windows, rate_limit_buckets | INFRA-002 |
| 004 | Knowledge Hub | collections, collection_grants, documents, document_versions, chunks, chunk_embeddings, ingestion_jobs, retrieval_queries, retrieval_citations | INFRA-003 |
| 005 | Agents | agent_definitions, agent_versions, tools, agent_tool_grants, agent_runs, agent_steps, approval_requests | INFRA-003 |
| 006 | Evaluation | prompt_templates, prompt_versions, eval_datasets, eval_items, scorers, eval_runs, eval_results | INFRA-003 |
| 007 | Observability | traces, spans, span_events, metric_rollups, alert_rules | INFRA-003 |
| 008 | Governance | audit_log, policies, policy_violations, pii_detections, redaction_rules, feature_flags, data_retention_schedules | INFRA-003 |
| 009 | Triggers | `set_updated_at()` on all tables with the column; `log_audit()` on users, api_keys, routing_policies, policies, agent_tool_grants, collection_grants, role_assignments | INFRA-003 |
| 010 | Immutability & partitioning | RLS on the seven append-only tables; range partitions on audit_log and traces (monthly), spans and gateway_requests (daily); partition-creation function | INFRA-003 |

---

## Key relationships at a glance

| From | Card. | To | Business rule |
|---|---|---|---|
| workspaces | 1:N | everything | The tenancy boundary. Every business row carries `workspace_id`. |
| users | N:M | workspaces | Via workspace_memberships. A user may belong to several. |
| routing_policies | 1:N | routing_rules | Ordered, first match wins. |
| gateway_requests | 1:N | gateway_messages | One row per message, subject to logging mode. |
| gateway_requests | 1:N | fallback_events | One row per model switch. Usually zero. |
| gateway_requests | 1:1 | cost_entries | Exactly one cost entry per completed request. |
| models | 1:N | pricing_rates | Effective-dated, non-overlapping. |
| collections | 1:N | documents | A document belongs to exactly one collection. |
| documents | 1:N | document_versions | Re-upload versions rather than overwrites. |
| document_versions | 1:N | chunks | Re-chunking replaces the set transactionally. |
| chunks | 1:N | chunk_embeddings | One per embedding version, enabling zero-downtime model migration. |
| collections | 1:N | collection_grants | Retrieval joins here. Default deny. |
| retrieval_queries | 1:N | retrieval_citations | Every retrieved chunk, cited or not. |
| agent_definitions | 1:N | agent_versions | Labels point at versions; rollback is a pointer move. |
| agent_versions | 1:N | agent_tool_grants | Default deny. No grant, no tool. |
| agent_runs | 1:N | agent_steps | Full execution trace, append-only. |
| agent_runs | 1:N | approval_requests | One per pause. |
| agent_runs | N:1 | users (delegating) | Tools execute as this principal, never as a service account. |
| prompt_templates | 1:N | prompt_versions | Immutable revisions. |
| eval_datasets | 1:N | eval_items | Locked once referenced by a run. |
| eval_runs | 1:N | eval_results | One row per item per scorer. |
| traces | 1:N | spans | Spans partitioned by day, 30-day retention; rollups kept indefinitely. |
| gateway_requests | 1:1 | traces | Joined on `trace_id`. One request ID resolves request, cost, trace and agent run. |
