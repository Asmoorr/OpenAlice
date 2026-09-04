import random
from collections.abc import Sequence


class PendingPhraseProvider:
    """Selects Alice's reply while an OpenClaw answer is still pending."""

    def __init__(self, phrases: Sequence[str]) -> None:
        if not phrases:
            raise ValueError("At least one pending phrase is required")
        self._phrases = tuple(phrases)

    def choose(self) -> str:
        return random.choice(self._phrases)
