import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]


def test_documentation_local_file_links_exist() -> None:
    for path in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if "://" in target:
                continue
            filename, _, fragment = target.partition("#")
            destination = path.parent / unquote(filename) if filename else path
            assert destination.exists(), f"{path.name}: {target}"
            if fragment:
                headings = re.findall(
                    r"^#{1,6}\s+(.+)$", destination.read_text(encoding="utf-8"), re.MULTILINE
                )
                anchors = {
                    re.sub(r"[^\w\- ]", "", heading.casefold()).replace(" ", "-")
                    for heading in headings
                }
                assert unquote(fragment) in anchors, f"{path.name}: invalid anchor {target}"


def test_configuration_documents_every_environment_setting() -> None:
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    names = set(re.findall(r"^([A-Z][A-Z_]+)=", template, re.MULTILINE))
    documented = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
    assert names <= set(re.findall(r"`([A-Z][A-Z_]+)`", documented))
