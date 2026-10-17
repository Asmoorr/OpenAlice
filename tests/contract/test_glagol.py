import json
from pathlib import Path

import aiohttp
import pytest
from pydantic import ValidationError
from ya_passport_auth import Credentials, SecretStr

from openalice.config import Settings
from openalice.infrastructure.glagol import (
    GlagolClient,
    GlagolDevice,
    GlagolError,
    JsonCredentialStore,
    MdnsDeviceResolver,
    PassportDeviceTokenProvider,
    StaticDeviceResolver,
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
    def __init__(self, status: str = "success") -> None:
        self.payload: dict[str, object] | None = None
        self._delivered = False
        self.status = status

    async def send_json(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __aiter__(self) -> "FakeSocket":
        return self

    async def __anext__(self) -> FakeMessage:
        if self._delivered or self.payload is None:
            raise StopAsyncIteration
        self._delivered = True
        return FakeMessage(json.dumps({"requestId": self.payload["id"], "status": self.status}))


class FakeWebSocketContext:
    def __init__(self, socket: FakeSocket) -> None:
        self.socket = socket

    async def __aenter__(self) -> FakeSocket:
        return self.socket

    async def __aexit__(self, *_exc: object) -> None:
        return None


class FakeSession:
    def __init__(self, status: str = "success") -> None:
        self.socket = FakeSocket(status)
        self.url = ""
        self.options: dict[str, object] = {}
        self.closed = False

    def ws_connect(self, url: str, **options: object) -> FakeWebSocketContext:
        self.url = url
        self.options = options
        return FakeWebSocketContext(self.socket)

    async def close(self) -> None:
        self.closed = True


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

    await client.close()
    assert session.closed is False


@pytest.mark.asyncio
async def test_glagol_client_closes_owned_session(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeTokenProvider()
    session = FakeSession()
    device = GlagolDevice("device-1", "yandexstation", "192.168.1.20", 1961)
    monkeypatch.setattr(
        "openalice.infrastructure.glagol.aiohttp.ClientSession",
        lambda **_options: session,
    )
    client = GlagolClient(provider, StaticDeviceResolver(device))

    await client.say("device-1", "Ответ готов.")
    await client.close()

    assert session.closed is True


@pytest.mark.asyncio
async def test_glagol_client_normalizes_station_rejection() -> None:
    provider = FakeTokenProvider()
    session = FakeSession(status="failed")
    device = GlagolDevice("device-1", "yandexstation", "192.168.1.20", 1961)
    client = GlagolClient(provider, StaticDeviceResolver(device), session=session)  # type: ignore[arg-type]

    with pytest.raises(GlagolError, match="rejected"):
        await client.say("device-1", "Ответ готов.")


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


@pytest.mark.asyncio
async def test_token_provider_fetches_missing_music_token(monkeypatch: pytest.MonkeyPatch) -> None:
    credentials = Credentials(x_token=SecretStr("x-token"))

    class MemoryStore:
        saved: list[Credentials] = []

        async def load(self) -> Credentials:
            return credentials

        async def save(self, value: Credentials) -> None:
            self.saved.append(value)

    class FakePassport:
        async def __aenter__(self) -> "FakePassport":
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def refresh_music_token(self, token: SecretStr) -> SecretStr:
            assert token.get_secret() == "x-token"
            return SecretStr("music-token")

        async def get_glagol_device_token(
            self,
            token: SecretStr,
            *,
            device_id: str,
            platform: str,
        ) -> SecretStr:
            assert token.get_secret() == "music-token"
            assert (device_id, platform) == ("device-1", "platform-1")
            return SecretStr("device-token")

    store = MemoryStore()
    passport = FakePassport()
    monkeypatch.setattr(
        "openalice.infrastructure.glagol.PassportClient.create",
        lambda: passport,
    )

    token = await PassportDeviceTokenProvider(store).get_token("device-1", "platform-1")

    assert token.get_secret() == "device-token"
    assert store.saved[0].music_token is not None
    assert store.saved[0].music_token.get_secret() == "music-token"


@pytest.mark.asyncio
async def test_token_provider_refreshes_rejected_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = Credentials(
        x_token=SecretStr("old-x-token"),
        music_token=SecretStr("old-music-token"),
        refresh_token=SecretStr("refresh-token"),
    )
    refreshed = Credentials(
        x_token=SecretStr("new-x-token"),
        music_token=SecretStr("new-music-token"),
        refresh_token=SecretStr("refresh-token"),
    )

    class MemoryStore:
        saved: list[Credentials] = []

        async def load(self) -> Credentials:
            return original

        async def save(self, value: Credentials) -> None:
            self.saved.append(value)

    class FakePassport:
        calls = 0

        async def __aenter__(self) -> "FakePassport":
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def get_glagol_device_token(
            self,
            token: SecretStr,
            **_device: str,
        ) -> SecretStr:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("rejected")
            assert token.get_secret() == "new-music-token"
            return SecretStr("device-token")

        async def refresh_credentials(self, value: Credentials) -> Credentials:
            assert value is original
            return refreshed

    store = MemoryStore()
    passport = FakePassport()
    monkeypatch.setattr(
        "openalice.infrastructure.glagol.PassportClient.create",
        lambda: passport,
    )

    token = await PassportDeviceTokenProvider(store).get_token("device-1", "platform-1")

    assert token.get_secret() == "device-token"
    assert store.saved == [refreshed]


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
async def test_mdns_handler_accepts_zeroconf_keyword_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    monkeypatch.setattr("openalice.infrastructure.glagol.AsyncZeroconf", FakeAsyncZeroconf)
    monkeypatch.setattr("openalice.infrastructure.glagol.AsyncServiceBrowser", FakeBrowser)

    devices = await MdnsDeviceResolver(0.001).discover_all()

    assert devices == ()
