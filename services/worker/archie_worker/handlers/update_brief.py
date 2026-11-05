"""`update_brief`: rewrite the user's open newsletter brief from every newsletter it covers now.

Covered are all of the user's ready, live inbox newsletters (`briefs.covered_newsletters`). Essays are listed with
their summary's gist as the pitch, with no model call; news newsletters go to one call that groups, ranks and writes
the stories, which `brief_content.assemble` then trims and orders. That call reads each newsletter's current
(cleaned) text, newest first, until the 150,000-character budget is spent; older ones are given as their summary
until a 60,000-character summary budget is spent. Newsletters older than that are deferred, not dropped: they are left
out of the call and out of the brief (`source_ids`, `since`), so Done doesn't brief them, they stay in the inbox, and
a later brief covers them once this one is Done. The model writes at most `prompts.MAX_MODEL_STORIES` stories.

Follows the loop's handler contract: read and commit, call the model holding no transaction, then lock and write.
There is no failure hook: a failed rewrite leaves the previous content in place, so a brief never shows an error.
"""

from __future__ import annotations

import datetime
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy
import sqlalchemy.orm
from archie_db import briefs, changes, models, pipeline, user_topics

from archie_worker import brief_content, content, llm, prompts

MAX_OUTPUT_TOKENS = 32000

# What an essay-only brief's (absent) model answer amounts to.
_NO_STORIES: dict[str, Any] = {"domains": [], "also": []}


@dataclass(frozen=True)
class _NewsCall:
    """The one model call for the news newsletters, copied out of the session."""

    context: llm.CallContext
    api_key: str
    user_message: str


@dataclass(frozen=True)
class _NewsInput:
    """One news newsletter with the text and summary the call may read, and which of them it gets."""

    source: models.Source
    text: str
    summary: str
    choice: prompts.BriefInput


@dataclass(frozen=True)
class _BriefRun:
    """What the rewrite needs after its first transaction ends; `news_call` is None when only essays are covered."""

    brief_id: uuid.UUID
    user_id: int
    covered_ids: list[uuid.UUID]
    since: datetime.datetime
    news_ids: frozenset[uuid.UUID]
    essays: list[brief_content.Essay]
    news_call: _NewsCall | None


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Write the open brief's next version, or clear it when it covers nothing any more."""
    run = _prepare(db, job)
    if run is None:
        return

    assembled = brief_content.assemble(_stories(db, run), news_ids=run.news_ids, essays=run.essays)

    # The user may have tapped Done during the call; whatever it left unbriefed already has its own rewrite queued.
    changes.lock_user_writes(db, run.user_id)
    brief = db.get_one(models.Brief, run.brief_id)
    db.refresh(brief)
    if brief.status != models.BriefStatus.OPEN:
        return

    _write_version(brief, brief_json=assembled.to_json(), source_ids=run.covered_ids, since=run.since)


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _BriefRun | None:
    """Collect the covered newsletters under the user's lock, opening a brief for them, and commit.

    None when nothing is covered: an open brief with content is cleared (its newsletters were all queued or deleted),
    one without is left as is, and no brief is opened. Raises `PermanentJobError` for a user without an API key when
    there is news to write.
    """
    user = db.get_one(models.User, int(job.payload[briefs.USER_ID_KEY]))
    changes.lock_user_writes(db, user.id)
    covered = briefs.covered_newsletters(db, user_id=user.id)
    brief = briefs.open_brief(db, user_id=user.id)

    if not covered:
        if brief is not None and brief.content is not None:
            _write_version(brief, brief_json=None, source_ids=[], since=None)
        return None

    brief = brief or _open_brief(db, user_id=user.id)
    # A newsletter not filed as an essay (including one not filed yet) is news.
    essays = [source for source in covered if source.newsletter_kind == models.NewsletterKind.ESSAY]
    news_sources = [source for source in covered if source.newsletter_kind != models.NewsletterKind.ESSAY]
    inputs = _news_inputs(db, news=news_sources)

    # The oldest news may not fit the call; it stays out of the brief so Done leaves it for the next one.
    omitted_ids = {item.source.id for item in inputs if item.choice == prompts.BriefInput.OMITTED}
    briefed = [source for source in covered if source.id not in omitted_ids]
    news = [item for item in inputs if item.choice != prompts.BriefInput.OMITTED]
    run = _BriefRun(
        brief_id=brief.id,
        user_id=user.id,
        covered_ids=[source.id for source in briefed],
        since=briefed[0].created_at,
        news_ids=frozenset(item.source.id for item in news),
        essays=[_essay(db, source=source) for source in essays],
        news_call=_news_call(user=user, news=news, topics=_topic_labels(db, user_id=user.id), job_id=job.id)
        if news
        else None,
    )
    db.commit()
    return run


def _stories(db: sqlalchemy.orm.Session, run: _BriefRun) -> dict[str, Any]:
    """The model's `{domains, also}` answer about the news newsletters, made on the call's own connection."""
    if run.news_call is None:
        return _NO_STORIES

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    completion = llm.complete(
        engine,
        api_key=run.news_call.api_key,
        context=run.news_call.context,
        models=llm.BRIEF_MODELS,
        system=prompts.BRIEF_SYSTEM,
        user_message=run.news_call.user_message,
        max_tokens=MAX_OUTPUT_TOKENS,
        json_schema=prompts.BRIEF_SCHEMA,
    )
    answer: dict[str, Any] = json.loads(completion.text)
    return answer


def _news_inputs(db: sqlalchemy.orm.Session, *, news: Sequence[models.Source]) -> list[_NewsInput]:
    """Each news newsletter (oldest first) with its capped text, its summary and how the call takes it."""
    texts = [_current_text(db, source=source)[: prompts.MAX_BRIEF_TEXT_CHARACTERS] for source in news]
    summaries = [prompts.summary_text(_summary(db, source=source).content) for source in news]
    choices = prompts.choose_brief_inputs(
        text_lengths=[len(text) for text in texts], summary_lengths=[len(summary) for summary in summaries]
    )
    return [
        _NewsInput(source=source, text=text, summary=summary, choice=choice)
        for source, text, summary, choice in zip(news, texts, summaries, choices, strict=True)
    ]


def _topic_labels(db: sqlalchemy.orm.Session, *, user_id: int) -> list[str]:
    return [f"{topic.domain} › {topic.name}" for topic in user_topics.live_topics(db, user_id=user_id)]


def _news_call(*, user: models.User, news: Sequence[_NewsInput], topics: Sequence[str], job_id: int) -> _NewsCall:
    """The call's key, cost record and message: the news newsletters within the budgets, and the user's topics."""
    newsletters = [
        prompts.BriefNewsletter(
            source_id=str(item.source.id),
            sender=item.source.sender,
            subject=item.source.title,
            received_at=item.source.created_at,
            text=item.text if item.choice == prompts.BriefInput.FULL else item.summary,
            is_summary=item.choice != prompts.BriefInput.FULL,
        )
        for item in news
    ]
    return _NewsCall(
        context=llm.CallContext(user_id=user.id, source_id=None, job_id=job_id, step=models.JobKind.UPDATE_BRIEF),
        api_key=llm.api_key_for(user),
        user_message=prompts.brief_message(newsletters=newsletters, live_topics=topics),
    )


def _current_text(db: sqlalchemy.orm.Session, *, source: models.Source) -> str:
    text = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.TEXT)
    if text is None:
        raise LookupError(f"Ready newsletter {source.id} has no text artifact")
    text_value: str = text.content[content.TEXT_KEY]
    return text_value


def _summary(db: sqlalchemy.orm.Session, *, source: models.Source) -> models.SourceArtifact:
    summary = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.SUMMARY)
    if summary is None:
        raise LookupError(f"Ready newsletter {source.id} has no summary")
    return summary


def _essay(db: sqlalchemy.orm.Session, *, source: models.Source) -> brief_content.Essay:
    return brief_content.Essay(source_id=source.id, pitch=_summary(db, source=source).content["summary"]["gist"])


def _open_brief(db: sqlalchemy.orm.Session, *, user_id: int) -> models.Brief:
    brief = models.Brief(
        id=uuid.uuid4(),
        user_id=user_id,
        status=models.BriefStatus.OPEN.value,
        change_seq=changes.next_change_seq(),
    )
    db.add(brief)
    db.flush()
    return brief


def _write_version(
    brief: models.Brief,
    *,
    brief_json: dict[str, Any] | None,
    source_ids: list[uuid.UUID],
    since: datetime.datetime | None,
) -> None:
    """Replace the brief's content as its next version; the caller holds the user's write lock."""
    brief.content = brief_json
    brief.source_ids = source_ids
    brief.since = since
    brief.version = brief.version + 1
    brief.updated_at = sqlalchemy.func.now()
    brief.change_seq = changes.next_change_seq()
