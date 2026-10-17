from dataclasses import dataclass, field

import pytest

from openalice.application.commands import (
    CommandContext,
    CommandDispatcher,
    StaticReplyHandler,
    build_command_dispatcher,
)
from openalice.domain.commands import CommandIntent
from openalice.domain.models import Reply


@dataclass
class RecordingActions:
    calls: list[tuple[str, CommandContext]] = field(default_factory=list)

    async def get_result(self, context: CommandContext) -> Reply:
        self.calls.append(("result", context))
        return Reply("Результат")

    async def cancel(self, context: CommandContext) -> Reply:
        self.calls.append(("cancel", context))
        return Reply("Отмена")

    async def start_new_dialog(self, context: CommandContext) -> Reply:
        self.calls.append(("new_dialog", context))
        return Reply("Новый диалог")


@pytest.mark.parametrize(
    ("intent", "expected_text", "expected_action", "end_session"),
    [
        (
            CommandIntent.HELP,
            "Я передаю ваши вопросы домашнему помощнику OpenClaw. Можно сказать "
            "«готово», «новый диалог», «отмена» или «выйти».",
            None,
            False,
        ),
        (CommandIntent.RESULT, "Результат", "result", False),
        (CommandIntent.CANCEL, "Отмена", "cancel", False),
        (CommandIntent.NEW_DIALOG, "Новый диалог", "new_dialog", False),
        (CommandIntent.EXIT, "До встречи.", None, True),
    ],
)
async def test_dispatches_each_command(
    intent: CommandIntent,
    expected_text: str,
    expected_action: str | None,
    end_session: bool,
) -> None:
    actions = RecordingActions()
    context = CommandContext("conversation", "identity")

    reply = await build_command_dispatcher(actions).dispatch(intent, context)

    assert reply == Reply(expected_text, end_session=end_session)
    assert [name for name, _ in actions.calls] == (
        [expected_action] if expected_action is not None else []
    )


async def test_handler_is_added_by_registration_only() -> None:
    context = CommandContext("conversation", "identity")
    dispatcher = CommandDispatcher({CommandIntent.HELP: StaticReplyHandler(Reply("Новая справка"))})

    assert await dispatcher.dispatch(CommandIntent.HELP, context) == Reply("Новая справка")
    with pytest.raises(LookupError, match="No handler registered"):
        await dispatcher.dispatch(CommandIntent.EXIT, context)
