# M3: All sources (podcasts, YouTube, newsletters)

> Milestone 3 of the [backend architecture roadmap](2026-11-02-backend-architecture-design.md#roadmap). Builds on
> [M2](2026-11-03-m2-capture-pipeline-design.md): same jobs, artifacts, `llm_calls`, processing status and sync.

**Status:** Implemented on `m3-sources`; not deployed.

**How this spec was made:** the owner asked for M3 to be built overnight without them, so the decisions below were
made without a brainstorming round. Anything the owner might reasonably want differently is listed under
**Decisions to confirm** at the end. Inputs: the de-risk findings and the `podcast_resolve`, `transcription`,
`youtube_transcripts` and `newsletter_ingest` spikes.

**Checked before writing (2026-11-03):**
- `youtube-transcript-api` from the Railway container: **blocked** (`RequestBlocked`, 3 of 3 videos). Railway can't
  fetch YouTube directly, as the spike predicted.
- The newsletter spike is live: `archiesecondbrain.com` routes all mail to the `archie-newsletter-spike` Worker,
  which stores raw emails in KV. 7 have arrived (Morning Brew ×4, two Substack posts, a test).

## Goal

On the phone, the user can:

1. Share a podcast episode from **Spotify** or **Apple Podcasts** (or paste its link in ＋) and, a few minutes later,
   read its summary, key ideas with timestamps, primer and cards, as for an article.
2. Share a **YouTube** video and get the same, wherever the server can get its captions (see YouTube below).
3. See **newsletters** sent to their Archie address arrive in Library as **Inbox** items with a summary.

## Out of scope

- Spotify-exclusive shows (no RSS; DRM). They fail with "This show is only on Spotify, so Archie can't get its audio."
- Videos with no captions (audio download needs a residential proxy). They fail with "This video has no captions."
- Pulse, story grouping, the brief and "Go deeper" (M7). M3 only stores newsletters as Inbox items with a summary.
- The show registry correction UI. The registry is built and used; correcting a wrong match waits for M4's item page.
- Speaker labels.

## Kinds

`SourceKind` gains `newsletter`. `youtube` and `podcast` (already detected by `archie_shared.urls`) move from "title
only" to processed. `UrlKind.PODCAST` covers `open.spotify.com/episode/<id>` and `podcasts.apple.com/...?i=<id>`;
a Spotify **show** link or an Apple show link with no `?i=` is `unsupported` ("Share an episode, not the show"), and a
YouTube link with no video id (a channel) is `unsupported` ("Share a video, not the channel."). The reason is stored in
`processing_error`, which `pipeline.set_processing` now keeps for `unsupported` as well as `failed`, and the app shows
it in place of "Not processed yet".

## Pipeline

Steps stay jobs (`JobKind`), each enqueuing the next in the same transaction as its writes. New kinds:

| Step | Runs for | Does |
|---|---|---|
| `fetch_content` (existing) | article, x, **youtube**, **podcast** | youtube: fetch captions → `text`. podcast: resolve the episode, then either a published transcript → `text`, or enqueue `transcribe` |
| `transcribe` (new) | podcast without a published transcript | audio → chunks → Groq → corrections pass → `text` |
| `analyze`, `primer` (existing) | everything with a `text` artifact | as M2; newsletters run `analyze` only, with no cards |

The `text` artifact gains an optional `segments` list for timed sources (below), and analyze's prompt uses it to
fill the existing nullable timestamp fields on key ideas and numbers.

### Podcasts: resolving the episode

New module `archie_worker.content.podcast`, following `spikes/podcast_resolve/resolve_episodes.py`:

1. **Spotify episode:** GET the public page (15 s, 5 MB), parse its `application/ld+json`: episode `name`,
   `datePublished`, and the show name from the description prefix "Listen to this episode from {show} on Spotify."
   No Spotify API.
2. **Apple episode:** iTunes Lookup `https://itunes.apple.com/lookup?id=<show id>&entity=podcastEpisode&limit=200`
   gives the show's `feedUrl` and the episodes' titles and dates; the `?i=` id picks the episode.
3. **Show → feed** (Spotify only; Apple already has `feedUrl`): look up the show in the **show registry** first; on a
   miss, iTunes Search (`media=podcast&entity=podcast`), preferring an exact (case-insensitive) title match, else the
   top hit. Save the result in the registry only once step 4 has matched the episode in that feed, so a wrong top
   hit is never remembered.
4. **Feed → episode:** GET the RSS feed (30 s, 50 MB), parse with `defusedxml`, keep items published within ±3 days
   of the episode's date, pick the closest title by `difflib.SequenceMatcher` ratio ≥ 0.6. No match →
   `PermanentJobError` "Couldn't find this episode's audio. If the show is only on Spotify, Archie can't get it."
5. Title: the episode title (unless the source already has one). The resolved episode (show name, title, description,
   `feed_url`, `guid`, `audio_url`, `duration_s`) goes in the `transcribe` job's payload under `episode` (there is no
   `text` artifact yet when `transcribe` runs), and on the finished `text` artifact's content under `episode`, so later
   milestones don't resolve again.

**Show registry:** table `podcast_shows` (global, not per user): id, `name_key` (lower-cased, whitespace-collapsed
show name, unique), `name`, `feed_url`, `itunes_id`, created_at, updated_at. It fills on first resolution, so a show
goes through iTunes Search once. Not seeded: the spike didn't keep its feed URLs, and some of its top hits were wrong.

### Podcasts: the transcript

- **Published transcript:** if the matched item has `<podcast:transcript>`, prefer `text/vtt`, then
  `application/x-subrip`/`application/srt`, then `application/json` (Podcasting 2.0 JSON), then `text/html`/plain.
  Parse VTT/SRT/JSON into segments (start seconds + text); HTML/plain becomes text with no segments. Write `text`
  (and segments) and enqueue analyze and primer. A transcript under 200 words is ignored, and the episode is
  transcribed as if it had none.
- **Otherwise** `fetch_content` enqueues `transcribe` and leaves the source `processing`.

### `transcribe`

New module `archie_worker.transcription` plus the handler:

1. **Download** the enclosure to a temp file (streamed, 10 min total, 600 MB cap → `PermanentJobError` "This
   episode is too long to transcribe").
2. **Chunk** with `ffmpeg` (added to the Docker image and CI): mono, 16 kHz, 32 kbps MP3, 10-minute segments
   (`-f segment -segment_time 600`). A 10-minute chunk is ~2.4 MB, under Groq's 25 MB limit.
3. **Transcribe** each chunk with Groq `whisper-large-v3-turbo`, `response_format=verbose_json` (segments with
   times), `language=en`, `temperature=0`, and the **basic hint** as `prompt`: "{show}. {episode title}." (the spike
   found richer hints derail Whisper). Segment times are offset by the chunk's start.
4. **Fallback per chunk:** if Groq errors with a non-retryable error, or the chunk comes back under 100 words per
   minute of audio, redo that chunk with OpenAI `gpt-4o-mini-transcribe` as two 5-minute halves (it truncates around
   1,700 words per request). OpenAI's plain JSON has no segment times, so that chunk gets one segment at its start.
5. **Progress survives retries:** each finished chunk is stored in `transcript_chunks` (source_id, chunk_index,
   provider, model, segments jsonb, unique on (source_id, chunk_index)) and committed immediately. A retried job
   re-downloads but skips finished chunks. Groq 429s raise a retryable error that honours `retry-after` (a new
   `RetryLaterError`: the loop re-queues the job after that delay instead of its fixed backoff; `transcribe` jobs get
   6 attempts).
6. **Corrections pass** (Haiku 5.5, structured output, the `correct_names` spike's prompt and schema): given the show,
   episode title and description and the transcript, return `{heard, correct, context}` corrections. Code applies
   each **only where `heard` appears inside its `context` snippet**, never as a global replace; single common words
   never change globally. No web-search tool in M3 (the spike: barely used). Logged in `llm_calls` as step
   `corrections`. If the call fails after its fallback, the transcript is used uncorrected (logged), not failed.
7. Write `text` with segments; enqueue analyze and primer.
8. **Stale timeout:** `HandlerSpec` gains `stale_after` (default the loop's 900 s); `transcribe` uses 3,600 s so a
   3-hour episode isn't swept mid-run.

**Costs in `llm_calls`:** `llm_calls` gains nullable `audio_seconds`. Transcription rows: provider `groq` or `openai`,
tokens 0, `cost_usd` from a per-audio-hour price table in code (Groq turbo $0.04/h, gpt-4o-mini-transcribe $0.18/h),
`stop_reason` null. `provider` widens from 16 to 32 characters only if needed (it isn't for these names).

**Keys:** `GROQ_API_KEY` and `OPENAI_API_KEY` (both `preserve()` in `.railway/railway.ts`). Whitelisted users only, as
for Anthropic; others fail with `needs_api_key`. A missing Groq key with an OpenAI key present goes straight to the
OpenAI path; neither key → `PermanentJobError` "Transcription isn't set up on the server."

### Timestamps

- `text` content for timed sources: `{"text": "...", "segments": [{"start": 734.2, "text": "..."}]}`.
- The analyze input for a timed source is the text with a `[mm:ss]` (or `[h:mm:ss]`) marker at the first segment
  after every 60 seconds, and the prompt asks for each key idea's and number's timestamp from the nearest marker.
  Prompt version `analyze-v2`; the output schema is unchanged.
- The input cap rises from 200,000 to **600,000 characters** for timed sources (a 3-hour episode is ~200k), still
  well inside Haiku 5.5's context. Primer gets the same marked text.
- **Long mixed shows:** the analyze prompt adds that cards come only from educational stretches, so an
  entertainment show with one educational segment still gets cards for that segment (the M2 note "per-section cards
  come with podcasts"). Still 3–5 cards per source.

### YouTube

New module `archie_worker.content.youtube`. In order:

1. **Supadata** when `SUPADATA_API_KEY` is set: `GET https://api.supadata.ai/v1/youtube/transcript?videoId=<id>&lang=en`
   with `x-api-key` (per its docs; native captions only, never the AI-generated mode, which costs 2 credits a minute).
2. **Direct** `youtube-transcript-api` (1.x, `YouTubeTranscriptApi().fetch(id, languages=["en"])`) otherwise. This
   works from a home IP (local dev, and recording), and is blocked from Railway.
3. `RequestBlocked`/`IpBlocked` with no Supadata key → `PermanentJobError` "YouTube transcripts need setup on the
   server (a Supadata key)." `TranscriptsDisabled`/`NoTranscriptFound` → "This video has no captions."
4. Segments come from the caption cues; the title from the watch page's `og:title` through the existing M1 title
   extractor when the source has none (Supadata gives no title; the watch page is reachable from Railway for the
   title even when captions aren't — if not, the title stays the URL).
5. Video id parsing: `youtube.com/watch?v=`, `youtu.be/<id>`, `/shorts/<id>`, `/live/<id>`, `m.youtube.com`.

### Newsletters

**Address:** each user gets an `ingest_token` (users column, 10 lowercase letters/digits, unique, made by the
migration for existing users and at user creation). Their address is `<ingest_token>@<INGEST_EMAIL_DOMAIN>`. The
spike addresses `news@` and `test@archiesecondbrain.com` (both used by real subscriptions) keep working through
`INGEST_ALIASES` (`news=<owner email>,test=<owner email>`), so existing subscriptions don't move.

**Worker:** `workers/newsletter/` (new, deployable with wrangler; replaces the spike worker on the same route):
on `email`, read the raw message and POST it to `POST /ingest/email` with headers `x-ingest-secret`
(`INGEST_SECRET`, a Worker secret and a Railway `preserve()` variable), `x-ingest-to` (envelope recipient) and
`x-ingest-from`. Keeps writing the raw email to the spike's KV as well (cheap, and a debugging record). A non-2xx
response throws, so Cloudflare's retry/bounce behaviour applies.

**API `POST /ingest/email`:**
- Rejects a missing/wrong secret with 401 (constant-time compare). Body is the raw RFC 822 message, 10 MB cap (413).
- Maps the recipient's local part to a user (token, then alias); unknown → 202 and dropped (logged), so senders don't
  learn which addresses exist.
- Parses with the stdlib `email` package (`policy.default`): subject (decoded), `From` display name and address,
  `Date`, `Message-ID`, `List-Unsubscribe`, and the best body: HTML converted to text with `trafilatura` (falling back
  to the `text/plain` part).
- Creates a `sources` row: kind `newsletter`, state `inbox`, intent `queue` (`sources.intent` is NOT NULL on the
  server and the phone; `state` is what marks it Inbox), url = the post's web link if the email names one (the
  `List-Post` header, else a plain-text "View this post on the web at <url>" line; per-recipient tracked redirect
  links are never used), else `newsletter:<message-id>`; title = subject; `processing` = `pending` (as `add_source`
  does; `fetch_content` moves it to `processing`); a
  `source_captures` row with the extracted text, and a `fetch_content` job. Idempotent on (user, Message-ID): a
  re-delivery returns 202 without a second row. An email with no Message-ID uses `sha256:<hex digest of the raw
  message>` in its place.
- `fetch_content` for a newsletter uses the capture (as for a Safari share), writes `text`, enqueues **analyze only**.
  `analyze` for a newsletter never creates cards (product scope: Inbox items get no cards). The source is `ready` when
  analyze is done.

**App:** Library already lists sources by state; Inbox items show the sender as the host line and a small "Inbox"
label. The account sheet shows "Newsletter address" with the address and a copy button (from a new `GET /me` field
`ingest_address`, null when `INGEST_EMAIL_DOMAIN` is unset). No other app work.

### Retry

`retry_source` (M2) learns the new steps: no current `text` → from `fetch_content` (which resumes into `transcribe`
for a podcast whose transcript chunks are partly done); newsletters retry analyze only.

## Data

Migration `0003_all_sources`:
- `SourceKind` value `newsletter` (the column is a string; check constraint updated if one exists).
- `podcast_shows` and `transcript_chunks`.
- `users.ingest_token` (unique, backfilled).
- `llm_calls.audio_seconds` (numeric, nullable).
- `sources.newsletter_message_id` (nullable) with a unique index on (user_id, newsletter_message_id).
- `sources.sender` (nullable string, synced) for the newsletter's display name.

Sync: `SourceOut` adds `sender`. Nothing else new reaches the phone (`transcript_chunks`, `podcast_shows` stay
server-side).

## Testing

**Backend e2e** (pytest + Postgres, outside calls replayed from cassettes recorded once against the real services):
- **Spotify → RSS → Groq:** a real Spotify link for a **short** real episode (under ~3 MB of audio, so the cassette
  stays small; pick a news-brief style show with a small feed) → resolve → download → ffmpeg chunk → Groq →
  corrections → analyze → primer → pull shows `ready`, a summary whose key ideas carry timestamps, and `llm_calls`
  rows for groq, corrections, analyze and primer with costs.
- **Apple link with a published transcript:** a real Apple link to an episode whose feed has `<podcast:transcript>`
  (Bankless, Darknet Diaries or another with a small transcript) → no audio download in the cassette → ready.
- **OpenAI fallback:** recorded Groq failure is hard to provoke for real; the fallback is tested at the unit level on
  the decision function (under 100 wpm → fall back) plus one recorded OpenAI call on the same short audio.
- **Resume:** a `transcribe` job whose first attempt stored chunk 0 and then failed resumes without calling Groq for
  chunk 0 (the cassette holds only the later chunks' calls).
- **YouTube:** a real short captioned video recorded locally through the direct path → ready with timestamps. A
  blocked response (recorded from a datacenter-like failure isn't reproducible locally, so this one is a unit test on
  the error mapping).
- **Newsletters:** two real emails from the spike KV (Morning Brew, a Substack post), with tracking query strings and
  per-recipient tokens scrubbed before committing, POSTed to `/ingest/email` → Inbox source with sender and title →
  analyze (recorded) → ready, no cards, no primer. Wrong secret → 401; unknown address → 202, no row; re-delivery →
  one row.
- **Spotify show link / Spotify-exclusive:** unsupported / failed with the right reasons.

**Backend unit:** VTT/SRT/JSON transcript parsing; `[mm:ss]` marker insertion; episode title/date matching;
context-anchored correction replacement (including the "Gary" case: a common word replaced only in its snippet);
YouTube id parsing; the transcription fallback decision; email body selection and newsletter user mapping.

**App:** jest for the Inbox label/sender line and the account sheet address; **Maestro** `add_podcast.yaml`: paste the
short Spotify episode link in ＋ against the local backend (real keys, a few cents), wait for the summary, check a
timestamp shows. `share_sheet.yaml` keeps passing.

## Deploy

- Dockerfile installs `ffmpeg`; CI installs it for the tests.
- `.railway/railway.ts`: `GROQ_API_KEY`, `OPENAI_API_KEY`, `SUPADATA_API_KEY`, `INGEST_SECRET`,
  `INGEST_EMAIL_DOMAIN`, `INGEST_ALIASES` as `preserve()`.
- The newsletter Worker is deployed with wrangler after the API is live, replacing the spike Worker on the domain's
  catch-all route.

## Decisions to confirm

Made without the owner; each is easy to change.

1. **YouTube in production needs a Supadata key** (free tier, 100 transcripts/month). Until one is set, YouTube links
   fail with "needs setup" on Railway (they work in local dev).
2. **Transcription is Groq turbo with an OpenAI fallback, then a Haiku corrections pass without web search.**
3. **Newsletters are Inbox items with a summary and no cards or primer**; Pulse uses them in M7.
4. **The spike addresses `news@` and `test@` map to the owner**, and each user also gets a token address.
5. **The new Worker keeps copying raw mail to the spike's KV.**
6. **The show registry is global** (show → feed isn't personal) and starts empty (no seed of the owner's 28 shows).
7. **A wrong podcast match can't be corrected in the app yet** (M4).

## Follow-ups

- Record a Supadata cassette (`youtube_supadata.yaml`, same video) once `SUPADATA_API_KEY` exists; until then the Supadata branch is untested.
- Deploy M3: set the Railway variables listed in `docs/deploy.md`, `railway config plan` then `railway config apply`,
  deploy the newsletter Worker from `workers/newsletter/README.md`, then switch Email Routing to it.
- Feed-supplied URLs (enclosure, transcript) are fetched without a private-address check; SSRF hardening is needed
  before this is exposed to untrusted feeds.
- Dynamic ad insertion can change a feed's audio between `transcribe` retries, so resumed chunks could misalign with
  freshly transcribed ones.
