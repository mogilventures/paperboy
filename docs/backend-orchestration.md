# Backend daily orchestration (n8n replacement)

## Goal and parity

The backend can replace the three production n8n workflows without a UI or a
second Fly.io Machine. The implementation preserves their operational contract:

1. At 13:00 UTC, fetch arXiv/news sources for yesterday.
2. Select profiles where `goals IS NOT NULL` and `remove IS NULL`.
3. Generate one mixed digest per profile using `name`, `title`, `goals`, and
   `interests` (forwarded as `news_interest`), with five papers and five news
   articles.
4. Update `profiles.task_id`, `started_at`, `task_html`, and `completed_at`.
5. Link `digest_tasks.user_id` when the task is created, then email the rendered
   HTML through Resend.

No frontend changes are required. Existing public `/fetch-sources` and
`/generate-digest` callback behavior remains available for other callers.

## Architecture

The coordinator is intentionally a small in-process module:

- `orchestration.py` owns sequencing, idempotent resume behavior, pacing, and
  per-profile failure isolation.
- `orchestration_adapters.py` invokes the existing fetch and digest services
  directly, avoiding HTTP calls back into the same process.
- `orchestration_repository.py` stores run claims and delivery checkpoints in
  Supabase using the service-role key.
- `orchestration_scheduler.py` checks the UTC schedule from the FastAPI lifespan.
- `resend_email.py` sends email with retries and a stable Resend idempotency key.
- `docs/supabase_orchestration.sql` defines the backend-owned state tables and
  atomic run-claim function.

The scheduler is disabled by default. Fly already keeps exactly one app Machine
warm, but the database claim also prevents duplicate work if the app is later
scaled horizontally.

## Durable state and recovery

`orchestration_runs` has one row per source date. The SQL function
`claim_orchestration_run` atomically allows:

- the first run for a date;
- takeover of a `running` row whose heartbeat is stale; or
- an explicit retry of a `failed`/`completed_with_errors` row.

`orchestration_deliveries` has one row per `(source_date, user_id)`, keeps an
immutable profile snapshot so retries reuse the same recipient/content inputs,
and moves through:

```text
pending -> generating -> generated -> sending -> sent
                         \-> failed      \-> ambiguous
```

A restart or explicit retry behaves as follows:

- `sent`: skip permanently;
- completed `task_id`: reuse its HTML and resume profile/email delivery;
- incomplete or missing task: create a new task;
- email retry within 23 hours: reuse both the task and
  `paperboy:{date}:{user_id}` Resend idempotency key;
- an ambiguous provider receipt older than 23 hours: do not resend
  automatically, because Resend's 24-hour key may have expired; expose it for
  operator reconciliation instead.

A single profile failure is recorded and the batch continues. Source fetch
failure stops the batch before any profile is processed. Run and delivery claim
IDs fence workers that wake after a stale-run takeover.

## Runtime controls

All administrative routes require the existing `X-API-Key` header:

```http
POST /admin/orchestration/run
Content-Type: application/json

{"source_date":"2026-07-09","retry_failed":false}
```

The request returns `202` immediately. The database claim determines whether it
actually runs. Use `retry_failed: true` only to retry a failed/partial date; sent
users remain skipped.

```http
GET /admin/orchestration/status/2026-07-09
```

## Configuration

Required before enabling:

- `SUPABASE_SERVICE_ROLE_KEY`: server-only access to protected profile rows;
- `RESEND_API_KEY`: Resend bearer token;
- existing `SUPABASE_URL`, `SUPABASE_KEY`, API, LLM, and news credentials.

Settings:

| Variable | Default | Purpose |
| --- | ---: | --- |
| `ORCHESTRATION_ENABLED` | `false` | Start the scheduler and enable admin operations |
| `ORCHESTRATION_HOUR_UTC` | `13` | Daily UTC start hour |
| `ORCHESTRATION_POLL_SECONDS` | `60` | Due-date check interval |
| `ORCHESTRATION_CATCHUP_HOURS` | `24` | Maximum automatic missed-slot catch-up age |
| `ORCHESTRATION_PROFILE_INTERVAL_SECONDS` | `60` | Spacing between profile launches |
| `ORCHESTRATION_MAX_CONCURRENT_PROFILES` | `2` | Bound overlapping digest generations |
| `ORCHESTRATION_STALE_AFTER_MINUTES` | `120` | Stale run takeover threshold |
| `RESEND_FROM_ADDRESS` | Paperboy digest address | Verified sender identity |

The service refuses to start with orchestration enabled but missing the
service-role or Resend secret.

## Rollout and rollback plan

No production action is part of the code PR. After review:

1. Apply `docs/supabase_orchestration.sql` in the shared Supabase project.
2. Install `SUPABASE_SERVICE_ROLE_KEY` and `RESEND_API_KEY` as Fly secrets.
3. Deploy with `ORCHESTRATION_ENABLED=false` and verify `/health`.
4. Use a non-customer test profile/date to exercise the protected manual route,
   temporarily directing delivery to an internal address if needed.
5. Before 13:00 UTC, disable n8n workflow `1_Fetch_Sources_Daily`, then enable
   backend orchestration at or just after 13:00 UTC. Do not enable it earlier:
   the 24-hour catch-up window would correctly claim the prior slot that n8n
   already handled. Alternatively seed that prior date as `completed` first.
   Never overlap the schedulers.
6. Monitor the run row, delivery counts, `digest_tasks.user_id`, profile HTML,
   and Resend delivery for one full batch.
7. Disable the remaining n8n webhook workflows after the successful batch,
   rotate the backend API key formerly stored there, then cancel n8n.

Rollback is to set `ORCHESTRATION_ENABLED=false` and reactivate the three n8n
workflows. Existing run/delivery rows are safe to retain and ensure a later retry
does not resend completed deliveries.

## Verification plan

Automated tests cover:

- successful fetch/generate/profile-link/email flow;
- atomic duplicate-run no-op behavior at the coordinator boundary;
- per-profile failure isolation;
- reuse of a completed task on retry;
- task creation with `user_id` before digest execution;
- cached-source task completion;
- UTC due-date calculation;
- Resend request shape, retry, idempotency reuse, and ambiguous receipts; and
- startup refusal when orchestration secrets are absent.

Before merging, run the focused tests and the complete `pytest` suite, import the
app in a fresh process, inspect the complete diff for secrets, and confirm PR CI.
