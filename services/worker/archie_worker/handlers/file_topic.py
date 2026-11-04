"""`file_topic`: decide a source's domain and topic from its summary, reusing the user's topics wherever one fits.

The model proposes; the server guard decides. A name matching a live topic (case and punctuation aside) files the
source there; one matching a removed topic leaves it without a topic (domain kept); anything else becomes a new
`archie` topic. Filing never blocks a source from being ready, so this step has no failure hook.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, pipeline, user_topics
from archie_shared import domains
from archie_shared.domains import Domain

from archie_worker import llm, prompts

MAX_OUTPUT_TOKENS = 400


@dataclass(frozen=True)
class FilingDecision:
    """What the model proposed for one source, already cleaned."""

    domain: Domain
    topic: str
    newsletter_kind: models.NewsletterKind | None


@dataclass(frozen=True)
class _FilingRun:
    """What the model call needs, copied out so no ORM object is held across it."""

    source_id: uuid.UUID
    user_id: int
    is_newsletter: bool
    context: llm.CallContext
    api_key: str
    user_message: str


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """File the job's source under a domain and topic, creating an `archie` topic only when nothing fits."""
    run = _prepare(db, job)
    if run is None:
        return

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    completion = llm.complete(
        engine,
        api_key=run.api_key,
        context=run.context,
        models=llm.FILE_TOPIC_MODELS,
        system=prompts.FILE_TOPIC_SYSTEM,
        user_message=run.user_message,
        max_tokens=MAX_OUTPUT_TOKENS,
        json_schema=prompts.FILE_TOPIC_SCHEMA,
    )
    decision = parse_decision(json.loads(completion.text), is_newsletter=run.is_newsletter)

    changes.lock_user_writes(db, run.user_id)
    source = db.get_one(models.Source, run.source_id)
    db.refresh(source)
    if source.deleted_at is not None:
        return
    apply_filing(db, source=source, decision=decision)


def parse_decision(raw: Mapping[str, Any], *, is_newsletter: bool) -> FilingDecision:
    """The model's answer, cleaned: an unknown domain becomes Other, the name is trimmed to the topic length cap."""
    kind = raw.get("newsletter_kind")
    return FilingDecision(
        domain=domains.parse_domain(str(raw["domain"])),
        topic=user_topics.clean_name(str(raw["topic"]))[: user_topics.MAX_TOPIC_NAME_LENGTH],
        newsletter_kind=models.NewsletterKind(kind) if is_newsletter and kind in set(models.NewsletterKind) else None,
    )


def apply_filing(db: sqlalchemy.orm.Session, *, source: models.Source, decision: FilingDecision) -> None:
    """Write the decision through the server guard; the caller holds the user's write lock."""
    existing = user_topics.named_topic(db, user_id=source.user_id, name=decision.topic) if decision.topic else None
    if existing is not None and existing.removed_at is None:
        source.topic_id = existing.id
        source.domain = existing.domain
    elif existing is not None or not decision.topic:
        # A removed topic is the user's "not this": keep the domain, file under no topic.
        source.topic_id = None
        source.domain = decision.domain.value
    else:
        created = user_topics.create_topic(
            db,
            user_id=source.user_id,
            domain=decision.domain,
            name=decision.topic,
            origin=models.TopicOrigin.ARCHIE,
        )
        source.topic_id = created.id
        source.domain = created.domain

    if decision.newsletter_kind is not None:
        source.newsletter_kind = decision.newsletter_kind.value
    changes.touch(source)


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _FilingRun | None:
    """Read the source, its summary and the user's topics, then commit; None when there is nothing to file."""
    source = db.get(models.Source, uuid.UUID(job.payload[pipeline.SOURCE_ID_KEY]))
    if source is None or source.deleted_at is not None:
        return None
    user = db.get_one(models.User, source.user_id)
    if user.topics_chosen_at is None:
        return None
    summary = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.SUMMARY)
    if summary is None:
        return None

    # Checked before reading topics so a user without a key fails at once (PermanentJobError, no hook).
    api_key = llm.api_key_for(user)
    kind = models.SourceKind(source.kind)
    run = _FilingRun(
        source_id=source.id,
        user_id=source.user_id,
        is_newsletter=kind == models.SourceKind.NEWSLETTER,
        context=llm.CallContext(
            user_id=source.user_id, source_id=source.id, job_id=job.id, step=models.JobKind.FILE_TOPIC
        ),
        api_key=api_key,
        user_message=prompts.file_topic_message(
            kind=kind,
            title=source.title,
            analysis=summary.content,
            live_topics=[f"{topic.domain} › {topic.name}" for topic in user_topics.live_topics(db, user_id=user.id)],
            removed_topics=[topic.name for topic in user_topics.removed_topics(db, user_id=user.id)],
        ),
    )
    db.commit()
    return run
