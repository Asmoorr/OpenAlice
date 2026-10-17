from types import SimpleNamespace

from openalice import glagol_setup
from openalice.infrastructure.glagol import GlagolDevice


async def test_discovery_prints_configuration(monkeypatch, capsys) -> None:
    async def discover(self):
        return (GlagolDevice("device", "station", "192.168.1.2", 1961),)

    monkeypatch.setattr(glagol_setup.MdnsDeviceResolver, "discover_all", discover)
    await glagol_setup._discover(0.01)
    assert "GLAGOL_DEVICE_ID=device" in capsys.readouterr().out


async def test_empty_discovery_explains_network_requirement(monkeypatch, capsys) -> None:
    async def discover(self):
        return ()

    monkeypatch.setattr(glagol_setup.MdnsDeviceResolver, "discover_all", discover)
    await glagol_setup._discover(0.01)
    assert "Станции не найдены" in capsys.readouterr().out


async def test_login_saves_credentials_and_prints_device_code(
    monkeypatch, tmp_path, capsys
) -> None:
    saved = []

    class Passport:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def login_device_code(self, on_code):
            on_code(SimpleNamespace(verification_url="https://example.test", user_code="1234"))
            return "credentials"

    async def save(self, credentials):
        saved.append(credentials)

    monkeypatch.setattr(glagol_setup.PassportClient, "create", lambda: Passport())
    monkeypatch.setattr(glagol_setup.JsonCredentialStore, "save", save)
    await glagol_setup._login(tmp_path / "credentials.json")
    assert saved == ["credentials"]
    assert "1234" in capsys.readouterr().out


async def test_main_routes_discovery_and_login(monkeypatch) -> None:
    calls = []

    async def discover(timeout):
        calls.append(timeout)

    async def login(path):
        calls.append(path)

    monkeypatch.setattr(glagol_setup, "_discover", discover)
    monkeypatch.setattr(glagol_setup, "_login", login)
    monkeypatch.setattr("sys.argv", ["setup", "discover", "--timeout", "0.1"])
    await glagol_setup._main()
    monkeypatch.setattr("sys.argv", ["setup", "--credentials", "local.json", "login"])
    await glagol_setup._main()
    assert calls[0] == 0.1
    assert str(calls[1]) == "local.json"
