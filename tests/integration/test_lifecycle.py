from unittest.mock import AsyncMock

import pytest

from openalice.app import create_app
from openalice.config import Settings


@pytest.mark.parametrize("failure", ["none", "startup", "body"])
async def test_lifespan_closes_owned_resources_once(tmp_path, failure):
    gateway = AsyncMock()
    settings = Settings(
        _env_file=None,
        openclaw_gateway_token="test-token",
        alice_webhook_secret="long-test-webhook-secret",
        database_path=tmp_path / "lifecycle.db",
    )
    app = create_app(settings, gateway)
    runtime = app.state.runtime
    runtime.store.close = AsyncMock()
    runtime.coordinator.close = AsyncMock()
    if failure == "startup":
        runtime.store.initialize = AsyncMock(side_effect=RuntimeError("startup failed"))

    async def run():
        async with app.router.lifespan_context(app):
            if failure == "body":
                raise RuntimeError("body failed")

    if failure == "none":
        await run()
    else:
        with pytest.raises(RuntimeError):
            await run()
    gateway.close.assert_awaited_once()
    runtime.store.close.assert_awaited_once()
    runtime.coordinator.close.assert_awaited_once()
