# Second Brain: De-risk Findings (research pass)

> Desk research done 2026-10-26 by four parallel research agents. Many prices and limits come from third-party sources or the agents' background knowledge rather than vendor pages. **Treat every number as "verify before budgeting."** The hands-on spikes (bottom of this doc) are what settle things.
> Companion to [product scope](2026-10-26-product-scope.md).

## Verdicts at a glance

| Area | Verdict | Recommended approach | Rough cost |
|---|---|---|---|
| Apple Podcasts links | 🟢 | iTunes Lookup API → RSS feed → episode audio | Free |
| Generic RSS podcasts | 🟢 | Use `<podcast:transcript>` if present (~10% of top shows), else transcribe | Free when a transcript exists |
| Transcribing audio | 🟢 | **Tested on 20 episodes:** Groq whisper-large-v3-turbo with a short hint. No model was better beyond chance, and Groq is the cheapest. If it fails, fall back to gpt-4o-mini-transcribe with 5-min chunks. Names get fixed by a Claude corrections pass. See `spikes/transcription/RESULTS.md` | ~$2/mo for 10 hrs/week |
| Spotify links | 🟡 | Scrape the episode and show title from the public page, then match to the show's RSS via iTunes Search or Podcast Index. Don't depend on the Spotify API (it was cut back in Feb 2026) | Free |
| Spotify-exclusive shows | 🔴 | No RSS and DRM-protected. **Unsupported** | n/a |
| YouTube | 🟡 | `youtube-transcript-api`, then `yt-dlp` subtitles, then download audio and transcribe. **YouTube blocks most cloud server IPs.** Run from a home machine or through a residential proxy | Free from home, ~$5–10/mo for a proxy |
| X / Twitter | 🟡 | Free fxtwitter JSON API first, then the official X pay-per-use API (~$0.005 per post) for full threads. twitterapi.io is the cheap paid middle option | ~$0–5/mo |
| Newsletter ingest | 🟢 | A dedicated address on your own domain via Cloudflare Email Routing and an Email Worker that POSTs to the backend. **Email carries the full paid text** (RSS truncates paid posts). Avoid the Gmail API (tokens expire weekly in testing mode, and verification for restricted scopes is painful) | Free |
| Paywalled articles | 🟡 | Share from **Safari**: the share extension runs JS on the page you're logged in to and captures the rendered text. Other apps share only a URL. Paid Substack posts already arrive by email | Free |
| General articles | 🟢 | `trafilatura` on the server, with Jina Reader as a fallback for JS-heavy pages | Free |
| iOS share sheet | 🟡 | **A web app (PWA) cannot appear in the iOS share sheet.** Use Expo plus `expo-share-extension` (custom UI with chips, text and voice), built with EAS. An iOS Shortcut works as a day-one stopgap | $99/yr Apple developer account |
| Daily notification | 🟢 | Local scheduled notification (`expo-notifications`). No server needed | Free |
| Books | 🟡 | No automatic capture. Share the title, get metadata from Open Library or Google Books, and have the LLM write the primer (risk of spoilers or made-up details for obscure books). Readwise is optional for Kindle highlights. The Goodreads API is dead | Free, or ~$10/mo for Readwise |
| Notes import | 🟢 | Turn everything into markdown first (Apple Notes on iOS 26 exports Markdown, and Notion and Obsidian are already markdown), then use one importer | ~1 day |
| Voice answers | 🟢 | Record a clip and send it to a cloud speech-to-text API (OpenAI or Deepgram, ~$0.004/min). On-device iOS 26 `SpeechAnalyzer` is the fallback | <$1/mo |
| Card grading | 🟡 | A small, fast LLM (Haiku, GPT-mini or Gemini Flash class) with a structured schema: verdict, what was missing, and confidence, in one call. Get the confidence signal from token probabilities or from sampling several times and checking agreement | <$1/mo |
| Jev specifically | 🟡 | Typed answers with calibrated probabilities, cheap and fast. **But it can't write the "what was missing" explanation**, the only benchmarks are the vendor's own, and access is a waitlist or Cloudflare Workers AI. Worth testing as the verdict-and-confidence step alongside an LLM, not as the only grader | Fractions of a cent |
| Pulse story grouping | 🟢 | Use an LLM to split each newsletter into stories, embed them (`text-embedding-3-small`, ~$0.02 per 1M tokens), cluster by cosine similarity, then use an LLM to merge borderline groups and write headlines. At this volume, a single LLM grouping call is a valid fallback | Pennies |
| Library search / vector store | 🟢 | Reuse the same embeddings in pgvector on Postgres, which also gives hybrid keyword search, or sqlite-vec for a single file | Free |

**Not researched yet:** LLM costs for summaries, primers and cards. These are likely the biggest line item, and the next step is to estimate them from real transcripts.

## My setup (answered 2026-10-26)

- **Apple developer account:** already have one, so there's no extra $99.
- **Always-on Mac:** none. YouTube needs a residential proxy or a managed transcript API, and transcription goes through a paid API.
- **Domain:** none yet. Plan to buy one (~$10/yr, e.g. via Cloudflare Registrar) for newsletter ingest.
- **Podcast app:** **Spotify**, so Spotify-to-RSS matching is the most important podcast spike.
- **Old notes:** **Bear** (native bulk Markdown export) and **Google Docs** (Drive export to Markdown or docx).

## What this changes in the product

1. **The app is an Expo (React Native) app plus a Python backend.** A PWA is ruled out because it can't receive shares. This also requires a $99/yr Apple developer account (needed for stable signing of a share extension, and for TestFlight).
2. **Spotify-exclusive shows aren't supported.** Everything else from Spotify should work, depending on the match rate.
3. **Some work should run from a residential IP.** YouTube blocks cloud servers. Either a small worker runs on a home Mac, or we pay ~$5–10/mo for a residential proxy. Running Whisper on a home Mac would also make transcription free.
4. **Newsletters move to a new address.** You'd re-subscribe them to an address like `brain@yourdomain.com` (or set up a Gmail filter that forwards them there), which requires a domain on Cloudflare.
5. **For paywalled articles, share from Safari.** Sharing from an app (X, Substack, Bloomberg) passes only the link. If the server can't fetch the text, Carl marks the item "text missing — paste it?"
6. **Books are capture-by-hand.** Readwise is worth it only if you read on Kindle and highlight.
7. **Grading = a small LLM, with Jev as a possible add-on**, since Jev can't write explanations. Self-grading is always available.

## Monthly cost model (target: under $20/mo of new spend)

**Volume assumptions (to be checked against real usage):**
- ~10 hrs of podcasts/week, which is ~43 hrs/mo or ~20 episodes, ~12k transcript tokens per hour
- ~20 articles or threads/mo
- ~50 newsletters/week
- ~30 card grades/day
- ~5 chat questions/day

**Prices used:** Claude list prices as of 2026-10:
- Haiku 5.5: $0.10 in / $0.50 out per M tokens
- Sonnet 5.5: $2 / $10
- Opus 5.5: $4 / $20
- Batch API: 50% off
- Transcription prices are from third-party sources and **unverified**

| Line item | Lean | Recommended | Notes |
|---|---|---|---|
| Hosting (API, worker, Postgres + pgvector) | $5 | $5 | e.g. Railway hobby, or Supabase free tier for the DB |
| Domain (for newsletter ingest) | $1 | $1 | ~$10/yr |
| Apple developer account | $0 | $0 | Already have one |
| Transcription (~43 hrs) | ~$2 (Groq Whisper, no speaker labels) | ~$2 (Groq, chosen by the 20-episode spike) | Speaker labels (AssemblyAI or ElevenLabs) would cost ~$7–17. The LLM can usually infer who's speaking from context |
| Source processing (summary, tags, cards, links) | ~$0.30 (Haiku) | ~$2–3 (Sonnet, Batch API) | Podcasts aren't urgent, so Batch's 50% discount applies |
| Primers | ~$1 (Sonnet) | ~$3 (Opus) | Foundations are the most important output, so they get the best model |
| Pulse (split, group, write the brief) | ~$0.50 (Haiku) | ~$2–3 (Haiku split + Sonnet brief) | |
| Chat | ~$0.30 (Haiku) | ~$2–3 (Sonnet) | Depends on how much I use it |
| Grading + embeddings | <$0.20 | <$0.50 | Haiku-class grader |
| YouTube | $0–3 | $0–5 | Managed transcript API free tier or a pay-per-GB proxy. Spike 4 decides |
| X | $0 | $0–1 | fxtwitter first |
| **Total** | **~$10–13** | **~$17–25** | |

### Split: infrastructure vs. AI

**Principle:** keep fixed infra and SaaS spend minimal and avoid subscriptions. AI usage is acceptable and should get cheaper over time.

| Bucket | Items | Monthly |
|---|---|---|
| **Infra / SaaS (fixed)** | Hosting (API, worker, Postgres) ~$5–10 · domain ~$1 · Cloudflare email $0 · Apple dev $0 (already have it) | **~$6–11** |
| **Infra / SaaS (usage-based, small)** | YouTube transcript API or proxy $0–5 · X pay-per-use fallback $0–1 | **~$0–6** |
| **AI usage** | Transcription ~$2–8 · Claude (processing, primers, Pulse, chat, grading) ~$7–12 · embeddings ~$0 | **~$10–20**, tunable by model choice |

Subscriptions deliberately avoided: Readwise (~$10/mo), Taddy (~$75/mo), Firecrawl (~$16/mo), managed scraping plans, Gmail API verification.

**Biggest levers:**
1. **Model choice per job.** Opus primers and Sonnet chat make up most of the gap between the two columns.
2. **Transcription vendor.** Groq costs ~$2. Paying for speaker labels adds ~$5–15.
3. **Listening volume.** Transcription and processing scale linearly with hours.

**Plan:** start at Recommended, with **Sonnet for primers** (not Opus) to land around **$15/mo**. Track the real cost per hour of content (spike 8), and upgrade primers to Opus if their quality falls short.

## Hands-on spikes (prioritized)

| # | Spike | Pass looks like |
|---|---|---|
| 1 | **Share extension on a real iPhone**: log what Spotify, Apple Podcasts, YouTube, X, Safari and Substack actually send; build a custom UI with chips, a text field and voice; check memory use and microphone permission inside the extension | All six apps give at least a URL. The custom UI works within memory limits |
| 2 | **Podcast link → transcript**: about 20 real Spotify and Apple links → match to RSS → transcript (published or Scribe/AssemblyAI) | ≥90% matched, transcript quality good enough to summarize |
| 3 | **Card grading**: 30–50 real answers you've labeled, graded by Haiku, GPT-mini and Flash class models (plus Jev if access comes through) | Matches your labels, especially on "partly". High-confidence grades really are more accurate. A rubric edit flips the grade |
| 4 | **YouTube from the intended host** (cloud vs. home vs. proxy), over a few days | A reliable path is identified |
| 5 | **X threads and articles via fxtwitter**, plus the cost of the official pay-per-use API for a 20-post thread | Full thread text for real examples |
| 6 | **Newsletter ingest**: subscribe 3 real newsletters (one paid) to a Cloudflare address | Full text arrives and parses cleanly |
| 7 | **Pulse grouping** on one real week of newsletters, hand-labeled | Same-story groups match your labels |
| 8 | **LLM processing cost**: run summary, primer and cards on 5 real transcripts | A cost per hour of content |
| 9 | **Safari paywall capture** on logged-in WSJ, The Information, Bloomberg and a paid Substack | Full article text captured |

Later, during the build: notes import quality, primer quality for books, voice latency.
