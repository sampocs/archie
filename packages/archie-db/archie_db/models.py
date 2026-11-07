"""SQLAlchemy ORM models for Archie's Postgres database.

The phone keeps a full copy of each user's rows, so every synced table carries a `change_seq`
from one shared Postgres sequence: a pull asks for everything past the last position it saw.
The migrations in `migrations/versions/` must match these exactly (a test compares them).
"""

from __future__ import annotations

import datetime
import secrets
import string
import uuid
from decimal import Decimal
from enum import StrEnum
from typing import Any

import sqlalchemy
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from archie_db import vector

TIMESTAMP = sqlalchemy.DateTime(timezone=True)
CHANGE_SEQ_NAME = "change_seq"


class Base(DeclarativeBase):
    """Declarative base whose metadata Alembic compares against."""


# Declared on the metadata so autogenerate and `create_all` know the sequence exists.
CHANGE_SEQ = sqlalchemy.Sequence(CHANGE_SEQ_NAME, metadata=Base.metadata)


class SourceKind(StrEnum):
    """What a source points at."""

    LINK = "link"
    ARTICLE = "article"
    X = "x"
    YOUTUBE = "youtube"
    PODCAST = "podcast"
    NEWSLETTER = "newsletter"


class CollectionItemKind(StrEnum):
    """What a saved post links to; only X and YouTube have their own preview lookups."""

    X = "x"
    YOUTUBE = "youtube"
    LINK = "link"


class MetadataStatus(StrEnum):
    """Whether a saved post's preview (title, author, thumbnail) has been fetched."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class TakeKind(StrEnum):
    """What a take is: what the owner thinks (an opinion), or the case they make for something (a talking point)."""

    OPINION = "opinion"
    TALKING_POINT = "talking_point"


class ProcessingStatus(StrEnum):
    """Where a source stands in the capture pipeline, separate from the user's reading `SourceState`."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class Reaction(StrEnum):
    """How the user says the material landed, which tunes later primers."""

    EASY = "easy"
    MOSTLY = "mostly"
    LOST = "lost"


class ArtifactKind(StrEnum):
    """What a stored artifact holds; only the summary and primer reach the phone."""

    TEXT = "text"
    SUMMARY = "summary"
    PRIMER = "primer"


class CardKind(StrEnum):
    """The shape of a spaced-repetition card.

    `foundation` cards come from primers, `quiz` cards from briefs, `take` cards from the owner's takes.
    """

    CONCEPT = "concept"
    MECHANISM = "mechanism"
    NUMBER = "number"
    FOUNDATION = "foundation"
    QUIZ = "quiz"
    TAKE = "take"


class FsrsState(StrEnum):
    """A card's FSRS learning state, as the phone's scheduler (`ts-fsrs`) names them."""

    NEW = "new"
    LEARNING = "learning"
    REVIEW = "review"
    RELEARNING = "relearning"


class ReviewGrade(StrEnum):
    """How an answer was graded."""

    GOT_IT = "got_it"
    PARTLY = "partly"
    MISSED = "missed"


class GradedBy(StrEnum):
    """Who graded an answer: the model, or the user (offline, after a timeout, or overriding the model)."""

    MODEL = "model"
    SELF = "self"


class CardPreferenceKind(StrEnum):
    """What the user told Archie about a card: what they care about, or that they don't want cards like it."""

    CARE = "care"
    DROP = "drop"


class SourceState(StrEnum):
    """Where a source stands in the user's reading and in processing."""

    QUEUED = "queued"
    INBOX = "inbox"
    BRIEFED = "briefed"
    CONSUMED = "consumed"
    PROCESSING = "processing"
    FAILED = "failed"


class SourceIntent(StrEnum):
    """Why the user captured a source: already read it, or saving it for later."""

    FINISHED = "finished"
    QUEUE = "queue"


class JobKind(StrEnum):
    """The kinds of background work the worker knows how to run."""

    FETCH_TITLE = "fetch_title"
    FETCH_CONTENT = "fetch_content"
    ANALYZE = "analyze"
    PRIMER = "primer"
    TRANSCRIBE = "transcribe"
    FILE_TOPIC = "file_topic"
    TOPIC_PRIMER = "topic_primer"
    CLEAN_TEXT = "clean_text"
    UPDATE_BRIEF = "update_brief"
    NEWS_QUIZ = "news_quiz"
    FETCH_COLLECTION_ITEM = "fetch_collection_item"
    CLEAN_TAKE = "clean_take"
    TAKE_CARDS = "take_cards"
    EMBED = "embed"


class TopicOrigin(StrEnum):
    """Who put a topic on the user's list: the starter list, Archie's filing, or the user."""

    STARTER = "starter"
    ARCHIE = "archie"
    USER = "user"


class NewsletterKind(StrEnum):
    """What a newsletter is: a digest of short items, or one piece of writing worth reading whole."""

    NEWS = "news"
    ESSAY = "essay"


class BriefStatus(StrEnum):
    """Whether a newsletter brief is still being rewritten as newsletters arrive, or the user tapped Done on it."""

    OPEN = "open"
    DONE = "done"


class TranscriptProvider(StrEnum):
    """The speech-to-text service that produced a transcript chunk."""

    GROQ = "groq"
    OPENAI = "openai"


class JobStatus(StrEnum):
    """Where a job is in its lifecycle."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ChunkOwner(StrEnum):
    """What a passage was cut from: a source's own text, Archie's summary or primer of it, a topic primer, or a take."""

    SOURCE_TEXT = "source_text"
    SOURCE_SUMMARY = "source_summary"
    SOURCE_PRIMER = "source_primer"
    TOPIC_PRIMER = "topic_primer"
    TAKE = "take"


class SearchItemKind(StrEnum):
    """The library items search returns and a chat can be about; each owns its passages."""

    SOURCE = "source"
    TOPIC_PRIMER = "topic_primer"
    TAKE = "take"


class MessageRole(StrEnum):
    """Who wrote a chat message."""

    USER = "user"
    ASSISTANT = "assistant"


class MessageStatus(StrEnum):
    """Whether an answer finished; a failed one keeps the text that arrived."""

    COMPLETE = "complete"
    FAILED = "failed"


class ActionResult(StrEnum):
    """How the server answered a phone's action."""

    APPLIED = "applied"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


INGEST_TOKEN_LENGTH = 10
_INGEST_TOKEN_ALPHABET = string.ascii_lowercase + string.digits


def new_ingest_token() -> str:
    """A random lowercase-letters-and-digits token that makes up the local part of a user's newsletter address."""
    return "".join(secrets.choice(_INGEST_TOKEN_ALPHABET) for _ in range(INGEST_TOKEN_LENGTH))


# Artifact kinds the phone syncs; the raw text stays on the server.
SYNCED_ARTIFACT_KINDS = frozenset({ArtifactKind.SUMMARY, ArtifactKind.PRIMER})

EMBEDDING_DIMENSIONS = 1536
# A chat's title is its first question, cut to this many characters.
CONVERSATION_TITLE_LENGTH = 60
CHUNK_OWNER_CHECK = "num_nonnulls(source_id, topic_primer_id, take_id) = 1"
CONVERSATION_ABOUT_CHECK = "num_nonnulls(about_source_id, about_topic_primer_id, about_take_id) <= 1"


class User(Base):
    """A person who signed in with Apple; `is_whitelisted` means the owner's API keys pay for their processing."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.Identity(), primary_key=True)
    apple_sub: Mapped[str] = mapped_column(sqlalchemy.String(255), unique=True)
    email: Mapped[str | None] = mapped_column(sqlalchemy.String(320))
    is_whitelisted: Mapped[bool] = mapped_column(sqlalchemy.Boolean, server_default=sqlalchemy.false())
    # Names the user's newsletter address; generated in Python so every `User(...)` gets one.
    ingest_token: Mapped[str] = mapped_column(sqlalchemy.String(16), unique=True, default=new_ingest_token)
    # Set once the user finished the topic picker (or was seeded as the owner).
    topics_chosen_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())


class Session(Base):
    """A signed-in device; only the hash of its API key is stored, so a database leak reveals no usable key."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    key_hash: Mapped[str] = mapped_column(sqlalchemy.String(64), unique=True, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    last_used_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)


class Source(Base):
    """One captured item. The id is generated on the phone so an offline-created row keeps its identity."""

    __tablename__ = "sources"
    __table_args__ = (
        sqlalchemy.Index("ix_sources_user_id_change_seq", "user_id", "change_seq"),
        sqlalchemy.Index("ix_sources_user_id_normalized_url", "user_id", "normalized_url"),
        # A newsletter delivered twice (Cloudflare retries) maps to one source.
        sqlalchemy.Index("uq_sources_user_id_newsletter_message_id", "user_id", "newsletter_message_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(sqlalchemy.String(2048))
    title: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    kind: Mapped[str] = mapped_column(sqlalchemy.String(16))
    state: Mapped[str] = mapped_column(sqlalchemy.String(16))
    intent: Mapped[str] = mapped_column(sqlalchemy.String(16))
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    processing: Mapped[str] = mapped_column(sqlalchemy.String(16), server_default=ProcessingStatus.PENDING)
    processing_error: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    reaction: Mapped[str | None] = mapped_column(sqlalchemy.String(16))
    note: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    # What duplicate detection compares: the URL with tracking noise removed (see archie_shared.urls).
    normalized_url: Mapped[str] = mapped_column(sqlalchemy.String(2048))
    # Set when this capture duplicated another source and was folded into it.
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("sources.id")
    )
    # Newsletters only: who sent it, and the email's Message-ID.
    sender: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    newsletter_message_id: Mapped[str | None] = mapped_column(sqlalchemy.String(998))
    # Filing: null until `file_topic` ran; `topic_id` stays null when the only fit was a removed topic.
    domain: Mapped[str | None] = mapped_column(sqlalchemy.String(32))
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("topics.id", ondelete="SET NULL")
    )
    image_url: Mapped[str | None] = mapped_column(sqlalchemy.String(2048))
    # Queued sources only; lower is higher in the queue.
    queue_position: Mapped[float | None] = mapped_column(sqlalchemy.Double)
    read_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    snoozed_until: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    primer_opened_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    # Set while the source's primer sits in the queue as its own entry; shares one position space with
    # `queue_position`, and null means the primer is not queued.
    primer_queue_position: Mapped[float | None] = mapped_column(sqlalchemy.Double)
    primer_snoozed_until: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    newsletter_kind: Mapped[str | None] = mapped_column(sqlalchemy.String(16))
    # "No cards for this": the source's cards are retired and analyze/primer write none while it is set.
    cards_off: Mapped[bool] = mapped_column(sqlalchemy.Boolean, server_default=sqlalchemy.false())
    # When the user starred it; null = not starred. Starring changes nothing else about the source.
    favorited_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    # Server only (never pulled): the feed guid the user chose with "Wrong episode?".
    episode_guid: Mapped[str | None] = mapped_column(sqlalchemy.String(1024))
    # Always assigned via changes.next_change_seq() under changes.lock_user_writes(); see changes.py for why.
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class Topic(Base):
    """A topic on a user's curated list. Removed topics stay (blocked, restorable); merged ones point at the winner."""

    __tablename__ = "topics"
    __table_args__ = (
        sqlalchemy.Index("ix_topics_user_id_change_seq", "user_id", "change_seq"),
        # Live and removed topics keep their names unique; a merged topic gives its name up.
        sqlalchemy.Index(
            "uq_topics_user_id_lower_name",
            "user_id",
            sqlalchemy.text("lower(name)"),
            unique=True,
            postgresql_where=sqlalchemy.text("merged_into_id IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    domain: Mapped[str] = mapped_column(sqlalchemy.String(32))
    name: Mapped[str] = mapped_column(sqlalchemy.String(200))
    origin: Mapped[str] = mapped_column(sqlalchemy.String(16))
    removed_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("topics.id")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class TopicPrimer(Base):
    """One version of a topic's general-background primer; exactly one version per topic is current."""

    __tablename__ = "topic_primers"
    __table_args__ = (
        sqlalchemy.UniqueConstraint("topic_id", "version", name="uq_topic_primers_version"),
        sqlalchemy.Index(
            "uq_topic_primers_current", "topic_id", unique=True, postgresql_where=sqlalchemy.text("is_current")
        ),
        sqlalchemy.Index("ix_topic_primers_user_id_change_seq", "user_id", "change_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    topic_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("topics.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(sqlalchemy.Integer)
    is_current: Mapped[bool] = mapped_column(sqlalchemy.Boolean)
    # Markdown under "markdown", the same shape as a source primer artifact.
    content: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB)
    model: Mapped[str | None] = mapped_column(sqlalchemy.String(64))
    prompt_version: Mapped[str | None] = mapped_column(sqlalchemy.String(32))
    opened_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    snoozed_until: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class Brief(Base):
    """The rolling newsletter brief: rewritten by `update_brief` while open, closed when the user taps Done.

    One brief per user is open at a time, which the partial unique index enforces.
    """

    __tablename__ = "briefs"
    __table_args__ = (
        sqlalchemy.Index("ix_briefs_user_id_change_seq", "user_id", "change_seq"),
        sqlalchemy.Index(
            "uq_briefs_user_id_open", "user_id", unique=True, postgresql_where=sqlalchemy.text("status = 'open'")
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(sqlalchemy.String(16))
    # Domains of stories, "also happening" lines and essays, already ordered; null until the first version is written.
    content: Mapped[dict[str, Any] | None] = mapped_column(postgresql.JSONB)
    # Every newsletter the current content covers (news and essays): Done marks these briefed.
    source_ids: Mapped[list[uuid.UUID]] = mapped_column(
        postgresql.ARRAY(postgresql.UUID(as_uuid=True)), server_default=sqlalchemy.text("'{}'")
    )
    # The oldest covered newsletter's `created_at`.
    since: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    # Bumped on every rewrite, so each version is distinguishable.
    version: Mapped[int] = mapped_column(sqlalchemy.Integer, server_default="0")
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    done_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class Collection(Base):
    """A just-for-fun scrapbook ("Bears hype"). Its posts are never sources and never reach the learning side."""

    __tablename__ = "collections"
    __table_args__ = (sqlalchemy.Index("ix_collections_user_id_change_seq", "user_id", "change_seq"),)

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(sqlalchemy.String(200))
    # Tile order on Saved; a new collection goes at the end, so this is creation order until something reorders it.
    position: Mapped[float] = mapped_column(sqlalchemy.Double)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class CollectionItem(Base):
    """A link saved into a collection, with the preview `fetch_collection_item` fills in once.

    Lives in its own table rather than `sources`, so no library, search, review or pipeline query can see it.
    """

    __tablename__ = "collection_items"
    __table_args__ = (
        sqlalchemy.Index("ix_collection_items_user_id_change_seq", "user_id", "change_seq"),
        sqlalchemy.Index("ix_collection_items_collection_id", "collection_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    collection_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("collections.id", ondelete="CASCADE")
    )
    url: Mapped[str] = mapped_column(sqlalchemy.String(2048))
    kind: Mapped[str] = mapped_column(sqlalchemy.String(16))
    # The preview: the post's caption or the page's title, who posted it, its thumbnail and a video's length.
    title: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    author: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    image_url: Mapped[str | None] = mapped_column(sqlalchemy.String(2048))
    duration_seconds: Mapped[int | None] = mapped_column(sqlalchemy.Integer)
    note: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    metadata_status: Mapped[str] = mapped_column(sqlalchemy.String(16), server_default=MetadataStatus.PENDING.value)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class Take(Base):
    """Something the owner wrote: an opinion or a talking point.

    Title and kind live here; only the body is versioned.
    """

    __tablename__ = "takes"
    __table_args__ = (sqlalchemy.Index("ix_takes_user_id_change_seq", "user_id", "change_seq"),)

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(sqlalchemy.String(16))
    title: Mapped[str] = mapped_column(sqlalchemy.String(200))
    # The `take_versions.version` the take page shows; every save that changes the body adds one.
    current_version: Mapped[int] = mapped_column(sqlalchemy.Integer)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class TakeVersion(Base):
    """One dated version of a take's body, with the raw text the owner typed or dictated for it."""

    __tablename__ = "take_versions"
    __table_args__ = (
        sqlalchemy.UniqueConstraint("take_id", "version", name="uq_take_versions_version"),
        sqlalchemy.Index("ix_take_versions_user_id_change_seq", "user_id", "change_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    take_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("takes.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(sqlalchemy.Integer)
    # What the take page shows (markdown); null while `clean_take` is still writing it.
    body: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    raw_body: Mapped[str] = mapped_column(sqlalchemy.Text)
    # Clean it up was on for this version.
    cleaned: Mapped[bool] = mapped_column(sqlalchemy.Boolean)
    # Clean it up gave up: `body` holds the raw text and the take page offers Try again.
    clean_failed: Mapped[bool] = mapped_column(sqlalchemy.Boolean, server_default=sqlalchemy.false())
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class Chunk(Base):
    """One search passage of a live item, with its words indexed for keyword search and (when paid for) an embedding.

    Server only: chunks never reach the phone. `embed` rebuilds an item's chunks from scratch.
    """

    __tablename__ = "chunks"
    __table_args__ = (
        sqlalchemy.CheckConstraint(CHUNK_OWNER_CHECK, name="ck_chunks_one_owner"),
        # Partial, because a unique key over nullable owner columns never fires; they double as the owner lookups.
        sqlalchemy.Index(
            "uq_chunks_source",
            "source_id",
            "owner_kind",
            "chunk_index",
            unique=True,
            postgresql_where=sqlalchemy.text("source_id IS NOT NULL"),
        ),
        sqlalchemy.Index(
            "uq_chunks_topic_primer",
            "topic_primer_id",
            "owner_kind",
            "chunk_index",
            unique=True,
            postgresql_where=sqlalchemy.text("topic_primer_id IS NOT NULL"),
        ),
        sqlalchemy.Index(
            "uq_chunks_take",
            "take_id",
            "owner_kind",
            "chunk_index",
            unique=True,
            postgresql_where=sqlalchemy.text("take_id IS NOT NULL"),
        ),
        sqlalchemy.Index("ix_chunks_user_id", "user_id"),
        sqlalchemy.Index(
            "ix_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        sqlalchemy.Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    owner_kind: Mapped[str] = mapped_column(sqlalchemy.String(16))
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("sources.id", ondelete="CASCADE")
    )
    topic_primer_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("topic_primers.id", ondelete="CASCADE")
    )
    take_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("takes.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int] = mapped_column(sqlalchemy.Integer)
    text: Mapped[str] = mapped_column(sqlalchemy.Text)
    # Transcript passages only: where the passage's first segment starts, in seconds.
    start_seconds: Mapped[float | None] = mapped_column(sqlalchemy.Double)
    # Null when nobody paid for an embedding (no owner key); the passage still serves keyword search.
    embedding: Mapped[list[float] | None] = mapped_column(vector.Vector(EMBEDDING_DIMENSIONS))
    # Generated by Postgres from `text`; never written. Nullable as Postgres reflects a generated column.
    tsv: Mapped[str | None] = mapped_column(
        postgresql.TSVECTOR, sqlalchemy.Computed("to_tsvector('english', text)", persisted=True)
    )
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())


class Conversation(Base):
    """A saved Ask chat. The id is made on the phone; the title is the first question, cut to 60 characters.

    At most one `about_*` id is set: the item the chat was started from with Ask about this.
    """

    __tablename__ = "conversations"
    __table_args__ = (
        sqlalchemy.Index("ix_conversations_user_id_change_seq", "user_id", "change_seq"),
        sqlalchemy.CheckConstraint(CONVERSATION_ABOUT_CHECK, name="ck_conversations_one_about"),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(sqlalchemy.String(200))
    # A `SearchItemKind` value naming which `about_*` id is set; null for a general chat.
    about_kind: Mapped[str | None] = mapped_column(sqlalchemy.String(16))
    about_source_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("sources.id", ondelete="SET NULL")
    )
    about_topic_primer_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("topic_primers.id", ondelete="SET NULL")
    )
    about_take_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("takes.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class Message(Base):
    """One question or answer in a chat. An answer's `segments` are its text blocks with their labels and citations."""

    __tablename__ = "messages"
    __table_args__ = (
        sqlalchemy.Index("ix_messages_user_id_change_seq", "user_id", "change_seq"),
        sqlalchemy.Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(sqlalchemy.String(16))
    # The question, or the answer's plain text (all its segments joined) for history and copying.
    text: Mapped[str] = mapped_column(sqlalchemy.Text)
    segments: Mapped[list[dict[str, Any]] | None] = mapped_column(postgresql.JSONB)
    # The globe toggle as the question was sent.
    web_search: Mapped[bool] = mapped_column(sqlalchemy.Boolean, server_default=sqlalchemy.false())
    status: Mapped[str] = mapped_column(sqlalchemy.String(16))
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class SourceCapture(Base):
    """The text the phone or the fetcher captured for a source; the pipeline's input, kept on the server only."""

    __tablename__ = "source_captures"

    source_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    )
    title: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    text: Mapped[str] = mapped_column(sqlalchemy.Text)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())


class SourceArtifact(Base):
    """One version of something generated for a source (text, summary, primer); regenerating adds a version.

    Exactly one version per (source, kind) is current, which the partial unique index enforces.
    """

    __tablename__ = "source_artifacts"
    __table_args__ = (
        sqlalchemy.UniqueConstraint("source_id", "kind", "version", name="uq_source_artifacts_version"),
        sqlalchemy.Index(
            "uq_source_artifacts_current",
            "source_id",
            "kind",
            unique=True,
            postgresql_where=sqlalchemy.text("is_current"),
        ),
        sqlalchemy.Index("ix_source_artifacts_user_id_change_seq", "user_id", "change_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    source_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("sources.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(sqlalchemy.String(16))
    version: Mapped[int] = mapped_column(sqlalchemy.Integer)
    content: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB)
    is_current: Mapped[bool] = mapped_column(sqlalchemy.Boolean)
    model: Mapped[str | None] = mapped_column(sqlalchemy.String(64))
    prompt_version: Mapped[str | None] = mapped_column(sqlalchemy.String(32))
    # The artifact this one was regenerated from, and the user's instruction for the change.
    derived_from_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("source_artifacts.id")
    )
    instruction: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


# Exactly one origin per card; `take_version_id` and `message_id` only record which version or answer it came from.
CARD_ORIGIN_CHECK = "num_nonnulls(source_id, topic_primer_id, brief_id, take_id, conversation_id) = 1"


class Card(Base):
    """A spaced-repetition question and answer, with its FSRS state as the phone's scheduler last wrote it.

    Its origin is a source (cards from the summary, or foundation cards from the source's primer, with `artifact_id`
    naming that summary or primer version), a topic primer (foundation cards), a brief (quiz cards), a take (take
    cards, with `take_version_id` naming the version they were written from) or a chat (a card made from an answer,
    with `message_id` naming it).
    """

    __tablename__ = "cards"
    __table_args__ = (
        sqlalchemy.Index("ix_cards_user_id_change_seq", "user_id", "change_seq"),
        sqlalchemy.CheckConstraint(CARD_ORIGIN_CHECK, name="ck_cards_one_origin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("sources.id", ondelete="CASCADE")
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("source_artifacts.id")
    )
    topic_primer_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("topic_primers.id", ondelete="CASCADE")
    )
    brief_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("briefs.id", ondelete="CASCADE")
    )
    take_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("takes.id", ondelete="CASCADE")
    )
    take_version_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("take_versions.id", ondelete="CASCADE")
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("conversations.id", ondelete="CASCADE")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("messages.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(sqlalchemy.String(16))
    question: Mapped[str] = mapped_column(sqlalchemy.Text)
    answer: Mapped[str] = mapped_column(sqlalchemy.Text)
    fsrs_state: Mapped[str] = mapped_column(sqlalchemy.String(16), server_default=FsrsState.NEW.value)
    stability: Mapped[float | None] = mapped_column(sqlalchemy.Double)
    difficulty: Mapped[float | None] = mapped_column(sqlalchemy.Double)
    due_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    last_review_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    reps: Mapped[int] = mapped_column(sqlalchemy.Integer, server_default="0")
    lapses: Mapped[int] = mapped_column(sqlalchemy.Integer, server_default="0")
    # Quiz cards only: after this they are no longer offered.
    expires_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class Review(Base):
    """One graded answer, append-only. The id is made on the phone, so a re-sent review is recognized."""

    __tablename__ = "reviews"
    __table_args__ = (sqlalchemy.Index("ix_reviews_card_id_reviewed_at", "card_id", "reviewed_at"),)

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    card_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("cards.id", ondelete="CASCADE")
    )
    grade: Mapped[str] = mapped_column(sqlalchemy.String(16))
    graded_by: Mapped[str] = mapped_column(sqlalchemy.String(16))
    answer: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    missing: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    was_due: Mapped[bool] = mapped_column(sqlalchemy.Boolean)
    reviewed_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP)
    # The card's FSRS fields before and after, in the wire's FsrsState shape.
    state_before: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB)
    state_after: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB)
    # Set by "I actually knew it": the review this one overrides.
    replaces_review_id: Mapped[uuid.UUID | None] = mapped_column(postgresql.UUID(as_uuid=True))
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())


class CardPreference(Base):
    """What the user said about a card ("What I care about…" or Drop); card generation reads the latest ones."""

    __tablename__ = "card_preferences"
    __table_args__ = (sqlalchemy.Index("ix_card_preferences_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    card_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("cards.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(sqlalchemy.String(16))
    note: Mapped[str] = mapped_column(sqlalchemy.Text)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())


class LlmCall(Base):
    """One model call and what it cost, kept so spend can be audited per user and per source."""

    __tablename__ = "llm_calls"
    __table_args__ = (sqlalchemy.Index("ix_llm_calls_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("sources.id", ondelete="SET NULL")
    )
    job_id: Mapped[int | None] = mapped_column(
        sqlalchemy.BigInteger, sqlalchemy.ForeignKey("jobs.id", ondelete="SET NULL")
    )
    step: Mapped[str] = mapped_column(sqlalchemy.String(32))
    provider: Mapped[str] = mapped_column(sqlalchemy.String(16))
    model: Mapped[str] = mapped_column(sqlalchemy.String(64))
    input_tokens: Mapped[int] = mapped_column(sqlalchemy.Integer)
    output_tokens: Mapped[int] = mapped_column(sqlalchemy.Integer)
    # Ten decimal places: a query embedding costs well under a millionth of a dollar.
    cost_usd: Mapped[Decimal] = mapped_column(sqlalchemy.Numeric(16, 10))
    stop_reason: Mapped[str | None] = mapped_column(sqlalchemy.String(32))
    # Transcription calls are billed by audio length, not tokens.
    audio_seconds: Mapped[Decimal | None] = mapped_column(sqlalchemy.Numeric(10, 3))
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())


class PodcastShow(Base):
    """A podcast's RSS feed, remembered by normalized show name so later episodes skip the lookup."""

    __tablename__ = "podcast_shows"

    id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.Identity(), primary_key=True)
    name_key: Mapped[str] = mapped_column(sqlalchemy.String(512), unique=True)
    name: Mapped[str] = mapped_column(sqlalchemy.Text)
    feed_url: Mapped[str] = mapped_column(sqlalchemy.String(2048))
    itunes_id: Mapped[int | None] = mapped_column(sqlalchemy.BigInteger)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())


class TranscriptChunk(Base):
    """One transcribed slice of an episode's audio, stored as it finishes so a retry resumes after the last chunk."""

    __tablename__ = "transcript_chunks"
    __table_args__ = (
        sqlalchemy.UniqueConstraint("source_id", "chunk_index", name="uq_transcript_chunks_source_id_chunk_index"),
    )

    id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.Identity(), primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("sources.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int] = mapped_column(sqlalchemy.Integer)
    provider: Mapped[str] = mapped_column(sqlalchemy.String(16))
    model: Mapped[str] = mapped_column(sqlalchemy.String(64))
    # Absolute episode times: [{"start": float, "text": str}].
    segments: Mapped[list[dict[str, Any]]] = mapped_column(postgresql.JSONB)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())


class AppliedAction(Base):
    """A phone action the server has already answered, so a retried upload is recognized and not applied twice."""

    __tablename__ = "applied_actions"

    action_id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    applied_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    result: Mapped[str] = mapped_column(sqlalchemy.String(16))
    reason: Mapped[str | None] = mapped_column(sqlalchemy.Text)


class Job(Base):
    """One unit of background work for the worker, enqueued in the same transaction as the change that needs it."""

    __tablename__ = "jobs"
    __table_args__ = (sqlalchemy.Index("ix_jobs_status_next_run_at", "status", "next_run_at"),)

    id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(sqlalchemy.String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(sqlalchemy.String(16))
    attempts: Mapped[int] = mapped_column(sqlalchemy.Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(sqlalchemy.Integer, server_default="3")
    next_run_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    last_error: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    started_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
