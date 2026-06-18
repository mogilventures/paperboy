# Running Paperboy on Fireworks AI

Paperboy can run its LLM workloads (ranking, analysis, summarization, digest
generation) on [Fireworks AI](https://fireworks.ai) through Fireworks'
OpenAI-compatible API. OpenAI remains the default and fallback — switching is a
configuration change only, with no code edits required.

## How it works

`LLMClient` talks to both providers through the same `AsyncOpenAI` client. Only
four things differ per provider, all driven by config:

| Setting        | OpenAI                       | Fireworks                                              |
| -------------- | ---------------------------- | ------------------------------------------------------ |
| API key        | `OPENAI_API_KEY`             | `FIREWORKS_API_KEY`                                    |
| Base URL       | (default OpenAI)             | `FIREWORKS_BASE_URL` (`https://api.fireworks.ai/inference/v1`) |
| Model          | `OPENAI_MODEL`               | `FIREWORKS_MODEL` (e.g. `accounts/fireworks/models/llama-v3p1-70b-instruct`) |
| Default API mode | `responses`                | `chat_completions`                                     |

Fireworks does not implement OpenAI's Responses API, so the client defaults to
**chat completions** for Fireworks. You can force a surface with `LLM_API_MODE`
if a specific model needs it.

If `LLM_PROVIDER=fireworks` but `FIREWORKS_API_KEY` is unset, the client fails
fast at construction with a clear error rather than making a doomed call. API
keys are never logged — only provider, model, and API mode are emitted.

## Configuration

Add to `config/.env` (see `config/.env.example`):

```bash
LLM_PROVIDER=fireworks
FIREWORKS_API_KEY=fw-...                 # do not commit a real key
FIREWORKS_MODEL=accounts/fireworks/models/llama-v3p1-70b-instruct
FIREWORKS_BASE_URL=https://api.fireworks.ai/inference/v1
# LLM_API_MODE=chat_completions          # optional; this is the Fireworks default
```

To revert to OpenAI, set `LLM_PROVIDER=openai` (or remove the line). No other
change is needed.

A Fireworks-only deployment does **not** need `OPENAI_API_KEY` at all —
`OPENAI_API_KEY` is only required when `LLM_PROVIDER` is unset or `openai`.
Startup validation enforces the key for whichever provider is selected, so a
missing key fails fast with a clear error.

## Pre-start guardrails (safety)

Before pointing Paperboy at Fireworks for anything beyond a smoke test:

- **Public / synthetic data only.** Use arXiv abstracts, NewsAPI articles, and
  synthetic user profiles. Do not send private or customer data to a new
  provider while evaluating it.
- **Keep contexts separate.** This change is scoped to the Paperboy app. Do not
  reuse keys, models, or data from other projects.
- **Secrets stay out of git.** Provide `FIREWORKS_API_KEY` via environment /
  secret manager, never hardcoded or committed.
- **Verify the swap before trusting output.** Run the smoke harness:

  ```bash
  LLM_PROVIDER=fireworks FIREWORKS_API_KEY=... \
    python3 scripts/eval_provider_smoke.py
  ```

  It runs a tiny synthetic ranking task and skips cleanly (exit 0) when no key
  is present, so it is safe in CI.

## What to compare in evals (OpenAI vs Fireworks)

Run the same fixture inputs through both providers and compare:

1. **JSON validity** — share of ranking/analysis responses that parse and pass
   Pydantic validation on the first attempt (i.e. without hitting the manual
   fallback path). Chat-completions models are more likely to wrap JSON in code
   fences; the client strips fences, but track first-pass validity anyway.
2. **Ranking quality** — for a fixed synthetic article set + user profile, do
   the top-N selections and relevance scores look sensible and stable? Spot-check
   `score_reason` for relevance to the stated goals.
3. **Latency** — wall-clock per call (the smoke harness prints elapsed time).
   Compare p50/p95 over several runs.
4. **Cost** — per-1K-token pricing × tokens used per digest. Fireworks open
   models are typically cheaper; confirm against your actual digest sizes.
5. **Retry / error rate** — frequency of retries (the client retries 3x with
   exponential backoff) and terminal failures. A provider that needs frequent
   retries erodes any latency/cost advantage.

## Notes

- Structured output uses prompt-based JSON (schema embedded in the system
  prompt) plus Pydantic validation and a manual-parse fallback. This path is
  provider-agnostic and works for both Responses and Chat Completions.
- The retry/backoff, caching, and circuit-breaker behavior are unchanged by the
  provider swap.
