"""OpenAI embeddings against a recorded real response: one vector per text, in order, with the request's cost recorded.

Re-record `embeddings_two_texts` by deleting it and running
`uv run pytest packages/archie-llm/tests/test_embeddings_e2e.py --record-mode=once -m postgres` with
`TEST_DATABASE_URL` set (a tiny fraction of a cent; needs OPENAI_API_KEY in the repo root .env).
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import models, session
from archie_llm import embeddings, llm
from archie_shared import config
from archie_testing import recording

pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
TEXTS = ["The Fed creates reserves when it buys bonds.", "Stablecoins settle payments without a bank."]


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real OpenAI key while recording, a placeholder on replay."""
    recording.use_recording_api_key(request, monkeypatch, env_names=(config.OPENAI_API_KEY_ENV,))


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[sqlalchemy.Engine]:
    """An engine on the migrated test database."""
    database_engine = session.engine_for(migrated_database_url)
    yield database_engine
    database_engine.dispose()


def test_two_texts_get_two_1536_dimension_vectors_and_one_costed_record(
    engine: sqlalchemy.Engine, request: pytest.FixtureRequest
) -> None:
    """Different texts get different vectors; the call is one `embed` row billed by its input tokens."""
    user_id = _add_user(engine)
    context = llm.CallContext(user_id=user_id, source_id=None, job_id=None, step=llm.EMBED_STEP)
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)

    with recorder.use_cassette("embeddings_two_texts.yaml"):
        vectors = embeddings.embed(engine, api_key=config.Settings().openai_api_key or "", context=context, texts=TEXTS)

    assert [len(vector) for vector in vectors] == [models.EMBEDDING_DIMENSIONS] * 2
    assert vectors[0] != vectors[1]
    with sqlalchemy.orm.Session(engine) as db:
        [call] = db.scalars(sqlalchemy.select(models.LlmCall)).all()
    assert (call.step, call.provider, call.model, call.output_tokens) == ("embed", "openai", llm.EMBEDDING_MODEL, 0)
    assert call.input_tokens > 0
    assert call.cost_usd > 0


def _add_user(engine: sqlalchemy.Engine) -> int:
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub="embed-user", is_whitelisted=True)
        db.add(user)
        db.commit()
        return user.id
