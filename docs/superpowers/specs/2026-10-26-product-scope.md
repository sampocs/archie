# Second Brain: Product Scope (v1)

> Working name is TBD: **Carl**, **Archie**, **Gary**, or **Ralph**. This doc says "Carl."
> Status: product scope only. Data sources, UI, and architecture come in later phases (see [Roadmap](#roadmap)).

## Why

I consume a lot of podcasts, newsletters, threads, and books, but it doesn't compound. Every episode feels new because there's nothing for it to attach to. The goal is **level 2 knowledge** across subjects I choose: enough to hold a real conversation with a stranger at a poker table.

| Level | Meaning |
|---|---|
| 1. Foreign | The vocabulary itself is unfamiliar |
| **2. Conversational** | **Can discuss it: the vocabulary, how it works, the players, rough numbers, current debates, and a take of my own. This is the target.** |
| 3. Expert | Needs hands-on experience and the knowledge that only comes from doing the work |

The core problem is **integration, not consumption**. Carl turns what I already consume into connected knowledge I can recall, and fills the foundational gaps that make content hard to follow.

## Principles

- **Mobile only.** I consume almost everything on my phone.
- **App-first, with chat inside it.** Structured screens for reviewing and browsing, plus chat for questions.
- **Foundations over facts.** Background knowledge (primers) matters more than one-off facts from an episode.
- **Calm.** One notification a day at most. Nothing should feel like homework.
- **Built for me, publishable to others.** I'm the main user. It ships on the App Store because TestFlight builds expire. Sign-in is Sign in with Apple only (Google can be added later). Other people can sign in too, but only whitelisted emails use my API keys, and everyone else brings their own. Onboarding friction for other users is acceptable. (Decided 2026-11-02.)
- **One reading voice.** Everything Carl writes (summaries, primers, Pulse, chat, card explanations) uses one style tuned to what I find easiest to read.

## Getting content in

1. **Share sheet** from any app (Podcasts, Spotify, YouTube, Safari, Substack, X):
   - **Finished**: optional "how'd it go?" (Easy / Mostly followed / Parts lost me) plus an optional typed or voice note on what was confusing.
   - **Queue it**: optional "Queue the primer too" (e.g. a spoiler-free primer for a book).
2. **Notes import**: years of existing notes become library items and go through the same processing.
3. **Newsletter ingest** (for Pulse): newsletters arrive automatically, e.g. through a forwarding address.

## Processing each source

Every source the user consumes goes through:

1. **Get the transcript or text**
2. **Summarize it**: the gist, key ideas, and numbers worth knowing, with timestamps where the source has them
3. **Categorize it**: place it under a domain → topic, creating the topic if it's new
4. **Tag it**: topics and **key concepts**. Concepts are recorded now so knowledge scoring can be added later without reprocessing.
5. **Build a primer**: the background this source assumes
6. **Generate review cards**
7. **Link it to related library items**

## Content states

| State | Meaning | Processing |
|---|---|---|
| **Queued** | I want to consume it | Primer reached from the item, or queued as its own entry |
| **Inbox** | Ingested automatically (newsletters), not seen yet | Indexed and searchable in chat, labeled unread. No cards |
| **Briefed** | Headline seen in Pulse | Counts as awareness only. No long-term cards |
| **Consumed** | Finished it, or tapped "Go deeper" | Full processing |

## Organization

- **Domains → Topics.** A short list of broad domains (AI, Macro, Crypto, Startups, Finance, History…), with unlimited topics underneath. Carl creates topics automatically, and I can add my own ("I want to understand how the Fed works").
- **Tags** (topics and concepts) on everything, for search and filters.

## Screens

Tab bar: **Today · Library · Review · Carl**

### Today
- **Pulse brief** (see below): a preview card that opens the brief
- **Review**: number of cards due and estimated time
- **Up next**: the top of my queue

### Library
- A four-way control under the title, **All · Domains · Saved · Takes**; search and filters belong to All.
- One list of everything: queued, in progress, consumed, inbox, and primers. Search bar on top. Filters for status, type, and domain/topic.
- **Item page**: gist, key ideas, numbers (timestamped), my reaction or notes, a primer section collapsed as "Background you might need," related items, the cards it produced, and an "Ask Carl about this" bar.
- **Domains view**: the Domains segment, showing domains → topics, each with its items.
- **Saved**: Favorites, a ★ on any library item (item page navbar, a gold ★ on its row), grouped by domain on Saved, each domain's favorites newest star first, swipe to unstar. **Collections**: just-for-fun scrapbooks saved from the add sheet's or share sheet's "Save to a collection" (a dropdown preselected to the last one used, ＋ New collection…), shown under Saved as tiles with a mosaic of the newest thumbnails and "N saved" (long-press to rename or delete). A collection page is a feed of posts (thumbnail, who posted it, where it's from, date saved, caption, note) that open the original; posts never appear in All, Domains, search, Today, Pulse, Ask or the pipeline. Takes is a placeholder until takes ship.

### ＋ (Add)
The ＋ in the Library header opens the add sheet: the same Finished / Queue flow as the share sheet, plus a third choice, **Save to a collection**.

### Review
- **Open recall only.** No multiple choice, because it gives away the answer.
- Answer by **typing or voice**. Voice goes through Groq Whisper with the card as vocabulary; the mic is hidden offline.
- **Graded on the idea, not the wording**, with three outcomes: *got it / partly / missed*. Grading is Haiku. After 3 seconds, on an error, or offline, the screen shows the model answer and I grade myself.
- **I can always override** a grade ("actually I knew that").
- *Partly* and *missed* show a short explanation of what was missing.
- **Tell Carl**: after any grade, I can say what I actually care about (e.g. "I mainly want to remember which agency is Soviet and which is British; the secret police part matters less"). That **rewrites the card's accepted answer** and informs future card generation.
- Swiping a card away as "don't care" removes it and teaches Carl what not to generate.
- **Spaced repetition** (FSRS) schedules cards from my answers and runs on the phone. Fast, correct answers mean I see the card less often.
- **Extra practice only brings cards sooner.** Reviewing ahead or practising a topic never pushes a card's due date later.
- **When cards join reviews**: a source's cards join once it's consumed. Foundation cards come from primers and topic primers and join once the primer is opened. A source with none shows "No cards for this".
- **Order within a session**: foundation cards from primers first, then mechanisms, then rough numbers. Trivia is avoided.
- **Keep going past today**: once the due cards are done, I can review ahead or practice a topic or source.
- **Works offline**: reviews, reading and capture all work without signal, for example on a plane, and sync when I'm back online.

### Carl (chat)
- Ask about anything in the library, including unread inbox items. Answers cite sources.
- Explains things in plain language and adds context ("is $400B a lot?").
- **Library first, then background, then the web.** Answers come from my library where possible, fill gaps from general knowledge, and search the web when needed (recent events, fast-changing facts) or when I ask ("look it up," or a toggle). Each part is labeled: *your library* / *background* / *web*, with links.
- **Edit through chat**: e.g. "remove this bullet from the summary." Edits create a new version, so the original is always kept and can be restored.
- Turns any answer into a card.
- Can be opened from any primer or item page, already knowing what I'm looking at.

## Primers

- **Always built** for every consumed or queued source, and always available on the item page.
- **A resource, not a task.** Reached from the item, or queued as its own queue entry (when I said "Parts lost me" or "Queue the primer"). Newsletters get one on request. Topic primers live on their topic page, with an unread dot in Domains.
- Written for a smart beginner: friendly, short (~5–8 min), no assumed jargon, spoiler-free for books and shows.
- v1 detects gaps from **my stated reaction plus what is or isn't already in my library**. There's no knowledge scoring yet.

## Cards

- Carl generates **3–5 cards per consumed source**, focused on concepts, mechanisms ("why does X cause Y"), and **rough numbers** ("~1 GW," not "1.07 GW").
- Cards are generated **regardless of what I already know**. Reviews take care of that.
- **Educational content only (decided 2026-10-31).** Entertainment, like a sports interview or banter, gets a summary and no cards. Educational parts of any show still get cards, e.g. NFL play schemes or how NFL contracts work. Carl decides per source, and per section within long episodes.
- **Calibration before launch**: from imported notes, pick ~10 examples, mark what I'd actually want to be quizzed on, and adjust card generation until it matches.

## Reading voice

- Before launch, Carl writes the same primer and summary in a few styles. I pick the easiest to read and refine it, and the result becomes a **style guide** applied to everything Carl writes.
- One voice in v1. A setting to change it can come later.

## Pulse (keeping up with the news)

The goal is to know the water-cooler topics in about 2 minutes, without reading every newsletter.

- Newsletters are ingested automatically into the **Inbox**.
- **The brief** sits at the top of Today as a preview card. It is rolling: it is rewritten in the background whenever a newsletter finishes processing, so it is ready (and works offline) when I open Today. One brief is open at a time.
- It covers **every unbriefed newsletter since the last Done**, however old, with no time window. Skipping three days (or three weeks) still produces one ~2-minute brief, kept short by ranking.
- **News newsletters are split into stories** and grouped by domain. Domains are ordered by their top story, and stories within a domain by importance. Up to 10 stories are shown in full (a headline plus 2-3 lines on what happened and why it matters); the rest are one-liners under "Also happening."
- **Essays are never split.** They are listed at the end under "Worth reading" (sender, subject, a one-line pitch, and a "＋ Queue" link) so several can be compared before choosing.
- **A story's page** has a longer detail paragraph and "Covered by": the newsletters that reported it, each opening its item page. Stories are awareness only: they never become library items or cards. Going deeper on a newsletter is the way to keep something.
- **Done ✓ marks exactly the newsletters shown as briefed** and closes the brief. Anything that arrived while I was reading starts the next one.
- One LLM call groups, ranks and writes each update; there are no embeddings yet (Search + chat, M7).
- **Weekly news quiz**: on Sundays, 5 cards from stories in briefs Done in the last 7 days, offered on Today. They **expire** after 7 days instead of entering long-term review.

## Notifications

- **One daily notification, for card reviews only**, at a time I choose: 8:30 PM by default, sent only when cards are due, set in Settings → Review reminder. It is a local notification only.
- No notifications for Pulse, primers, or reading check-ins.

## Out of scope for v1

- **Proactive feed** (v2): Carl finds new material to consume, ranked by my gaps. It reuses the Pulse and processing pipeline.
- **Knowledge scores and tier labels** (Foreign / Familiar / Conversational per topic). Concepts are captured now so scoring can be added later.
- **Growth vs. interest focus pins.**
- **Card selection for very large decks** (thousands of cards) beyond standard spaced repetition.
- Web or desktop clients, and Obsidian. A one-way markdown export could come later if I want a desktop view.

## Roadmap

1. **Product scope**: this doc.
2. **De-risk**: spike the big unknowns before committing to a design.
   - Podcast transcripts: Spotify links, Apple Podcasts links, and podcasts with no published transcript
   - YouTube transcripts
   - Reading X posts and threads without the expensive official API
   - Newsletter ingest (forwarding address vs. Gmail access) and paywalled Substack content
   - Books, which have no transcript (title knowledge, Kindle highlights, my notes?)
   - Importing my existing notes (format and source TBD)
   - iOS share sheet: probably requires a native app (or Expo/React Native), because a web app can't easily appear in the iOS share sheet
   - Answer grading quality: Jev (or similar) on real answers to real cards
   - Story grouping for Pulse: likely text embeddings plus clustering, with an LLM merging borderline cases. The same embeddings would also power Library search, chat retrieval, and related-item links
   - Voice answers: speech-to-text on device vs. through an API
3. **Finalize the product**: the exact interface, down to styling, plus the reading voice.
4. **Technical spec and backend**, then build.
