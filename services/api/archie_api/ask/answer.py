"""One Ask answer: the tool loop against Sonnet 5.5, streamed as server-sent events, then saved.

The server runs up to `MAX_ROUNDS` model requests: `search_library` (run here, results returned as citable
`search_result` blocks), Anthropic's web search tool (run by Anthropic), the editing tools of `edit_tools` and
`propose_cards` of `card_set_tools` (both run here). Text streams as `delta` events; each finished text block becomes a
`block` carrying its paragraph's label, sent when the paragraph closes; a search shows as `searching`; an editing tool
call shows as `editing` when it starts, and each proposed edit as an `edit` event; a `propose_cards` call shows as
`drafting_cards` when it starts, and each proposed card set as a `cards` event. Proposals are stored with the answer.
Uncited paragraphs the model writes before a tool call (announcing its search) are streamed but not saved.
The answer is stored when the stream ends — complete only if the model finished its turn (`end_turn` or a stop
sequence), else failed with whatever text arrived: a refusal, a cut-off (`max_tokens`), no answer within `MAX_ROUNDS`,
an API or database error, or the phone hanging up mid-answer. Every model round, finished or not, is recorded in
`llm_calls` (step `ask`). No database transaction is open while the model works.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import uuid
from collections.abc import AsyncGenerator, Generator, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import anthropic
import anyio.to_thread
import httpx
import sqlalchemy
import sqlalchemy.exc
import sqlalchemy.orm
from archie_db import changes, models, search
from archie_llm import embeddings, llm
from archie_shared import logging

from archie_api.ask import card_set_tools, citations, edit_tools, prompts
from archie_api.sync import conversation_actions

# Room for read, propose a summary edit and its card edit, then answer.
MAX_ROUNDS = 6
MAX_TOKENS = 8000
LIBRARY_RESULTS = 8
REQUEST_TIMEOUT_SECONDS = 120
QUERY_TIMEOUT_SECONDS = 5
FAILED_MESSAGE = "Didn't finish. Try again"
# Answers should start fast: thinking only between tool calls, at medium effort (Sonnet 5.5 rejects "disabled").
THINKING: anthropic.types.ThinkingConfigParam = {"type": "between_tools"}
OUTPUT_CONFIG: anthropic.types.OutputConfigParam = {"effort": "medium"}
_TOOL_CHOICE: anthropic.types.ToolChoiceParam = {"type": "auto"}
# The last round may not call tools, so it has to answer.
_LAST_ROUND_TOOL_CHOICE: anthropic.types.ToolChoiceParam = {"type": "none"}
# The SDK's tool types don't cover these plain dicts, hence `Any`.
_TOOLS: list[Any] = [prompts.SEARCH_LIBRARY_TOOL, prompts.WEB_SEARCH_TOOL, *edit_tools.TOOLS, *card_set_tools.TOOLS]
# The stop reasons of a model that finished its turn; any other (e.g. `max_tokens`) leaves the answer unfinished.
_FINISHED_STOP_REASONS = frozenset({"end_turn", "stop_sequence"})
# The `search_library` inputs that bound its results by day.
_SAVED_AFTER = "saved_after"
_SAVED_BEFORE = "saved_before"
_PUBLISHED_AFTER = "published_after"
_PUBLISHED_BEFORE = "published_before"
_DATE_BOUNDS = (_SAVED_AFTER, _SAVED_BEFORE, _PUBLISHED_AFTER, _PUBLISHED_BEFORE)
_MIN_YEAR = 1900
_MAX_YEAR = 2200

_logger = logging.get_logger(logging.LoggerName.API, "ask")


class EventName(StrEnum):
    """The server-sent events of an answer stream."""

    DELTA = "delta"
    BLOCK = "block"
    SEARCHING = "searching"
    EDITING = "editing"
    EDIT = "edit"
    DRAFTING_CARDS = "drafting_cards"
    CARDS = "cards"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True)
class Event:
    """One server-sent event."""

    name: EventName
    data: dict[str, Any]

    def sse(self) -> str:
        """The event on the wire."""
        return f"event: {self.name.value}\ndata: {json.dumps(self.data)}\n\n"


@dataclass(frozen=True)
class AnswerRequest:
    """Everything one answer needs, read before the stream starts so no request-scoped session is used."""

    user_id: int
    conversation_id: uuid.UUID
    user_message_id: uuid.UUID
    web_search: bool
    system: str
    messages: list[dict[str, Any]]
    boost: search.ItemRef | None
    # The note the chat is about, if it is about one: a card set proposed here is that note's cards, named after it.
    note_title: str | None
    # The owner's zone: what day an item belongs to, for the date bounds and the result titles.
    day_zone: datetime.tzinfo
    anthropic_key: str
    # None: the chat's library search is keyword only.
    openai_key: str | None


@dataclass
class _Block:
    """A finished text block, labelled by its paragraph; a dropped one was streamed but isn't saved."""

    segment: citations.Segment
    dropped: bool = False


@dataclass
class _Progress:
    """The answer so far: text blocks whose paragraph closed (in wire order), the open paragraph, the streaming text,
    and the proposals made. The answer's id is fixed up front, so a `cards` event can name the message it is saved on.
    """

    blocks: list[_Block] = field(default_factory=list)
    paragraphs: citations.Paragraphs = field(default_factory=citations.Paragraphs)
    partial: str = ""
    proposals: list[edit_tools.Proposal] = field(default_factory=list)
    card_sets: list[card_set_tools.Proposal] = field(default_factory=list)
    message_id: uuid.UUID = field(default_factory=uuid.uuid4)

    @property
    def next_block(self) -> int:
        """The wire index of the text block streaming now: every text block of the answer counts, dropped or not."""
        return len(self.blocks) + len(self.paragraphs.open)


class AnswerRefusedError(Exception):
    """The model declined to answer; stored as a failed answer the owner can retry."""


class AnswerIncompleteError(Exception):
    """The model stopped before finishing its turn (cut off, or out of rounds); stored as a failed answer."""


def stream(engine: sqlalchemy.Engine, request: AnswerRequest) -> Generator[str, None, None]:
    """The answer's events as SSE text, ending with `done` or `error`; the answer is saved either way."""
    progress = _Progress()
    try:
        # Closing `_run` explicitly on hang-up records its round before `_save` runs below.
        with contextlib.closing(_run(engine, request=request, progress=progress)) as events:
            for event in events:
                yield event.sse()
    except GeneratorExit:
        # The phone hung up: keep what arrived so the chat shows "Didn't finish" rather than nothing.
        _save(engine, request=request, progress=progress, failed=True)
        raise
    except (
        anthropic.APIError,
        AnswerRefusedError,
        AnswerIncompleteError,
        ValueError,
        sqlalchemy.exc.SQLAlchemyError,
    ) as error:
        # ValueError: the SDK could not parse the stream (e.g. a tool input that isn't JSON). SQLAlchemyError: a
        # library search or a cost record failed; keep the owner's partial answer and end the stream cleanly.
        _logger.warning("Answer failed for conversation %s: %r", request.conversation_id, error)
        _save(engine, request=request, progress=progress, failed=True)
        yield Event(name=EventName.ERROR, data={"message": FAILED_MESSAGE}).sse()
        return

    message_id = _save(engine, request=request, progress=progress, failed=False)
    yield Event(name=EventName.DONE, data={"message_id": str(message_id)}).sse()


async def stream_async(engine: sqlalchemy.Engine, request: AnswerRequest) -> AsyncGenerator[str, None]:
    """`stream` for the event loop: each event is pulled on a worker thread, and closing this closes `stream`.

    Starlette's own sync-iterator adapter never closes the generator, so a hang-up would save the unfinished answer
    only at garbage collection, on the event loop's thread. Closing it here runs that save on a worker thread, now.
    """
    generator = stream(engine, request)
    done = object()
    try:
        while (event := await anyio.to_thread.run_sync(next, generator, done)) is not done:
            assert isinstance(event, str)
            yield event
    finally:
        await anyio.to_thread.run_sync(generator.close)


def _run(engine: sqlalchemy.Engine, *, request: AnswerRequest, progress: _Progress) -> Generator[Event, None, None]:
    """The tool loop; the last round may not call tools, so it has to answer."""
    client = anthropic.Anthropic(api_key=request.anthropic_key, max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS)
    context = llm.CallContext(user_id=request.user_id, source_id=None, job_id=None, step=llm.ASK_STEP)
    messages: list[Any] = list(request.messages)
    passages: dict[str, search.ChunkHit] = {}

    for round_number in range(1, MAX_ROUNDS + 1):
        tool_choice = _LAST_ROUND_TOOL_CHOICE if round_number == MAX_ROUNDS else _TOOL_CHOICE
        round_start = len(progress.blocks)
        response = yield from _round(
            engine,
            client=client,
            context=context,
            request=request,
            messages=messages,
            tool_choice=tool_choice,
            progress=progress,
            passages=passages,
        )

        if response.stop_reason == "refusal":
            raise AnswerRefusedError(str(response.stop_details))
        if response.stop_reason in _FINISHED_STOP_REASONS:
            return
        # Web search's own loop paused; re-sending the turn resumes it.
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue
        tool_uses = [block for block in response.content if block.type == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            raise AnswerIncompleteError(f"the model stopped on {response.stop_reason}")

        # An uncited paragraph before a tool call announces the search ("Let me search your library"); it isn't the
        # answer. A cited paragraph is kept whole, including the uncited fragments citations cut it into.
        announced = progress.blocks[round_start:]
        dropped = citations.uncited_paragraphs_dropped([block.segment for block in announced])
        for block, is_dropped in zip(announced, dropped, strict=True):
            block.dropped = is_dropped
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for tool_use in tool_uses:
            result = yield from _run_tool(
                engine, request=request, tool_use=tool_use, passages=passages, progress=progress
            )
            results.append(result)
        messages.append({"role": "user", "content": results})

    raise AnswerIncompleteError(f"no answer within {MAX_ROUNDS} rounds")


def _round(
    engine: sqlalchemy.Engine,
    *,
    client: anthropic.Anthropic,
    context: llm.CallContext,
    request: AnswerRequest,
    messages: list[Any],
    tool_choice: anthropic.types.ToolChoiceParam,
    progress: _Progress,
    passages: dict[str, search.ChunkHit],
) -> Generator[Event, None, anthropic.types.Message]:
    """One model request streamed as events, its paragraph closed at the end; returns the finished message.

    The round is recorded in `llm_calls` once, finished or not: a round cut off mid-stream (an API error, or the phone
    hanging up) has still spent the tokens of the message so far.
    """
    with client.messages.stream(
        model=llm.SONNET,
        max_tokens=MAX_TOKENS,
        system=request.system,
        messages=messages,
        tools=_TOOLS,
        tool_choice=tool_choice,
        thinking=THINKING,
        output_config=OUTPUT_CONFIG,
    ) as response_stream:
        started = False
        response: anthropic.types.Message | None = None
        try:
            for stream_event in response_stream:
                started = started or stream_event.type == "message_start"
                yield from _events_of(stream_event, progress=progress, passages=passages)
            yield from _blocks_of(progress.paragraphs.finish(), progress=progress)
            response = response_stream.get_final_message()
            return response
        finally:
            # The SDK's message snapshot exists only once `message_start` arrived; before that nothing was spent.
            spent = response or (response_stream.current_message_snapshot if started else None)
            if spent is not None:
                llm.record_call(engine, context=context, model=llm.SONNET, response=spent)


def _events_of(stream_event: Any, *, progress: _Progress, passages: dict[str, search.ChunkHit]) -> Iterator[Event]:
    """The phone's events for one SDK stream event; most SDK events have none."""
    if stream_event.type == "text":
        progress.partial += stream_event.text
        yield Event(name=EventName.DELTA, data={"block": progress.next_block, "text": stream_event.text})
        return
    # A tool call, a search result or thinking ends the paragraph before it.
    if stream_event.type == "content_block_start" and stream_event.content_block.type != "text":
        yield from _blocks_of(progress.paragraphs.close(), progress=progress)
        block = stream_event.content_block
        if block.type == "tool_use" and block.name in edit_tools.TOOL_NAMES:
            yield Event(name=EventName.EDITING, data={"target_kind": None})
        elif block.type == "tool_use" and block.name in card_set_tools.TOOL_NAMES:
            yield Event(name=EventName.DRAFTING_CARDS, data={})
        return
    if stream_event.type != "content_block_stop":
        return

    block = stream_event.content_block
    if block.type == "text":
        progress.partial = ""
        closed = progress.paragraphs.add(citations.segment_of(block, passages=passages))
        yield from _blocks_of(closed, progress=progress)
    elif block.type == "tool_use" and block.name == prompts.SEARCH_LIBRARY_TOOL["name"]:
        yield Event(name=EventName.SEARCHING, data={"kind": "library", "query": _query_of(block.input) or ""})
    elif block.type == "server_tool_use" and block.name == prompts.WEB_SEARCH_TOOL["name"]:
        yield Event(name=EventName.SEARCHING, data={"kind": "web", "query": _query_of(block.input) or ""})


def _blocks_of(closed: list[citations.Segment], *, progress: _Progress) -> Iterator[Event]:
    """A closed paragraph's blocks, kept in order and sent as `block` events with the paragraph's label."""
    for segment in closed:
        progress.blocks.append(_Block(segment=segment))
        data = {"block": len(progress.blocks) - 1, "label": segment.label.value, "citations": segment.citations}
        yield Event(name=EventName.BLOCK, data=data)


def _run_tool(
    engine: sqlalchemy.Engine,
    *,
    request: AnswerRequest,
    tool_use: anthropic.types.ToolUseBlock,
    passages: dict[str, search.ChunkHit],
    progress: _Progress,
) -> Generator[Event, None, dict[str, Any]]:
    """One tool call's result block; a proposal is kept for the save and shown at once as an `edit` or `cards` event."""
    if tool_use.name in card_set_tools.TOOL_NAMES:
        card_set = card_set_tools.run(tool_use_id=tool_use.id, tool_input=tool_use.input, note_title=request.note_title)
        if card_set.proposal is not None:
            progress.card_sets.append(card_set.proposal)
            data = card_set.proposal.to_event(conversation_id=request.conversation_id, message_id=progress.message_id)
            yield Event(name=EventName.CARDS, data=data)
        return card_set.result
    if tool_use.name not in edit_tools.TOOL_NAMES:
        return _search_library(engine, request=request, tool_use=tool_use, passages=passages)

    context = edit_tools.ToolContext(
        user_id=request.user_id, conversation_id=request.conversation_id, pending=tuple(progress.proposals)
    )
    outcome = edit_tools.run(
        engine, context=context, tool_use_id=tool_use.id, name=tool_use.name, tool_input=tool_use.input
    )
    if outcome.proposal is not None:
        progress.proposals.append(outcome.proposal)
        yield Event(name=EventName.EDIT, data=outcome.proposal.to_event())
    return outcome.result


def _search_library(
    engine: sqlalchemy.Engine,
    *,
    request: AnswerRequest,
    tool_use: anthropic.types.ToolUseBlock,
    passages: dict[str, search.ChunkHit],
) -> dict[str, Any]:
    """Run `search_library` and answer with citable passages; a bad input goes back as an error the model can fix."""
    query = _query_of(tool_use.input)
    dates = _dates_of(tool_use.input, day_zone=request.day_zone)
    if not query or dates is None:
        error = json.dumps({"INVALID_JSON": json.dumps(tool_use.input)})
        return {"type": "tool_result", "tool_use_id": tool_use.id, "is_error": True, "content": error}

    # Embedded before the session opens: no transaction is held across the OpenAI call.
    embedding = _query_embedding(engine, request=request, query=query)
    with sqlalchemy.orm.Session(engine) as db:
        hits = search.search_chunks(
            db,
            user_id=request.user_id,
            query=query,
            query_embedding=embedding,
            limit=LIBRARY_RESULTS,
            boost=request.boost,
            match_any=True,
            dates=dates,
        )
    passages.update({citations.source_key(hit): hit for hit in hits})

    content: list[dict[str, Any]] = [citations.search_result_block(hit, day_zone=request.day_zone) for hit in hits] or [
        {"type": "text", "text": "Nothing in the owner's library matched."}
    ]
    return {"type": "tool_result", "tool_use_id": tool_use.id, "content": content}


def _query_of(tool_input: object) -> str | None:
    """The `query` string of a tool input, or None when the input isn't one (eager streaming skips validation)."""
    if not isinstance(tool_input, dict):
        return None
    query = tool_input.get("query")
    return query.strip() if isinstance(query, str) and query.strip() else None


def _dates_of(tool_input: object, *, day_zone: datetime.tzinfo) -> search.DateFilter | None:
    """The tool input's day bounds, as the owner's days; None when one is given but isn't a YYYY-MM-DD date."""
    if not isinstance(tool_input, dict):
        return search.DateFilter(day_zone=day_zone)
    bounds = {name: tool_input.get(name) for name in _DATE_BOUNDS}
    # Eager input streaming skips the schema's validation, so a bound can be anything.
    if not all(bound is None or _is_day(bound) for bound in bounds.values()):
        return None

    days = {name: datetime.date.fromisoformat(bound) if bound else None for name, bound in bounds.items()}
    return search.DateFilter(
        saved_after=days[_SAVED_AFTER],
        saved_before=days[_SAVED_BEFORE],
        published_after=days[_PUBLISHED_AFTER],
        published_before=days[_PUBLISHED_BEFORE],
        day_zone=day_zone,
    )


def _is_day(bound: object) -> bool:
    if not isinstance(bound, str):
        return False
    try:
        day = datetime.date.fromisoformat(bound)
    except ValueError:
        return False
    # A model's "no end" 9999-12-31 would overflow the day-after arithmetic in search.
    return _MIN_YEAR <= day.year <= _MAX_YEAR


def _query_embedding(engine: sqlalchemy.Engine, *, request: AnswerRequest, query: str) -> list[float] | None:
    if request.openai_key is None:
        return None
    context = llm.CallContext(user_id=request.user_id, source_id=None, job_id=None, step=llm.EMBED_STEP)
    try:
        [vector] = embeddings.embed(
            engine, api_key=request.openai_key, context=context, texts=[query], timeout_seconds=QUERY_TIMEOUT_SECONDS
        )
    except (httpx.HTTPError, embeddings.EmbeddingError) as error:
        _logger.warning("Chat query embedding failed, searching by keyword only: %r", error)
        return None
    return vector


def _save(engine: sqlalchemy.Engine, *, request: AnswerRequest, progress: _Progress, failed: bool) -> uuid.UUID:
    """Store the answer and give the question, the answer and the chat new positions, so the phone pulls them."""
    # The answer ended (or broke) mid-paragraph: its finished blocks still get the paragraph's label.
    blocks = [*progress.blocks, *(_Block(segment=segment) for segment in progress.paragraphs.finish())]
    segments = [block.segment for block in blocks if not block.dropped]
    # A block cut off mid-stream has no citations yet; keep its words as background so the owner sees them.
    if progress.partial.strip():
        segments.append(citations.Segment(label=citations.AnswerLabel.BACKGROUND, text=progress.partial, citations=[]))
    message_id = progress.message_id

    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, request.user_id)
        db.add(
            models.Message(
                id=message_id,
                user_id=request.user_id,
                conversation_id=request.conversation_id,
                role=models.MessageRole.ASSISTANT.value,
                text="".join(segment.text for segment in segments).strip(),
                segments=[segment.to_wire() for segment in segments],
                web_search=request.web_search,
                status=(models.MessageStatus.FAILED if failed else models.MessageStatus.COMPLETE).value,
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        # A failed answer keeps its proposals too: each edit is checked against its target again on Apply, and a card
        # set holds everything Save needs.
        edit_tools.save_proposals(
            db,
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            message_id=message_id,
            proposals=progress.proposals,
        )
        card_set_tools.save_proposals(
            db,
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            message_id=message_id,
            proposals=progress.card_sets,
        )
        question = db.get_one(models.Message, request.user_message_id)
        question.change_seq = changes.next_change_seq()
        conversation_actions.touch_conversation(db.get_one(models.Conversation, request.conversation_id))
        db.commit()
    return message_id
