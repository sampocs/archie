# Spike: grading typed recall answers with an LLM (2026-11-04)

For M6 (cards + review). Question: can a model grade a typed or dictated answer "on the idea, not the wording" (got it / partly / missed, plus what was missing) accurately, cheaply and fast enough to feel instant (target under ~1.5 s)?

## Method

- **Cards:** all 27 distinct cards found in the recorded analyze outputs under `services/*/tests/**/cassettes` (`extract_cards.py` -> `cards_all.json`). Kinds: 12 mechanism, 9 concept, 6 number; sources: Money Stuff/Morning Brew, a Netflix newsletter, a Paul Graham essay (two runs), Darknet Diaries, a Fed press conference. (The recorded cards have no `foundation` kind.)
- **Answers:** 124 hand-labelled answers (`build_dataset.py` -> `dataset.json`): per card one correct answer in different words, one correct but terse and typo-ridden "dictation" answer, one half-the-idea answer, one plausible-but-wrong answer; plus 10 extras (numbers within precision, near-miss numbers, vague answers) and 6 blank / "I don't know" answers. Expected: 60 got_it, 25 partly, 39 missed. A wrong number counts as missed.
- **Grader:** one Messages API call per answer, `output_config` JSON schema `{grade, missing, confident}` (the same mechanism `llm.py` uses), no extended thinking (`thinking: disabled` on Haiku, `between_tools` on Sonnet, whose default is to think; Opus accepts neither and ran with defaults), 4 calls in parallel. Models and prices from `llm.py` (Haiku $0.10/$0.50, Sonnet $2/$10, Opus $4/$20 per M tokens). No prompt caching (the prompt is only ~850 tokens).
- **Variants:** Haiku 5.5, Sonnet 5.5, Haiku + 1-shot example, Opus 5.5 on the 8 answers either of the first two got wrong.
- Latency is wall-clock time for the complete (non-streaming) response, from a laptop, n=124.

## Results

| Variant | Accuracy | got_it | partly | missed | p50 | p90 | $/grade |
|---|---|---|---|---|---|---|---|
| **Haiku 5.5** | **95.2%** (118/124) | 58/60 | 23/25 | 37/39 | **0.96 s** | **1.35 s** | **$0.00011** |
| Haiku 5.5 + 1-shot | 97.6% (121/124) | 58/60 | 25/25 | 38/39 | 0.98 s | 1.36 s | $0.00013 |
| Sonnet 5.5 | 98.4% (122/124) | 60/60 | 23/25 | 39/39 | 1.56 s | 3.93 s | $0.00217 |
| Opus 5.5 (8 disputed only) | 5/8 | | | | 1.83 s | 2.63 s | $0.00502 |

Confusion matrices (rows expected, columns graded; got_it / partly / missed):

| | Haiku | Haiku 1-shot | Sonnet |
|---|---|---|---|
| expected got_it | 58 / 2 / 0 | 58 / 2 / 0 | 60 / 0 / 0 |
| expected partly | 2 / 23 / 0 | 0 / 25 / 0 | 2 / 23 / 0 |
| expected missed | 0 / 2 / 37 | 0 / 1 / 38 | 0 / 0 / 39 |

No variant ever confused got_it with missed or the reverse: every error is an adjacent grade. Cost at 124 grades per variant: Haiku about $0.014, Sonnet $0.27, Opus (8 calls) $0.04.

**Where the errors are.** 
- Haiku's 2 got_it -> partly errors are the number cards (`about 45% ... roughly 20 times faster` against 46% / 22x, and `about 4 hours` because it wanted the "contiguous blocks" detail). It is a little strict about secondary detail and about numbers. The 1-shot example did not fix this; it fixed the "partly graded as got_it" errors instead.
- The remaining errors are mostly label noise: Sonnet's only 2 errors, and Opus's disagreement on 3 of the 4 `partly` ones, are answers I labelled partly that are defensible as got_it ("People are unhappy with the president so they vote against his party", "They hacked the system ... and turned on defrost mode"). Treat the ceiling as roughly 98-99%.
- Haiku/1-shot's `missed -> partly` errors are plausible-but-wrong answers that mention the right topic ("memory leaks" for the LLM-performance card), which the grader credits as half.
- `missing` was filled for 100% of partly/missed grades and empty for every got_it. The sentences are specific and usable, but Haiku sometimes runs long (two clauses, over the 20-word limit).

**Confidence flag.** Useless in this test: `confident=false` was returned once in 124 on Haiku's first, discarded run (a forced-tool-call version of the same prompt; that grade was correct) and 0 times in every final run, for all models. Low confidence therefore can't be shown to correlate with errors (the 3-6 errors per variant were all reported confident). The model is not good at introspecting about its own uncertainty with this prompt, and my dataset has few truly ambiguous answers. See recommendation.

## Recommendation

- **Use Haiku 5.5 with the 1-shot prompt for grading.** 97.6% agreement with my labels at about $0.00013 a grade (a 100-card day costs about 1.3 cents; Sonnet would be about 22 cents), p50 0.98 s and p90 1.36 s for the complete response. The output is only ~43 tokens, so streaming wouldn't help; the time is mostly network + time to first token. Sonnet is slightly more accurate (98.4%) but 16x the cost and its p90 of 3.9 s misses the 1.5 s target.
- **Is it "feels instant"?** Borderline but acceptable: p50 under 1 s, p90 about 1.4 s from a laptop. Hide the latency by starting the grade call on submit and showing the model answer / animation immediately, and reveal the verdict when it lands. Requires being online; offline reviews need self-grading (as the product scope says).
- **Do not rely on `confident` as it stands.** Keep it in the schema if wanted, but the "when it isn't confident, show the model answer and grade myself" path should also trigger on cheap structural signals: a request failure or timeout (over ~3 s), and answers that are near the border (e.g. grade `partly` on a number card). Optionally escalate `partly` grades to Sonnet or Opus in the background, since that is where models and labels disagree. The owner's override ("actually I knew that") is the real safety net; a Haiku error is always one grade off, never got_it vs missed.
- The prompt should receive the card's question and accepted answer, and a 4-5 line few-shot block costs only about 180 extra input tokens.

## Caveats

- Expected labels, and the wrong/partial answers, were written by an LLM (Claude), not by the owner, and not reviewed by a second person. About 3 of the disputed `partly` labels are debatable; the accuracy numbers carry that noise.
- 124 answers over 27 cards: one error is 0.8 points, so Haiku-1shot (97.6%) and Sonnet (98.4%) are not distinguishable. The 1-shot gain over plain Haiku (+2.4 points) is 3 answers, and the 1-shot variant was added after seeing Haiku's errors, so its gain is partly tuned to this dataset.
- Answers are idealised: real dictation produces homophones, run-ons and half-sentences that are more ambiguous than my "sloppy" examples. Real owner answers are also likelier to be correct-but-different (adding extra true facts) or partially remembered in less tidy ways.
- Cards from the recorded set are all mechanism / concept / number; no `foundation` kind and no cards on the owner's real topics.
- Latency was measured from one laptop and one network over a single run, with 4 parallel calls; production latency from Railway to Anthropic may differ, and a cold connection adds a few hundred ms. No prompt caching was used.
- Opus ran with default settings (it rejects both ways of disabling thinking), which makes its latency and cost not directly comparable.
- Total spend of the spike: about $0.50, including a few aborted runs.

## Files

- `extract_cards.py`, `cards_all.json`: the cards pulled from cassettes.
- `build_dataset.py`, `dataset.json`: the labelled answers.
- `grade.py`: the grader (`uv run --package archie-worker python spikes/card_grading/grade.py haiku sonnet haiku_1shot opus`; reads `ANTHROPIC_API_KEY` from the environment or the repo-root `.env`).
- `analyze.py`: the tables above (`uv run python spikes/card_grading/analyze.py haiku sonnet haiku_1shot opus -v`).
- `results_*.json`: per-answer grades, latency, tokens and cost.

## The prompt as tested

System prompt (all variants):

```
You grade a typed or dictated recall answer to a spaced-repetition flashcard.

Judge the IDEA, not the wording. Be lenient on phrasing, word order, typos, missing punctuation, dictation errors and terseness. Be strict on the core idea: the answer must contain the essential point(s) of the accepted answer and must not contradict them.

Grades:
- got_it: the answer carries the core idea of the accepted answer, in any words. Minor omitted detail is fine.
- partly: the answer is correct as far as it goes but misses an essential part of the idea (for example gives what but not why, or only one of several required parts), or is too vague to show real understanding.
- missed: the answer is wrong, contradicts the accepted answer, is off-topic, or is blank / "I don't know".

Numbers: right if within roughly the precision of the accepted answer (about 5% unless the card says "roughly"/"about", then about 15%). A wrong order of magnitude is missed.

`missing`: for partly and missed, ONE short sentence (under 20 words) saying what the answer lacked or got wrong, addressed to the learner without quoting the whole accepted answer. Empty string for got_it.

`confident`: false only if you genuinely cannot tell whether the answer matches the idea (ambiguous wording, answer might be right under another reading, or the accepted answer itself is unclear). Otherwise true. Do not mark a clear miss or a clear match as not confident.
```

Appended for the 1-shot variant:

```
Example
Question: Why does a regular fridge stay cold when the door is closed?
Accepted answer: The insulated door seal traps cold air, and the compressor only runs to remove the small amount of heat that leaks in.
Answer: "cuz the seal keeps the cold in and the motor kicks on once in a while"
Grade: got_it (the seal and the intermittent compressor are the core idea; wording is casual).
Answer: "The compressor keeps running."
Grade: partly, missing "It doesn't say the insulated seal is what keeps heat out."
```

User message:

```
Question: <card question>
Accepted answer: <card answer>
Answer: <typed answer, repr-quoted>
```

Output schema: `{grade: "got_it" | "partly" | "missed", missing: string, confident: boolean}`.
