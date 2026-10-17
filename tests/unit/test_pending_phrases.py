from openalice.pending_phrases import PendingPhraseProvider


def test_pending_phrase_provider_uses_only_configured_phrases() -> None:
    phrases = ("Первая фраза", "Вторая фраза")
    provider = PendingPhraseProvider(phrases)

    assert {provider.choose() for _ in range(20)} <= set(phrases)
