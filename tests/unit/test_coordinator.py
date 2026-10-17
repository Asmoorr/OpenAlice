import asyncio

from openalice.application.coordinator import RequestCoordinator


async def test_duplicates_share_work_and_release_registries() -> None:
    coordinator = RequestCoordinator()
    release = asyncio.Event()
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        await release.wait()
        return "answer"

    first = asyncio.create_task(coordinator.run_once("key", operation))
    second = asyncio.create_task(coordinator.run_once("key", operation))
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(first, second) == ["answer", "answer"]
    assert calls == 1
    assert coordinator.registry_sizes == (0, 0, 0, 0)
    await coordinator.close()


async def test_keyed_locks_are_serial_and_released() -> None:
    coordinator = RequestCoordinator()
    active = 0
    maximum = 0

    async def operation() -> None:
        nonlocal active, maximum
        async with coordinator.hold("identity"):
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            active -= 1

    await asyncio.gather(*(operation() for _ in range(50)))
    assert maximum == 1
    assert coordinator.registry_sizes == (0, 0, 0, 0)
    await coordinator.close()
