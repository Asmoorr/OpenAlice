from collections.abc import Awaitable, Callable

import httpx
import pytest

from openalice.infrastructure.gateway import (
    ExponentialBackoffRetry,
    OpenClawClient,
    OpenClawError,
)


def client_with_handler(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    retry: ExponentialBackoffRetry | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    timeout_seconds: float = 42.0,
) -> OpenClawClient:
    options: dict[str, object] = {
        "transport": httpx.MockTransport(handler),
        "retry_strategy": retry or ExponentialBackoffRetry(max_attempts=1),
    }
    if sleep is not None:
        options["sleep"] = sleep
    return OpenClawClient(
        "http://gateway.local",
        "secret-token",
        "openclaw/default",
        timeout_seconds,
        **options,  # type: ignore[arg-type]
    )


async def test_gateway_sends_contract_payload_and_configured_timeout() -> None:
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(200, json={"output_text": "  Готовый ответ  "})

    client = client_with_handler(handler)
    try:
        answer = await client.ask("Вопрос", "conversation-1")
    finally:
        await client.close()

    assert answer == "Готовый ответ"
    assert captured is not None
    assert captured.url.path == "/v1/responses"
    assert captured.headers["Authorization"] == "Bearer secret-token"
    assert captured.extensions["timeout"]["connect"] == 5.0
    assert captured.extensions["timeout"]["read"] == 42.0
    assert captured.read().decode() == (
        '{"model":"openclaw/default","input":"Вопрос",'
        '"user":"conversation-1","instructions":"Отвечай по-русски, '
        "пригодным для озвучивания текстом без Markdown. Сначала дай краткий "
        'полезный ответ, желательно до 800 символов."}'
    )


async def test_gateway_extracts_nested_output_chunks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "output": [
                    {"content": [{"type": "output_text", "text": "Первая"}]},
                    {"content": [{"type": "output_text", "text": "Вторая"}]},
                ]
            },
        )

    client = client_with_handler(handler)
    try:
        assert await client.ask("Вопрос", "conversation") == "Первая\nВторая"
    finally:
        await client.close()


async def test_gateway_retries_transient_statuses_with_strategy() -> None:
    statuses = iter((503, 502, 504, 200))
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        return httpx.Response(status, json={"output_text": "Ответ"}, request=request)

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    client = client_with_handler(
        handler,
        retry=ExponentialBackoffRetry(max_attempts=4),
        sleep=record_sleep,
    )
    try:
        assert await client.ask("Вопрос", "conversation") == "Ответ"
    finally:
        await client.close()

    assert delays == [0.5, 1.0, 2.0]


async def test_gateway_does_not_retry_non_transient_http_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, text="invalid\nrequest", request=request)

    client = client_with_handler(handler, retry=ExponentialBackoffRetry(max_attempts=3))
    try:
        with pytest.raises(OpenClawError, match="HTTP 400: invalid request"):
            await client.ask("Вопрос", "conversation")
    finally:
        await client.close()

    assert calls == 1


async def test_gateway_retries_network_error_and_normalizes_failure() -> None:
    calls = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("gateway unavailable", request=request)

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    client = client_with_handler(
        handler,
        retry=ExponentialBackoffRetry(max_attempts=2),
        sleep=record_sleep,
    )
    try:
        with pytest.raises(OpenClawError, match="gateway unavailable"):
            await client.ask("Вопрос", "conversation")
    finally:
        await client.close()

    assert calls == 2
    assert delays == [0.5]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(200, content=b"not-json"), "invalid JSON"),
        (httpx.Response(200, json={"output": []}), "no output text"),
    ],
)
async def test_gateway_rejects_invalid_success_response(
    response: httpx.Response,
    message: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        response.request = request
        return response

    client = client_with_handler(handler)
    try:
        with pytest.raises(OpenClawError, match=message):
            await client.ask("Вопрос", "conversation")
    finally:
        await client.close()


@pytest.mark.parametrize(
    "policy",
    [
        lambda: ExponentialBackoffRetry(max_attempts=0),
        lambda: ExponentialBackoffRetry(initial_delay_seconds=-1),
        lambda: ExponentialBackoffRetry(maximum_delay_seconds=-1),
    ],
)
def test_retry_strategy_rejects_invalid_configuration(policy) -> None:
    with pytest.raises(ValueError):
        policy()
