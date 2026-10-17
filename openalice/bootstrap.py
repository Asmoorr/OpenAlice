from dataclasses import dataclass, field

from openalice.application.conversation import ConversationPolicy, ConversationService
from openalice.application.coordinator import RequestCoordinator
from openalice.application.ports import AssistantGateway as AssistantClient
from openalice.application.ports import Notifier
from openalice.config import Settings
from openalice.infrastructure.gateway import FakeOpenClawClient, OpenClawClient
from openalice.infrastructure.glagol import (
    GlagolClient,
    GlagolDevice,
    JsonCredentialStore,
    MdnsDeviceResolver,
    PassportDeviceTokenProvider,
    StaticDeviceResolver,
)
from openalice.infrastructure.notifications.notifiers import GlagolNotifier, HomeAssistantNotifier
from openalice.infrastructure.notifications.worker import NotificationWorker
from openalice.infrastructure.persistence import SqliteStore as Store
from openalice.pending_phrases import PendingPhraseProvider


@dataclass
class Runtime:
    settings: Settings
    store: Store
    openclaw: AssistantClient
    pending_phrases: PendingPhraseProvider
    notification_worker: NotificationWorker | None
    coordinator: RequestCoordinator = field(default_factory=RequestCoordinator)
    service: ConversationService | None = None


def build_runtime(
    resolved: Settings,
    openclaw_client: AssistantClient | None = None,
    notifier: Notifier | None = None,
) -> Runtime:
    store = Store(resolved.database_path)
    resolved_notifier = notifier or _create_notifier(resolved)
    runtime = Runtime(
        settings=resolved,
        store=store,
        openclaw=openclaw_client or _create_assistant_client(resolved),
        pending_phrases=PendingPhraseProvider(resolved.alice_pending_phrases),
        notification_worker=(
            NotificationWorker(
                store,
                resolved_notifier,
                resolved.notification_max_attempts,
                resolved.notification_poll_seconds,
                resolved.notification_channel,
            )
            if resolved_notifier is not None
            else None
        ),
    )

    runtime.service = ConversationService(
        store,
        store,
        store,
        runtime.openclaw,
        runtime.pending_phrases,
        runtime.coordinator,
        ConversationPolicy(
            resolved.alice_fast_timeout_seconds,
            resolved.alice_max_response_chars,
            resolved.notifications_enabled,
            resolved.notification_channel,
            resolved.notification_target,
            resolved.notification_ready_phrase,
        ),
        runtime.notification_worker.wake if runtime.notification_worker else lambda: None,
    )

    return runtime


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
        settings.openclaw_timeout_seconds,
    )


def _create_notifier(settings: Settings) -> Notifier | None:
    if not settings.notifications_enabled:
        return None
    if settings.notification_provider == "glagol":
        resolver = (
            StaticDeviceResolver(
                GlagolDevice(
                    settings.glagol_device_id,
                    settings.glagol_platform,
                    settings.glagol_host,
                    settings.glagol_port,
                )
            )
            if settings.glagol_host
            else MdnsDeviceResolver(settings.glagol_discovery_timeout_seconds)
        )
        token_provider = PassportDeviceTokenProvider(
            JsonCredentialStore(settings.glagol_credentials_path)
        )
        return GlagolNotifier(
            GlagolClient(
                token_provider,
                resolver,
                settings.glagol_timeout_seconds,
            )
        )
    return HomeAssistantNotifier(
        settings.home_assistant_url,
        settings.home_assistant_token,
        settings.home_assistant_timeout_seconds,
    )
