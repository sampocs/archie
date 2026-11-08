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
    FINISH_BRIEF = "finish_brief"
    REVIEW_CARD = "review_card"
    DROP_CARD = "drop_card"
    SET_CARDS_OFF = "set_cards_off"
    REQUEST_NEWS_QUIZ = "request_news_quiz"
    SET_FAVORITE = "set_favorite"
    CREATE_COLLECTION = "create_collection"
    UPDATE_COLLECTION = "update_collection"
    ADD_COLLECTION_ITEM = "add_collection_item"
    UPDATE_COLLECTION_ITEM = "update_collection_item"
    SAVE_TAKE = "save_take"
    UPDATE_TAKE = "update_take"
    RESTORE_TAKE_VERSION = "restore_take_version"
    RETRY_TAKE_CLEANUP = "retry_take_cleanup"
    DELETE_CONVERSATION = "delete_conversation"
    # Removed feature; it stays only so an old phone's pending action is rejected rather than failing the push.
    SET_PREP_ME = "set_prep_me"


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
    cards_off: bool
    favorited_at: datetime.datetime | None
    published_at: datetime.datetime | None
    confirm_url: str | None
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
    origin: str
    instruction: str | None
    is_current: bool
    created_at: datetime.datetime
    change_seq: int


class CardOut(pydantic.BaseModel):
    """A spaced-repetition card as the phone stores it, with the FSRS state its scheduler last wrote."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID | None
    topic_primer_id: uuid.UUID | None
    brief_id: uuid.UUID | None
    take_id: uuid.UUID | None
    take_version_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    message_id: uuid.UUID | None
    kind: str
    question: str
    answer: str
    version: int
    fsrs_state: str
    stability: float | None
    difficulty: float | None
    due_at: datetime.datetime | None
    last_review_at: datetime.datetime | None
    reps: int
    lapses: int
    expires_at: datetime.datetime | None
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
    origin: str
    instruction: str | None
    opened_at: datetime.datetime | None
    snoozed_until: datetime.datetime | None
    created_at: datetime.datetime
    change_seq: int


class BriefOut(pydantic.BaseModel):
    """A newsletter brief as the phone stores it; `content` is null until its first version is written."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    content: dict[str, Any] | None
    source_ids: list[uuid.UUID]
    since: datetime.datetime | None
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    done_at: datetime.datetime | None
    change_seq: int


class CollectionOut(pydantic.BaseModel):
    """A collection as the phone stores it."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    position: float
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    change_seq: int


class CollectionItemOut(pydantic.BaseModel):
    """A saved post as the phone stores it; the preview fields stay null until `fetch_collection_item` fills them."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    collection_id: uuid.UUID
    url: str
    kind: str
    title: str | None
    author: str | None
    image_url: str | None
    duration_seconds: int | None
    note: str | None
    metadata_status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    change_seq: int


class TakeOut(pydantic.BaseModel):
    """A take as the phone stores it; its body lives in its versions."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    current_version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    change_seq: int


class TakeVersionOut(pydantic.BaseModel):
    """One version of a take's body as the phone stores it; `body` is null while Clean it up runs."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    take_id: uuid.UUID
    version: int
    body: str | None
    raw_body: str
    cleaned: bool
    clean_failed: bool
    origin: str
    created_at: datetime.datetime
    change_seq: int


class ConversationOut(pydantic.BaseModel):
    """A saved Ask chat as the phone stores it."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    about_kind: str | None
    about_source_id: uuid.UUID | None
    about_topic_primer_id: uuid.UUID | None
    about_take_id: uuid.UUID | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    change_seq: int


class MessageOut(pydantic.BaseModel):
    """One chat message as the phone stores it; `segments` is null for a question."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    text: str
    segments: list[dict[str, Any]] | None
    web_search: bool
    status: str
    created_at: datetime.datetime
    change_seq: int


class CardVersionOut(pydantic.BaseModel):
    """One version of a card's question and answer as the phone stores it."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    card_id: uuid.UUID
    version: int
    question: str
    answer: str
    origin: str
    instruction: str | None
    created_at: datetime.datetime
    change_seq: int


class EditProposalOut(pydantic.BaseModel):
    """An edit Ask proposed in a chat, as the phone stores it and as the edit routes return it."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    target_kind: str
    target_id: uuid.UUID
    title: str
    description: str
    base_version: int
    before: dict[str, Any]
    after: dict[str, Any]
    status: str
    applied_version: int | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    change_seq: int


class PulledRows(pydantic.BaseModel):
    """Changed rows by table."""

    sources: list[SourceOut]
    artifacts: list[ArtifactOut]
    cards: list[CardOut]
    topics: list[TopicOut]
    topic_primers: list[TopicPrimerOut]
    briefs: list[BriefOut]
    collections: list[CollectionOut]
    collection_items: list[CollectionItemOut]
    takes: list[TakeOut]
    take_versions: list[TakeVersionOut]
    conversations: list[ConversationOut]
    messages: list[MessageOut]
    card_versions: list[CardVersionOut]
    edit_proposals: list[EditProposalOut]


class PullResponse(pydantic.BaseModel):
    """One page of changes; the phone pulls again from `position` while `more` is true."""

    rows: PulledRows
    position: int
    more: bool
