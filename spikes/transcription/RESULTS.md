# Spike: transcription quality on jargon-heavy podcasts (2026-10-26)

`uv run spikes/transcription/compare_transcription.py` (needs `GROQ_API_KEY` and/or `OPENAI_API_KEY` in `.env`)

The first 15 minutes of 5 episodes were transcribed by each provider. Four have published VTT transcripts used as the reference: Bankless (crypto), Money Stuff (finance), Darknet Diaries (security), and Acquired (business). 0xResearch (niche crypto) has none. Every provider ran with two hint styles:
- **basic:** show name and hosts
- **rich:** also the episode title and description from the feed

## Results: 75 min of audio per run

| Provider / hint | Bankless | Money Stuff | Darknet | Acquired | Time | Cost |
|---|---|---|---|---|---|---|
| groq whisper-large-v3-turbo / basic | 5.7% · skip 55† | 8.7% · skip 57† | 9.2% · 0 | 3.4% · **skip 84** | **12 s** | **$0.05** |
| groq whisper-large-v3-turbo / rich | 13.3% · **skip 383** | 12.8% · 39 | 9.5% · **skip 971** | 6.9% · **skip 145** | 21 s | $0.05 |
| openai gpt-4o-mini-transcribe / basic | 13.7%‡ · 0 | 9.4% · 68† | 10.2% · 0 | 1.8% · 0 | 127 s | $0.23 |
| openai gpt-4o-mini-transcribe / rich | 12.4%‡ · 0 | 8.8% · 84† | 9.6% · 0 | 1.7% · 0 | 108 s | $0.23 |
| openai gpt-4o-transcribe / basic | 6.3% · 0 | 10.2% · 86† | 9.6% · 17 | 1.8% · **skip 353** | 186 s | $0.45 |
| openai gpt-4o-transcribe / rich | 6.1% · 18 | 9.7% · 54† | 9.8% · 0 | 3.3% · 0 | 171 s | $0.45 |
| ~~groq whisper-large-v3~~ (first run) | dropped 15–40% of words everywhere | | | | | |

Each cell is word-level disagreement with the published transcript (ads excluded) · words in skipped passages (runs of 15+ missing words).
- † Every provider "skips" roughly the same passage here. It's text in the published transcript that isn't in our audio (e.g. a sponsor read), not a model failure.
- ‡ Mostly insertions of filler speech ("I don't know if", "you don't have to") that the published transcript leaves out. The published transcripts look Whisper-generated themselves, which biases this score toward Whisper.

**Known jargon** (count of correct spellings):
- **No provider got these at all:** *Tyce* (Brown), *Dyre* (malware), *Morpho*, and *Uniswap* in Bankless.
- **Every provider got about the same share** of *Conti*, *Handy Dan*, *Arthur Blank*, *Bernie Marcus*, *mNAV*, and *Aerodrome*.
- **Rich hints helped OpenAI a little** with *Citrini* (0 → 1–2 mentions).
- An earlier note claiming turbo wrote *Aerodrome* as "Eredrum" was wrong. That was large-v3. Turbo spelled it correctly.

## Takeaways

1. **Accuracy is roughly a tie.** All three usable models land at about 2–10% word-level disagreement, and the reference itself is imperfect. None of them reliably gets rare names right.
2. **Skipped passages are the real difference.** Turbo skipped one real passage (Acquired's 84-word intro) and gpt-4o-transcribe skipped 353 words on Acquired with the basic hint. **gpt-4o-mini-transcribe skipped nothing real** in either hint style.
3. **Never give Whisper long prompts.** The rich hint made turbo skip hundreds of words and produce garbage ("AeskwakanIROBEZIERCHEK", ALL-CAPS runs). Whisper gets a short hint only. OpenAI models tolerate the rich hint and benefit slightly.
4. **Hints don't fix names. A cleanup pass has to.** Claude gets the episode title and description, the show's saved vocabulary, and web search when needed, and returns a **list of corrections** ("Ty Sprown" → "Tyce Brown") that code applies. It doesn't rewrite the transcript. This can be folded into the summarization call.
5. **Cost and speed:** turbo ~$0.04/hr and 10× faster. mini ~$0.18/hr. Both are fine for background jobs. At ~43 hrs/mo that's **~$2 vs ~$8**.

## Recommendation

**Primary: `gpt-4o-mini-transcribe` with the rich hint**, because it was the most complete (no skips), and **Groq turbo with the basic hint as the cheap fallback**. Both use the same OpenAI-compatible API, so switching is a config change. Names get fixed by a Claude corrections pass.

## Still to test

- The Claude corrections pass: how many known terms (Tyce, Dyre, Citrini, Morpho) does it recover, and does it introduce wrong "fixes"? Needs `ANTHROPIC_API_KEY`.
- Chunk size versus skips for turbo, if we ever want turbo as primary.
