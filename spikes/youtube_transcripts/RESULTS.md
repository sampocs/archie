# Spike 4: YouTube transcripts from a cloud host

Run 2026-10-31.

## Conclusions

1. **Captions work perfectly from a home IP and do not work at all from Cloudflare.** From this Mac, 6 of 6 videos with captions returned a full transcript in about 1 second, with both `youtube-transcript-api` and `yt-dlp`. From a Cloudflare Worker, 0 of 7 worked, blocked at every step.
2. **Plan on a managed API or a paid residential proxy. Do not plan on fetching directly from a cloud backend.** Cloudflare is one of the IP ranges most likely to be blocked, so its result is a worst case. But YouTube's own documented behavior (and the library's README) is that AWS, GCP and Azure ranges are blocked too. Railway and Fly run on those clouds, so assume they are blocked until a test proves otherwise.
3. **Recommended path: Supadata free tier (100 transcripts/month), which covers 5-15 videos/month at $0.** If that ever isn't enough, use `youtube-transcript-api` through a Webshare **rotating residential** proxy (~$3.50/month for the smallest 1 GB plan, more than 10x the bandwidth we need).
4. **Fallback for videos with no captions (or if both captions paths fail): download audio and send it to Groq Whisper (~$0.04 per audio hour).** The audio download is blocked from cloud IPs too, so it needs the same proxy, or a local run.
5. **Auto-generated captions are good enough.** 3 of the 6 test videos had only auto captions and came back complete.

## Videos tested

| ID | What | Length | Captions |
|---|---|---|---|
| ugvHCXCOmm4 | Lex Fridman x Dario Amodei (AI) | 5.2 h | Human |
| y0YkGWKT0gI | Odd Lots, AI trade (macro/finance) | 40 min | Human |
| LPZh9BOjkQs | 3Blue1Brown, LLMs explained (AI) | 8 min | Human |
| 0lJKucu6HJc | Sam Altman, how to succeed with a startup | 16 min | Auto only |
| iClsnZ1KYSk | Bankless, Tom Lee on ETH (crypto) | 63 min | Auto only |
| e0gVE3YxZs8 | Powell and the Fed in 60 seconds (macro) | 1 min | Auto only |
| SlpcNYFuuWw | Bitcoin live stream | live | Disabled |

The no-captions case is a live stream, so that ID may stop working once the stream ends. Any live stream with captions off reproduces it.

## Local results (this Mac, residential IP)

Script: `fetch_local.py` (`uv run fetch_local.py`). `youtube-transcript-api` 1.x uses `YouTubeTranscriptApi().fetch(video_id, languages=["en"])` (the old static `get_transcript` is gone). yt-dlp downloads the `json3` subtitle file only, no video.

| Video | transcript-api: ok / words / s | yt-dlp: ok / words / s |
|---|---|---|
| Lex x Dario (5.2 h) | yes / 59,948 / 1.1 | yes / 63,588 / 2.0 |
| Odd Lots (40 min) | yes / 7,618 / 0.9 | yes / 7,618 / 2.7 |
| 3Blue1Brown (8 min) | yes / 1,305 / 1.1 | yes / 1,305 / 1.7 |
| Altman (16 min, auto) | yes / 3,056 / 1.0 | yes / 3,056 / 1.1 |
| Bankless (63 min, auto) | yes / 10,590 / 1.4 | yes / 10,590 / 1.3 |
| Powell 60 s (auto) | yes / 193 / 1.1 | yes / 193 / 0.9 |
| Live stream, captions off | no (`TranscriptsDisabled`) / 1.8 | no (no subtitle file) / 1.1 |

Both methods agree on word count (the Lex gap is yt-dlp counting speaker-turn text slightly differently). A 5-hour episode is still a single ~1 second call, and the transcript is about 80k tokens, so very long episodes need chunked summarizing. yt-dlp printed a warning that it wants a JavaScript runtime (deno) for some formats, but subtitles worked without one.

## Cloud results (Cloudflare Worker, first run)

Worker: `https://archie-youtube-spike.newsletter-ingest.workers.dev` (code in `worker/`). KV namespace `RESULTS`, id `f464afb5c3c0421289d12ccc1aaf81a1`. Free plan, cron every 6 hours. Ran from the Chicago datacenter (ORD).

The Worker mimics `youtube-transcript-api`: (1) fetch the watch page, (2) call the InnerTube `player` endpoint as the Android client, (3) fetch the `timedtext` URL.

| Video | Watch page | InnerTube player | Transcript |
|---|---|---|---|
| All 7 | HTTP 429 + reCAPTCHA page (the library's `IpBlocked`) | See below | never reached |

Because step 1 only exists to scrape a public, constant API key, I also let the Worker continue with that key to see if the player call was blocked too. It was:

| Video | InnerTube player result |
|---|---|
| Lex, Odd Lots, Altman, Powell, live stream | HTTP 200 but `LOGIN_REQUIRED: Sign in to confirm you're not a bot`, no caption tracks |
| 3Blue1Brown, Bankless | HTTP 403 "Sorry..." block page |

Result: **0 of 7**. YouTube blocks Cloudflare at the watch page and at the player API.

**What this means for the conclusion.** Cloudflare Workers egress from Cloudflare's own ranges, which YouTube treats as datacenter traffic, and the tests above are a worst case. Railway and Fly are different IP ranges (mostly AWS/GCP underneath), so this does not prove they are blocked. The library's README says AWS, GCP and Azure are blocked, and the anti-bot message ("Sign in to confirm you're not a bot") matches what cloud hosts report. I would not build on a cloud host passing. To check, deploy the same `fetch_local.py` logic (for example `youtube-transcript-api` with no proxy) to the real host once it is chosen. It takes minutes.

### Reading the cron results (collects every 6 hours)

```bash
curl https://archie-youtube-spike.newsletter-ingest.workers.dev/        # latest run as JSON
curl https://archie-youtube-spike.newsletter-ingest.workers.dev/run     # run now and store it
cd spikes/youtube_transcripts/worker
npx wrangler kv key list --namespace-id f464afb5c3c0421289d12ccc1aaf81a1
npx wrangler kv key get "latest" --namespace-id f464afb5c3c0421289d12ccc1aaf81a1 --remote
```

Each run is stored as `run:<ISO time>` with `okCount`, `colo` and per-video `step`, `status`, `playability`, `error`. If later runs succeed, the block is intermittent per IP, which would be a useful finding. Remove the Worker when done: `npx wrangler delete` in `worker/`.

## Options and monthly cost

Prices from vendor pages on 2026-10-31. For 5-15 videos a month.

| Option | How it works | Free tier | Cost at 5-15 videos/mo | Notes |
|---|---|---|---|---|
| **Supadata** | API returns the transcript; 1 credit per native transcript; AI-generated transcripts cost 2 credits per minute | 100 credits/month, no card, 1 req/s | **$0** | Paid: Basic $5/mo (300 credits, annual billing only), Pro $17/mo (3,000). No pure pay-as-you-go: auto-recharge only on paid plans. Credits don't roll over |
| youtube-transcript.io | API with token quota | 25 tokens/month | $0 (25 is enough for most months) | Paid Plus is $9.99/mo for 1,000, Pro $24.99/mo. Subscription only |
| TranscriptAPI | Hosted API | 100 credits | $0 | Reported $5/mo plan plus top-ups. Taken from a third-party comparison, unverified |
| Apify actors | Pay per successful transcript | Apify gives monthly free credit | ~$0.05 | Listed from about $3-10 per 1,000 transcripts. True pay-per-use, quality varies by actor |
| SearchAPI | General SERP API | 100 requests | n/a | Pricing page lists no YouTube transcript endpoint ($40/mo minimum). Skip |
| Webshare rotating residential + `youtube-transcript-api` | Library routes through `WebshareProxyConfig` | Free plan is shared datacenter proxies, which YouTube blocks | **~$3.50/mo** (smallest 1 GB plan) | Needs the **Residential** package, not "Proxy Server" or "Static Residential". A transcript costs roughly 1-2 MB of traffic, so 15 videos is about 25 MB. Subscription, but cheap |
| Other residential (Bright Data, Oxylabs, etc.) | Same | Trials | $5-15/mo typical minimums | Not researched in depth. Webshare is the one the library documents |
| Home machine / residential IP | `fetch_local.py` | Free | $0 | Ruled out: no always-on machine |

## Fallback: audio download and Groq Whisper

If a video has no captions (the live-stream case) or the caption path is blocked, download the audio and transcribe it. Groq Whisper is about $0.04 per audio hour, so a 1-hour video is 4 cents.

I did not test audio download from a cloud IP (only reasoned). `yt-dlp` audio downloads hit the same bot checks as the player API, and video file URLs are additionally tied to the requesting IP, so **a cloud IP will most likely be blocked here too**. It would need the same residential proxy. Audio bandwidth is much bigger than text: roughly 30-60 MB per hour at low bitrate. With 10 hours a month that is under 1 GB, so the 1 GB Webshare plan would roughly cover it, and tight months need the next tier. Managed APIs avoid this: Supadata's AI-generated transcript mode handles no-caption videos itself at 2 credits per minute, but that burns the free tier fast (a 30 min video is 60 credits), so it only suits an occasional video.

## Recommendation and fallback order

1. **Supadata free tier.** Zero fixed cost, no proxy to maintain, one HTTP call. 100 credits covers 5-15 videos with room to spare.
2. **`youtube-transcript-api` through a Webshare rotating residential proxy** (~$3.50/mo) if Supadata's free tier is withdrawn, rate-limited, or fails on a video. Keep `yt-dlp` subtitles behind it as a second method on the same proxy.
3. **Audio download (through the same proxy) and Groq Whisper** for videos with no captions at all. Rare, about 4 cents an hour plus proxy bandwidth.
4. If a video fails everything, mark it "transcript unavailable, paste it?" like the paywalled-article case.

Cost against the budget: $0/month expected, $3.50/month worst case. This fits inside the findings doc's "$0-5 YouTube" line, and the "~$5-10/mo proxy" estimate there is somewhat high.

Before building, worth doing: (a) pick the host, then run the same no-proxy test from it (cheap, and might pass), (b) check Supadata's accuracy on one long episode, (c) check the cron results after a few days for any intermittent success.

## Surprises

- Cloudflare is blocked even at the watch page with a reCAPTCHA 429, and the player API gives "Sign in to confirm you're not a bot" for most videos but a hard 403 for others, so blocking is per request, not uniform.
- The old `get_transcript` function no longer exists in `youtube-transcript-api` 1.x.
- yt-dlp and the library returned identical word counts for every normal video.
- A second back-to-back local run of `fetch_local.py` hit `HTTP 429 Too Many Requests` on yt-dlp's subtitle download, even from the residential IP. YouTube rate-limits the timedtext endpoint per IP, so a few repeated fetches in a minute can trip it. This matters for a proxy or backend design: cache transcripts and don't re-fetch.
