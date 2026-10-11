"""Synthetic pipeline through the meter: event -> parse -> decide -> build -> sign -> write.

Everything here is a stand-in. The "decision" is a parity check on a counter and does not trade.
"Signing" is HMAC-SHA256 with a random in-memory key, not a chain signature. The "send" writes
to one end of a local socket pair; nothing leaves the process.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import socket
import struct
import time

from .meter import Meter


def run(n: int = 2000, seed: int = 7, out_path: str | None = None, clock=time.perf_counter_ns) -> Meter:
    rng = random.Random(seed)
    key = os.urandom(32)
    a, b = socket.socketpair()  # local pair; no connect(), no network
    a.setblocking(False)
    b.setblocking(False)
    meter = Meter(capacity=max(n, 1), clock=clock)
    try:
        for i in range(n):
            # "event": a JSON message with a made-up remote timestamp 1-5 ms in the past
            produced = time.time_ns() - rng.randint(1_000_000, 5_000_000)
            raw = json.dumps({"seq": i, "t": produced, "v": rng.getrandbits(32)}).encode()

            h = meter.begin(i, remote_ts_ns=produced)
            msg = json.loads(raw)
            h.mark("parsed")
            go = msg["seq"] % 2 == 0  # placeholder predicate
            h.mark("decided")
            body = struct.pack("<QQQ", msg["seq"], msg["v"], 0) if go else b""
            h.mark("built")
            sig = hmac.new(key, body, hashlib.sha256).digest()
            h.mark("signed")
            a.send(body + sig)
            h.mark("sent")
            h.end()
            b.recv(65536)  # drain the other end outside the timed region
    finally:
        a.close()
        b.close()
    if out_path:
        meter.flush(out_path, append=False)
    return meter
