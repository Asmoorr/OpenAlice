from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from openalice.application.command_parser import detect_command_intent, normalize_command
from openalice.application.commands import CommandContext, build_command_dispatcher
from openalice.application.coordinator import RequestCoordinator
from openalice.application.ports import (
    AssistantError,
    AssistantGateway,
    ConversationGenerationRepository,
    DeferredCompletionRepository,
    JobRepository,
    PendingPhraseStrategy,
)
from openalice.domain.models import ConversationKey, Job, JobStatus, Notification, Reply
from openalice.domain.text import shorten_for_alice


@dataclass(frozen=True, slots=True)
class ConversationPolicy:
    fast_timeout_seconds: float
    max_response_chars: int
    notifications_enabled: bool = False
    notification_channel: str = ""
    notification_target: str = ""
    notification_text: str = "Ответ готов."


class ConversationService:
    def __init__(
        self,
        jobs: JobRepository,
        generations: ConversationGenerationRepository,
        completion: DeferredCompletionRepository,
        gateway: AssistantGateway,
        phrases: PendingPhraseStrategy,
        coordinator: RequestCoordinator,
        policy: ConversationPolicy,
        wake: Callable[[], None] = lambda: None,
    ) -> None:
        self.jobs = jobs
        self.generations = generations
        self.completion = completion
        self.gateway = gateway
        self.phrases = phrases
        self.coordinator = coordinator
        self.policy = policy
        self.wake = wake
        self.commands = build_command_dispatcher(self)

    async def handle(self, utterance: str, identity: str, new: bool = False) -> Reply:
        command = normalize_command(utterance)
        identity_hash = hashlib.sha256(identity.encode()).hexdigest()
        # Lock the stable identity across generation lookup and command dispatch.
        async with self.coordinator.hold(identity_hash):
            generation = await self.generations.get_generation(identity_hash)
            context = CommandContext(str(ConversationKey(identity_hash, generation)), identity_hash)
            if new and not command:
                return Reply(
                    "Это Открытый помощник. Задайте вопрос. Если ответ готовится долго, скажите «готово» немного позже."
                )
            intent = detect_command_intent(command)
            if intent is not None:
                return await self.commands.dispatch(intent, context)
            if not command:
                return Reply("Я вас не расслышала. Повторите вопрос.")
            existing = await self.jobs.get_job(context.conversation_id)
            if existing and existing.status is JobStatus.PENDING:
                return Reply(self.phrases.choose())
            await self.jobs.set_job(context.conversation_id, Job.pending())
            task = self.coordinator.start_pending(
                context.conversation_id,
                self.gateway.ask(command, context.conversation_id),
            )
        done, _ = await asyncio.wait({task}, timeout=self.policy.fast_timeout_seconds)
        if task in done:
            async with self.coordinator.hold(identity_hash):
                if not self.coordinator.is_current_pending(context.conversation_id, task):
                    return Reply("Запрос отменён.")
                self.coordinator.pop_pending(context.conversation_id, task)
                await self.jobs.delete_job(context.conversation_id)
                try:
                    answer = task.result()
                except (AssistantError, asyncio.CancelledError):
                    return Reply("Домашний помощник сейчас недоступен. Попробуйте ещё раз позже.")
                return Reply(shorten_for_alice(answer, self.policy.max_response_chars))
        self.coordinator.track_background(self._save_result(context, task))
        return Reply(self.phrases.choose())

    async def _save_result(self, context: CommandContext, task: asyncio.Task[str]) -> None:
        try:
            answer = await asyncio.shield(task)
            job = Job.pending().complete(answer)
        except asyncio.CancelledError:
            return
        except Exception:
            job = Job.pending().fail("Домашний помощник не смог подготовить ответ.")
        async with self.coordinator.hold(context.identity_hash):
            if not self.coordinator.is_current_pending(context.conversation_id, task):
                return
            self.coordinator.pop_pending(context.conversation_id, task)
            if job.status is JobStatus.DONE and self.policy.notifications_enabled:
                notification = Notification(
                    uuid.uuid4().hex,
                    context.conversation_id,
                    "answer_ready",
                    self.policy.notification_channel,
                    self.policy.notification_target,
                    self.policy.notification_text,
                )
                await self.completion.complete_with_notification(
                    context.conversation_id,
                    job.response or "",
                    notification,
                )
                self.wake()
            else:
                await self.jobs.set_job(context.conversation_id, job)

    async def get_result(self, context: CommandContext) -> Reply:
        job = await self.jobs.get_job(context.conversation_id)
        if job is None:
            return Reply("Нет ожидающего ответа. Задайте новый вопрос.")
        if job.status is JobStatus.PENDING:
            return Reply(self.phrases.choose())
        await self.jobs.delete_job(context.conversation_id)
        if job.status is JobStatus.FAILED:
            return Reply(job.error or "Не удалось подготовить ответ. Попробуйте ещё раз.")
        return Reply(
            shorten_for_alice(job.response or "Ответ пуст.", self.policy.max_response_chars)
        )

    async def _cancel(self, context: CommandContext) -> bool:
        existed = self.coordinator.cancel_pending(context.conversation_id)
        job = await self.jobs.get_job(context.conversation_id)
        await self.jobs.delete_job(context.conversation_id)
        return existed or job is not None

    async def cancel(self, context: CommandContext) -> Reply:
        existed = await self._cancel(context)
        return Reply("Запрос отменён." if existed else "Сейчас нет ожидающего запроса.")

    async def start_new_dialog(self, context: CommandContext) -> Reply:
        await self._cancel(context)
        await self.generations.increment_generation(context.identity_hash)
        return Reply("Начинаю новый диалог. О чём поговорим?")
