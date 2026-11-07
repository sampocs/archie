# Edits through chat

**Status:** implemented on branch `chat-edits` (Maestro flow `edit.yaml`); designed 2026-11-08 from the owner's binding decisions (what chat can edit, versions for everything,
confirm-to-apply with Undo, owner edits never silently overwritten, whitelist and models as M7); the technical
choices below were deferred to this spec. Plan: `docs/superpowers/plans/2026-11-08-chat-edits.md`. Product background
is `2026-10-26-product-scope.md` ("Carl (chat)": "Edit through chat … Edits create a new version, so the original is
always kept and can be restored") and `2026-11-02-backend-architecture-design.md` (Data model: versions); Ask itself is
`2026-11-06-m7-search-ask-design.md`, and take versions are `2026-11-05-saved-and-takes-design.md`. Where they differ,
this spec wins and those docs are updated when it ships.

## Decisions

- **Ask can edit five things:** a source's **summary**, a source's **primer**, a **topic primer**, the owner's
  **takes**, and **review cards** (any live card: from a source, a primer, a topic primer, a brief quiz, a take or a
  chat).
- **Every change makes a new version; nothing is overwritten.** Summaries, primers and topic primers are already
  versioned rows with one current version, and takes already have `take_versions`. **Cards get versions too**
  (`card_versions`). Restoring an earlier version copies it into a new version (as takes do today), so history only
  grows and Undo is just another restore.
- **Confirm to apply.** Archie never changes anything from the chat on its own. It **proposes** an edit, the chat
  shows it as a card with a readable before/after diff and **Apply** / **Discard**, and only Apply writes the new
  version. An applied edit shows **Applied · Undo**; Undo restores the version the edit was made against.
- **Earlier versions for everything, in the lightest UI that fits:** one shared **versions sheet** (a bottom sheet:
  versions newest first, tap one to preview it, "Restore this version"). It opens from the ••• menu entries that
  already hold an item's actions — **Summary versions** and **Primer versions** on the source page, **Primer
  versions** on the topic page — and from a **Versions** swipe action on a card row in "Cards from this". Each entry
  shows only when there is more than one version, so pages without history look exactly as they do now. Takes keep
  their existing "Earlier versions" list and version page, whose rows now say how a version was made. Why a sheet: the
  ••• menu is where item actions already live, a sheet keeps reading pages uncluttered, and one component serves four
  kinds of content. The primer screen gets nothing new (its source's menu covers it, as with Ask about this).
- **The regeneration rule: Archie never replaces a version the owner chose.** A version the owner chose is any version
  not written by Archie (an applied chat edit, a restore, a care rewrite, a take the owner wrote). When analyze or
  primer runs again while such a version is current, Archie's new version is still saved, but **not as current**: it
  appears in the versions sheet as the newest version, ready to restore. The one exception is a source whose **text
  was replaced after the owner's version** ("Wrong episode?", a re-fetch): the owner's edit described different text,
  so Archie's rewrite becomes current and the owner's version stays in the list. Why this rule: it is one check in
  the one function that writes artifact versions, no job is skipped (cards, filing and readiness still run exactly as
  today), and nothing is lost either way. Topic primers are never regenerated today (a primer is written only when the
  topic has none), so the rule only matters for source summaries and primers.
- **Cards stay consistent the way the code already ties them:**
  - **Take edits** (and their Undo and restores) make a new take version, which rewrites the take's cards with
    `take_cards`, exactly as a save in the take editor does.
  - **Summary, primer and topic primer edits leave their cards as they are.** Those cards were written from the source
    in the same model call as the content, not from its wording, and the current code only replaces them when Archie
    regenerates. Instead the chat is told: when an edit removes or changes a fact that one of the item's cards asks
    about, propose a matching card edit in the same answer. Each card edit is its own proposal with its own Apply.
  - **A card edit** changes only that card's question and answer; its schedule (FSRS state) and review history stay.
  - Archie's regeneration while an owner version is current still replaces the source's cards as today (the cards
    follow Archie's newest analysis).
- **How Archie finds what to edit.** The model gets the target's id from: the chat's about item (its ids are added to
  the about block of the system prompt), library search results (each result's title now ends with its item tag,
  e.g. `[source 6f1c…]`), and earlier turns (history lines now list the items an answer cited and the edits it
  proposed, with their status). Cards are found with a `find_cards` tool (by words, by item, or both). Before editing
  text it reads the exact current text with `read_item`.
- **Whitelisted only, same as Ask.** Proposals are only made inside Ask, which is whitelisted. Apply, Undo, Discard and
  Restore call no model; applying a take edit queues `take_cards` and embedding like any take save.
- **Models and contract as M7.** Sonnet 5.5 (`llm.SONNET`) with `thinking={"type": "between_tools"}` and
  `output_config={"effort": "medium"}`; tool calls are executed by the server between rounds, each in its own short
  session; no database transaction is held across a model call. Apply/Undo/Restore make no outside calls and run in
  one transaction under the user's write lock.
- **Cassette rule.** Ask's system prompt keeps its first 60 characters ("You are Archie's Ask, answering the owner's
  questions from th"); the editing rules are appended after the existing rules. No new system prompt is introduced.

## Data (server migration 0013, phone drizzle 0013)

A parallel branch, `item-dates`, adds server migration `0012_published_at` and the phone's drizzle `0012`. This
work uses **`0013_chat_edits`** for both and revises `0012`; the build starts once `item-dates` is merged to `main`
(the plan's first step checks, and merges the `item-dates` branch if it is not on `main` yet).

- **`models.VersionOrigin`** (`StrEnum`): `archie` (Archie wrote it), `owner` (the owner wrote it in the take
  editor), `chat_edit` (an applied Ask edit), `care` (Review's "Tell Archie" rewrite of a card), `restore` (an
  earlier version saved again, by Restore or by Undo). "Owner-chosen" means any origin except `archie`.
- **`source_artifacts`**: add `origin varchar(16) not null default 'archie'`. The existing `derived_from_id` (the
  version an edit or restore came from) and `instruction` (the edit's one-line description) are now filled for
  `chat_edit` and `restore` versions.
- **`topic_primers`**: add `origin` (default `archie`), `derived_from_id uuid null` (references `topic_primers`) and
  `instruction text null`.
- **`take_versions`**: add `origin varchar(16) not null default 'owner'`; `restore_take_version` now writes
  `restore`, an applied chat edit writes `chat_edit`.
- **`cards`**: add `version int not null default 1` (the current version number).
- **`card_versions`** (new, synced): `id uuid`, `user_id`, `card_id` (cascade), `version int`, `question`, `answer`,
  `origin`, `instruction text null`, `created_at`, `change_seq`; unique `(card_id, version)`. **Created lazily:** a
  card has no rows until its first change, which writes version 1 (the card as it was, origin `archie`) and version 2
  together. So no card writer (analyze, primer, topic primer, take cards, news quiz, Make a card) changes.
- **`edit_proposals`** (new, synced): `id uuid` (server-made), `user_id`, `conversation_id` (cascade), `message_id`
  (the answer that proposed it, cascade), `target_kind` (`StrEnum EditTarget`: `summary`, `primer`, `topic_primer`,
  `take`, `card`), `target_id uuid` (the source for summary and primer, the **topic** for a topic primer, the take,
  the card; no foreign key, since targets are soft-deleted and liveness is checked on Apply), `title` (the target's
  title when proposed: source title, topic name, take title, or the card's question), `description` (one line, from
  the model), `base_version int` (the target's current version when proposed), `before` / `after` JSONB (the
  content in its edit shape, below), `status` (`StrEnum EditStatus`), `applied_version int null`, `created_at`,
  `updated_at`, `change_seq`. Indexes on `(user_id, change_seq)` and `conversation_id`.
- **Edit shapes** (`before`, `after`, `read_item` output, version previews):
  - summary: `{"gist": str, "key_ideas": [{"timestamp": str|null, "idea": str}], "numbers": [{"timestamp":
    str|null, "fact": str}]}` (the `summary` object of the artifact; applying copies the rest of the artifact's
    content — domain, tags, cards — unchanged);
  - primer, topic primer and take: `{"markdown": str}` (a take's body);
  - card: `{"question": str, "answer": str}`.
- **Phone (drizzle 0013):** the new columns on `artifacts` (`origin`, `instruction`), `topic_primers` (`origin`,
  `instruction`), `take_versions` (`origin`) and `cards` (`version`), and the two new tables; it ends with
  `UPDATE sync_state SET position = 0;` so rows written before the app update are pulled.

## The tools Archie gets

Five client tools join `search_library` and web search (all `strict`, executed by the server, results as plain text
JSON; a bad input returns `is_error: true` with a message the model can act on):

| Tool | Input | Returns |
|---|---|---|
| `read_item` | `kind` (`summary`, `primer`, `topic_primer`, `take`, `card`), `id` | `{kind, id, title, version, content, pending}` — `content` in the edit shape; `pending` is the `after` of this chat's still-proposed edit of the same target (or null), so a follow-up ("and the next one too") builds on it |
| `find_cards` | `query` (words, may be empty), `item` (`{kind: source\|topic_primer\|take, id}` or null) | up to 10 live cards `{id, question, answer}` matching any of the words, best first (or the item's cards, oldest first) |
| `propose_summary_edit` | `source_id`, `description`, `gist`, `key_ideas`, `numbers` | `{proposal_id, status}` |
| `propose_text_edit` | `kind` (`primer`, `topic_primer`, `take`), `id`, `description`, `replacements: [{find, replace}]` (1–20; each `find` must occur exactly once) | `{proposal_id, status}` |
| `propose_card_edit` | `card_id`, `description`, `question`, `answer` | `{proposal_id, status}` |

- Text edits are **find/replace**, not a full rewrite: a primer is thousands of words and the owner usually wants one
  line changed, so this is cheaper, faster and leaves the rest word for word. A `find` that is missing or appears
  more than once is an error naming the problem; the model reads again and retries.
- A summary edit sends the whole summary object (it is small and structured, and a find/replace over JSON is fragile).
- A topic primer is addressed by any of its version ids (what search results and the about block carry) or its topic
  id; the proposal stores the topic.
- Proposals are validated before they exist: the target must be live and owned, the new content must differ from the
  current one, and lengths are capped (gist 2,000 characters; at most 30 key ideas and 30 numbers; markdown 60,000,
  a take 20,000 as in the editor; a card question 500 and answer 2,000, as Make a card).
- The answer loop allows **6** model rounds (was 5) and **8,000** output tokens (was 4,000), so "read, propose the
  summary edit and its card edit, then answer" fits.
- **Prompt additions** (after the existing rules): propose edits only when asked; read the current text first and
  change only what was asked; ids come from the about block, `[kind id]` tags and earlier turns; use `find_cards`
  for cards; propose a matching card edit when an edit removes or changes a fact a card asks about; after proposing,
  say in one short sentence what will change and never say it is done; a take is the owner's own words, so change
  only what they asked.

## The proposal lifecycle

```
proposed ──Apply──▶ applied ──Undo──▶ undone
   │  └──Apply when the target changed──▶ stale
   ├──Discard──▶ discarded
   └──a newer proposal for the same target in this chat──▶ superseded
```

- **proposed**: saved with the answer that made it (when the stream ends, even a failed one). A newer proposal for
  the same target in the same chat marks older still-proposed ones **superseded** (the model was given the pending
  edit to build on, so the newest one holds every change).
- **Apply** checks, under the user's write lock: the proposal is the owner's and still `proposed` (Apply on an
  already applied proposal returns it unchanged); the target is still live and its current version is still
  `base_version`. If so it writes `after` as the target's next version (origin `chat_edit`, `instruction` =
  `description`, derived from `base_version`), sets `applied_version`, and marks it **applied**. If the target was
  deleted or changed since, it marks it **stale** and writes nothing; the card says "Changed since you asked. Ask
  again to redo it."
- **Undo** (applied only): if the target's current version is still `applied_version`, it restores `base_version`
  as a new version (origin `restore`) and marks the proposal **undone**. If something changed it since, it refuses
  (409) and the phone says "This was changed since. Use Earlier versions to go back." Undo on an undone proposal
  returns it unchanged.
- **Discard** (proposed only): marks it **discarded**. Terminal.
- Applied side effects match a normal save of that kind: a summary or primer edit re-queues the source's `embed`; a
  topic primer edit embeds the new version; a take edit makes a take version (queues `take_cards` and `embed`); a
  card edit writes card versions.

## Wire shapes

- **SSE events** (added to M7's `delta`, `block`, `searching`, `done`, `error`):
  - `editing {"target_kind": str|null}` when a `read_item`, `find_cards` or `propose_*` call starts (the phone shows
    "Drafting an edit…");
  - `edit {"id", "target_kind", "target_id", "title", "description", "base_version", "before", "after",
    "status": "proposed"}` once a proposal is validated.
- **Pulled rows:** `rows.edit_proposals: [{id, conversation_id, message_id, target_kind, target_id, title,
  description, base_version, before, after, status, applied_version, created_at, updated_at, change_seq}]`;
  `rows.card_versions: [{id, card_id, version, question, answer, origin, instruction, created_at, change_seq}]`;
  `artifacts` and `topic_primers` gain `origin`, `instruction`; `take_versions` gains `origin`; `cards` gain
  `version`. All optional on the phone.
- **Endpoints** (signed in; the owner's own rows only, else 404):
  - `POST /ask/edits/{proposal_id}/apply` → `200` the proposal row (`applied`, or `stale`); `409 {"detail": "edit is
    <status>"}` from discarded, undone or superseded.
  - `POST /ask/edits/{proposal_id}/undo` → `200` the row (`undone`); `409 "changed since"` when the target moved on;
    `409 "edit is <status>"` when it was never applied.
  - `POST /ask/edits/{proposal_id}/discard` → `200` the row (`discarded`); `409` unless proposed (or already
    discarded, which returns it).
  - `POST /versions/restore` `{"target_kind", "target_id", "version"}` → `200 {"version": <new current version>}`;
    `404` unknown target or version; `409 "already current"`. Not whitelisted-only: it calls no model.
  - Takes keep their offline `restore_take_version` outbox action (it now writes origin `restore`); the versions
    sheet for the other four kinds uses `/versions/restore`, which needs a connection.

## Screens (app)

- **Proposal card** in the chat (under the answer's sections, above "Make a card"; one per proposal, in order):
  - kicker `Edit · Summary` / `Edit · Primer` / `Edit · Topic primer` / `Edit · Take` / `Edit · Card`; the target's
    title (tapping it opens the item: source page, primer screen, topic page, take page, or the card in Review); the
    description in ink2;
  - the **diff**: the content as lines (a summary as "Gist", its text, "Key ideas", each idea, "Rough numbers", each
    number; markdown by line; a card as "Question: …" / "Answer: …"), compared line by line; removed lines struck
    through in the missed colour with "−", added lines in the got-it colour with "+", unchanged runs folded to "⋯ N
    unchanged" with one line of context either side;
  - **Apply** (primary) and **Discard** (secondary) while proposed; "Applied" with **Undo** after; "Undone";
    "Discarded"; "Replaced by a newer suggestion"; "Changed since you asked. Ask again to redo it." The phone also
    shows the stale line before Apply is tapped when its own copy of the target has moved past `base_version`.
  - While the answer streams, a proposal appears as soon as its `edit` event arrives, with Apply disabled until the
    answer is done; "Drafting an edit…" shows while a tool runs. Offline, the buttons are disabled and read "Needs a
    connection".
- **Versions sheet** (`app/src/edits/VersionsSheet.tsx`): title `Summary versions` / `Primer versions` / `Card
  versions`; rows newest first, "Version N · <date>" with how it was made (`Archie`, `Edited in Ask`, `Rewritten from
  your note`, `Restored`, `You`), the edit's description under it when there is one, and "Current" on the current
  one. Tapping a row shows that version read-only in the sheet (summary as its sections, markdown rendered, a card's
  question and answer) with **Restore this version** (hidden on the current one) and **Back**. Restore needs a
  connection ("Restoring needs a connection" otherwise); on success the sheet closes and the page shows a toast
  "Restored version N" (N is the version that was copied; the copy becomes the newest version).
- **Entry points:** source ••• menu `Summary versions` and `Primer versions` (each when that kind has more than one
  version); topic ••• menu `Primer versions` (when the topic's primer has more than one); "Cards from this" rows get a
  `Versions` swipe action and " · Edited" in their subtitle when the card is past version 1. The take page's
  "Earlier versions" rows and the version page's kicker add the origin label when it isn't the owner's own save.

## Error handling

- A tool input that fails validation goes back to the model as an error result; it can retry within the six rounds.
  An answer that ends without a proposal is just an answer.
- The stream's failure handling is M7's: a failed answer is stored as failed, and any proposals it made are stored
  with it (each is checked again on Apply).
- Apply, Undo, Discard and Restore: `404` (not the owner's, or the chat was deleted), `409` with the reasons above,
  network failures → a toast "Couldn't reach Archie. Try again." with nothing changed locally. After any success the
  phone writes the returned proposal row into its own copy at once and asks for a sync.
- A proposal whose target was deleted is stale on Apply. Deleting a chat leaves its applied edits in place (they are
  versions now) and its proposals go with the chat.

## Testing

- **Python (pytest, Postgres):**
  - migration 0013 (existing artifacts, topic primers, take versions and cards keep their rows with the new defaults;
    the new tables cascade with their chat and card);
  - `archie_db.versions`: writing and restoring each of the five kinds (version numbers, origin, `derived_from`, the
    current pointer, a card's lazy version 1, a take edit queueing `take_cards` and `embed`);
  - the regeneration rule through `analyze` with the existing `analyze_greatwork` cassette: an owner-chosen summary
    stays current and Archie's new version lands non-current (its cards still replace the old ones); with the text
    replaced after the owner's version, Archie's becomes current;
  - Review's care rewrite writes card versions 1 and 2;
  - the edit endpoints e2e on seeded proposals: apply, stale on a changed or deleted target, undo, undo refused after
    a later change, discard, idempotent repeats, 404 for another user, `/versions/restore` for each kind, and the
    pulled rows;
  - the Ask stream against recorded Anthropic responses: `ask_edit_summary` (an about-source chat asking to remove
    one key idea: `read_item` then `propose_summary_edit`, an `edit` event, a stored proposal whose `after` has one
    key idea fewer and the same gist) and `ask_edit_card` (`find_cards` then `propose_card_edit`); units for
    find/replace application, input validation, supersede, and the history lines.
- **App (jest):** the line diff and its folding; the content-to-lines conversion; version lists and labels per kind;
  the stale check; applying `edit` / `editing` events to a live answer; drizzle migration 0013 keeps an existing card
  and resets the position; pulled proposal and card version rows are stored.
- **Maestro:** a paid `maestro/edit.yaml` (`make maestro-edit`, a few cents): add and finish an article, open Ask
  about this from its ••• menu, ask to remove the first key idea from the summary, see the proposal card, Apply, see
  "Applied", tap Undo, see "Undone", go back to the source page, open ••• → Summary versions and see three rows
  (Archie's, the edit, the restore).

## Not in scope

- Editing anything else through chat: titles, notes, topics, briefs, collections, a take's kind or title.
- Free-form "rewrite this whole primer in a different style" beyond what find/replace and the summary shape allow
  (a large rewrite still works as many replacements, but is not tuned).
- Redo after Undo (ask again), batch "apply all", or editing a proposal's text before applying it.
- Card versions for cards not listed on a source or take page (topic primer, quiz and chat cards): their edits and
  Undo work from the chat, but they have no versions sheet entry.
- Offline Apply, Undo or Restore (Ask needs a connection anyway); take restores stay offline-capable.
- Edit quality and tone tuning (the final eval pass).
