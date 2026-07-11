# Paperboy

Paperboy is a FastAPI service that generates personalized research digests. It fetches recent arXiv papers (and optionally industry news), ranks and analyzes content with OpenAI models, and produces an HTML digest.

## Quick start (Docker)

### Prerequisites

- Docker + Docker Compose
- OpenAI API key
- Supabase project (URL + anon key)

### Configure

```bash
cp config/.env.example config/.env
```

Set at least:

```env
OPENAI_API_KEY=...
API_KEY=...
SUPABASE_URL=...
SUPABASE_KEY=...
```

Notes:
- News fetching is enabled by default. If you want news, set `NEWSAPI_KEY` (and optionally `TAVILY_API_KEY` for richer extraction). Otherwise set `NEWS_ENABLED=false`.

### Run

```bash
docker-compose up --build
```

Then open:
- API docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`

## Quick start (local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.lightweight.txt
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

## Configuration

Configuration is loaded from `config/.env` (see `config/.env.example`).

### Required

- `OPENAI_API_KEY`: OpenAI API key (required when `LLM_PROVIDER` is unset/`openai`; not required when `LLM_PROVIDER=fireworks`, which uses `FIREWORKS_API_KEY` instead — see [LLM provider](#llm-provider-openai-or-fireworks))
- `API_KEY`: required for authenticated endpoints via `X-API-Key`
- `SUPABASE_URL`, `SUPABASE_KEY`: used for task state + caching (required by the current implementation)

### Common optional

- `OPENAI_MODEL` (default: `gpt-4o`)
- `NEWS_ENABLED` (default: `true`)
- `NEWSAPI_KEY` (required only if `NEWS_ENABLED=true` and you want news results)
- `TAVILY_API_KEY` (optional, improves news article extraction)
- `LOGFIRE_TOKEN` (optional)
- `SENTRY_DSN` (optional): enables backend error reporting to Sentry. Unset = disabled (no-op). No PII is sent — `send_default_pii=False` and user/request contexts are stripped before send. Requires `sentry-sdk` (declared in requirements); if absent the backend logs a warning and stays disabled.
- `SENTRY_ENVIRONMENT` (optional, default `production`): environment tag for Sentry events
- `ORCHESTRATION_ENABLED` (default: `false`): enables the backend-hosted daily scheduler that replaces n8n. It requires `SUPABASE_SERVICE_ROLE_KEY`, `RESEND_API_KEY`, and the schema in [`docs/supabase_orchestration.sql`](docs/supabase_orchestration.sql). See the [backend orchestration rollout guide](docs/backend-orchestration.md).

### LLM provider (OpenAI or Fireworks)

LLM workloads run through an OpenAI-compatible client and default to OpenAI.
To run on [Fireworks AI](https://fireworks.ai) instead, set:

- `LLM_PROVIDER`: `openai` (default) or `fireworks`
- `LLM_API_MODE` (optional): `responses` or `chat_completions`. Unset uses the
  provider default (`responses` for OpenAI, `chat_completions` for Fireworks).
- `FIREWORKS_API_KEY`: required when `LLM_PROVIDER=fireworks`
- `FIREWORKS_MODEL` (default: `accounts/fireworks/models/gpt-oss-120b`)
- `FIREWORKS_BASE_URL` (default: `https://api.fireworks.ai/inference/v1`)

OpenAI remains the fallback/default and its behavior is unchanged. See
[docs/fireworks-migration.md](docs/fireworks-migration.md) for safe rollout
guardrails and what to compare in evals.

## API

Backend orchestration adds protected `POST /admin/orchestration/run` and
`GET /admin/orchestration/status/{source_date}` operations. They use the same
`X-API-Key` authentication as other administrative endpoints and require
`ORCHESTRATION_ENABLED=true`. See
[`docs/backend-orchestration.md`](docs/backend-orchestration.md) for request
examples, recovery behavior, and the n8n cutover plan.


### Authentication

All endpoints except basic health/readiness checks require `X-API-Key`:

```bash
curl -H "X-API-Key: $API_KEY" "http://localhost:8000/health"
```

### Endpoints

| Endpoint | Method | Auth | Purpose |
| --- | --- | --- | --- |
| `/generate-digest` | POST | Yes | Create a digest (returns `task_id`) |
| `/digest-status/{task_id}` | GET | Yes | Poll digest status / result |
| `/fetch-sources` | POST | Yes | Pre-fetch daily sources for a date |
| `/fetch-status/{task_id}` | GET | Yes | Poll fetch status |
| `/preview-new-format/{task_id}` | GET | Yes | Render HTML for a completed task |
| `/metrics` | GET | Yes | Metrics + circuit breaker status |
| `/health` | GET | No | Basic health check |
| `/ready` | GET | No | Dependency readiness check |

## Deployment

- Docker: `paperboy/Dockerfile`, `paperboy/docker-compose.yaml`
- Cloud Run: `paperboy/deploy_cloudrun.sh`, `paperboy/cloudbuild.yaml`

## Further reading

- Architecture: `PROJECT_ARCH.md`
- Contributing: `CONTRIBUTING.md`
- AI assistant notes: `CLAUDE.md`
