import socket
import sqlite3

import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def forbid_external_io(monkeypatch):
    # The async fixture runs after Windows has initialized the loop socketpair.
    def denied(*args, **kwargs):
        raise AssertionError("Unit tests must use in-memory ports")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(sqlite3, "connect", denied)
