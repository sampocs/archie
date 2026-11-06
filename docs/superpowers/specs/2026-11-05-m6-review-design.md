# M6 Review: cards, grading and spaced repetition

**Status:** Implemented on `m6-review` (plan `docs/superpowers/plans/2026-11-05-m6-review.md`).

Do the daily reviews on the phone, including offline, and keep the things you consume. The owner approved the mocks
in `2026-11-05-m6-review-mocks.html` (01 Today/answer/graded, 02 timed out/offline, 03 done/keep going, 04 item
cards/quiz/reminder) with the changes below. Product background: "Review" in `2026-10-26-product-scope.md`; where
they differ, this spec wins. Grading research: `spikes/card_grading/README.md`.

Output quality (ideal cards, tone, grading accuracy on the owner's own answers, session order) is tuned in a final eval
pass after the last milestone. This milestone picks reasonable defaults and builds the whole loop.

## Decisions

- **Next is a button.** After a grade the card stays until you tap Next, so you can read the answer.
- **Voice goes through a model.** The mic records audio and sends it to Groq Whisper (`whisper-large-v3-turbo`) with
  the card's question and answer as the vocabulary prompt, so names and jargon come out right. Offline the mic button
  is hidden; the iOS keyboard's own dictation still works.
- **Session order:** foundation cards first, then concept and mechanism cards, then number cards; within each group
  the most overdue first. A placeholder to tune in the eval pass.
- **Grading:** Haiku 5.5 with the spike's one-shot prompt (`got_it | partly | missed` + what was missing). The phone
  shows the self-grade screen when grading takes more than `GRADE_TIMEOUT_MS` = 3000, fails, or the phone is offline.
  "I actually knew it" stays under every grade.
- **Offline:** you grade yourself and the card is scheduled at once; the review syncs later.
- **Spaced repetition is FSRS, run on the phone** (`ts-fsrs`), so scheduling works offline. The phone is the
  scheduler; the server stores each review and the card's latest state. Grades map to FSRS ratings: got_it → Good,
  partly → Hard, missed → Again.
- **Extra practice can only bring a card sooner, never push it later.** Review ahead and topic/source practice grade
  cards that aren't due yet. Such a review is logged, but a got_it leaves the card's schedule unchanged; partly or
  missed applies FSRS normally (so the card comes back sooner). Going ahead never empties tomorrow.
- **No daily limit on new cards** for now.
- **A card is reviewable only once you've taken in what it came from:** source cards when the source is `consumed`;
  foundation cards when their primer has been opened (`primer_opened_at` for a source primer, `opened_at` for a
  topic primer). Until then they exist (and show on the item page as "After you finish") but aren't scheduled.
- **No cards for a source:** "No cards for this" in the item's ••• menu soft-deletes the source's cards and stops new
  ones. "Make review cards" (already in the menu) turns cards back on and re-runs analyze. Single cards are removed
  with Drop (in review) or the card's own Remove (on the item page).
- **"What I care about…"** rewrites only this card's answer and saves the note as a preference that future card
  generation reads. Drop saves a "not this" preference the same way. Card editing stays out.
- **Weekly news quiz:** on Sundays, 5 cards from the stories in briefs you marked Done in the last 7 days, offered on
  Today under the review card. Graded the same way but never scheduled; they expire 7 days after they're made.
- **One reminder a day** at 8:30pm by default, only when cards are due, changeable or off in Settings. It's a local
  notification; there's no push server.

## Screens

- **Today — review card** (mock 01): the only forest-green block on Today, above the brief preview. "N cards",
  mono "about M minutes" (M = ceil(N × 20 s / 60), min 1), and "K foundations first" when K > 0. Tapping starts the
  due session. No card when nothing is due. On Sundays (and until it expires) the quiz row sits under it: "This
  week's news quiz", "5 questions · from your briefs · until <weekday>".
- **Review session** (`app/src/app/review/session.tsx`, full screen, `?mode=due|ahead|topic|source|quiz&id=`):
  - Top: ✕ (ends the session, keeping what was graded) and "n of N".
  - Question card: domain colour kicker "<Domain> · <Kind label>" (Foundation, Concept, Mechanism, Rough number,
    News), question in the large review type (the same size while the keyboard is up).
  - Answer box: a big white card with Drop, 🎙 and ↑. 🎙 records until tapped again, then transcribes into the box
    (editable). ↑ submits; with an empty box it reads "Show answer" and goes straight to self-grade.
  - Graded (mock 01 "Partly"): "You said …", the verdict pill in its colour, the missing line (partly/missed only),
    "Answer …", then "I actually knew it" and "What I care about…", and the primary Next →.
  - Self-grade (mock 02): "You said …", "Answer …", the reason line ("Couldn't grade this one. How did you do?" or
    "Offline · grading yourself · syncs later"), and Got it / Partly / Missed.
  - "What I care about…" opens a sheet with one text field ("What do you want to remember about this?"); Save
    rewrites the answer (online only; offline the entry is disabled with "Needs a connection").
  - Drop asks nothing: it removes the card, counts as Dropped in the tally, and moves on.
- **Done** (mock 03): "Done." + "N cards in M minutes. Next review <tomorrow|weekday>: K cards.", the tally (Got it /
  Partly / Missed / Dropped), "Keep going": Review ahead (cards due in the next `AHEAD_DAYS` = 3 days, "14 due by
  Sat") and "Practise a topic ›", then "Back to Today".
- **Review tab** (`app/src/app/(tabs)/review.tsx`): with cards due, the same start card as Today. With nothing due:
  "All caught up. K cards are due <tomorrow|weekday>." then the keep-going options. "Practise a topic" opens a list
  of topics with reviewable card counts (topics with none hidden).
- **Item page — Cards from this** (mock 04): on any item with cards, after the summary sections: "Cards from this ·
  N" (with "Practise" on the right when any are reviewable), each row the question, kind label and "Due tomorrow /
  Due Sat / Due in 9 days / After you finish". Tapping a row opens a one-card session. Each row swipes to Remove.
- **Item ••• menu:** adds "No cards for this" (hidden when cards are already off); "Make review cards" shows when cards
  are off or the source has none.
- **Settings → Review** (`app/src/app/settings/review.tsx`, from the account sheet next to Removed topics): Daily
  reminder on/off, Time (default 8:30 PM), and "Only sent when cards are due".

## Data

Migration `0007_review`:

```
cards
  ~ source_id, artifact_id become nullable
  + topic_primer_id uuid null fk topic_primers on delete cascade   -- foundation cards from a topic primer
  + brief_id uuid null fk briefs on delete cascade                 -- quiz cards
  + fsrs_state text not null default 'new'   -- new | learning | review | relearning
  + stability float null, difficulty float null
  + due_at timestamptz null, last_review_at timestamptz null
  + reps int not null default 0, lapses int not null default 0
  + expires_at timestamptz null                                    -- quiz cards only
  CHECK exactly one of (source_id, topic_primer_id, brief_id) is not null
sources
  + cards_off boolean not null default false
reviews
  id uuid pk (phone-made), user_id fk, card_id fk cards on delete cascade,
  grade text ('got_it' | 'partly' | 'missed'), graded_by text ('model' | 'self'),
  answer text null, missing text null, was_due boolean,
  reviewed_at timestamptz, state_before jsonb, state_after jsonb,
  replaces_review_id uuid null,            -- set by "I actually knew it"
  created_at
card_preferences
  id bigint identity pk, user_id fk, card_id uuid null fk cards on delete set null,
  kind text ('care' | 'drop'), note text, created_at
```

`CardKind` gains `foundation` and `quiz` (Saved and Takes later adds `take` and its own nullable origin column, which
widens the CHECK). Reviews are not pulled back to the phone; the phone keeps its own log. Cards gain the FSRS columns
in the pull; the drizzle `cards` table mirrors them (re-pull migration), plus `sources.cardsOff`.

## Phone actions (outbox)

| Action | Payload | Effect |
|---|---|---|
| `review_card` | review_id, card_id, grade, graded_by, answer?, missing?, was_due, reviewed_at, state_after, replaces_review_id? | inserts the review (idempotent on review_id); writes `state_after` to the card's FSRS columns unless the card already has a later `last_review_at` |
| `drop_card` | card_id | soft-deletes the card; adds a `drop` preference with the question |
| `set_cards_off` | source_id, off | `off`: sets `cards_off`, soft-deletes the source's live cards. `!off`: clears it and re-queues analyze (the existing go-deeper path) |
| `request_news_quiz` | week_start (date) | queues `news_quiz` unless a quiz exists for that week or no brief was Done in the last 7 days |

The phone sends `request_news_quiz` when Today opens on a Sunday while online (so no server cron or user time zone
is needed). Every action is applied optimistically on the phone first.

## API (online, synchronous)

The model and Groq helpers move from `services/worker/archie_worker/llm.py` (and the Groq request in
`transcription.py`) into a new workspace package `packages/archie-llm` that both the worker and the API import.

- `POST /review/grade {card_id, answer}` → `{grade, missing}`. One Haiku call (no fallback: the phone's timeout is the
  fallback), logged in `llm_calls` with step `grade`. 404 for a card that isn't the user's.
- `POST /review/transcribe` (multipart: `card_id`, `audio` m4a up to 2 minutes) → `{text}`. Groq Whisper with the
  card's question + answer as `prompt`; OpenAI transcription as the fallback, like the pipeline. Logged in
  `llm_calls`.
- `POST /review/cards/{id}/care {note}` → the updated card. Haiku rewrites the accepted answer to keep what the note
  says matters (it may only drop or reweight, never add facts); saves a `care` preference; bumps the card's
  change_seq.

## Worker

- **Foundation cards:** the `primer` and `topic_primer` prompts also return 2–3 `foundation` cards (the background
  ideas the primer teaches). Re-writing a primer retires its previous foundation cards.
- **Preferences in generation:** `analyze`, `primer`, `topic_primer` include the user's last 20 `card_preferences`
  notes as guidance ("cares about …", "doesn't want cards like …").
- **`analyze` skips cards when `sources.cards_off`.**
- **`news_quiz`** (`JobKind.NEWS_QUIZ`, Haiku with Sonnet fallback): reads the stories (headline, body, why, detail)
  of the user's briefs Done in the last 7 days, writes 5 `quiz` cards on the top stories by importance, each with
  `brief_id` and `expires_at` = now + 7 days. Fewer stories than 5 → that many cards.

## Phone logic (`app/src/review/`, pure where possible)

- `session.ts`: builds a session's card list for each mode from the local db (due: reviewable, `due_at` ≤ now or new;
  ahead: due within `AHEAD_DAYS`; topic: reviewable cards of the topic's sources and topic primer; source: that
  source's reviewable cards; quiz: unexpired, unanswered quiz cards), in the order from Decisions.
- `schedule.ts`: wraps `ts-fsrs` — `applyGrade(card, grade, now, wasDue)` returns the new state per the
  never-push-later rule; "I actually knew it" recomputes from the replaced review's `state_before` with Good.
- `reminder.ts`: on app foreground and after each session, cancels and re-schedules local notifications
  (`expo-notifications`) for the next 7 days at the reminder time, each only when cards will be due then, with the
  body "N cards · about M min".
- Grade flow: on submit, start `POST /review/grade` and show the answer animation; reveal the verdict when it lands;
  after `GRADE_TIMEOUT_MS`, on error or offline, switch to self-grade.

## Out of scope

Card editing, a new-card daily limit, FSRS parameter optimisation, review statistics, tuning card/grade prompts (eval pass). Reviewing take cards shipped in Saved piece 3.

## Testing

- Server e2e (Postgres): `review_card` stores the review and state, ignores an older state, is idempotent; `drop_card`
  and `set_cards_off` (cards retired, analyze skips them, turning back on re-analyzes); `request_news_quiz` once per
  week. `/review/grade`, `/review/transcribe` and `/review/cards/{id}/care` against recorded cassettes.
- Worker: primer and topic-primer cassettes re-recorded with foundation cards; `news_quiz` cassette on a real brief.
- App jest: session building and order per mode, eligibility rules, the never-push-later rule, "I actually knew it"
  recompute, reminder scheduling (only days with cards due), minutes estimate.
- Maestro `review.yaml`: finish an item, its cards appear on Today, answer one typed (graded by the local backend with real
  keys, a fraction of a cent, like `brief.yaml`), see the graded card, Next, Done screen with the tally.

## Build plan

Large: see `docs/superpowers/plans/2026-11-05-m6-review.md` (written after this spec is approved).
