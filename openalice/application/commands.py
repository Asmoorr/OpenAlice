from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol

from openalice.domain.commands import CommandIntent
from openalice.domain.models import Reply


@dataclass(frozen=True, slots=True)
class CommandContext:
    conversation_id: str
    identity_hash: str


class CommandActions(Protocol):
    async def get_result(self, context: CommandContext) -> Reply: ...

    async def cancel(self, context: CommandContext) -> Reply: ...

    async def start_new_dialog(self, context: CommandContext) -> Reply: ...


class CommandHandler(Protocol):
    async def handle(self, context: CommandContext) -> Reply: ...


@dataclass(frozen=True, slots=True)
class StaticReplyHandler:
    reply: Reply

    async def handle(self, context: CommandContext) -> Reply:
        del context
        return self.reply


@dataclass(frozen=True, slots=True)
class ResultCommandHandler:
    actions: CommandActions

    async def handle(self, context: CommandContext) -> Reply:
        return await self.actions.get_result(context)


@dataclass(frozen=True, slots=True)
class CancelCommandHandler:
    actions: CommandActions

    async def handle(self, context: CommandContext) -> Reply:
        return await self.actions.cancel(context)


@dataclass(frozen=True, slots=True)
class NewDialogCommandHandler:
    actions: CommandActions

    async def handle(self, context: CommandContext) -> Reply:
        return await self.actions.start_new_dialog(context)


class CommandDispatcher:
    def __init__(self, handlers: Mapping[CommandIntent, CommandHandler]) -> None:
        self._handlers = MappingProxyType(dict(handlers))

    async def dispatch(self, intent: CommandIntent, context: CommandContext) -> Reply:
        try:
            handler = self._handlers[intent]
        except KeyError as exc:
            raise LookupError(f"No handler registered for {intent.value}") from exc
        return await handler.handle(context)


def build_command_dispatcher(actions: CommandActions) -> CommandDispatcher:
    return CommandDispatcher(
        {
            CommandIntent.HELP: StaticReplyHandler(
                Reply(
                    "Я передаю ваши вопросы домашнему помощнику OpenClaw. Можно сказать "
                    "«готово», «новый диалог», «отмена» или «выйти»."
                )
            ),
            CommandIntent.RESULT: ResultCommandHandler(actions),
            CommandIntent.CANCEL: CancelCommandHandler(actions),
            CommandIntent.NEW_DIALOG: NewDialogCommandHandler(actions),
            CommandIntent.EXIT: StaticReplyHandler(Reply("До встречи.", end_session=True)),
        }
    )
