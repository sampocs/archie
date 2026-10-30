# Spike: transcription quality on jargon-heavy podcasts (2026-10-29)

`uv run spikes/transcription/compare_transcription.py` (needs `GROQ_API_KEY` and/or `OPENAI_API_KEY` in `.env`)

**Decision rule:** pick a model only if it's better beyond random chance; otherwise pick the cheapest of the top group.

## Setup

- **20 episodes**, each scored against its published transcript: 5 Bankless, 5 Money Stuff, 5 Darknet Diaries, 4 Bussin', and 1 Acquired (the only Acquired episode with a transcript).
- **Audio:** the first 15 minutes of each episode (5 h in total), cut into 10-minute chunks.
- **Five setups:**
  - Groq whisper-large-v3-turbo with the basic hint. Rich hints were dropped because they derailed it in the first spike.
  - gpt-4o-mini-transcribe with the basic hint and with the rich hint.
  - gpt-4o-transcribe with the basic hint and with the rich hint.
- **Significance:** a paired sign test for each pair of setups, counting the episodes where each did better. p < 0.05 counts as a real difference.

## Results

| Setup | Median error | Mean error | Episodes with real skips | Words skipped | Cost per audio hour |
|---|---|---|---|---|---|
| **groq turbo / basic** | 5.5% | 6.7% | **5** | **457** | **$0.04** |
| 4o-mini / basic | 5.2% | 6.2% | 14 | 1728 | $0.18 |
| 4o-mini / rich | 5.2% | 6.0% | 12 | 1389 | $0.18 |
| 4o-transcribe / basic | 5.3% | 6.3% | 11 | 1855 | $0.36 |
| 4o-transcribe / rich | 5.3% | 6.5% | 12 | 2171 | $0.36 |

- **Error** is the share of words that disagree with the published transcript, with ads excluded.
- **Skipped words** count only what a setup missed beyond the episode's baseline. The baseline is the smallest skip any setup had on that episode, because text that every setup misses is reference text that isn't in our audio.

**No pair is significantly different on accuracy.** The closest is turbo vs 4o-mini/rich: mini did better on 14 of 19 episodes, p = 0.064. **No pair is significantly different on skips either.** Turbo vs 4o-mini/basic is 12/5, p = 0.14.

## Findings

1. **Accuracy is a statistical tie.** OpenAI leans slightly better (5.2% vs 5.5% median), but 20 episodes can't separate them. The published transcripts look Whisper-made, which, if anything, biases the scores toward turbo.
2. **OpenAI truncates long chunks.** gpt-4o-(mini-)transcribe stops at about 1,600–1,800 words per request. When a 10-minute chunk holds more speech than that (Bussin' at about 185 words/min, some Money Stuff), the end of the chunk is silently dropped: 200–360 words on every Bussin' episode, in all four OpenAI setups. Groq returned the whole chunk every time. If OpenAI is used, chunks must be 5 minutes or shorter.
3. **The first spike's "mini never skips" was luck.** With 20 episodes, mini skipped as often as the others.
4. **Rich hints don't measurably help** OpenAI (mini basic vs rich: p = 0.26).
5. **Names are still a weak point everywhere.** No setup wrote *Dyre*, and *Hyperliquid* was missed. OpenAI got *Morpho* and *Uniswap* once each where turbo got none, but turbo wrote *Rhysider* correctly (6 of 6) where OpenAI never did. The hint helps Whisper with names that are in it. The Claude corrections pass is still needed.
6. **Correction from the first spike:** the Money Stuff guest is *Tice* Brown (per the episode title). The published transcript's "Tyce" was the error, not the models'.
7. **A skip detector based on speaking rate only catches catastrophic failures.** Normal chunks run 159+ words/min (10th percentile), and 2 runs collapsed to 7 and 23 words/min. A check for chunks under about 100 words/min catches those collapses. Skips of 30–300 words don't change the rate enough to detect.
8. **A scoring bug was fixed.** The reference is deliberately longer than the clip. A stray matching word in that extra tail used to make the whole tail count as "skipped". Scoring now trims to the first and last runs of 8+ matching words.

## Recommendation

**Groq whisper-large-v3-turbo with a short hint** (show, hosts, and the show's known vocabulary), at about $0.04 per audio hour, or **about $2/mo** at 43 h. Nothing is significantly better, and it's the cheapest.
- **Fallback:** if Groq errors, or a chunk comes back under about 100 words/min, rerun that chunk on gpt-4o-mini-transcribe with 5-minute chunks.
- **Names:** a Claude corrections pass fixes them, using the episode description, the show's vocabulary, and web search.
