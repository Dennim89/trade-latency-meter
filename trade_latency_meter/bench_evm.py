"""Offline benchmark: build and sign an EIP-1559 (type 2) transaction. Sends nothing.

Steps are timed separately: RLP encoding of the unsigned payload, Keccak-256 of the typed
payload, and the secp256k1 signature. The key is fresh from os.urandom and lives in memory only.
The recipient, calldata and values are random bytes with no meaning on any chain.
"""
from __future__ import annotations

import os
import random
import time

from . import stats


class Unavailable(RuntimeError):
    pass


def _imports():
    try:
        import rlp
        from eth_hash.auto import keccak
        from eth_keys import keys
    except ImportError:
        raise Unavailable(
            "tlm bench evm needs rlp, eth-keys and eth-hash: pip install 'trade-latency-meter[evm]'"
        ) from None
    return rlp, keccak, keys


def available() -> bool:
    try:
        _imports()
    except Unavailable:
        return False
    return True


def backend_name() -> str:
    _, _, keys = _imports()
    return type(keys.backend).__name__


def make_fields(chain_id: int, rng: random.Random) -> list:
    rand_bytes = lambda k: bytes(rng.getrandbits(8) for _ in range(k))  # noqa: E731
    return [
        chain_id,
        rng.getrandbits(16),  # nonce
        1,  # max priority fee per gas (placeholder, shape only)
        rng.getrandbits(32),  # max fee per gas
        250_000,  # gas limit
        rand_bytes(20),  # recipient: random bytes, not an address anyone controls
        0,  # value
        rand_bytes(68),  # calldata: 4-byte selector + two words
        [],  # access list
    ]


def sign_once(fields: list, key) -> bytes:
    """Encode, hash and sign once. Returns the raw signed transaction (used by tests)."""
    rlp, keccak, _ = _imports()
    payload = b"\x02" + rlp.encode(fields)
    sig = key.sign_msg_hash(keccak(payload))
    return b"\x02" + rlp.encode(fields + [sig.v, sig.r, sig.s])


def new_key():
    _, _, keys = _imports()
    return keys.PrivateKey(os.urandom(32))


def run(n: int = 20000, chain_id: int = 1, seed: int = 1, warmup: int = 50, clock=time.perf_counter_ns) -> dict:
    rlp, keccak, keys = _imports()
    rng = random.Random(seed)
    key = new_key()
    fields = make_fields(chain_id, rng)
    enc_ns, hash_ns, sign_ns = [], [], []
    for i in range(warmup + n):  # the first `warmup` rounds are timed but not recorded
        t0 = clock()
        payload = b"\x02" + rlp.encode(fields)
        t1 = clock()
        digest = keccak(payload)
        t2 = clock()
        key.sign_msg_hash(digest)
        t3 = clock()
        if i < warmup:
            continue
        enc_ns.append(t1 - t0)
        hash_ns.append(t2 - t1)
        sign_ns.append(t3 - t2)
    total = [a + b + c for a, b, c in zip(enc_ns, hash_ns, sign_ns)]
    return {
        "bench": "evm",
        "n": n,
        "chain_id": chain_id,
        "secp256k1_backend": backend_name(),
        "stages": {
            "rlp_encode": stats.summarize(enc_ns),
            "keccak": stats.summarize(hash_ns),
            "sign": stats.summarize(sign_ns),
            "total": stats.summarize(total),
        },
    }
