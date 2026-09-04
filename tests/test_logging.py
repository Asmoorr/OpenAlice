import logging

from openalice.logging import LogType, get_logger


def test_logger_marks_log_type(caplog) -> None:
    logger = get_logger("openalice.test")

    with caplog.at_level(logging.INFO, logger="openalice.test"):
        logger.info(LogType.TECH, "stage=test status=ok")
        logger.info(LogType.USER, "event=test_completed")

    assert [record.message for record in caplog.records] == [
        "[Тех] stage=test status=ok",
        "[Пол] event=test_completed",
    ]
