from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import aiohttp
from ya_passport_auth import Credentials, PassportClient, SecretStr
from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf


class GlagolError(RuntimeError):
    """A safe, non-secret-bearing Glagol failure."""


@dataclass(frozen=True, slots=True)
class GlagolDevice:
    device_id: str
    platform: str
    host: str
    port: int

    def __post_init__(self) -> None:
        address = ipaddress.ip_address(self.host)
        if not (address.is_private or address.is_link_local):
            raise ValueError("Glagol host must be a private or link-local IP address")


class DeviceResolver(Protocol):
    async def resolve(self, device_id: str) -> GlagolDevice: ...


class DeviceTokenProvider(Protocol):
    async def get_token(self, device_id: str, platform: str) -> SecretStr: ...


class JsonCredentialStore:
    """Stores OAuth credentials outside Git; tokens are never logged."""

    def __init__(self, path: Path) -> None:
        self._path = path

    async def load(self) -> Credentials:
        try:
            payload = json.loads(await asyncio.to_thread(self._path.read_text, encoding="utf-8"))
            return Credentials(
                x_token=SecretStr(payload["x_token"]),
                music_token=SecretStr(payload["music_token"]) if payload.get("music_token") else None,
                uid=payload.get("uid"),
                display_login=payload.get("display_login"),
                refresh_token=SecretStr(payload["refresh_token"]) if payload.get("refresh_token") else None,
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GlagolError("Glagol credentials are missing or invalid; run setup first") from exc

    async def save(self, credentials: Credentials) -> None:
        payload = {
            "x_token": credentials.x_token.get_secret(),
            "music_token": credentials.music_token.get_secret() if credentials.music_token else None,
            "uid": credentials.uid,
            "display_login": credentials.display_login,
            "refresh_token": credentials.refresh_token.get_secret() if credentials.refresh_token else None,
        }
        await asyncio.to_thread(self._save_sync, payload)

    def _save_sync(self, payload: dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            if os.name != "nt":
                temporary.chmod(0o600)
            os.replace(temporary, self._path)
        finally:
            temporary.unlink(missing_ok=True)


class PassportDeviceTokenProvider:
    def __init__(self, store: JsonCredentialStore) -> None:
        self._store = store

    async def get_token(self, device_id: str, platform: str) -> SecretStr:
        credentials = await self._store.load()
        async with PassportClient.create() as passport:
            if credentials.music_token is None:
                music_token = await passport.refresh_music_token(credentials.x_token)
                credentials = Credentials(
                    x_token=credentials.x_token,
                    music_token=music_token,
                    uid=credentials.uid,
                    display_login=credentials.display_login,
                    refresh_token=credentials.refresh_token,
                )
                await self._store.save(credentials)
            try:
                return await passport.get_glagol_device_token(
                    credentials.music_token,
                    device_id=device_id,
                    platform=platform,
                )
            except Exception as exc:
                if credentials.refresh_token is None:
                    raise GlagolError("Yandex rejected the stored Glagol credentials") from exc
                try:
                    credentials = await passport.refresh_credentials(credentials)
                    await self._store.save(credentials)
                    if credentials.music_token is None:
                        raise GlagolError("Yandex did not return a music token")
                    return await passport.get_glagol_device_token(
                        credentials.music_token,
                        device_id=device_id,
                        platform=platform,
                    )
                except Exception as refresh_exc:
                    raise GlagolError("Yandex rejected the stored Glagol credentials") from refresh_exc


class MdnsDeviceResolver:
    SERVICE_TYPE = "_yandexio._tcp.local."

    def __init__(self, timeout_seconds: float = 3.0) -> None:
        self._timeout_seconds = timeout_seconds

    async def resolve(self, device_id: str) -> GlagolDevice:
        devices = await self.discover_all()
        for device in devices:
            if device.device_id == device_id:
                return device
        raise GlagolError("Yandex Station was not found on the local network")

    async def discover_all(self) -> tuple[GlagolDevice, ...]:
        devices: dict[str, GlagolDevice] = {}
        tasks: list[asyncio.Task[None]] = []
        zeroconf = AsyncZeroconf()

        async def inspect(service_type: str, name: str) -> None:
            info = AsyncServiceInfo(service_type, name)
            if not await info.async_request(zeroconf.zeroconf, self._timeout_seconds * 1000):
                return
            properties = {
                key.decode(): value.decode() if isinstance(value, bytes) else str(value)
                for key, value in info.properties.items()
            }
            device_id = properties.get("deviceId")
            platform = properties.get("platform")
            if not device_id or not platform or not info.addresses:
                return
            host = str(ipaddress.ip_address(info.addresses[0]))
            devices[device_id] = GlagolDevice(device_id, platform, host, info.port)

        def handler(
                zeroconf: object,
                service_type: str,
                name: str,
                state_change: ServiceStateChange,
        ) -> None:
            del zeroconf
            if state_change is not ServiceStateChange.Removed:
                task = asyncio.create_task(inspect(service_type, name))
                tasks.append(task)

        browser = AsyncServiceBrowser(zeroconf.zeroconf, self.SERVICE_TYPE, handlers=[handler])
        try:
            await asyncio.sleep(self._timeout_seconds)
        finally:
            await browser.async_cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await zeroconf.async_close()
        return tuple(devices.values())


class StaticDeviceResolver:
    def __init__(self, device: GlagolDevice) -> None:
        self._device = device

    async def resolve(self, device_id: str) -> GlagolDevice:
        if device_id != self._device.device_id:
            raise GlagolError("Configured Glagol device does not match notification target")
        return self._device


class GlagolClient:
    def __init__(
            self,
            token_provider: DeviceTokenProvider,
            resolver: DeviceResolver,
            timeout_seconds: float = 5.0,
            session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._token_provider = token_provider
        self._resolver = resolver
        self._timeout = timeout_seconds
        self._session = session
        self._owns_session = session is None
        self._lock = asyncio.Lock()

    async def say(self, device_id: str, text: str) -> None:
        async with self._lock:
            device = await self._resolver.resolve(device_id)
            token = await self._token_provider.get_token(device.device_id, device.platform)
            session = self._session
            if session is None:
                session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._timeout))
                self._session = session
            request_id = str(uuid.uuid4())
            envelope = {
                "conversationToken": token.get_secret(),
                "id": request_id,
                "payload": self._speech_payload(text),
                "sentTime": int(time.time() * 1000),
            }
            try:
                async with session.ws_connect(
                    f"wss://{device.host}:{device.port}", heartbeat=55, ssl=False
                ) as socket:
                    await socket.send_json(envelope)
                    async with asyncio.timeout(self._timeout):
                        async for message in socket:
                            if message.type is aiohttp.WSMsgType.TEXT:
                                response = json.loads(message.data)
                                if response.get("requestId") == request_id:
                                    if response.get("status") != "success":
                                        raise GlagolError("Yandex Station rejected the speech request")
                                    return
                            elif message.type in {aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED}:
                                break
            except GlagolError:
                raise
            except (aiohttp.ClientError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                raise GlagolError("Unable to deliver speech through Glagol") from exc
            raise GlagolError("Yandex Station closed the Glagol connection")

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()

    @staticmethod
    def _speech_payload(text: str) -> dict[str, object]:
        return {
            "command": "serverAction",
            "serverActionEventPayload": {
                "type": "server_action",
                "name": "update_form",
                "payload": {
                    "form_update": {
                        "name": "personal_assistant.scenarios.quasar.iot.repeat_phrase",
                        "slots": [{"type": "string", "name": "phrase_to_repeat", "value": text}],
                    },
                    "resubmit": True,
                },
            },
        }
