"""The Archie HTTP API: the one server the phone app talks to.

`create_app` builds a fresh app per call so tests can stand up isolated instances; `app` is the
module-level instance uvicorn serves.
"""

from __future__ import annotations

import fastapi
import pydantic
import sqlalchemy
from archie_db import session
from archie_shared import config, logging

from archie_api.routes import sources


class HealthView(pydantic.BaseModel):
    """Liveness plus whether the database answered, so Railway and the live check see one signal."""

    ok: bool
    database: bool


def create_app() -> fastapi.FastAPI:
    """Build the API with every router mounted."""
    logging.configure()
    app = fastapi.FastAPI(title="Archie")
    app.add_api_route("/health", health, methods=["GET"])
    app.include_router(sources.router)
    return app


def health() -> HealthView:
    """Report liveness and whether the database can be reached."""
    return HealthView(ok=True, database=_database_reachable())


def _database_reachable() -> bool:
    database_url = config.get_settings().database_url
    if not database_url:
        return False

    engine = session.engine_for(database_url)
    try:
        with engine.connect() as connection:
            connection.execute(sqlalchemy.text("SELECT 1"))
        return True
    except sqlalchemy.exc.OperationalError:
        # An unreachable database is the answer this endpoint exists to report, not a server error.
        return False
    finally:
        engine.dispose()


app = create_app()
