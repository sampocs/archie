# Today and Review polish: design

Approved mocks: `docs/superpowers/specs/2026-11-10-today-review-polish-mocks.html` (heading style **A**; the "day
finishing" demo; the three Review screens). App-only: no server, schema or sync changes.

## Why

Today works, but finished things vanish (no sense of progress), the review card shows no progress when you come back
mid-session, and the three task cards open with three different heading styles. Review is a copy of Today's top plus
two rows, and there is nowhere to see all your cards.

## Today

Layout and order stay as they are (review, note refresher, news quiz, brief, Up next, empty state).

1. **One card-header pattern (style A)** for every task card: `CardHeader` = a small uppercase label on the left
   (the existing kicker style, ink2; on the green review card white at 85%) and a mono detail on the right (monoLabel,
   ink3; white 85% on green). Used by:
   - Review: `REVIEW` / `about N min` before any review today, `R of T done` once some are done.
   - Refresh a note: `REFRESH A NOTE` / `P of 2 today` (moved from the label to the right).
   - News quiz: `NEWS QUIZ` / `N questions · until Sat`.
   - Brief: `YOUR BRIEF` / `N stories · M min` (ready) or `writing… · N newsletters` (writing). "Your brief" is no
     longer a bold headline.
   Up next keeps its section label (grey mono `UP NEXT`, `See all N ›`): it is a list, not a task.
2. **Review progress.** Today's set T = cards reviewed today (local day) that were due + cards due now. Before any
   review: big `N cards`, mono `about N minutes`. With R ≥ 1 reviewed and some left: big `N cards left`, mono
   `about N minutes`, and a 4px white progress bar (R / T) at the bottom. The "N foundations first" line is removed
   (Today and Review).
3. **Done rows.** A finished task becomes a one-line `DoneRow` card: a 20px green check, **bold title** · detail,
   optional right link. Tapping the row does what its link says.
   - Review (T ≥ 1 and nothing due now): `✓ R cards reviewed · next N {tomorrow|on Thu}` · `More ›` → Review tab.
   - Notes (refresher done for today and ≥ 1 refreshed today): `✓ N notes refreshed · next: {title}` (no link;
     tapping opens the next note's item if any).
   - Brief (today's brief marked done today): `✓ Brief read · N stories` · `Open ›` → `/brief`.
   - News quiz (finished this week, shown only on the day it was finished): `✓ News quiz · G of N got it`.
   A task that never appeared today (no cards due, no brief) gets no row.
4. **Today's done.** When at least one task was done today and none is pending, the done rows are replaced by one
   `DayDoneCard` (green 12% tint, 20px radius): a 28px check, big `Today's done`, secondary `Back tomorrow: …`
   (built from what applies: `N cards`, `2 notes`, `a new brief`; joined naturally), and ticked chips for each task
   done today (`12 cards`, `2 notes`, `Brief`, `Quiz`). No Keep going row. Up next follows as usual.
5. **Animation and haptics** (Reanimated; `expo-haptics` via the existing `haptic()`), only when the change happens
   while Today is on screen or is the first Today render after it happened (e.g. returning from the brief):
   - A task finishing: its card eases down to the done row (layout transition ~450ms), the row's check pops (spring
     scale 0→1), light haptic.
   - The last task finishing: ~900ms later the done rows slide up and fade, `Today's done` springs in (scale .92→1),
     its check pops with a small 7-dot burst and a success haptic, then the chips tick in 100ms apart, a light
     haptic each. About a second in all.
   - Each celebration plays once per task per day: the phone remembers what it has animated today (kv-store key per
     local day); later renders show the final state without motion. Reduce Motion: no movement, the same end states,
     haptics kept.

## Review (tab keeps the name "Review")

1. **Header**: `Review`; right side a mono `N-day streak` when the streak is ≥ 2 (consecutive local days with ≥ 1
   review, ending today or yesterday, from the phone's `reviews` table). No other stats.
2. **Top, cards due**: the existing green start card (no foundations line) → `?mode=due`.
3. **Top, caught up** (replaces the plain "All caught up." text): a surface card with headline `All caught up`,
   secondary `Next N cards are due {tomorrow|Thu|Nov 14}.` (or nothing if no cards), and two secondary buttons side
   by side: `Review ahead · N` (only when N > 0; → `?mode=ahead`) and `Shuffle 10` (only when ≥ 1 live reviewable
   card; → `?mode=shuffle`: up to 10 random live, reviewable cards, a normal session that doesn't change due dates any
   differently from an ahead review). With no cards at all, the card reads `No cards yet` / `Cards from your items
   and chats show up here.`
4. **Browse**: a search field `Search N cards` (local, case-insensitive substring over question and answer, results
   as card rows), then a segmented control `Topics | Items | Missed` (remembered on the phone):
   - **Topics**: topics that have live reviewable cards: domain kicker, topic name, secondary `N cards`, a green
     `N due` tag when > 0, `›` → topic card list.
   - **Items**: sources and takes with live cards, most recently reviewed or created first: artwork tile, title,
     `N cards`, `N due` tag, `›` → that item's card list.
   - **Missed**: cards whose latest review in the last 30 days was missed or partly, worst first (missed count, then
     most recent), each with a red tag `missed` / `missed 2×` (partly counts as half, shown as `partly`); a primary
     `Practice these N` button → `?mode=missed`. Empty: `Nothing missed lately.`
5. **Card list screen** (`/review/cards?topic=` or `?source=`/`?take=`), replacing `/review/topics` (whose list
   becomes the Topics tab): back `‹`, title = topic or item name, a primary `Practice all N` → `?mode=topic&id=` (or
   `source`/`take`), then card rows reusing the item page's card row (question, origin `From {title}` or kind,
   next-due), tap → `?mode=card&id=` as today, swipe → Remove.
6. Remove the `Keep going` group from the Review tab (its two actions now live in the caught-up card and Topics).
   The session Done screen keeps its Keep going.

## Testing

Jest: Today task-state derivation (pending / in progress / done / day done for each task, T and R maths across
midnight, tasks absent today), `Back tomorrow` copy, streak (gaps, today vs yesterday), missed ordering and partly
weighting, search matching, Shuffle picking only live reviewable cards. Maestro: extend an existing free flow (or add
`today_done.yaml`) to see a done row after finishing the brief; Review flow: caught-up card buttons, Topics → card
list → Practice all.

## Build plan

### Chunk 1: Today
Files: `app/src/app/(tabs)/today.tsx`, `review/ui/ReviewStartCard.tsx`, `notes/RefresherCard.tsx`,
`brief/BriefPreviewCard.tsx`, the news quiz card, new `today/CardHeader.tsx`, `today/DoneRow.tsx`,
`today/DayDoneCard.tsx`, `today/todayTasks.ts` (pure derivation + tests), celebration memory.
Depends on: none.

### Chunk 2: Review
Files: `app/src/app/(tabs)/review.tsx`, new `review/ui/CaughtUpCard.tsx`, `review/browse.ts` (pure: topics, items,
missed, search, streak, shuffle + tests), `app/src/app/review/cards.tsx` (replacing `review/topics.tsx`), session
modes `shuffle` and `missed` in `review/session.ts`/`session.tsx`, card row extracted from `item/CardsSection.tsx`
for reuse. Chunk 2 does not edit `ReviewStartCard` (chunk 1 owns it, including
removing the foundations line).
Depends on: none.
