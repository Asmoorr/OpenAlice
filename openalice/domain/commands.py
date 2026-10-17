from enum import StrEnum


class CommandIntent(StrEnum):
    HELP = "help"
    RESULT = "result"
    CANCEL = "cancel"
    NEW_DIALOG = "new_dialog"
    EXIT = "exit"
