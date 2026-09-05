import json
from pathlib import Path

import aiohttp
import pytest
from pydantic import ValidationError
from ya_passport_auth import Credentials, SecretStr

from openalice.config import Settings
from openalice.glagol import (
    GlagolClient,
    GlagolDevice,
    JsonCredentialStore,
    StaticDeviceResolver,
    MdnsDeviceResolver,
)


class FakeTokenProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def get_token(self, device_id: str, platform: str) -> SecretStr:
        self.calls.append((device_id, platform))
        return SecretStr("device-token")


class FakeMessage:
    type = aiohttp.WSMsgType.TEXT

    def __init__(self, data: str) -> None:
        self.data = data


class FakeSocket:
    def __init__(self) -> None:
        self.payload: dict[str, object] | None = None
        self._delivered = False

    async def send_json(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __aiter__(self) -> "FakeSocket":
        return self

    async def __anext__(self) -> FakeMessage:
        if self._delivered or self.payload is None:
            raise StopAsyncIteration
        self._delivered = True
        return FakeMessage(json.dumps({"requestId": self.payload["id"], "status": "success"}))


class FakeWebSocketContext:
    def __init__(self, socket: FakeSocket) -> None:
        self.socket = socket

    async def __aenter__(self) -> FakeSocket:
        return self.socket

    async def __aexit__(self, *_exc: object) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.socket = FakeSocket()
        self.url = ""
        self.options: dict[str, object] = {}

    def ws_connect(self, url: str, **options: object) -> FakeWebSocketContext:
        self.url = url
        self.options = options
        return FakeWebSocketContext(self.socket)


@pytest.mark.asyncio
async def test_glagol_client_sends_repeat_phrase() -> None:
    provider = FakeTokenProvider()
    session = FakeSession()
    device = GlagolDevice("device-1", "yandexstation", "192.168.1.20", 1961)
    client = GlagolClient(
        provider,
        StaticDeviceResolver(device),
        session=session,  # type: ignore[arg-type]
    )

    await client.say("device-1", "Ответ готов.")

    assert provider.calls == [("device-1", "yandexstation")]
    assert session.url == "wss://192.168.1.20:1961"
    assert session.options["ssl"] is False
    assert session.socket.payload is not None
    assert session.socket.payload["conversationToken"] == "device-token"
    form = session.socket.payload["payload"]["serverActionEventPayload"]["payload"]["form_update"]  # type: ignore[index]
    assert form["name"] == "personal_assistant.scenarios.quasar.iot.repeat_phrase"
    assert form["slots"][0]["value"] == "Ответ готов."


@pytest.mark.asyncio
async def test_credentials_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    store = JsonCredentialStore(path)
    original = Credentials(
        x_token=SecretStr("x-token"),
        music_token=SecretStr("music-token"),
        refresh_token=SecretStr("refresh-token"),
        uid=42,
        display_login="user",
    )

    await store.save(original)
    loaded = await store.load()

    assert loaded == original
    assert "x-token" in path.read_text(encoding="utf-8")


def test_glagol_notification_settings() -> None:
    settings = Settings(
        _env_file=None,
        openclaw_gateway_token="test-token",
        alice_webhook_secret="a-very-long-test-secret",
        notifications_enabled=True,
        notification_provider="glagol",
        glagol_device_id="device-1",
    )

    assert settings.notification_channel == "glagol"
    assert settings.notification_target == "device-1"


def test_glagol_requires_device_id() -> None:
    with pytest.raises(ValidationError, match="GLAGOL_DEVICE_ID"):
        Settings(
            _env_file=None,
            openclaw_gateway_token="test-token",
            alice_webhook_secret="a-very-long-test-secret",
            notifications_enabled=True,
            notification_provider="glagol",
        )


def test_glagol_rejects_public_destination() -> None:
    with pytest.raises(ValueError, match="private or link-local"):
        GlagolDevice("device-1", "yandexstation", "8.8.8.8", 1961)


@pytest.mark.asyncio
async def test_mdns_handler_accepts_zeroconf_keyword_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeAsyncZeroconf:
        zeroconf = object()

        async def async_close(self) -> None:
            return None

    class FakeBrowser:
        def __init__(self, zeroconf: object, service_type: str, handlers: list[object]) -> None:
            del service_type
            handlers[0](
                zeroconf=zeroconf,
                service_type="_yandexio._tcp.local.",
                name="station._yandexio._tcp.local.",
                state_change=__import__("zeroconf").ServiceStateChange.Removed,
            )

        async def async_cancel(self) -> None:
            return None

    monkeypatch.setattr("openalice.glagol.AsyncZeroconf", FakeAsyncZeroconf)
    monkeypatch.setattr("openalice.glagol.AsyncServiceBrowser", FakeBrowser)

    devices = await MdnsDeviceResolver(0.001).discover_all()

    assert devices == ()
