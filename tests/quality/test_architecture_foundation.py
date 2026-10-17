import ast
from pathlib import Path

import pytest

from openalice.domain import ConversationKey, Job, JobStatus, Notification, Reply

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_IMPORTS = {
    "aiohttp",
    "fastapi",
    "httpx",
    "pydantic",
    "pydantic_settings",
    "sqlite3",
    "ya_passport_auth",
    "zeroconf",
}


def test_domain_value_objects_and_transitions() -> None:
    conversation = ConversationKey("identity-hash", 3)
    pending = Job.pending()

    assert str(conversation) == "openalice:yandex-user:identity-hash:v3"
    assert Reply("Ответ").end_session is False
    assert pending.complete("Готово") == Job(JobStatus.DONE, response="Готово")
    assert pending.fail("Ошибка") == Job(JobStatus.FAILED, error="Ошибка")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Reply(""),
        lambda: ConversationKey("", 0),
        lambda: ConversationKey("hash", -1),
        lambda: Job(JobStatus.PENDING, response="unexpected"),
        lambda: Job(JobStatus.PENDING, error="unexpected"),
        lambda: Job(JobStatus.DONE, error="unexpected"),
        lambda: Job(JobStatus.FAILED, response="unexpected"),
        lambda: Job(JobStatus.DONE).complete("again"),
        lambda: Job(JobStatus.FAILED).fail("again"),
        lambda: Notification("", "conversation", "kind", "channel", "target", "text"),
        lambda: Notification("event", "conversation", "kind", "channel", "target", "text", -1),
    ],
)
def test_domain_rejects_invalid_state(factory) -> None:
    with pytest.raises(ValueError):
        factory()


def test_internal_layers_do_not_import_frameworks_or_infrastructure() -> None:
    violations: list[str] = []
    for layer in (ROOT / "openalice" / "domain", ROOT / "openalice" / "application"):
        for path in layer.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imported: list[str] = []
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = [node.module]
                for module in imported:
                    root = module.split(".", maxsplit=1)[0]
                    if root in FORBIDDEN_IMPORTS or module.startswith(
                        ("openalice.infrastructure", "openalice.presentation")
                    ):
                        violations.append(f"{path.relative_to(ROOT)} imports {module}")
                    if module.startswith("openalice."):
                        allowed = ("openalice.domain",)
                        if layer.name == "application":
                            allowed += ("openalice.application",)
                        if not module.startswith(allowed):
                            violations.append(
                                f"{path.relative_to(ROOT)} crosses boundary: {module}"
                            )

    assert violations == []


def test_outer_adapters_do_not_depend_on_each_other():
    for name, forbidden in (
        ("infrastructure", ("openalice.presentation", "openalice.bootstrap", "openalice.app")),
        ("presentation", ("openalice.infrastructure", "openalice.bootstrap")),
    ):
        for path in (ROOT / "openalice" / name).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not any(
                        node.module == prefix or node.module.startswith(prefix + ".")
                        for prefix in forbidden
                    ), f"{path}: {node.module}"
