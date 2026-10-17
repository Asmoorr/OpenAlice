import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts" / "OpenAlice.Testing.psm1"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def _quote(value: Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_cleanup_rejects_path_outside_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    command = (
        f"Import-Module {_quote(MODULE)} -Force; "
        f"Remove-TestWorkspace -RepositoryRoot {_quote(repository)} "
        f"-CandidatePath {_quote(outside)}"
    )

    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert marker.read_text(encoding="utf-8") == "keep"


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_cleanup_removes_only_exact_test_workspace(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    workspace = repository / ".test-tmp"
    workspace.mkdir(parents=True)
    (workspace / "temporary.txt").write_text("temporary", encoding="utf-8")
    command = (
        f"Import-Module {_quote(MODULE)} -Force; "
        f"Remove-TestWorkspace -RepositoryRoot {_quote(repository)} "
        f"-CandidatePath {_quote(workspace)}"
    )

    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not workspace.exists()
