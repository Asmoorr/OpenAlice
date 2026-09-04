import logging
from enum import StrEnum
from typing import Any


class LogType(StrEnum):
    TECH = "Тех"
    USER = "Пол"


class AppLogger:
    """Logger wrapper that marks technical and user-facing application events."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def debug(self, log_type: LogType, message: str, *args: Any, **kwargs: Any) -> None:
        self._logger.debug(self._message(log_type, message), *args, **kwargs)

    def info(self, log_type: LogType, message: str, *args: Any, **kwargs: Any) -> None:
        self._logger.info(self._message(log_type, message), *args, **kwargs)

    def warning(self, log_type: LogType, message: str, *args: Any, **kwargs: Any) -> None:
        self._logger.warning(self._message(log_type, message), *args, **kwargs)

    def error(self, log_type: LogType, message: str, *args: Any, **kwargs: Any) -> None:
        self._logger.error(self._message(log_type, message), *args, **kwargs)

    def exception(self, log_type: LogType, message: str, *args: Any, **kwargs: Any) -> None:
        self._logger.exception(self._message(log_type, message), *args, **kwargs)

    @staticmethod
    def _message(log_type: LogType, message: str) -> str:
        return "[%s] %s" % (log_type.value, message)


def get_logger(name: str) -> AppLogger:
    return AppLogger(logging.getLogger(name))
