# Monitoring: problems on Today

**Status:** approved design, 2026-11-13.

## Why

Parts of Archie can break without making any noise. Spotify can change its page format, a newsletter can move to a
new sending domain and stop arriving, a Claude key can run out of credit, or the worker can stop. Today the owner finds
out only by noticing that something is missing. The server has no way to reach the owner. The only notification is
the phone's own daily review reminder.

The owner opens Archie every day, so problems show up inside the app (decided 2026-11-13). There is no push or email,
and no outside service.

## What the owner sees

- **Banner.** When something is wrong, a quiet banner sits at the top of Today: "1 thing needs a look" or "3 things
  need a look". When nothing is wrong, there is no banner and no empty state.
- **Problems sheet.** Tapping the banner opens a bottom sheet. It lists one row per problem: a one-line title ("Podcast
  imports failing"), a detail line ("3 since Tue · Spotify page format not recognized"), and when it started
  ("since 2 days ago").
- **Self-clearing.** Nothing is dismissed by hand. A problem disappears once its condition stops being true.
- **Offline.** No problems are shown. A dead zone is not a problem.

## Checks (server)

There is one authenticated endpoint, `GET /problems`. It runs every check for the signed-in user when called and
returns `{"problems": [...]}`. Each problem has:

- `kind`: a StrEnum value.
- `key`: a stable id, such as the kind plus the job kind or the sender id.
- `title`
- `detail`
- `since`: an ISO timestamp.

Problems are computed on request. They are never stored, and their text is never logged.

1. **`failing_jobs`, one per job kind.**
   - **Which failures count:** jobs with status `failed` created after the most recent `done` job of the same kind,
     looking back at most 7 days.
   - **When it clears:** once one job of that kind succeeds.
   - **Title:** a per-kind label, such as "Podcast imports failing" for transcribe and "Summaries failing" for
     analyze. A Claude key or billing failure shows up here through its error.
   - **Detail:** the count, then the newest `last_error`. The error is cut to its first line and 140 characters.
   - **`since`:** the oldest counted failure.
2. **`worker_stalled`, a single problem.**
   - **Trigger:** any `queued` job whose `next_run_at` is more than 1 hour in the past, or any `running` job whose
     `started_at` is more than 1 hour in the past.
   - **Why:** this means the worker isn't taking jobs.
   - **Detail:** how many jobs are waiting, plus the oldest one's kind.
3. **`quiet_sender`, one per allowed sender.**
   - **Who qualifies:** allowed senders with at least 4 received newsletters in the last 180 days.
   - **Usual gap:** the median gap between consecutive issues.
   - **Trigger:** the time since the last issue is more than `max(3 × usual gap, 3 days)`.
   - **Title:** "<label> has gone quiet".
   - **Detail:** "Last issue 9 days ago · usually daily" (daily, every few days, weekly, or every N weeks).
   - **`since`:** the moment the silence passed the threshold.
   - **When it clears:** when the next issue arrives.
4. **`no_email`, a single problem.**
   - **Trigger:** the user has at least one allowed sender, and no newsletter has arrived in 48 hours.
   - **Effect:** this problem replaces the `quiet_sender` rows, since they share one cause.
5. **`no_brief`, a single problem.**
   - **Trigger:** a `news` newsletter arrived more than 3 hours ago, but no brief's `source_ids` includes it and no
     `update_brief` job for it is queued or running.
   - **Overlap:** if `update_brief` is failing, `failing_jobs` already covers it, so this problem is left out.

**Thresholds.** The values are 7 days, 1 hour, 4 issues, 3×, 3 days, 48 hours and 3 hours. They are named constants in
one module.

**Matching a newsletter to its sender.** This reuses how ingest already matches a newsletter to its sender. The
implementer reads the ingest code; it must not invent a second matching rule.

## App

- **Fetching.** Today calls `/problems` when it gains focus and after each sync completes. It holds the last answer in
  memory only.
- **Unreachable server.**
  - **Recording contact:** the sync engine records `lastServerContactAt` in the local store after every successful
    pull.
  - **Trigger:** the phone is online (expo-network) and `lastServerContactAt` is more than 24 hours old.
  - **Effect:** the app adds its own problem, "Can't reach Archie's server · last synced <relative time>". This works
    even when `/problems` can't be fetched.
- **Request failures.** A failed `/problems` call keeps the previous list. If there is no previous list, nothing shows.
  A single failed request never raises a banner by itself.
- **Look.** The banner and the sheet use the existing `Card`, `BottomSheet`, `Text` and theme tokens. The banner
  carries a small warning signal color, and it is not red.

## Testing

- **Server e2e (Postgres).** For each check, seed the condition through the database and assert the problem appears.
  Then seed the fix and assert it disappears:
  - a `done` job after the failures
  - the stuck job running
  - a new issue arriving
  - a brief covering the newsletter

  Also assert that another user's jobs and senders never appear.
- **App jest.** Cover the pure logic: combining server problems with the unreachable-server problem, the banner count
  wording, and the cadence wording if it lives in the app.
- **Maestro, `problems.yaml`.** A dev-only test route, `POST /test/failed-job`, seeds a failed `analyze` job for the
  signed-in user. The flow then checks that Today shows the banner and that the sheet shows "Summaries failing". It
  spends nothing.

## Out of scope

Push and email, a history of problems, spend alerts, and alerts for anyone other than the owner.

## Build plan

### Chunk 1: server checks and endpoint

Depends on: none.

- **New module `services/api/archie_api/problems/`.**
  - `checks.py`: one function per check, each returning a list of `Problem`. `Problem` is a dataclass, and `kind` is
    a StrEnum.
  - `routes.py`: `GET /problems`, authenticated like `/search`, returning the pydantic `ProblemsOut`.
  - Register the router in `main.py`.
- **Thresholds.** Module-level constants.
- **Job-kind titles.** A dict from `JobKind` to a title, with a generic "<kind> jobs failing" fallback.
- **Dev-only test route.** `POST /test/failed-job` in `test_routes.py`, which seeds a failed analyze job with a fake
  error for the signed-in user.
- **Tests.** Add `services/api/tests/e2e/test_problems_e2e.py` with an appear and clear test per check, plus an
  isolation test across users.

### Chunk 2: app banner, sheet and unreachable detection

Depends on: the response shape from Chunk 1 only, which is `{"problems": [{kind, key, title, detail, since}]}`.

- **Fetching and merging.** `app/src/problems/useProblems.ts` fetches with `apiFetch`, parses defensively by dropping
  malformed rows (as `serverSearch.ts` does), and merges in the local unreachable problem.
- **Last contact.** The sync engine records the last successful pull time where it already keeps sync metadata.
- **Views.** `app/src/problems/ProblemsBanner.tsx` and `ProblemsSheet.tsx`. The banner sits at the top of
  `app/src/app/(tabs)/today.tsx`.
- **Tests.** Jest for the merge and wording logic. Add `maestro/problems.yaml` and a `make maestro-problems` target,
  and update `maestro/README.md`.
