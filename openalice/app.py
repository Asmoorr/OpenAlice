import logging

from fastapi import FastAPI

from openalice.application.ports import AssistantGateway, Notifier
from openalice.bootstrap import build_runtime
from openalice.config import Settings, get_settings
from openalice.presentation.alice.http import create_http_app


def create_app(
    settings: Settings | None = None,
    openclaw_client: AssistantGateway | None = None,
    notifier: Notifier | None = None,
) -> FastAPI:
    resolved = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, resolved.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return create_http_app(build_runtime(resolved, openclaw_client, notifier))


__all__ = ["create_app"]
