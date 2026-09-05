from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from ya_passport_auth import PassportClient

from openalice.glagol import JsonCredentialStore, MdnsDeviceResolver


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Настройка прямого подключения к Яндекс Станции")
    parser.add_argument(
        "--credentials",
        type=Path,
        default=Path("./data/glagol_credentials.json"),
        help="файл для локального хранения токенов",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("login", help="войти в Яндекс по коду устройства")
    discover = subcommands.add_parser("discover", help="найти Станции в локальной сети")
    discover.add_argument("--timeout", type=float, default=5.0)
    return parser


async def _login(path: Path) -> None:
    def show_code(session: object) -> None:
        print(f"Откройте {session.verification_url} и введите код: {session.user_code}")

    async with PassportClient.create() as passport:
        credentials = await passport.login_device_code(on_code=show_code)
    await JsonCredentialStore(path).save(credentials)
    print(f"Авторизация сохранена локально: {path}")


async def _discover(timeout: float) -> None:
    devices = await MdnsDeviceResolver(timeout).discover_all()
    if not devices:
        print("Станции не найдены. Проверьте, что компьютер и колонка находятся в одной сети.")
        return
    for device in devices:
        print(
            f"GLAGOL_DEVICE_ID={device.device_id}\n"
            f"GLAGOL_PLATFORM={device.platform}\n"
            f"GLAGOL_HOST={device.host}\n"
            f"GLAGOL_PORT={device.port}\n"
        )


async def _main() -> None:
    args = _parser().parse_args()
    if args.command == "login":
        await _login(args.credentials)
    else:
        await _discover(args.timeout)


if __name__ == "__main__":
    asyncio.run(_main())
