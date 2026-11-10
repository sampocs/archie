# Short card answers, and the note beside its chat

Mocks: `2026-11-10-short-card-answers-mocks.html` (approved). Eval of the rules below: two rounds with the owner on
real notes, sources and a brief (round 2 approved, with the three-line allowance added).

## Why

Card answers grew into paragraphs (1-3 sentences, more for chat note cards, whose rules set no length). The grader
compares a recall answer against the whole paragraph and marks a fair, short answer Partly for leaving out the
rest: "real time apps" for "When would you choose Convex?" should be Got it. And while shaping a note's cards in the
Make-cards chat, the owner can't see the note without leaving the chat.

## What changes

1. Every card has a short **answer** (what is graded) and a **detail**: 0-3 bullet lines shown after answering,
   never graded.
2. Every card writer follows one shared set of rules for both.
3. The grader grades against the answer only, counts an answer that shows the idea without its words, and treats the
   detail as background.
4. The review result, the chat proposal, Ask's card edits and versions show the detail.
5. The Make-cards chat: "‹ <note>" back label when opened from a note, a tappable About chip that pulls up the item's
   write-up (and original note) in a sheet, and no "Background" label over a reply that sits beside a proposal.

Existing cards: production has none live, so there is no backfill. A card without detail shows exactly as today.

## The card rules (shared by every writer)

One constant in `archie_llm` (both the worker and the API import it), worded as eval round 2 plus the three-line
allowance:

- **question:** ONE focused question with ONE thing to recall. Never join two asks with "and" ("What does X give you,
  and what can you lose?" is two cards, or pick one). Ask only what has a short answer.
- **answer:** the one thing to recall, in as few words as carry it: a phrase, not a sentence. Aim for 2-8 words,
  never more than 15. The learner is graded only on this, so it is what someone who knows the material would say off
  the top of their head. When two things are both essential, name both briefly ("Supply and demand"). A number
  card's answer is the rough figure with its unit.
- **detail:** 0-3 short bullet lines, each under 12 words. Shown after the learner answers, never graded; every line
  is more to read, so add one only when it carries something worth remembering on its own: the why behind the
  answer, a contrast or example that makes it stick. Most cards need 0 or 1, and most number cards none; use 2 or 3
  only when they genuinely build the explanation (a short chain: A happens, so B, so C). Never a line that restates
  or is implied by the answer; that is trivia from this one source (who said it, when, a passing example or
  anecdote) rather than a lasting fact about the subject; or that is a side remark that doesn't help recall.

Writers that adopt it, replacing their own answer-length wording (and their "1-3 sentences"):

| Writer | Where | Today |
|---|---|---|
| Summary cards | `worker/prompts.py` ANALYZE system + `ANALYSIS_SCHEMA.cards` | 1-3 sentences |
| Foundation cards (source + topic primer) | `FOUNDATION_CARDS_INSTRUCTIONS`, `FoundationCard` | 1-3 sentences, JSON in tags |
| Note cards (worker) | `NOTE_CARDS_SYSTEM` (schema reuses analysis cards) | 1-3 sentences |
| Take cards | `TAKE_CARDS_SYSTEM`/schema | 1-3 sentences of the take's words; detail too may use only the take's claims |
| News quiz | `NEWS_QUIZ_SYSTEM`/schema | 1-2 sentences |
| Chat card sets | `ask/prompts.py` `CARD_SET_RULES`, `card_set_tools` propose_cards | no rule |
| Ask card edits | `edit_tools` propose card edit | question + answer |

Every structured output gains `detail: string[]` (required, may be empty). Prompt-version constants that exist
(`NOTE_CARDS_PROMPT_VERSION`, …) bump.

## Storage and wire

- `cards.detail` and `card_versions.detail`: `Text NOT NULL DEFAULT ''`, the lines joined by `\n` (a line never
  contains a newline; writers strip them). One migration.
- Card content shape (`archie_db.versions`): `{question, answer, detail}`; `detail` is optional on read (older
  versions and proposals lack it → `""`), always written. Snapshot, restore and `_write_card` carry it; a card's
  first change writes version 1 with the card's detail.
- `card_set_proposals.cards` items: `{kind, question, answer, detail: string[]}`; missing → `[]`. Save copies it to
  the card. The kept-card match stays on (question, answer).
- Pull: `CardOut` and the card-version row gain `detail: str`. Card-set rows already ship `cards` as JSON.
- Phone: drizzle migration `0018` adds `detail TEXT NOT NULL DEFAULT ''` to `cards` and `card_versions`; the engine
  writes it (absent from an older server → `""`). A shared `detailLines(detail: string): string[]` splits and drops
  blanks.

## Grading and care

- `GRADE_SYSTEM` becomes eval round 2's grader: grade only against the accepted answer; "More" (the detail) is never
  required and saying something true from it is not wrong; partly also covers "only true side facts from More that
  don't lead to the idea"; an answer that shows the idea by its reasoning or by saying something that plainly amounts
  to it is got_it, with the Sequoia example. Keep the numbers rule, `missing` and `confident` as today. Its one-shot
  example is rewritten for a short answer. `grade_message` adds a `More (not required):` block when the card has
  detail. Model unchanged (Haiku).
- Care ("What I care about…"): may draw from the answer and the detail, returns a new short answer under the same
  answer rule; the detail stays. Its 1-3 sentence wording goes.
- The answer-transcription prompt keeps question + answer only.

## App

**Review result** (`GradedCard`, `GradingCard`, `SelfGradeCard` via `AcceptedAnswer`): the ANSWER label, the answer
in `readingBody` set semibold, then, when there is detail, a hairline and the lines as bullets (`secondary`, ink2,
"•" in ink3), as in mock 1 (recommended). No detail → exactly today's layout.

**Card set proposal** (`CardSetProposal`): `ListRow` shows the answer in ink (`secondary`) with the bullets under it
in ink3; `CardFace` shows the answer under the dashed rule with the bullets beneath. Struck (unkept) cards dim both.

**Card edits and versions** (`edits/content.ts`, `VersionPreview`, `EditProposalCard`): the card shape gains
`detail`; the preview lists `Detail:` lines after the answer when present, so a detail-only edit shows a change.

**Make-cards chat** (`app/ask/[id].tsx`):
- Back label: `fromNote` set → `‹ <aboutTitle>` (ellipsized by the nav bar); otherwise `‹ Ask`. Back behaviour is
  unchanged (`router.back`, which already returns to the note).
- About chip: when the chat is about a source that is still live, "About: X" becomes a chip (surface, line border,
  `▤ About: X ›`, testID `chat-about`) that opens `ItemSheet`; about anything else (topic, take, or a gone source) it
  stays plain text as today.
- `ItemSheet` (new, `app/src/ask/ItemSheet.tsx`, on `BottomSheet`): kicker (`Notes · Domain` / the source's kind
  kicker), title, the write-up via a shared `SummarySections` extracted from `app/source/[id].tsx` (moved, not
  copied, to `app/src/item/SummarySections.tsx` with `SectionTitle`/`TimestampChip` it needs), scrollable to ~75% of
  the screen; Done and the backdrop close it. For a note with `noteMarkdown`, "See original note ›" switches the
  sheet's body to the original (headline "Your original note", "From Bear · last edited …", markdown) with "‹ Write-up"
  to go back. No write-up yet → the original note's markdown (as the note page does). Works offline (all synced).
- Background label: an answer that carries a card set or an edit proposal drops the kicker of any uncited
  `background` section (`AnswerView` gets a `quietLabels` prop the screen sets when the message has proposals or
  card sets, stored or live).

## Testing

- Python: re-record the cassettes whose prompts change (analyze/primer, topic primer, note cards, take cards, news
  quiz, grade, care, chat card sets, card edits), a few cents. E2E assertions: cards come back with short answers and
  a `detail` list stored as joined lines; a card-set save copies detail; a card edit and restore carry detail; pull
  ships `detail`. Unit: `versions` reads an old content without detail; the proposal parser tolerates missing detail.
- App jest: `detailLines`; card-set parsing with and without detail; edit content shape; the back-label and
  quiet-label choices if they live in pure helpers.
- Maestro: extend `chat_cards` (fixture cards gain detail): the proposal shows a detail line; the About chip opens
  the sheet and Done closes it. Screenshot check of the review result with detail on the simulator.

## Out of scope

A backfill (no live cards), changing the grade model, showing detail on the Review tab's card browser rows.

## Build plan

Three chunks; 1 and 3 are independent, 2 needs 1's wire shape (fixed above), so it can build in parallel against
the spec and merge after 1.

**Chunk 1 — backend: storage, writers, grader** (most capable tier: prompts plus a migration)
- Files: `packages/archie-llm/archie_llm/` (new `cards.py` with the rules constant), `packages/archie-db/archie_db/`
  (`models.py`, a new migration, `versions.py`), `services/worker/archie_worker/prompts.py` and the handlers that
  insert cards (`analyze`, `primer`, `topic_primer`, `note_cards`, `take_cards`, `news_quiz`),
  `services/api/archie_api/ask/` (`prompts.py`, `card_set_tools.py`, `card_routes.py`, `edit_tools.py`),
  `services/api/archie_api/review/` (`prompts.py`, `routes.py`), `services/api/archie_api/sync/` (`schemas.py`,
  pull), tests and cassettes.
- Produces: `detail` on cards/card versions/pull rows (`\n`-joined string), card-set cards with `detail: string[]`,
  card edit content with `detail`.
- Decisions: lines joined with `\n`, newlines inside a line replaced by spaces; content reads default missing detail
  to `""`; kept match on (question, answer).
- Tests: as in Testing (Python).
- Depends on: none.

**Chunk 2 — app: data and card display** (standard tier)
- Files: `app/src/db/schema.ts`, `app/drizzle/0018_card_detail.sql` (+ meta, `migrations.js`), `app/src/sync/`
  (engine/transport types), `app/src/review/` (types, `session/GradedCard.tsx`, `SelfGradeCard.tsx`, a
  `detailLines` helper), `app/src/ask/cardSets.ts`, `CardSetProposal.tsx`, `app/src/edits/` (`content.ts`,
  `types.ts`, `VersionPreview.tsx`), `maestro/fixtures/chat_cards.json`, test card fixtures.
- Consumes: chunk 1's wire shape.
- Tests: jest as above; maestro `chat_cards` detail assertion.
- Depends on: chunk 1 (wire shape only; may build in parallel).

**Chunk 3 — app: the note beside its chat** (standard tier)
- Files: `app/src/app/ask/[id].tsx`, new `app/src/ask/ItemSheet.tsx`, new `app/src/item/SummarySections.tsx`
  (moved out of `app/src/app/source/[id].tsx`, which then imports it), `app/src/ask/AnswerView.tsx`
  (`quietLabels`), `maestro/chat_cards.yaml` (About chip opens and closes the sheet).
- Tests: jest for any pure helper (back label, quiet labels); maestro step.
- Depends on: none.
