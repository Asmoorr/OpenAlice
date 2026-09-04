import asyncio
import hashlib
import hmac
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException, Path
from fastapi.responses import JSONResponse

from openalice.alice_models import AliceWebhookRequest, AliceWebhookResponse, AliceResponseBody
from openalice.commands import CommandIntent, detect_command_intent, normalize_command
from openalice.config import Settings, get_settings
from openalice.logging import LogType, get_logger
from openalice.openclaw_client import (
    AssistantClient,
    FakeOpenClawClient,
    OpenClawClient,
    OpenClawError,
)
from openalice.pending_phrases import PendingPhraseProvider
from openalice.store import Store
from openalice.text import shorten_for_alice

logger = get_logger("openalice")


@dataclass
class Runtime:
    settings: Settings
    store: Store
    openclaw: AssistantClient
    pending_phrases: PendingPhraseProvider
    pending_tasks: dict[str, asyncio.Task[str]] = field(default_factory=dict)


def create_app(
        settings: Settings | None = None,
        openclaw_client: AssistantClient | None = None,
) -> FastAPI:
    resolved = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, resolved.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    runtime = Runtime(
        settings=resolved,
        store=Store(resolved.database_path),
        openclaw=openclaw_client or _create_assistant_client(resolved),
        pending_phrases=PendingPhraseProvider(resolved.alice_pending_phrases),
    )

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
        await runtime.store.initialize()
        logger.info(LogType.TECH, "stage=startup status=ready")
        yield
        logger.info(LogType.TECH, "stage=shutdown status=starting pending_tasks=%d", len(runtime.pending_tasks))
        for task in runtime.pending_tasks.values():
            task.cancel()
        if runtime.pending_tasks:
            await asyncio.gather(*runtime.pending_tasks.values(), return_exceptions=True)
        await runtime.openclaw.close()
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
            logger.warning(LogType.TECH, "stage=authentication status=rejected reason=wrong_webhook_secret")
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
        if runtime.settings.alice_allowed_user_ids and raw_identity not in runtime.settings.alice_allowed_user_ids:
            logger.warning(LogType.TECH, "stage=authorization status=rejected request=%s user=%s", request_ref, identity_ref)
            logger.warning(LogType.USER, "event=access_denied request=%s user=%s", request_ref, identity_ref)
            return _json_response(_alice_response("У этого аккаунта нет доступа к навыку.", end_session=True))

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

        response = await _handle_request(runtime, request, raw_identity, request_ref, identity_ref)
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
        return JSONResponse(response_dict)

    return app


def _create_assistant_client(settings: Settings) -> AssistantClient:
    if settings.openalice_fake_mode:
        return FakeOpenClawClient(
            settings.openalice_fake_response,
            settings.openalice_fake_delay_seconds,
        )
    return OpenClawClient(
        settings.openclaw_base_url,
        settings.openclaw_gateway_token,
        settings.openclaw_agent,
    )


async def _handle_request(
        runtime: Runtime,
        request: AliceWebhookRequest,
        raw_identity: str,
        request_ref: str,
        identity_ref: str,
) -> AliceWebhookResponse:
    command = normalize_command(request.request.command or request.request.original_utterance)
    intent = detect_command_intent(command)
    identity_hash = hashlib.sha256(raw_identity.encode("utf-8")).hexdigest()
    generation = await runtime.store.get_generation(identity_hash)
    conversation_id = f"openalice:yandex-user:{identity_hash}:v{generation}"
    logger.info(
        LogType.TECH,
        "stage=command status=classified request=%s user=%s intent=%s generation=%d",
        request_ref,
        identity_ref,
        intent.value if intent is not None else "message",
        generation,
    )

    if request.session.new and not command:
        logger.info(LogType.USER, "event=skill_opened request=%s user=%s", request_ref, identity_ref)
        return _alice_response(
            "Это Открытый помощник. Задайте вопрос. Если ответ готовится долго, скажите «готово» немного позже."
        )
    if intent is CommandIntent.HELP:
        logger.info(LogType.USER, "event=help_requested request=%s user=%s", request_ref, identity_ref)
        return _alice_response(
            "Я передаю ваши вопросы домашнему помощнику OpenClaw. Можно сказать «готово», «новый диалог», «отмена» или «выйти»."
        )
    if intent is CommandIntent.EXIT:
        logger.info(LogType.USER, "event=session_closed request=%s user=%s", request_ref, identity_ref)
        return _alice_response("До встречи.", end_session=True)
    if intent is CommandIntent.NEW_DIALOG:
        await _cancel_pending(runtime, conversation_id)
        await runtime.store.increment_generation(identity_hash)
        logger.info(LogType.USER, "event=new_dialog_started request=%s user=%s", request_ref, identity_ref)
        return _alice_response("Начинаю новый диалог. О чём поговорим?")
    if intent is CommandIntent.CANCEL:
        cancelled = await _cancel_pending(runtime, conversation_id)
        logger.info(LogType.USER, "event=request_cancelled request=%s user=%s existed=%s", request_ref, identity_ref, cancelled)
        return _alice_response("Запрос отменён." if cancelled else "Сейчас нет ожидающего запроса.")
    if intent is CommandIntent.RESULT:
        logger.info(LogType.USER, "event=deferred_result_requested request=%s user=%s", request_ref, identity_ref)
        return await _get_deferred_result(runtime, conversation_id)
    if not command:
        return _alice_response("Я вас не расслышала. Повторите вопрос.")

    existing = await runtime.store.get_job(conversation_id)
    if existing and existing["status"] == "pending":
        logger.info(LogType.TECH, "stage=openclaw status=already_pending request=%s user=%s", request_ref, identity_ref)
        logger.info(LogType.USER, "event=question_rejected reason=request_pending request=%s user=%s", request_ref, identity_ref)
        return _alice_response(runtime.pending_phrases.choose())

    logger.info(LogType.TECH, "stage=openclaw status=started request=%s user=%s", request_ref, identity_ref)
    logger.info(LogType.USER, "event=question_accepted request=%s user=%s", request_ref, identity_ref)
    openclaw_started = time.perf_counter()
    task = asyncio.create_task(runtime.openclaw.ask(command, conversation_id))
    runtime.pending_tasks[conversation_id] = task
    done, _ = await asyncio.wait({task}, timeout=runtime.settings.alice_fast_timeout_seconds)
    if task in done:
        runtime.pending_tasks.pop(conversation_id, None)
        try:
            answer = task.result()
        except (OpenClawError, asyncio.CancelledError):
            logger.exception(
                LogType.TECH,
                "stage=openclaw status=failed request=%s user=%s elapsed_ms=%.1f",
                request_ref,
                identity_ref,
                _elapsed_ms(openclaw_started),
            )
            return _alice_response("Домашний помощник сейчас недоступен. Попробуйте ещё раз позже.")
        await runtime.store.delete_job(conversation_id)
        logger.info(
            LogType.TECH,
            "stage=openclaw status=completed request=%s user=%s answer_chars=%d elapsed_ms=%.1f",
            request_ref,
            identity_ref,
            len(answer),
            _elapsed_ms(openclaw_started),
        )
        logger.info(LogType.USER, "event=answer_delivered request=%s user=%s mode=immediate", request_ref, identity_ref)
        return _alice_response(shorten_for_alice(answer, runtime.settings.alice_max_response_chars))

    await runtime.store.set_job(conversation_id, "pending")
    logger.info(
        LogType.TECH,
        "stage=openclaw status=deferred request=%s user=%s elapsed_ms=%.1f",
        request_ref,
        identity_ref,
        _elapsed_ms(openclaw_started),
    )
    logger.info(LogType.USER, "event=answer_deferred request=%s user=%s", request_ref, identity_ref)
    task.add_done_callback(
        lambda completed: asyncio.create_task(
            _save_deferred_result(runtime, conversation_id, completed, request_ref, identity_ref, openclaw_started)
        )
    )
    return _alice_response(runtime.pending_phrases.choose())


async def _save_deferred_result(
        runtime: Runtime,
        conversation_id: str,
        task: asyncio.Task[str],
        request_ref: str,
        identity_ref: str,
        started: float,
) -> None:
    runtime.pending_tasks.pop(conversation_id, None)
    try:
        answer = task.result()
    except asyncio.CancelledError:
        logger.info(LogType.TECH, "stage=openclaw status=cancelled request=%s user=%s", request_ref, identity_ref)
        await runtime.store.set_job(conversation_id, "failed", error="Запрос был отменён.")
    except Exception as exc:
        logger.warning(
            LogType.TECH,
            "stage=openclaw status=deferred_failed request=%s user=%s error_type=%s error_detail=%s elapsed_ms=%.1f",
            request_ref,
            identity_ref,
            type(exc).__name__,
            str(exc),
            _elapsed_ms(started),
        )
        await runtime.store.set_job(conversation_id, "failed", error="Домашний помощник не смог подготовить ответ.")
    else:
        logger.info(
            LogType.TECH,
            "stage=openclaw status=deferred_completed request=%s user=%s answer_chars=%d elapsed_ms=%.1f",
            request_ref,
            identity_ref,
            len(answer),
            _elapsed_ms(started),
        )
        logger.info(LogType.USER, "event=deferred_answer_ready request=%s user=%s", request_ref, identity_ref)
        await runtime.store.set_job(conversation_id, "done", response=answer)


async def _get_deferred_result(runtime: Runtime, conversation_id: str) -> AliceWebhookResponse:
    job = await runtime.store.get_job(conversation_id)
    if job is None:
        return _alice_response("Нет ожидающего ответа. Задайте новый вопрос.")
    if job["status"] == "pending":
        return _alice_response(runtime.pending_phrases.choose())
    if job["status"] == "failed":
        await runtime.store.delete_job(conversation_id)
        return _alice_response(job["error"] or "Не удалось подготовить ответ. Попробуйте ещё раз.")

    answer = shorten_for_alice(job["response"] or "Ответ пуст.", runtime.settings.alice_max_response_chars)
    await runtime.store.delete_job(conversation_id)
    return _alice_response(answer)


async def _cancel_pending(runtime: Runtime, conversation_id: str) -> bool:
    task = runtime.pending_tasks.pop(conversation_id, None)
    job = await runtime.store.get_job(conversation_id)
    if task is not None and not task.done():
        task.cancel()
    await runtime.store.delete_job(conversation_id)
    return task is not None or job is not None


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
