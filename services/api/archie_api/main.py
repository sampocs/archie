"""The Archie HTTP API: the one server the phone app talks to.

`create_app` builds a fresh app per call so tests can stand up isolated instances; `app` is the
module-level instance uvicorn serves.
"""

from __future__ import annotations

import fastapi
import pydantic
import sqlalchemy
from archie_shared import config, logging

from archie_api import deps, test_routes
from archie_api.auth import routes as auth_routes


class HealthView(pydantic.BaseModel):
    """Liveness plus whether the database answered, so Railway and the live check see one signal."""

    ok: bool
    database: bool


def create_app() -> fastapi.FastAPI:
    """Build the API with every router mounted."""
    logging.configure()
    app = fastapi.FastAPI(title="Archie")
    app.add_api_route("/health", health, methods=["GET"])
    app.include_router(auth_routes.router)

    # Test-only sign-in must never exist in production.
    if config.get_settings().env() is not config.ArchieEnv.PROD:
        app.include_router(test_routes.router)
    return app


def health() -> HealthView:
    """Report liveness and whether the database can be reached."""
    return HealthView(ok=True, database=_database_reachable())


def _database_reachable() -> bool:
    if not config.get_settings().database_url:
        return False

    try:
        with deps.get_engine().connect() as connection:
            connection.execute(sqlalchemy.text("SELECT 1"))
        return True
    except sqlalchemy.exc.OperationalError:
        # An unreachable database is the answer this endpoint exists to report, not a server error.
        return False


app = create_app()
