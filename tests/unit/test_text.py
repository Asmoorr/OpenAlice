import pytest

from openalice.domain.text import shorten_for_alice, speech_friendly


def test_markdown_is_converted_to_speech() -> None:
    assert (
        speech_friendly("# Заголовок\n- **Ответ** [ссылка](https://example.com)")
        == "Заголовок\nОтвет ссылка"
    )


@pytest.mark.parametrize("limit", [100, 200, 900, 1024])
def test_long_answer_respects_limit_and_word_boundary(limit: int) -> None:
    result = shorten_for_alice("Длинный полезный ответ " * 100, limit)
    assert len(result) <= limit
    assert result.endswith("…")


def test_sentence_boundary_is_preferred() -> None:
    sentence = "а" * 90 + ". "
    assert shorten_for_alice(sentence + "б" * 100, 150) == sentence.strip()


def test_unbroken_word_is_truncated() -> None:
    assert shorten_for_alice("а" * 200, 100) == "а" * 99 + "…"
