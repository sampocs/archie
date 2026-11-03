# Deploying Archie

The backend runs on Railway, as project `archie` in environment `production`. The repo records only
the app service's build and deploy settings, in `railway.json`: build with the Dockerfile, health check
on `/health`, restart on failure. Railway's config file can't hold databases, variables or domains, so
those were set by hand. They are listed here so the project can be rebuilt from scratch.

## Services

| Service | Source | Notes |
| --- | --- | --- |
| `Postgres` | Image `pgvector/pgvector:pg18` | Created from Railway's Postgres template, with its image swapped before first boot. Railway's standard image has no pgvector. The template supplies the volume at `/var/lib/postgresql/data`, `PGDATA=/var/lib/postgresql/data/pgdata`, a generated password and `DATABASE_URL`. |
| `archie` | GitHub `sampocs/archie`, branch `m1-foundation` until it merges, then `main` | One container runs migrations, then the API and the worker (`archie-launch`). |

## Variables on `archie`

| Name | Value |
| --- | --- |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `OWNER_EMAILS` | The owner's Apple ID email (comma-separated list) |
| `APPLE_AUDIENCE` | `com.sampocs.archie` |
| `ARCHIE_ENV` | `prod` (anything else except `dev`/`test` also hides `/test/session`, but set it explicitly) |
| `PORT` | `8000`, matching the domain's target port |

## Domain

`archie-production-4856.up.railway.app` routes to port 8000 on `archie`. The iOS release build bakes
this URL in; see `scripts/install_ios.sh`.

## Rebuilding from scratch

With the Railway CLI logged in and the project linked (`railway link --project archie`):

1. Add Postgres: `railway add --database postgres`, then set the Postgres service's source image to
   `pgvector/pgvector:pg18` **before it first boots**. Otherwise initdb runs on the template image and
   the volume has to be recreated. (Staging the template, changing the image, then deploying does this.)
2. Create the app service from the GitHub repo, then set the variables above:
   `railway variable set --service archie DATABASE_URL='${{Postgres.DATABASE_URL}}' OWNER_EMAILS=... APPLE_AUDIENCE=com.sampocs.archie ARCHIE_ENV=prod PORT=8000`
3. Generate a domain on port 8000: `railway domain --service archie --port 8000`. If the domain
   changes, update the default in `scripts/install_ios.sh`.
4. Check: `curl https://<domain>/health` returns `{"ok":true,"database":true}`, and
   `curl -X POST https://<domain>/test/session` returns 404.
