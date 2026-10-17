import pytest
from pydantic import ValidationError

from openalice.bootstrap import build_runtime
from openalice.config import Settings


def settings(tmp_path, **overrides):
    return Settings(
        _env_file=None,
        openclaw_gateway_token="test-token",
        alice_webhook_secret="long-test-webhook-secret",
        database_path=tmp_path / "runtime.db",
        **overrides,
    )


@pytest.mark.parametrize("provider", ["home_assistant", "glagol", "glagol-static"])
async def test_composition_builds_each_notification_provider(tmp_path, provider):
    options = {"notifications_enabled": True, "notification_provider": "glagol"}
    if provider == "home_assistant":
        options.update(
            notification_provider="home_assistant",
            home_assistant_token="test-token",
            home_assistant_entity_id="media_player.test",
        )
    else:
        options["glagol_device_id"] = "device"
        if provider == "glagol-static":
            options.update(glagol_host="192.168.1.2", glagol_platform="station")
    runtime = build_runtime(settings(tmp_path, **options))
    assert runtime.notification_worker is not None
    await runtime.notification_worker.stop()
    await runtime.openclaw.close()
    await runtime.coordinator.close()


@pytest.mark.parametrize(
    "options",
    [
        {"notifications_enabled": True},
        {"notifications_enabled": True, "home_assistant_token": "token"},
        {
            "notifications_enabled": True,
            "notification_provider": "glagol",
            "glagol_device_id": "device",
            "glagol_host": "192.168.1.2",
        },
    ],
)
def test_configuration_rejects_incomplete_notification_credentials(tmp_path, options):
    with pytest.raises(ValidationError):
        settings(tmp_path, **options)


def test_configuration_normalizes_allowlist_and_urls(tmp_path):
    configured = settings(
        tmp_path,
        alice_allowed_user_ids=" user-1, user-2 ,, ",
        openclaw_base_url="http://localhost:18789/",
        home_assistant_url="http://localhost:8123/",
    )
    assert configured.alice_allowed_user_ids == frozenset({"user-1", "user-2"})
    assert not configured.openclaw_base_url.endswith("/")
    assert not configured.home_assistant_url.endswith("/")
