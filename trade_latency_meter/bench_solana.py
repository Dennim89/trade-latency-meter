"""Offline benchmark: build and sign a v0 Solana transaction. Sends nothing.

The transaction is shaped like a typical swap: two compute-budget instructions, a few accounts
and one program instruction with 24 bytes of data. The program id, accounts and blockhash are
random bytes with no meaning on any chain. The signing key is a fresh in-memory keypair.
"""
from __future__ import annotations

import random
import time

from . import stats


class Unavailable(RuntimeError):
    pass


def available() -> bool:
    try:
        import solders  # noqa: F401
    except ImportError:
        return False
    return True


def run(n: int = 20000, seed: int = 1, warmup: int = 50, clock=time.perf_counter_ns) -> dict:
    try:
        from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
        from solders.hash import Hash
        from solders.instruction import AccountMeta, Instruction
        from solders.keypair import Keypair
        from solders.message import MessageV0
        from solders.pubkey import Pubkey
        from solders.transaction import VersionedTransaction
    except ImportError:
        raise Unavailable(
            "tlm bench solana needs the 'solders' package: pip install 'trade-latency-meter[solana]'"
        ) from None

    rng = random.Random(seed)
    rand_bytes = lambda k: bytes(rng.getrandbits(8) for _ in range(k))  # noqa: E731
    payer = Keypair()  # fresh random key, lives in memory only
    program = Pubkey.from_bytes(rand_bytes(32))
    others = [Pubkey.from_bytes(rand_bytes(32)) for _ in range(5)]
    blockhash = Hash(rand_bytes(32))
    metas = [AccountMeta(payer.pubkey(), True, True)] + [
        AccountMeta(k, False, i < 3) for i, k in enumerate(others)
    ]
    data = rand_bytes(24)

    build_ns, sign_ns = [], []
    size = 0
    for i in range(warmup + n):  # the first `warmup` rounds are timed but not recorded
        t0 = clock()
        ixs = [
            set_compute_unit_limit(200_000),  # placeholder values: only the shape matters here
            set_compute_unit_price(1),
            Instruction(program, data, metas),
        ]
        msg = MessageV0.try_compile(payer.pubkey(), ixs, [], blockhash)
        t1 = clock()
        tx = VersionedTransaction(msg, [payer])
        t2 = clock()
        size = len(bytes(tx))
        if i < warmup:
            continue
        build_ns.append(t1 - t0)
        sign_ns.append(t2 - t1)
    return {
        "bench": "solana",
        "n": n,
        "tx_bytes": size,
        "stages": {
            "build": stats.summarize(build_ns),
            "sign": stats.summarize(sign_ns),
            "build+sign": stats.summarize([a + b for a, b in zip(build_ns, sign_ns)]),
        },
    }
