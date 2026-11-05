"""Request and response shapes for `/sync/push` and `/sync/pull`."""

from __future__ import annotations

import datetime
import uuid
from enum import StrEnum
from typing import Any

import pydantic
from archie_db import models

MAX_ACTIONS_PER_PUSH = 50


class ActionType(StrEnum):
    """The actions a phone can push."""

    ADD_SOURCE = "add_source"
    RETRY_SOURCE = "retry_source"
    FINISH_SOURCE = "finish_source"
    QUEUE_PRIMER = "queue_primer"
    REQUEST_PRIMER = "request_primer"
    RETURN_TO_INBOX = "return_to_inbox"
    SET_READ = "set_read"
    SET_PRIMER_OPENED = "set_primer_opened"
    SNOOZE = "snooze"
    SET_QUEUE_POSITION = "set_queue_position"
    GO_DEEPER = "go_deeper"
    READ_LATER = "read_later"
    DELETE_SOURCE = "delete_source"
    ADD_TOPIC = "add_topic"
    RENAME_TOPIC = "rename_topic"
    MERGE_TOPIC = "merge_topic"
    REMOVE_TOPIC = "remove_topic"
    RESTORE_TOPIC = "restore_topic"
    REQUEST_TOPIC_PRIMER = "request_topic_primer"
    SET_SOURCE_TOPIC = "set_source_topic"
    CHOOSE_TOPICS = "choose_topics"
    CHOOSE_EPISODE = "choose_episode"


class ActionIn(pydantic.BaseModel):
    """One user action recorded on the phone; the id makes a retried upload recognizable."""

    id: uuid.UUID
    type: ActionType
    payload: dict[str, Any]


class PushRequest(pydantic.BaseModel):
    """A batch of actions, applied in order."""

    actions: list[ActionIn] = pydantic.Field(max_length=MAX_ACTIONS_PER_PUSH)


class ActionOut(pydantic.BaseModel):
    """How the server answered one action; `reason` is set only when it was rejected."""

    id: uuid.UUID
    result: models.ActionResult
    reason: str | None = None


class PushResponse(pydantic.BaseModel):
    """One answer per pushed action, in the same order."""

    results: list[ActionOut]


class SourceOut(pydantic.BaseModel):
    """A source row as the phone stores it."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    title: str | None
    kind: str
    state: str
    intent: str
    processing: str
    processing_error: str | None
    reaction: str | None
    note: str | None
    merged_into_id: uuid.UUID | None
    sender: str | None
    domain: str | None
    topic_id: uuid.UUID | None
    image_url: str | None
    queue_position: float | None
    read_at: datetime.datetime | None
    snoozed_until: datetime.datetime | None
    primer_opened_at: datetime.datetime | None
    primer_queue_position: float | None
    primer_snoozed_until: datetime.datetime | None
    newsletter_kind: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    change_seq: int


class ArtifactOut(pydantic.BaseModel):
    """A generated summary or primer version as the phone stores it."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    kind: str
    version: int
    content: dict[str, Any]
    is_current: bool
    created_at: datetime.datetime
    change_seq: int


class CardOut(pydantic.BaseModel):
    """A spaced-repetition card as the phone stores it."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    kind: str
    question: str
    answer: str
    created_at: datetime.datetime
    deleted_at: datetime.datetime | None
    change_seq: int


class TopicOut(pydantic.BaseModel):
    """A topic on the user's list as the phone stores it."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    domain: str
    name: str
    origin: str
    removed_at: datetime.datetime | None
    merged_into_id: uuid.UUID | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    change_seq: int


class TopicPrimerOut(pydantic.BaseModel):
    """A topic primer version as the phone stores it."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    topic_id: uuid.UUID
    version: int
    is_current: bool
    content: dict[str, Any]
    opened_at: datetime.datetime | None
    snoozed_until: datetime.datetime | None
    created_at: datetime.datetime
    change_seq: int


class PulledRows(pydantic.BaseModel):
    """Changed rows by table."""

    sources: list[SourceOut]
    artifacts: list[ArtifactOut]
    cards: list[CardOut]
    topics: list[TopicOut]
    topic_primers: list[TopicPrimerOut]


class PullResponse(pydantic.BaseModel):
    """One page of changes; the phone pulls again from `position` while `more` is true."""

    rows: PulledRows
    position: int
    more: bool
