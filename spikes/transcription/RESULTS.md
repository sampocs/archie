# Spike: transcription quality on jargon-heavy podcasts (2026-10-26)

`uv run spikes/transcription/compare_transcription.py` (needs `GROQ_API_KEY` and/or `OPENAI_API_KEY` in `.env`)

The first 15 minutes of 5 episodes were transcribed. Four have published VTT transcripts used as the reference: Bankless (crypto), Money Stuff (finance), Darknet Diaries (security), and Acquired (business). 0xResearch (niche crypto) has no published transcript and is compared by eye. Each request got a short vocabulary hint naming the show and its hosts.

**OpenAI not yet tested:** the account had no API credits (`credit_balance_exhausted`). Rerun once credits are added.

## Results (Groq)

| | Bankless | Money Stuff | Darknet Diaries | Acquired | Speed | Cost (75 min) |
|---|---|---|---|---|---|---|
| **whisper-large-v3-turbo**: word-level error* | 5.7% | 8.7% | 9.2% | 3.4% | ~12 s total | ~$0.05 |
| turbo: real content skipped | 0 | 2 passages (57 words) | 0 | 1 passage (84 words) | | |
| **whisper-large-v3** | silently dropped **15–40% of all words** on every episode | | | | ~19 s | ~$0.14 |

\* Ads that are in the audio but not in the published transcript (or the reverse) are excluded. Many remaining "errors" are harmless contractions (`it's → it`, `gonna → going to`). The published transcripts are probably machine-generated too, so this measures disagreement, not ground truth.

## Takeaways

- **whisper-large-v3 is unusable as-is.** It drops big stretches of audio. The cheaper turbo model is far better.
- **Turbo is good enough for summaries** (3–9% word-level disagreement, 75 min of audio in ~12 s, ~$0.04/hr), but it **occasionally skips a sentence or two** (2 of 4 episodes). That's tolerable for summaries but a risk for "find that exact number."
- **Jargon and names are the weak spot.** Turbo got these wrong:
  - *Tyce Brown* → "Ty Sprown"
  - *Janus Henderson* → "Janice Henderson"
  - *ChatGPT* → "Chachi PT"
  - *mNAV* → MNAP / MNEV / MNIV
  - *Dyre* (malware) → "Dyer"
  - 0xResearch: *Citrini* → "Citrine" / "Saturini", *Aerodrome* → "Eredrum", *Uni v4* → "Unifor"
- **Fix to try in production:** build the vocabulary hint from the **episode title and description** plus the show's past proper nouns, not just the show name. "Citrini" was in the episode title, but this spike's hint didn't include it. Claude can also fix obvious misspellings while summarizing, given the episode description.

## Still to test

- OpenAI `gpt-4o-mini-transcribe` and `gpt-4o-transcribe` on the same clips (needs credits). The questions: fewer skips? better jargon?
- Whether smaller chunks or a voice-activity split stop turbo from skipping passages.
- Hint built from the episode description: does it fix names like Citrini and Aerodrome?
