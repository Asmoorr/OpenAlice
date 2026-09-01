import pytest

from openalice.commands import CommandIntent, detect_command_intent


@pytest.mark.parametrize(
    ("phrase", "intent"),
    [
        ("Пожалуйста, расскажи мне, что ты умеешь", CommandIntent.HELP),
        ("Какие есть команды?", CommandIntent.HELP),
        ("Как этим навыком пользоваться", CommandIntent.HELP),
        ("Алиса, покажи мне готовый ответ", CommandIntent.RESULT),
        ("Что там с моим запросом?", CommandIntent.RESULT),
        ("Проверь текущую задачу", CommandIntent.RESULT),
        ("Будь добра, отмени последний запрос", CommandIntent.CANCEL),
        ("Остановить выполнение", CommandIntent.CANCEL),
        ("Я передумала", CommandIntent.CANCEL),
        ("Давай начнём новую беседу", CommandIntent.NEW_DIALOG),
        ("Сбрось текущий контекст", CommandIntent.NEW_DIALOG),
        ("Начни с начала", CommandIntent.NEW_DIALOG),
        ("Закрой этот навык, пожалуйста", CommandIntent.EXIT),
        ("Заверши наш разговор", CommandIntent.EXIT),
        ("До свидания", CommandIntent.EXIT),
    ],
)
def test_detects_local_command_variants(phrase: str, intent: CommandIntent) -> None:
    assert detect_command_intent(phrase) is intent


@pytest.mark.parametrize(
    "phrase",
    [
        "Помоги написать письмо",
        "Расскажи, что ты умеешь делать с файлами проекта",
        "Покажи результат вычисления интеграла",
        "Начни новый проект на Python",
        "Останови музыку на кухне",
        "Закончи предложение красивой метафорой",
    ],
)
def test_does_not_intercept_normal_agent_requests(phrase: str) -> None:
    assert detect_command_intent(phrase) is None
