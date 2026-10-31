# Spike: LLM processing cost per hour of content (2026-10-31)

`uv run spikes/llm_processing/process_sources.py` (needs `ANTHROPIC_API_KEY`). Every output is in `outputs/<show>.md`, side by side by model.

## Setup

- **5 full episodes, 8.0 h of audio in total:** the latest episode with a published transcript from each test show.

  | Show | Episode | Length |
  |---|---|---|
  | Bankless | the Binance hack | 0.5 h |
  | Money Stuff | the Anthropic IPO, options | 0.6 h |
  | Darknet Diaries | Conti | 1.0 h |
  | Bussin' | Best of the Bus | 2.3 h |
  | Acquired | The Home Depot | 3.6 h |

- **Input:** the published transcript, grouped into timestamped lines every ~30 s. This stands in for the Groq transcript: it's the same length, so it costs the same.
- **Steps, each run on two models:**
  - **Analyze** (one call, structured JSON): summary with timestamps, domain → topic, tags, concepts, and 3–5 cards. Run on Haiku 5.5 and Sonnet 5.5.
  - **Primer** (one call, markdown, a 5–8 min read): the background the episode assumes. Run on Sonnet 5.5 and Opus 5.5.
- **Reading voice:** a neutral placeholder, since the real style guide isn't written yet. No extended thinking and no prompt caching.

## Results

| Step | Model | $ per audio hour | $/mo at 43 h |
|---|---|---|---|
| Analyze | **Haiku 5.5** | **$0.003** | **$0.13** |
| Analyze | Sonnet 5.5 | $0.068 | $2.91 |
| Primer | **Sonnet 5.5** | **$0.067** | **$2.90** |
| Primer | Opus 5.5 | $0.130 | $5.60 |

**Whole pipeline per month at 43 h** (Groq transcription + Haiku name corrections + analyze + primer):

| Analyze + primer | List price | Batch API (50% off LLM) |
|---|---|---|
| **Haiku + Sonnet** | **$5.61** | **$4.10** |
| Haiku + Opus | $8.31 | $5.45 |
| Sonnet + Sonnet | $8.39 | $5.48 |
| Sonnet + Opus | $11.09 | $6.83 |

Input dominates: about 23k tokens per audio hour, compared with 2–4k output tokens per call.

## Quality (read by hand)

- **Analyze:**
  - **Haiku is close to Sonnet.** Its summaries, timestamps, concepts and categorization are all sound. Sonnet's key ideas are a bit richer and more nuanced.
  - **Haiku's cards are often better for review.** They're single, focused questions. Sonnet tends to write compound cards ("How big was X, *and* what did Y involve?"), which are harder to recall and grade.
  - **Haiku's misses:** it sometimes returns 4 cards instead of 5, and it once labeled a non-number card as "number".
- **Primers:**
  - **Both are good,** at about 1,100 words each. They pick out the right background (GAAP vs non-GAAP, call options, equity as an option, Delaware vs Texas, onion futures), and they don't recap the episode.
  - **Opus is slightly more polished** and adds useful outside context (e.g. Kalshi and Polymarket, the 2024 Delaware ruling on Musk's pay package). The gap is small.
- **Opus stopped mid-primer on Darknet Diaries.** The episode is about the Conti ransomware gang. Opus ended with `stop_reason: refusal` about 350 words into a harmless explainer on how ransomware crews operate. Sonnet wrote the whole primer. Security is one of your domains, so **the pipeline must treat a refusal as a failure and retry on another model.**
- **Banter-heavy shows produce trivia cards.** Bussin' gave cards like "What is a stinger?" and "Why did Merriman play with a 'see ball, go ball' plan?" These are on-topic, but they aren't level-2 knowledge you'd care to keep. Either sports shows get no cards, or "Don't care" will see a lot of use. **This is a product decision.**
- **Domains:** analysis picked AI vs Finance for Money Stuff and Startups vs "Other" for Acquired. Categorizing needs the user's real domain list, and some way to file one source under two domains.

## Recommendation

- **Analyze on Haiku 5.5. Primers on Sonnet 5.5, falling back to Opus on a refusal or truncation, or the reverse.** That's about **$6/mo** at list price, or **$4/mo** if podcasts go through the Batch API, including transcription. That's well under the ~$15/mo planned in the findings doc, which leaves room for Pulse, chat and grading.
- **Upgrading primers to Opus later costs about $2.70/mo.** Decide by reading primers once the reading voice exists, not now.
- **Later savings, not needed yet:**
  - Primer and analyze could share one cached transcript prefix on the same model.
  - Primers could be built only when asked for ("Parts lost me" or "Prep me") instead of always. That cuts most of the primer cost, but the product scope says "always built".
