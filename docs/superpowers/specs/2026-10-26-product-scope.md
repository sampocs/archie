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
   - **Queue it**: optional "Prep me before I start" (e.g. a spoiler-free primer for a book).
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
| **Queued** | I want to consume it | Primer available through "Prep me" |
| **Inbox** | Ingested automatically (newsletters), not seen yet | Indexed and searchable in chat, labeled unread. No cards |
| **Briefed** | Headline seen in Pulse | Counts as awareness only. No long-term cards |
| **Consumed** | Finished it, or tapped "Go deeper" | Full processing |

## Organization

- **Domains → Topics.** A short list of broad domains (AI, Macro, Crypto, Startups, Finance, History…), with unlimited topics underneath. Carl creates topics automatically, and I can add my own ("I want to understand how the Fed works").
- **Tags** (topics and concepts) on everything, for search and filters.

## Screens

Tab bar: **Today · Library · ＋ · Review · Carl**

### Today
- **Pulse brief** (see below)
- **Review**: number of cards due and estimated time
- **Primers ready**: only the ones pushed to me (see Primers)
- **Up next**: the top of my queue, with "Prep me" on each item

### Library
- One list of everything: queued, in progress, consumed, inbox, and primers. Search bar on top. Filters for status, type, and domain/topic.
- **Item page**: gist, key ideas, numbers (timestamped), my reaction or notes, a primer section collapsed as "Background you might need," related items, the cards it produced, and an "Ask Carl about this" bar.
- **Domains view**: a toggle at the top of Library showing domains → topics, each with its items.

### ＋ (Add)
The same Finished / Queue flow as the share sheet, for pasting links or searching books and podcasts by hand.

### Review
- **Open recall only.** No multiple choice, because it gives away the answer.
- Answer by **typing or voice**.
- **Graded on the idea, not the wording**, with three outcomes: *got it / partly / missed*. A fast, typed-output model like Jev looks like the right fit. When it isn't confident, the screen shows the model answer and I grade myself.
- **I can always override** a grade ("actually I knew that").
- *Partly* and *missed* show a short explanation of what was missing.
- **Tell Carl**: after any grade, I can say what I actually care about (e.g. "I mainly want to remember which agency is Soviet and which is British; the secret police part matters less"). That **rewrites the card's accepted answer** and informs future card generation.
- Swiping a card away as "don't care" removes it and teaches Carl what not to generate.
- **Spaced repetition** (e.g. FSRS) schedules cards from my answers. Fast, correct answers mean I see the card less often.
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
- **Pushed to Today only** when I said "Parts lost me" or tapped "Prep me." Otherwise they're opened on demand.
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
- Carl **groups coverage by story, not by newsletter**, then ranks by importance (how widely covered, how big) and relevance (my domains), and drops the noise.
- **The brief** sits at the top of Today: the top 5–8 stories, each with 2–3 lines on what happened and why it matters. "Go deeper" either queues the full piece or opens it as a consumed library item. Everything else is collapsed under "Also happening."
- **The brief covers "since you last checked,"** so it never stacks up. Skipping three days produces one ~2-minute brief.
- **Weekly news quiz**: a few short cards on the week's stories. They **expire** instead of entering long-term review.

## Notifications

- **One daily notification, for card reviews only**, at a time I choose.
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
