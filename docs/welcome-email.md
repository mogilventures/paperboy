# Signup welcome email (migrated off Pipedream)

## What this is

New-signup welcome emails used to be sent by an **external Pipedream workflow**,
triggered by a **Supabase database webhook** on `public.profiles` INSERT. This
moves that delivery onto the Fly-hosted backend using the existing Resend
integration, so Pipedream can be retired.

Flow after migration:

```
User signs up (Google OAuth)
  -> auth.users INSERT
  -> trigger on_auth_user_created -> handle_new_user() inserts public.profiles row
  -> trigger "Welcome Email" (DB webhook) -> POST https://paperboy-ai.fly.dev/hooks/welcome
  -> backend renders welcome HTML + sends via Resend (from: Welcome <hello@paper-boy.app>)
```

## Backend endpoint

`POST /hooks/welcome` (auth: `X-API-Key`)

- Body is the standard Supabase database-webhook payload; only `record.email`
  (and `record.user_id` for idempotency) are used.
- Responds immediately (`202`) and sends in the background — the DB webhook has
  a short (5s) timeout, so delivery must not block the response.
- Idempotency key `welcome:{user_id}` prevents duplicate sends on webhook
  retries / duplicate inserts (Resend dedupes within its idempotency window).
- Returns `{"status":"skipped"}` when the row has no email (acked, no retry).
- Returns `503` if `RESEND_API_KEY` is not configured.

Config:

| Variable | Default | Purpose |
| --- | --- | --- |
| `RESEND_API_KEY` | — | Required for the endpoint to send (already set in prod). |
| `WELCOME_FROM_ADDRESS` | `Welcome <hello@paper-boy.app>` | Verified Resend sender for the welcome email. |

The email content is static and byte-faithful to the prior Pipedream template
(`src/welcome_email.py`). `hello@paper-boy.app` is on the already-verified
`paper-boy.app` Resend domain (same domain as the digest sender).

## Cutover — repoint the Supabase trigger (run only after deploy + test)

The welcome trigger currently points at Pipedream:

```sql
-- current (Pipedream):
-- CREATE TRIGGER "Pipedream - Welcome Email" AFTER INSERT ON public.profiles
--   FOR EACH ROW EXECUTE FUNCTION supabase_functions.http_request(
--     'https://eoq61vpg5wtuih2.m.pipedream.net', 'POST',
--     '{"Content-type":"application/json"}', '{}', '5000');
```

Repoint it to the Fly endpoint (replace `<BACKEND_API_KEY>` with the backend
`API_KEY` secret — same key the other integrations use):

```sql
DROP TRIGGER IF EXISTS "Pipedream - Welcome Email" ON public.profiles;

CREATE TRIGGER "Welcome Email"
AFTER INSERT ON public.profiles
FOR EACH ROW EXECUTE FUNCTION supabase_functions.http_request(
  'https://paperboy-ai.fly.dev/hooks/welcome',
  'POST',
  '{"Content-type":"application/json","X-API-Key":"<BACKEND_API_KEY>"}',
  '{}',
  '5000'
);
```

Note: like the prior setup (and the old n8n nodes), the key lives inline in the
trigger definition. It is only readable with DB service-role access. If you want
a narrower blast radius, add a dedicated `WELCOME_WEBHOOK_SECRET` header + check
instead of reusing the powerful `API_KEY`.

## Verify

1. Deploy the backend, confirm `GET /health` is OK.
2. Smoke test the endpoint directly (safe: use a test address you control):
   ```bash
   curl -sS -X POST https://paperboy-ai.fly.dev/hooks/welcome \
     -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
     -d '{"type":"INSERT","table":"profiles","record":{"user_id":"test","email":"you@example.com"}}'
   ```
   Expect `202 {"status":"accepted"}` and the email in your inbox.
3. Apply the trigger repoint SQL above.
4. Create a real test signup (or insert a throwaway `profiles` row) and confirm
   the welcome arrives from `hello@paper-boy.app`.
5. Disable/delete the Pipedream workflow once satisfied.

## Rollback

Restore the Pipedream trigger:

```sql
DROP TRIGGER IF EXISTS "Welcome Email" ON public.profiles;

CREATE TRIGGER "Pipedream - Welcome Email"
AFTER INSERT ON public.profiles
FOR EACH ROW EXECUTE FUNCTION supabase_functions.http_request(
  'https://eoq61vpg5wtuih2.m.pipedream.net', 'POST',
  '{"Content-type":"application/json"}', '{}', '5000');
```

(Keep the Pipedream workflow enabled until the Fly path is proven.)
