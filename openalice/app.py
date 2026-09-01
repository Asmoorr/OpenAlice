import asyncio
import hashlib
import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException, Path
from fastapi.responses import JSONResponse

from openalice.alice_models import AliceWebhookRequest, AliceWebhookResponse, AliceResponseBody
from openalice.commands import CommandIntent, detect_command_intent, normalize_command
from openalice.config import Settings, get_settings
from openalice.openclaw_client import OpenClawClient, OpenClawError
from openalice.store import Store
from openalice.text import shorten_for_alice

logger = logging.getLogger("openalice")

@dataclass
class Runtime:
    settings: Settings
    store: Store
    openclaw: OpenClawClient
    pending_tasks: dict[str, asyncio.Task[str]] = field(default_factory=dict)


def create_app(
    settings: Settings | None = None,
    openclaw_client: OpenClawClient | None = None,
) -> FastAPI:
    resolved = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, resolved.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    runtime = Runtime(
        settings=resolved,
        store=Store(resolved.database_path),
        openclaw=openclaw_client
        or OpenClawClient(
            resolved.openclaw_base_url,
            resolved.openclaw_gateway_token,
            resolved.openclaw_agent,
        ),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await runtime.store.initialize()
        yield
        for task in runtime.pending_tasks.values():
            task.cancel()
        if runtime.pending_tasks:
            await asyncio.gather(*runtime.pending_tasks.values(), return_exceptions=True)
        await runtime.openclaw.close()

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
        return {"status": "ok", "service": "openalice"}

    @app.post("/alice/webhook/{secret}")
    async def alice_webhook(
        request: AliceWebhookRequest,
        secret: str = Path(min_length=1),
    ) -> JSONResponse:
        if not hmac.compare_digest(secret, runtime.settings.alice_webhook_secret):
            raise HTTPException(status_code=404, detail="Not found")

        raw_identity = _raw_identity(request)
        if runtime.settings.alice_allowed_user_ids and raw_identity not in runtime.settings.alice_allowed_user_ids:
            logger.warning("Rejected an Alice request from an unknown identity")
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
            return JSONResponse(cached)

        response = await _handle_request(runtime, request, raw_identity)
        response_dict = response.model_dump(exclude_none=True)
        await runtime.store.cache_response(request_key, response_dict)
        return JSONResponse(response_dict)

    return app


async def _handle_request(
    runtime: Runtime,
    request: AliceWebhookRequest,
    raw_identity: str,
) -> AliceWebhookResponse:
    command = normalize_command(request.request.command or request.request.original_utterance)
    intent = detect_command_intent(command)
    identity_hash = hashlib.sha256(raw_identity.encode("utf-8")).hexdigest()
    generation = await runtime.store.get_generation(identity_hash)
    conversation_id = f"openalice:yandex-user:{identity_hash}:v{generation}"

    if request.session.new and not command:
        return _alice_response(
            "Это Открытый помощник. Задайте вопрос. Если ответ готовится долго, скажите «готово» немного позже."
        )
    if intent is CommandIntent.HELP:
        return _alice_response(
            "Я передаю ваши вопросы домашнему помощнику OpenClaw. Можно сказать «готово», «новый диалог», «отмена» или «выйти»."
        )
    if intent is CommandIntent.EXIT:
        return _alice_response("До встречи.", end_session=True)
    if intent is CommandIntent.NEW_DIALOG:
        await _cancel_pending(runtime, conversation_id)
        await runtime.store.increment_generation(identity_hash)
        return _alice_response("Начинаю новый диалог. О чём поговорим?")
    if intent is CommandIntent.CANCEL:
        cancelled = await _cancel_pending(runtime, conversation_id)
        return _alice_response("Запрос отменён." if cancelled else "Сейчас нет ожидающего запроса.")
    if intent is CommandIntent.RESULT:
        return await _get_deferred_result(runtime, conversation_id)
    if not command:
        return _alice_response("Я вас не расслышала. Повторите вопрос.")

    existing = await runtime.store.get_job(conversation_id)
    if existing and existing["status"] == "pending":
        return _alice_response("Предыдущий запрос ещё выполняется. Скажите «готово» немного позже или «отмена».")

    task = asyncio.create_task(runtime.openclaw.ask(command, conversation_id))
    runtime.pending_tasks[conversation_id] = task
    done, _ = await asyncio.wait({task}, timeout=runtime.settings.alice_fast_timeout_seconds)
    if task in done:
        runtime.pending_tasks.pop(conversation_id, None)
        try:
            answer = task.result()
        except (OpenClawError, asyncio.CancelledError):
            logger.exception("OpenClaw failed to answer an Alice request")
            return _alice_response("Домашний помощник сейчас недоступен. Попробуйте ещё раз позже.")
        await runtime.store.delete_job(conversation_id)
        return _alice_response(shorten_for_alice(answer, runtime.settings.alice_max_response_chars))

    await runtime.store.set_job(conversation_id, "pending")
    task.add_done_callback(
        lambda completed: asyncio.create_task(_save_deferred_result(runtime, conversation_id, completed))
    )
    return _alice_response("Мне нужно немного времени. Скажите «готово» через несколько секунд.")


async def _save_deferred_result(
    runtime: Runtime,
    conversation_id: str,
    task: asyncio.Task[str],
) -> None:
    runtime.pending_tasks.pop(conversation_id, None)
    try:
        answer = task.result()
    except asyncio.CancelledError:
        await runtime.store.set_job(conversation_id, "failed", error="Запрос был отменён.")
    except Exception as exc:
        logger.warning("Deferred OpenClaw request failed: %s", type(exc).__name__)
        await runtime.store.set_job(conversation_id, "failed", error="Домашний помощник не смог подготовить ответ.")
    else:
        await runtime.store.set_job(conversation_id, "done", response=answer)


async def _get_deferred_result(runtime: Runtime, conversation_id: str) -> AliceWebhookResponse:
    job = await runtime.store.get_job(conversation_id)
    if job is None:
        return _alice_response("Нет ожидающего ответа. Задайте новый вопрос.")
    if job["status"] == "pending":
        return _alice_response("Ответ ещё готовится. Скажите «готово» немного позже.")
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


def _alice_response(text: str, end_session: bool = False) -> AliceWebhookResponse:
    return AliceWebhookResponse(
        response=AliceResponseBody(text=text, tts=text, end_session=end_session)
    )


def _json_response(response: AliceWebhookResponse) -> JSONResponse:
    return JSONResponse(response.model_dump(exclude_none=True))
