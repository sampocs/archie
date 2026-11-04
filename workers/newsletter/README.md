# Archie newsletter Email Worker

Receives every email sent to the Archie domain, keeps the raw message in KV (`INBOX`, for debugging), and forwards it
to the API's `POST /ingest/email`. The API turns it into a newsletter source in the recipient's Inbox. A failed
forward throws, so Cloudflare retries or bounces instead of losing the mail.

This replaces the spike in `spikes/newsletter_ingest` (same KV namespace). It is not deployed yet.

## Deploy (owner)

1. `cd workers/newsletter`
2. `npx wrangler secret put INGEST_SECRET`, with the same value as `INGEST_SECRET` on Railway's `api` service.
3. `npx wrangler deploy`
4. Cloudflare dashboard, Email Routing, catch-all address: action "Send to a Worker", destination `archie-newsletter`.
5. Send a test mail to the address shown in the app (Settings), and check it appears in Library as an Inbox item.
6. Delete the spike worker: `cd ../../spikes/newsletter_ingest && npx wrangler delete`.

## Local check

```bash
cd workers/newsletter
npx wrangler dev
# in another shell, from the repo root:
curl -X POST 'http://localhost:8787/cdn-cgi/handler/email?from=a@example.com&to=<token>@example.com' \
  --data-binary @services/api/tests/fixtures/newsletters/substack_bytebytego.eml
```

`wrangler dev` needs `INGEST_SECRET` in a `.dev.vars` file next to `wrangler.toml` (not committed) and `API_URL`
pointing at a running API (`API_URL=http://127.0.0.1:8000` in `.dev.vars` overrides the production value).
