"""Job handlers, one module per `JobKind`, and the registry the worker loop dispatches through."""

from archie_db import models

from archie_worker.handlers import fetch_title
from archie_worker.loop import Handler

HANDLERS: dict[models.JobKind, Handler] = {
    models.JobKind.FETCH_TITLE: fetch_title.handle,
}
