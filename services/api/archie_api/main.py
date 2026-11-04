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
from archie_api.ingest import routes as ingest_routes
from archie_api.sources import routes as sources_routes
from archie_api.sync import routes as sync_routes
from archie_api.topics import routes as topics_routes

_TEST_ROUTE_ENVS = frozenset({config.ArchieEnv.DEV, config.ArchieEnv.TEST})


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
    app.include_router(sync_routes.router)
    app.include_router(ingest_routes.router)
    app.include_router(sources_routes.router)
    app.include_router(topics_routes.router)

    if _test_routes_enabled():
        app.include_router(test_routes.router)
    return app


def _test_routes_enabled() -> bool:
    """Whether the auth-bypassing test routes may exist: only when `ARCHIE_ENV` is explicitly `dev` or `test`.

    `Settings.env()` defaults an unset variable to `DEV`, so it can't be the gate: a production deploy that
    forgot to set `ARCHIE_ENV` would otherwise expose a sign-in that needs no credentials.
    """
    settings = config.get_settings()
    return bool(settings.archie_env) and settings.env() in _TEST_ROUTE_ENVS


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
