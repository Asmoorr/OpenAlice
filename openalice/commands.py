import re
from enum import StrEnum


class CommandIntent(StrEnum):
    HELP = "help"
    RESULT = "result"
    CANCEL = "cancel"
    NEW_DIALOG = "new_dialog"
    EXIT = "exit"


_POLITE_PREFIX = r"(?:(?:алиса|слушай|пожалуйста|пожалуй|ну|а ну|будь добра|будь добр)\s+)*"
_POLITE_SUFFIX = r"(?:\s+(?:пожалуйста|если можно|будь добра|будь добр))?"


def _full(pattern: str) -> re.Pattern[str]:
    return re.compile(rf"^{_POLITE_PREFIX}(?:{pattern}){_POLITE_SUFFIX}$", re.IGNORECASE)


_PATTERNS: tuple[tuple[CommandIntent, tuple[re.Pattern[str], ...]], ...] = (
    (
        CommandIntent.HELP,
        (
            _full(r"помощь|справка|помоги|подскажи"),
            _full(r"(?:покажи|скажи|перечисли|подскажи)(?:\s+мне)?\s+(?:доступные\s+)?команды"),
            _full(r"(?:расскажи|объясни|скажи)(?:\s+мне)?\s+что\s+ты\s+умеешь"),
            _full(r"что\s+(?:ты\s+)?умеешь|какие\s+(?:есть\s+)?команды"),
            _full(r"как\s+(?:тобой|этим\s+навыком)\s+пользоваться"),
            _full(r"что\s+(?:здесь|тут)\s+можно\s+(?:делать|сделать)"),
        ),
    ),
    (
        CommandIntent.RESULT,
        (
            _full(r"готово|готов\s+ли\s+ответ|ответ\s+готов"),
            _full(r"(?:покажи|скажи|прочитай|дай)(?:\s+мне)?\s+(?:готовый\s+)?(?:ответ|результат)"),
            _full(r"(?:проверь|проверить)(?:\s+(?:мой|мою|последний|последнюю|текущий|текущую))?\s+(?:результат|ответ|запрос|задачу|готовность)"),
            _full(r"(?:что|как)\s+(?:там\s+)?(?:с\s+)?(?:моим\s+|последним\s+|текущим\s+)?(?:ответом|результатом|запросом|задачей)"),
            _full(r"(?:получи|получить|забери|забрать)\s+(?:готовый\s+)?(?:ответ|результат)"),
        ),
    ),
    (
        CommandIntent.CANCEL,
        (
            _full(r"отмена|не\s+надо|(?:я\s+)?передумал(?:а)?"),
            _full(r"(?:отмени|останови|прерви|отменить|остановить|прервать)(?:\s+мой|\s+последний|\s+текущий)?(?:\s+(?:запрос|задачу|выполнение|ответ))?"),
            _full(r"забудь\s+(?:мой\s+|последний\s+|текущий\s+)?(?:запрос|задачу)"),
        ),
    ),
    (
        CommandIntent.NEW_DIALOG,
        (
            _full(r"(?:новый|новая|новое)\s+(?:диалог|разговор|беседа|контекст|обсуждение)"),
            _full(r"(?:начни|начать|открой|открыть)(?:\s+новый|\s+новую|\s+новое)?\s+(?:диалог|разговор|беседу|обсуждение)"),
            _full(r"давай\s+(?:начнем|начать)(?:\s+новый|\s+новую)?(?:\s+(?:диалог|разговор|беседу))?"),
            _full(r"(?:начни|начнем|давай\s+начнем)\s+(?:сначала|с\s+начала|заново)"),
            _full(r"(?:сбрось|очисти|забудь)(?:\s+текущий|\s+наш|\s+этот)?\s+(?:контекст|историю|диалог|разговор|беседу)"),
        ),
    ),
    (
        CommandIntent.EXIT,
        (
            _full(r"выход|выйди|хватит|стоп|пока|до\s+свидания"),
            _full(r"(?:закрой|закрыть|выключи|выключить)\s+(?:этот\s+)?навык"),
            _full(r"(?:заверши|завершить|закончи|закончить|прекрати|прекратить)(?:\s+наш|\s+этот)?(?:\s+(?:диалог|разговор|беседу|работу|общение))?"),
            _full(r"(?:можешь\s+)?(?:выйти|закончить|завершить)\s+(?:из\s+навыка|разговор|диалог|беседу)"),
        ),
    ),
)


def normalize_command(command: str) -> str:
    command = command.casefold().replace("ё", "е")
    command = re.sub(r"[^\w\s-]", " ", command, flags=re.UNICODE)
    command = command.replace("-", " ")
    return " ".join(command.split())


def detect_command_intent(command: str) -> CommandIntent | None:
    normalized = normalize_command(command)
    if not normalized:
        return None
    for intent, patterns in _PATTERNS:
        if any(pattern.fullmatch(normalized) for pattern in patterns):
            return intent
    return None
