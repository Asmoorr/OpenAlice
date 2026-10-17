import asyncio

import pytest

from openalice.application.conversation import ConversationPolicy, ConversationService
from openalice.application.coordinator import RequestCoordinator
from openalice.domain.models import Job


class MemoryRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.generations: dict[str, int] = {}

    async def get_job(self, key: str) -> Job | None:
        return self.jobs.get(key)

    async def set_job(self, key: str, job: Job) -> None:
        self.jobs[key] = job

    async def delete_job(self, key: str) -> None:
        self.jobs.pop(key, None)

    async def get_generation(self, key: str) -> int:
        return self.generations.get(key, 0)

    async def increment_generation(self, key: str) -> int:
        self.generations[key] = self.generations.get(key, 0) + 1
        return self.generations[key]

    async def complete_with_notification(self, key, response, notification):
        self.jobs[key] = Job.pending().complete(response)
        self.notification = notification


class Gateway:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.calls: list[str] = []

    async def ask(self, message: str, user: str) -> str:
        self.calls.append(user)
        await self.release.wait()
        return "Ответ"


class Phrases:
    def choose(self) -> str:
        return "Подождите"


async def test_service_runs_in_memory_and_advances_conversation_generation() -> None:
    repository = MemoryRepository()
    gateway = Gateway()
    gateway.release.set()
    coordinator = RequestCoordinator()
    service = ConversationService(
        repository,
        repository,
        repository,
        gateway,
        Phrases(),
        coordinator,
        ConversationPolicy(0.01, 900),
    )
    assert (await service.handle("Вопрос", "user")).text == "Ответ"
    assert (await service.handle("новый диалог", "user")).text.startswith("Начинаю")
    assert (await service.handle("Другой вопрос", "user")).text == "Ответ"
    assert gateway.calls[0].endswith(":v0")
    assert gateway.calls[1].endswith(":v1")
    assert repository.jobs == {}
    await coordinator.close()


async def test_cancel_prevents_deferred_answer_from_reappearing() -> None:
    repository = MemoryRepository()
    gateway = Gateway()
    coordinator = RequestCoordinator()
    service = ConversationService(
        repository,
        repository,
        repository,
        gateway,
        Phrases(),
        coordinator,
        ConversationPolicy(0.001, 900),
    )
    assert (await service.handle("Вопрос", "user")).text == "Подождите"
    assert (await service.handle("отмена", "user")).text == "Запрос отменён."
    gateway.release.set()
    await asyncio.sleep(0)
    assert (await service.handle("готово", "user")).text.startswith("Нет ожидающего")
    assert repository.jobs == {}
    await coordinator.close()


async def test_immediate_gateway_failure_uses_safe_reply():
    from openalice.application.ports import AssistantError

    class FailingGateway:
        async def ask(self, message, user):
            raise AssistantError("safe failure")

    repository = MemoryRepository()
    coordinator = RequestCoordinator()
    service = ConversationService(
        repository,
        repository,
        repository,
        FailingGateway(),
        Phrases(),
        coordinator,
        ConversationPolicy(0.1, 900),
    )
    reply = await service.handle("Вопрос", "user")
    assert reply.text.startswith("Домашний помощник сейчас недоступен")
    assert repository.jobs == {}
    await coordinator.close()


@pytest.mark.parametrize("failed,notify", [(False, False), (True, False), (False, True)])
async def test_deferred_completion_failure_and_notification(failed, notify):
    from openalice.application.ports import AssistantError

    repository = MemoryRepository()
    release = asyncio.Event()

    class ControlledGateway:
        async def ask(self, message, user):
            await release.wait()
            if failed:
                raise AssistantError("safe failure")
            return "Готовый ответ"

    coordinator = RequestCoordinator()
    wake_calls = []
    service = ConversationService(
        repository,
        repository,
        repository,
        ControlledGateway(),
        Phrases(),
        coordinator,
        ConversationPolicy(0.001, 900, notify, "test", "target"),
        lambda: wake_calls.append(True),
    )
    assert (await service.handle("", "user", True)).text.startswith("Это Открытый")
    assert (await service.handle("", "user")).text.startswith("Я вас не расслышала")
    assert (await service.handle("Вопрос", "user")).text == "Подождите"
    assert (await service.handle("Ещё вопрос", "user")).text == "Подождите"
    assert (await service.handle("готово", "user")).text == "Подождите"
    release.set()
    for _ in range(20):
        await asyncio.sleep(0)
        if coordinator.registry_sizes[1] == 0:
            break
    reply = await service.handle("готово", "user")
    assert reply.text == (
        "Домашний помощник не смог подготовить ответ." if failed else "Готовый ответ"
    )
    assert bool(wake_calls) == notify
    assert not repository.jobs
    await coordinator.close()
