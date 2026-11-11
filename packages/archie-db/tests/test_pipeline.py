"""Artifact versions, processing status and retry planning, against a real Postgres."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, pipeline, session

pytestmark = pytest.mark.postgres


@pytest.fixture
def db(migrated_database_url: str) -> Iterator[sqlalchemy.orm.Session]:
    """A session on the migrated test database, rolled back at the end."""
    engine = session.engine_for(migrated_database_url)
    with sqlalchemy.orm.Session(engine) as database:
        yield database
        database.rollback()
    engine.dispose()


@pytest.fixture
def source(db: sqlalchemy.orm.Session) -> models.Source:
    """A pending source whose user's write lock this transaction already holds."""
    user = models.User(apple_sub=f"sub-{uuid.uuid4()}")
    db.add(user)
    db.flush()
    changes.lock_user_writes(db, user.id)
    new_source = models.Source(
        id=uuid.uuid4(),
        user_id=user.id,
        url="https://example.com/a",
        normalized_url="https://example.com/a",
        kind=models.SourceKind.LINK.value,
        state=models.SourceState.INBOX.value,
        intent=models.SourceIntent.QUEUE.value,
        change_seq=changes.next_change_seq(),
    )
    db.add(new_source)
    db.flush()
    return new_source


def test_writing_an_artifact_again_adds_a_version_and_keeps_only_the_newest_current(
    db: sqlalchemy.orm.Session, source: models.Source
) -> None:
    """Version 2 becomes current; version 1 stays with its content, no longer current, and both get newer positions."""
    first = _write(db, source, kind=models.ArtifactKind.SUMMARY, content={"text": "one"})
    db.refresh(first)
    first_seq = first.change_seq

    second = _write(db, source, kind=models.ArtifactKind.SUMMARY, content={"text": "two"})
    db.refresh(first)
    db.refresh(second)

    assert (first.version, second.version) == (1, 2)
    assert (first.is_current, second.is_current) == (False, True)
    assert first.content == {"text": "one"}
    assert first.change_seq > first_seq
    assert second.change_seq > first.change_seq
    assert pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.SUMMARY) is second


def test_versions_are_counted_per_kind(db: sqlalchemy.orm.Session, source: models.Source) -> None:
    """A primer's first version is 1 even when the summary has several, and the summary stays current."""
    _write(db, source, kind=models.ArtifactKind.SUMMARY, content={})
    summary = _write(db, source, kind=models.ArtifactKind.SUMMARY, content={})
    primer = _write(db, source, kind=models.ArtifactKind.PRIMER, content={})
    db.flush()

    assert (summary.version, primer.version) == (2, 1)
    assert summary.is_current is True


def test_current_artifact_is_none_when_nothing_was_written(db: sqlalchemy.orm.Session, source: models.Source) -> None:
    """No artifact of the kind yet."""
    assert pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.TEXT) is None


def test_set_processing_records_the_error_only_for_failed(db: sqlalchemy.orm.Session, source: models.Source) -> None:
    """FAILED keeps the reason; any later status clears it; each change raises the source's position."""
    db.refresh(source)
    seq_before = source.change_seq

    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.FAILED, error="boom")
    db.flush()
    db.refresh(source)
    assert (source.processing, source.processing_error) == (models.ProcessingStatus.FAILED, "boom")
    assert source.change_seq > seq_before

    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING, error="ignored")
    db.flush()
    db.refresh(source)
    assert (source.processing, source.processing_error) == (models.ProcessingStatus.PROCESSING, None)


def test_finish_step_is_ready_only_once_summary_and_primer_exist(
    db: sqlalchemy.orm.Session, source: models.Source
) -> None:
    """One artifact is not enough; the second flips the source to READY."""
    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)

    _write(db, source, kind=models.ArtifactKind.SUMMARY, content={})
    db.flush()
    pipeline.finish_step(db, source=source)
    db.flush()
    db.refresh(source)
    assert source.processing == models.ProcessingStatus.PROCESSING
    seq_waiting = source.change_seq

    _write(db, source, kind=models.ArtifactKind.PRIMER, content={})
    db.flush()
    pipeline.finish_step(db, source=source)
    db.flush()
    db.refresh(source)
    assert source.processing == models.ProcessingStatus.READY
    assert source.change_seq > seq_waiting


def test_steps_to_retry_picks_the_earliest_missing_work(db: sqlalchemy.orm.Session, source: models.Source) -> None:
    """No text: fetch. Text only: both LLM steps. Text and summary: just the primer. Everything present: redo both."""
    assert pipeline.steps_to_retry(db, source_id=source.id) == [models.JobKind.FETCH_CONTENT]

    _write(db, source, kind=models.ArtifactKind.TEXT, content={})
    db.flush()
    assert pipeline.steps_to_retry(db, source_id=source.id) == [models.JobKind.ANALYZE, models.JobKind.PRIMER]

    _write(db, source, kind=models.ArtifactKind.SUMMARY, content={})
    db.flush()
    assert pipeline.steps_to_retry(db, source_id=source.id) == [models.JobKind.PRIMER]

    _write(db, source, kind=models.ArtifactKind.PRIMER, content={})
    db.flush()
    assert pipeline.steps_to_retry(db, source_id=source.id) == [models.JobKind.ANALYZE, models.JobKind.PRIMER]


def test_steps_to_retry_without_a_summary_but_with_a_primer(db: sqlalchemy.orm.Session, source: models.Source) -> None:
    """Only the missing summary is redone."""
    _write(db, source, kind=models.ArtifactKind.TEXT, content={})
    _write(db, source, kind=models.ArtifactKind.PRIMER, content={})
    db.flush()

    assert pipeline.steps_to_retry(db, source_id=source.id) == [models.JobKind.ANALYZE]


def test_newsletter_is_ready_after_only_a_summary(db: sqlalchemy.orm.Session, source: models.Source) -> None:
    """A newsletter needs no primer, so its summary alone finishes it."""
    source.kind = models.SourceKind.NEWSLETTER.value
    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
    _write(db, source, kind=models.ArtifactKind.SUMMARY, content={})
    db.flush()

    pipeline.finish_step(db, source=source)
    db.flush()
    db.refresh(source)

    assert source.processing == models.ProcessingStatus.READY


def test_steps_to_retry_for_a_newsletter_never_includes_the_primer(
    db: sqlalchemy.orm.Session, source: models.Source
) -> None:
    """Uncleaned text: clean then analyze, even with a summary. Cleaned text: analyze only, missing or not."""
    source.kind = models.SourceKind.NEWSLETTER.value
    clean_then_analyze = [models.JobKind.CLEAN_TEXT, models.JobKind.ANALYZE]
    _write(db, source, kind=models.ArtifactKind.TEXT, content={"text": "raw"})
    db.flush()
    assert pipeline.steps_to_retry(db, source_id=source.id) == clean_then_analyze

    _write(db, source, kind=models.ArtifactKind.SUMMARY, content={})
    db.flush()
    assert pipeline.steps_to_retry(db, source_id=source.id) == clean_then_analyze

    _write(db, source, kind=models.ArtifactKind.TEXT, content={"text": "clean", pipeline.CLEANED_KEY: True})
    db.flush()
    assert pipeline.steps_to_retry(db, source_id=source.id) == [models.JobKind.ANALYZE]


def test_steps_to_retry_skips_cleaning_a_cleaned_newsletter_without_a_summary(
    db: sqlalchemy.orm.Session, source: models.Source
) -> None:
    """Cleaning already happened, so only the missing summary is made."""
    source.kind = models.SourceKind.NEWSLETTER.value
    _write(db, source, kind=models.ArtifactKind.TEXT, content={"text": "clean", pipeline.CLEANED_KEY: True})
    db.flush()

    assert pipeline.steps_to_retry(db, source_id=source.id) == [models.JobKind.ANALYZE]


def test_required_artifacts_for_a_book_follow_its_state() -> None:
    """A book being read needs its primer, a finished one its refresher; other kinds ignore the state."""
    book = models.SourceKind.BOOK
    reading, consumed = models.SourceState.READING, models.SourceState.CONSUMED

    assert pipeline.required_artifacts(kind=book, state=reading) == (models.ArtifactKind.PRIMER,)
    assert pipeline.required_artifacts(kind=book, state=consumed) == (models.ArtifactKind.SUMMARY,)
    assert pipeline.required_artifacts(kind=models.SourceKind.ARTICLE, state=consumed) == (
        models.ArtifactKind.SUMMARY,
        models.ArtifactKind.PRIMER,
    )
    assert pipeline.required_artifacts(kind=models.SourceKind.NOTE, state=models.SourceState.INBOX) == (
        models.ArtifactKind.SUMMARY,
    )


def test_a_reading_book_is_ready_on_its_primer_and_a_finished_one_only_on_its_refresher(
    db: sqlalchemy.orm.Session, source: models.Source
) -> None:
    """Finishing the book makes the primer no longer enough: it waits for the summary."""
    source.kind = models.SourceKind.BOOK.value
    source.state = models.SourceState.READING.value
    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
    _write(db, source, kind=models.ArtifactKind.PRIMER, content={})
    db.flush()
    pipeline.finish_step(db, source=source)
    assert source.processing == models.ProcessingStatus.READY

    source.state = models.SourceState.CONSUMED.value
    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
    pipeline.finish_step(db, source=source)
    assert source.processing == models.ProcessingStatus.PROCESSING

    _write(db, source, kind=models.ArtifactKind.SUMMARY, content={})
    db.flush()
    pipeline.finish_step(db, source=source)
    assert source.processing == models.ProcessingStatus.READY


def test_steps_to_retry_for_a_book_never_fetches(db: sqlalchemy.orm.Session, source: models.Source) -> None:
    """A book has no text: reading retries its primer, finished its refresher, whatever artifacts exist."""
    source.kind = models.SourceKind.BOOK.value
    source.state = models.SourceState.READING.value
    db.flush()
    assert pipeline.steps_to_retry(db, source_id=source.id) == [models.JobKind.PRIMER]

    source.state = models.SourceState.CONSUMED.value
    db.flush()
    assert pipeline.steps_to_retry(db, source_id=source.id) == [models.JobKind.WRITE_BOOK]

    _write(db, source, kind=models.ArtifactKind.TEXT, content={"text": "refresher"})
    db.flush()
    assert pipeline.steps_to_retry(db, source_id=source.id) == [models.JobKind.WRITE_BOOK]


def test_set_processing_keeps_the_error_for_unsupported(db: sqlalchemy.orm.Session, source: models.Source) -> None:
    """UNSUPPORTED explains itself like FAILED does; PROCESSING clears it."""
    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.UNSUPPORTED, error="x")
    assert source.processing_error == "x"

    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING, error="x")
    assert source.processing_error is None


def test_enqueue_steps_adds_one_job_per_step_in_order(db: sqlalchemy.orm.Session, source: models.Source) -> None:
    """Jobs carry the source id and are created in the given order."""
    steps = [models.JobKind.PRIMER, models.JobKind.ANALYZE]

    pipeline.enqueue_steps(db, source=source, steps=steps)

    query = sqlalchemy.select(models.Job).where(models.Job.user_id == source.user_id).order_by(models.Job.id)
    queued = db.scalars(query)
    assert [(job.kind, job.payload) for job in queued] == [
        (models.JobKind.PRIMER.value, {pipeline.SOURCE_ID_KEY: str(source.id)}),
        (models.JobKind.ANALYZE.value, {pipeline.SOURCE_ID_KEY: str(source.id)}),
    ]


def _write(
    db: sqlalchemy.orm.Session, source: models.Source, *, kind: models.ArtifactKind, content: dict[str, str | bool]
) -> models.SourceArtifact:
    return pipeline.write_artifact(
        db, source=source, kind=kind, content=content, model="test-model", prompt_version="v1"
    )
