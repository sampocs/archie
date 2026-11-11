# Daily card cap

Mocks: `2026-11-11-daily-card-cap-mocks.html` (published at https://claude.ai/artifact/T9WQQho6RyTh876y2D8zgm).

## Why

Nothing limits how many cards come due on one day. Finishing a textbook (up to 15 cards), refreshing two notes and
finishing a couple of podcasts can put 40+ new cards into one day, and since FSRS schedules them alike they come back
together too. A 40-card day mostly turns into a skipped day. A day late barely matters to FSRS (at ~90% target recall
the forgetting curve is flat when a card comes due, and a late review is scheduled from the time that really passed),
so the app caps what one day shows and lets the rest wait.

## Behavior

- **Cards per day**, default **20**. A setting: 10–50 in steps of 5, or Off (no cap, today's behavior).
- **Nothing is rescheduled.** The cap only limits which due cards a day's "due" session shows. A card left out stays
  due and is simply more overdue tomorrow.
- **Today's budget** = the cap minus the distinct non-quiz cards reviewed today that were due when reviewed (the same
  count Today's review task already uses, `reviewedDueToday`), floored at 0.
- **Which cards fill the budget**, from all due reviewable cards (`isDue` + `isReviewable`, quiz cards excluded as
  today):
  1. Split into **reviews** (`fsrsState !== "new"`) and **new** cards.
  2. Reviews rank earliest due first (`effectiveDue`, then id). New cards rank in arrival order
     (`availableAt ?? createdAt`, then id).
  3. **New slots:** `min(5, newDue, budget)` slots go to new cards first, so new material never stalls behind a review
     backlog. The rest of the budget goes to reviews; if reviews run out, leftover slots go to more new cards.
  4. The picked set is shown in the existing session order (`orderCards`).
  Already-reviewed new cards don't reduce the 5 new slots on a later same-day session (a day is usually one session;
  simplicity wins).
- **Waiting** = due reviewable cards not in today's set. They need no stored state: they're just due cards outside
  the budget.
- **Keep going** starts a new session mode `more`: the next `cap` cards of the waiting list, picked with the same
  ranking (so a 60-card backlog goes 20 at a time). These count as due reviews (`wasDue` true), graded and scheduled
  normally.
- **Off** (cap null): budget is unlimited, waiting is always 0, and every screen behaves exactly as today.

## Where it shows (see mocks)

- **Today review card, pending / in progress** (mock 1): the count, minutes and progress use today's set only
  ("20 cards", "about 7 minutes"). When waiting > 0 and no review has happened yet, one extra line under the minutes on
  the green card: "14 more wait for tomorrow" (mono label, on-green soft color). In progress, `total` = reviewed + left
  in today's set.
- **Today review, done** (mock 4): today's set is empty. Done counts as done: the task is DONE, the day can be done,
  the streak counts it (the streak needs no change). The `DoneRow` shows "20 cards reviewed"; when waiting > 0 its
  detail reads "14 more waiting" and its link is "Keep going ›", which opens a `more` session. With nothing waiting it
  is unchanged ("next 5 tomorrow", "More ›").
- **"Back tomorrow"** line: cards = `min(cap, waiting + dueByTomorrow)` (uncapped when Off).
- **Review tab:** `ReviewStartCard` counts today's set. When today's set is empty but waiting > 0, the caught-up card
  shows a "Today's cards are done" variant: line "14 more waiting. They'll lead tomorrow's session." and buttons
  "Keep going · 14" (starts `more`) and "Shuffle 10". With nothing waiting, the caught-up card is unchanged.
- **Session Done screen** (mock 3): the `KeepGoing` list gets a new first row when waiting > 0: "14 more waiting" on
  the left, "about 5 min ›" on the right (minutes for `min(waiting, cap)`), starting a `more` session via
  `router.replace` as Review ahead does. The rest of the screen is unchanged. Waiting is computed when the view first
  shows (like the ahead summary).
- **Reminders:** each planned reminder's count = `min(count at that time, cap)`; for today's reminder, the cap is
  today's remaining budget (cap − reviewed due today). A reminder with count 0 is dropped, as now.
- **Settings** (mock 6): the "Review reminder" screen becomes "Review" (screen title and the Settings tab row label).
  Above the reminder card, a new card with a "Cards per day" row: label, secondary line "Extra cards wait for the next
  day", and a − / value / + stepper. Values: 10, 15 … 50, then Off (+ at 50 goes to Off; − at Off goes to 50; − at 10
  and + at Off are disabled). Changing it saves, then replans reminders (as the reminder controls do).
- **Unchanged:** per-topic/item due tags in browse lists, topic/source/take/card/quiz/shuffle/missed sessions, Review
  ahead (still only not-yet-due cards), FSRS scheduling, the server.

## Storage

App-only (review settings never sync). `review_settings` gets a nullable integer column `daily_limit` (drizzle
migration 0020). `ReviewSettings` gains `dailyLimit: number | null`; `DEFAULT_REVIEW_SETTINGS.dailyLimit = 20`. A row
written before the migration has NULL; since NULL must mean Off only when the user chose it, store Off as **0** and
read NULL as the default 20 (`dailyLimit: row.dailyLimit === null ? 20 : row.dailyLimit === 0 ? null : row.dailyLimit`).

## Design

One new pure module, `app/src/review/dailyCap.ts`:

```ts
export const DEFAULT_DAILY_LIMIT = 20;
export const NEW_CARD_SLOTS = 5;
export const DAILY_LIMIT_STEPS = [10, 15, 20, 25, 30, 35, 40, 45, 50] as const;
export type DailyPlan = { today: CardRow[]; waiting: CardRow[]; budget: number | null };
/** Today's capped set and the due cards left waiting; limit null = no cap. */
export function dailyPlan(data: ReviewData, limit: number | null, now: Date): DailyPlan;
```

`reviewedDueToday` moves from `today/todayTasks.ts` into `dailyCap.ts` (exported) so both use one count.

Consumers take the limit as an explicit argument (no global read inside pure code):
- `buildSession(data, mode, id, now, random, limit)`: `due` → `orderCards(plan.today)`; new `more` →
  first `limit` of `plan.waiting` ranked (all of them when Off, though the UI never offers it then), ordered by
  `orderCards`. `SESSION_MODES` gains `more`.
- `dueSummary(data, now, limit)` → `{ count: today.length, waiting: waiting.length }`.
- `todayTasks` inputs gain `dailyLimit`; `ReviewTask` pending gains `waiting`, done gains `waiting`.
- `reminderPlan(data, settings, now)` reads `settings.dailyLimit`.
- Screens read the limit with `getReviewSettings(db).dailyLimit` (session screen at open; Today, Review tab, Done
  view per render — cheap single-row read; or a small `useDailyLimit()` hook re-reading on focus).

## Testing

Jest, pure functions (the logic that could plausibly be wrong):
- `dailyCap.test.ts`: under the cap everything is today; over it, reviews earliest-due first; 5 new slots reserved
  with a review backlog; leftover slots go to new cards when reviews are few; budget shrinks with cards reviewed due
  today (quiz answers and re-grades not double counted); budget 0 → today empty, all waiting; Off → no waiting.
- `session.test.ts`: `due` honors the cap; `more` takes the next batch of waiting cards.
- `todayTasks.test.ts`: pending shows waiting; done with waiting; back-tomorrow capped.
- `reminder.test.ts`: counts capped, today's reminder uses the remaining budget.
- `reviewSettings.test.ts`: NULL reads as 20, 0 round-trips as Off.
Then `npm test`, `npm run typecheck`, lint, and the existing `make maestro-review` flow as a regression smoke test.

## Build plan

One chunk (app only; logic and UI are tightly coupled and small).

**Chunk 1 — daily cap** · Depends on: none
- Files: `app/src/review/dailyCap.ts` (+ test), `review/session.ts`, `review/summary.ts`, `review/reminder.ts`,
  `today/todayTasks.ts`, `db/schema.ts`, `db/reviewSettings.ts`, `app/drizzle/0020_*.sql` + meta/migrations.js
  (generated with the repo's drizzle-kit script), `app/settings/review.tsx`, `app/(tabs)/settings.tsx`,
  `app/(tabs)/today.tsx`, `app/(tabs)/review.tsx`, `review/session/DoneView.tsx`, `review/ui/KeepGoing.tsx`,
  `review/ui/CaughtUpCard.tsx`, `review/ui/ReviewStartCard.tsx`, `app/review/session.tsx`, and the tests above.
- Key decisions: as above. Copy exactly as written in Behavior / Where it shows.
- Docs: product-scope doc's review section gets the cap (one short paragraph).
