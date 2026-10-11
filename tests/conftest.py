import socket

import pytest


LOOPBACK = {"127.0.0.1", "::1"}
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Any connection that would leave the machine fails the test.

    Loopback stays allowed: on Windows socket.socketpair() is built from a 127.0.0.1 connection.
    """

    def host_of(address):
        return address[0] if isinstance(address, tuple) else address

    def guarded_connect(self, address):
        if host_of(address) not in LOOPBACK:
            raise AssertionError("network access attempted in a test")
        return _real_connect(self, address)

    def guarded_connect_ex(self, address):
        if host_of(address) not in LOOPBACK:
            raise AssertionError("network access attempted in a test")
        return _real_connect_ex(self, address)

    def refuse(*a, **k):
        raise AssertionError("network access attempted in a test")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "create_connection", refuse)


class FakeClock:
    """Injectable clock: each call returns the next scripted value, or advances by `step`."""

    def __init__(self, values=None, step=100):
        self.values = list(values or [])
        self.t = 0
        self.step = step

    def __call__(self):
        if self.values:
            self.t = self.values.pop(0)
        else:
            self.t += self.step
        return self.t
