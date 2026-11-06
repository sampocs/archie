"""`news_quiz`: the week's news quiz cards, written from the stories of the user's recently Done briefs.

The stories of every brief Done in the last 7 days are de-duplicated by headline (the newest brief's copy wins) and
the `QUIZ_CARD_COUNT` most important are sent to one model call that writes a card per story. Each card keeps the
brief its story came from and expires `card_rows.QUIZ_LIFETIME` after it is made. There is no failure hook: a failed
quiz just means no quiz this week.

Follows the loop's handler contract: read and commit, call the model holding no transaction, then lock and write.
"""

from __future__ import annotations

import datetime
import json
import uuid
from dataclasses import dataclass

import pydantic
import sqlalchemy
import sqlalchemy.orm
from archie_db import briefs, card_rows, changes, models
from archie_llm import llm

from archie_worker import brief_content, keys, prompts

QUIZ_CARD_COUNT = 5
MAX_OUTPUT_TOKENS = 2000
# The week's job may be queued twice (the phone retries); a quiz made inside this window already answers it.
_DUPLICATE_WINDOW = datetime.timedelta(days=6)


class _QuizCard(pydantic.BaseModel):
    story_index: int
    question: str = pydantic.Field(min_length=1)
    answer: str = pydantic.Field(min_length=1)


class _QuizOutput(pydantic.BaseModel):
    cards: list[_QuizCard]


@dataclass(frozen=True)
class _QuizStory:
    """A story chosen for the quiz with the brief it came from."""

    brief_id: uuid.UUID
    story: brief_content.Story


@dataclass(frozen=True)
class _QuizRun:
    """What the model call and the write need after the first transaction ends."""

    user_id: int
    stories: list[_QuizStory]
    context: llm.CallContext
    api_key: str
    user_message: str


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Write one quiz card per top story of the week's Done briefs, unless the week already has its quiz."""
    run = _prepare(db, job)
    if run is None:
        return

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    completion = llm.complete(
        engine,
        api_key=run.api_key,
        context=run.context,
        models=llm.NEWS_QUIZ_MODELS,
        system=prompts.NEWS_QUIZ_SYSTEM,
        user_message=run.user_message,
        max_tokens=MAX_OUTPUT_TOKENS,
        json_schema=prompts.NEWS_QUIZ_SCHEMA,
    )
    output = _QuizOutput.model_validate(json.loads(completion.text))

    changes.lock_user_writes(db, run.user_id)
    if _has_recent_quiz(db, user_id=run.user_id):
        # A duplicate job finished first while this call ran.
        return

    _insert_cards(db, run=run, output=output)


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _QuizRun | None:
    """Choose the stories and build the call, then commit; None when no Done brief has any story."""
    user = db.get_one(models.User, int(job.payload[briefs.USER_ID_KEY]))
    api_key = keys.anthropic_key_for(user)
    stories = _top_stories(card_rows.recently_done_briefs(db, user_id=user.id))
    if not stories:
        db.commit()
        return None

    quiz_stories = [
        prompts.QuizStory(
            index=index,
            headline=item.story.headline,
            body=item.story.body,
            why=item.story.why,
            detail=item.story.detail,
        )
        for index, item in enumerate(stories, start=1)
    ]
    run = _QuizRun(
        user_id=user.id,
        stories=stories,
        context=llm.CallContext(user_id=user.id, source_id=None, job_id=job.id, step=models.JobKind.NEWS_QUIZ),
        api_key=api_key,
        user_message=prompts.news_quiz_message(quiz_stories),
    )
    db.commit()
    return run


def _top_stories(done_briefs: list[models.Brief]) -> list[_QuizStory]:
    """The most important stories across the briefs (newest first), one per headline, newest brief's copy winning."""
    by_headline: dict[str, _QuizStory] = {}
    for brief in done_briefs:
        if brief.content is None:
            continue

        for domain in brief_content.BriefContent.model_validate(brief.content).domains:
            for story in domain.stories:
                by_headline.setdefault(story.headline.casefold(), _QuizStory(brief_id=brief.id, story=story))

    # Sorting is stable, so equal importance keeps the newest brief's stories first.
    ranked = sorted(by_headline.values(), key=lambda item: -item.story.importance)
    return ranked[:QUIZ_CARD_COUNT]


def _has_recent_quiz(db: sqlalchemy.orm.Session, *, user_id: int) -> bool:
    return (
        db.scalar(
            sqlalchemy.select(models.Card.id)
            .where(
                models.Card.user_id == user_id,
                models.Card.kind == models.CardKind.QUIZ.value,
                models.Card.created_at >= sqlalchemy.func.now() - _DUPLICATE_WINDOW,
            )
            .limit(1)
        )
        is not None
    )


def _insert_cards(db: sqlalchemy.orm.Session, *, run: _QuizRun, output: _QuizOutput) -> None:
    """One card per story the model named (first answer per story; an unknown story number is ignored)."""
    seen: set[int] = set()
    for card in output.cards:
        if not 1 <= card.story_index <= len(run.stories) or card.story_index in seen:
            continue

        seen.add(card.story_index)
        db.add(
            models.Card(
                id=uuid.uuid4(),
                user_id=run.user_id,
                brief_id=run.stories[card.story_index - 1].brief_id,
                kind=models.CardKind.QUIZ.value,
                question=card.question,
                answer=card.answer,
                expires_at=sqlalchemy.func.now() + card_rows.QUIZ_LIFETIME,
                change_seq=changes.next_change_seq(),
            )
        )
