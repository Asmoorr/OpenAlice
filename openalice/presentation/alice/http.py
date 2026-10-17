"""Alice HTTP adapter and application lifecycle."""

import hashlib
import hmac
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Path
from fastapi.responses import JSONResponse

from openalice.application.conversation import ConversationService
from openalice.application.coordinator import RequestCoordinator
from openalice.application.ports import AssistantGateway as AssistantClient
from openalice.application.ports import RequestCache
from openalice.config import Settings
from openalice.logging import LogType, get_logger
from openalice.presentation.alice.models import (
    AliceResponseBody,
    AliceWebhookRequest,
    AliceWebhookResponse,
)

logger = get_logger("openalice")


class StoreLifecycle(RequestCache, Protocol):
    async def initialize(self) -> None: ...
    async def close(self) -> None: ...


class WorkerLifecycle(Protocol):
    def start(self) -> None: ...
    async def stop(self) -> None: ...


class HttpRuntime(Protocol):
    @property
    def settings(self) -> Settings: ...
    @property
    def store(self) -> StoreLifecycle: ...
    @property
    def coordinator(self) -> RequestCoordinator: ...
    @property
    def service(self) -> ConversationService | None: ...
    @property
    def notification_worker(self) -> WorkerLifecycle | None: ...
    @property
    def openclaw(self) -> AssistantClient: ...


def create_http_app(runtime: HttpRuntime) -> FastAPI:
    resolved = runtime.settings

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            LogType.TECH,
            "stage=startup status=starting database=%s mode=%s openclaw=%s agent=%s",
            resolved.database_path,
            "fake" if resolved.openalice_fake_mode else "live",
            resolved.openclaw_base_url,
            resolved.openclaw_agent,
        )
        try:
            await runtime.store.initialize()
            if runtime.notification_worker is not None:
                runtime.notification_worker.start()
            logger.info(LogType.TECH, "stage=startup status=ready")
            yield
        finally:
            try:
                await runtime.coordinator.close()
            finally:
                try:
                    if runtime.notification_worker is not None:
                        await runtime.notification_worker.stop()
                finally:
                    try:
                        await runtime.openclaw.close()
                    finally:
                        await runtime.store.close()
        logger.info(LogType.TECH, "stage=shutdown status=complete")

    app = FastAPI(
        title="OpenAlice",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.runtime = runtime

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "openalice",
            "mode": "fake" if runtime.settings.openalice_fake_mode else "live",
        }

    @app.post("/alice/webhook/{secret}")
    async def alice_webhook(
        request: AliceWebhookRequest,
        secret: str = Path(min_length=1),
    ) -> JSONResponse:
        started = time.perf_counter()
        if not hmac.compare_digest(secret, runtime.settings.alice_webhook_secret):
            logger.warning(
                LogType.TECH, "stage=authentication status=rejected reason=wrong_webhook_secret"
            )
            raise HTTPException(status_code=404, detail="Not found")

        raw_identity = _raw_identity(request)
        identity_ref = _identity_ref(raw_identity)
        request_ref = _request_ref(request)
        logger.info(
            LogType.TECH,
            "stage=webhook status=received request=%s user=%s session_new=%s command_chars=%d",
            request_ref,
            identity_ref,
            request.session.new,
            len(request.request.command or request.request.original_utterance),
        )
        if (
            runtime.settings.alice_allowed_user_ids
            and raw_identity not in runtime.settings.alice_allowed_user_ids
        ):
            logger.warning(
                LogType.TECH,
                "stage=authorization status=rejected request=%s user=%s",
                request_ref,
                identity_ref,
            )
            logger.warning(
                LogType.USER, "event=access_denied request=%s user=%s", request_ref, identity_ref
            )
            return _json_response(
                _alice_response("У этого аккаунта нет доступа к навыку.", end_session=True)
            )

        request_key = ":".join(
            (
                request.session.skill_id,
                request.session.session_id,
                str(request.session.message_id),
            )
        )
        cached = await runtime.store.get_cached_response(request_key)
        if cached is not None:
            logger.info(
                LogType.TECH,
                "stage=webhook status=cache_hit request=%s elapsed_ms=%.1f",
                request_ref,
                _elapsed_ms(started),
            )
            return JSONResponse(cached)

        async def process_request() -> dict[str, Any]:
            response = await _handle_request(
                runtime, request, raw_identity, request_ref, identity_ref
            )
            response_dict = response.model_dump(exclude_none=True)
            await runtime.store.cache_response(request_key, response_dict)
            logger.info(
                LogType.TECH,
                "stage=webhook status=completed request=%s end_session=%s response_chars=%d elapsed_ms=%.1f",
                request_ref,
                response.response.end_session,
                len(response.response.text),
                _elapsed_ms(started),
            )
            return response_dict

        response_dict = await runtime.coordinator.run_once(request_key, process_request)
        return JSONResponse(response_dict)

    return app


async def _handle_request(
    runtime: HttpRuntime,
    request: AliceWebhookRequest,
    raw_identity: str,
    request_ref: str,
    identity_ref: str,
) -> AliceWebhookResponse:
    assert runtime.service is not None
    reply = await runtime.service.handle(
        request.request.command or request.request.original_utterance,
        raw_identity,
        request.session.new,
    )
    return _alice_response(reply.text, reply.end_session)


def _raw_identity(request: AliceWebhookRequest) -> str:
    if request.session.user is not None:
        return request.session.user.user_id
    return request.session.application.application_id


def _identity_ref(raw_identity: str) -> str:
    return hashlib.sha256(raw_identity.encode("utf-8")).hexdigest()[:12]


def _request_ref(request: AliceWebhookRequest) -> str:
    value = f"{request.session.session_id}:{request.session.message_id}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _alice_response(text: str, end_session: bool = False) -> AliceWebhookResponse:
    return AliceWebhookResponse(
        response=AliceResponseBody(text=text, tts=text, end_session=end_session)
    )


def _json_response(response: AliceWebhookResponse) -> JSONResponse:
    return JSONResponse(response.model_dump(exclude_none=True))
