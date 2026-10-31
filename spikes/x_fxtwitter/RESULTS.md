# X / fxtwitter spike results

Run date 2026-10-31. Script: `fetch_x.py` (`uv run spikes/x_fxtwitter/fetch_x.py`). Raw JSON in `.cache/`.

## Conclusions

- fxtwitter returns everything we need, free, no key: full text of long posts (1,800+ chars, not truncated), quote post text, media URLs, X Article bodies, and whole threads.
- **Threads are one call.** `GET https://api.fxtwitter.com/2/thread/{id}` returns the whole same-author thread in order (tested up to 14 posts), whichever post of the thread you pass (first or last). On a reply, it returns the ancestor chain up to the root (including other authors). No walking needed.
- The official X API is not needed for anything we tested. Keep it only as an untested emergency fallback.
- Caveat: the free API is unofficial and run by volunteers. We saw sporadic 404s from `api.fxtwitter.com` on valid accounts (e.g. profile lookups for naval/levelsio at times) that succeeded on retry, plus one connect timeout. Retry 2-3x with a short sleep.

## Endpoints (from docs.fxembed.com and `https://api.fxtwitter.com/2/openapi.json`)

| Endpoint | Use |
|---|---|
| `/2/status/{id}` | One post (text, `is_note_tweet`, `quote`, `media`, `article`, `replying_to`) |
| `/2/thread/{id}` | Same shape plus a `thread` array (the unrolled conversation) |
| `/2/status/{id}/quotes`, `/reposts` | Not needed |
| `/2/profile/{handle}/statuses` (`with_replies`, `groupthreads`) | Handy for discovery; not needed for the app |
| `/2/search` | Free X search (works, handy for finding samples); `since:` operator broke it |

Docs state 1000 requests/min per IP. The legacy `/{handle}/status/{id}` form still works but lacks the newer fields; use `/2/`. The post ID alone is enough; the handle in the URL is ignored.

## Per-URL results (all HTTP 200)

"Full text" = text length matched what the post shows (checked against search snippets and, for long posts, `is_note_tweet` + length above 280).

| Type | Post | `/2/status` text | `/2/thread` | Full text? | Notes |
|---|---|---|---|---|---|
| Plain | hwchase17/2116279214731395453 | 197 chars | 1 post | yes | |
| Long post | packyM/2115928664479310208 | 1,333 chars, `is_note_tweet` | 1 post | yes | not truncated |
| Long post + quote | hwchase17/2116622802031710709 | 1,807 chars | 1 post | yes | quote text (199 chars) inline in `quote` |
| Thread, 3 posts, share first | sama/2107691261776052633 | 95 chars (first post only) | **3 posts, 360 chars** | yes via `/thread` | `/status` alone gives only the one post |
| Thread, 3 posts, share last | sama/2107691577015755196 | 168 chars | same 3 posts | yes via `/thread` | works from the last post too |
| Thread, 6 posts | levelsio/2116542410658324495 | 96 chars | 6 posts, 652 chars | yes via `/thread` | |
| Thread, 14 posts (Jun 2025) | rubenhassid/1931389580105925115 | 246 chars | **14 posts, 2,917 chars** | yes via `/thread` | long thread works |
| Image + 13-post thread | shcallaway/2116221631349850131 | 123 chars, 1 photo | **13 posts, 2,642 chars** | yes via `/thread` | found by accident: recent, 13 posts |
| Quote | hwchase17/2116230499140251964 | 166 chars | 1 post | yes | quoted post text (173 chars) in `quote` |
| X Article (status URL) | hwchase17/2116553654857867330 | 279 chars (teaser) | 1 post | article: yes | `article.content.blocks`: 20 blocks, 5,149 chars of body |
| X Article (`/article/` URL) | usetapestry/article/2033603974675227095 | empty text | | article: yes | 3,070 chars; the article ID in the URL works as a status ID. Backend URL parser must accept `/article/` as well as `/status/` |
| Reply, 3 deep (2 authors) | packyM/2116232895308202061 | 23 chars ("incredible...") | **3 posts**, root first | yes | walks up to the root automatically |
| Reply, 3 deep (2 authors) | hwchase17/2116576419010785421 | 64 chars | 3 posts, root first | yes | same |

Media: `media.all[]` gives photo/video entries with direct `pbs.twimg.com` URLs and dimensions. Only photos were in our samples; a video was not tested (the field is the same list, with type `video`/`gif`). No transcript or alt-text analysis, so images are links only.

Walking `replying_to` by hand also works (each `/2/status` returns `replying_to.status`), but `/2/thread` already does it, so the script only uses the walk as a cross-check. It matched the thread endpoint in every case.

## Not covered by `/2/thread`

- It returns the ancestors/same-author thread, not the replies underneath. There is a separate "thread and replies" operation in the docs; we did not need it.
- If the shared post is a reply, you get the conversation up to the root, not only the author's own posts. Filter by `author.screen_name` if only the author's posts matter.
- Article bodies are Draft.js blocks (`unstyled`, `unordered-list-item`, `atomic` for embedded media); concatenate `text` per block. Embedded images/tweets in `atomic` blocks and `media_entities` are not text.

## vxtwitter / fixupx

- `fixupx.com` is just the HTML-embed front end for the same FxEmbed project; it adds nothing to the API.
- `api.vxtwitter.com/{handle}/status/{id}` (separate project) returned the same full text for every sample (including 1,807 chars) and has `replyingToID`, `qrt`, `article`, `conversationID`. It has no unrolled thread endpoint, so it can only be walked one post at a time via `replyingToID`, and not downward to the author's next posts. Useful only as a second source if fxtwitter is down.

## Official X API cost (docs.x.com pricing page, read 2026-10-31; nothing signed up)

- Pay-per-use: post read $0.005 per post returned; user lookup $0.010; owned reads $0.001; writes $0.015+. No minimum or subscription; spend limit configurable; same resource requested again within 24h UTC is not re-billed (soft guarantee). Cap: 3M post reads/month.
- Pricing page does not say how search is billed; presumably per post returned.
- A 20-post thread: 20 x $0.005 = **about $0.10** (plus ~$0.005 to look up the first post). Unverified: how to fetch a whole thread in one request (likely recent-search by conversation ID, which would only reach back ~7 days), so older threads may need a different, costlier route.

## Recommendation for the backend

1. Parse the URL (`x.com` or `twitter.com`, `/status/` or `/article/`), take the numeric ID, drop `?s=`.
2. Call `GET https://api.fxtwitter.com/2/thread/{id}` (not `/status`). Retry up to 3x on 404/5xx/timeouts.
3. Build the LLM input: for a thread, join the `thread[]` posts in order (filter to the shared post's author); for an article, join `article.content.blocks[].text` with the title; also include `quote.text` and `media` URLs as context.
4. Fallbacks, in order: retry fxtwitter after a delay; `api.vxtwitter.com/{handle}/status/{id}` (single post only); then the official X API only if the user wants it (about $0.005/post). Do not build the X API path now.
5. Cost: $0 expected. Even if every share fell back to the X API, a few shares a week (say 15/month at 10 posts avg) is about $0.75/month, but we have not needed it once.
6. Open risk: fxtwitter is unofficial and could break or rate-limit; cache every response (the script does this) and show "couldn't fetch" in the app rather than failing silently.
