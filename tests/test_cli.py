import json
import socket
import subprocess
import sys

import pytest

from trade_latency_meter import bench_evm, bench_solana, cli, demo, report

needs_solders = pytest.mark.skipif(not bench_solana.available(), reason="solders not installed")
needs_evm = pytest.mark.skipif(not bench_evm.available(), reason="rlp/eth-keys/eth-hash not installed")


def test_network_is_blocked():
    s = socket.socket()
    try:
        with pytest.raises(AssertionError):
            s.connect(("192.0.2.1", 443))  # off the machine; loopback stays allowed for socketpair()
    finally:
        s.close()


def test_demo_end_to_end_and_report_roundtrip(tmp_path, capsys):
    out = tmp_path / "demo.jsonl"
    meter = demo.run(n=50, seed=3, out_path=str(out))
    recs = list(meter.records())
    assert len(recs) == 50
    assert [s for s, _ in recs[0]["stages"]] == ["parsed", "decided", "built", "signed", "sent"]
    assert all("age_ns" in r for r in recs)
    assert cli.main(["report", str(out)]) == 0
    text = capsys.readouterr().out
    assert "end-to-end" in text and "events: 50" in text
    assert cli.main(["report", str(out), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["events"] == 50


def test_demo_command_prints_overhead(capsys):
    assert cli.main(["demo", "--n", "30", "--no-hist"]) == 0
    text = capsys.readouterr().out
    assert "meter overhead:" in text and "histogram" not in text
    assert cli.main(["demo", "--n", "30", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["overhead"]["per_call_ns"] > 0


def test_report_errors(tmp_path, capsys):
    assert cli.main(["report", str(tmp_path / "missing.jsonl")]) == 2
    bad = tmp_path / "bad.jsonl"
    bad.write_text("nope\n")
    assert cli.main(["report", str(bad)]) == 2
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    assert cli.main(["report", str(empty)]) == 2
    assert "tlm:" in capsys.readouterr().err


def test_invalid_n_rejected(capsys):
    assert cli.main(["bench", "evm", "--n", "0"]) == 2


@needs_solders
def test_bench_solana_tiny(capsys):
    assert cli.main(["bench", "solana", "--n", "20", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n"] == 20 and set(out["stages"]) == {"build", "sign", "build+sign"}
    assert out["stages"]["sign"]["count"] == 20
    assert 200 < out["tx_bytes"] < 1232  # fits a Solana packet


@needs_solders
def test_solana_tx_has_valid_signature_shape():
    res = bench_solana.run(n=2, seed=5)
    assert res["tx_bytes"] > 64  # at least one 64-byte signature plus message


@needs_evm
def test_bench_evm_tiny(capsys):
    assert cli.main(["bench", "evm", "--n", "20", "--chain-id", "5", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["chain_id"] == 5
    assert set(out["stages"]) == {"rlp_encode", "keccak", "sign", "total"}
    cli.main(["bench", "evm", "--n", "5"])
    assert "fresh in-memory key" in capsys.readouterr().out


@needs_evm
def test_evm_signed_tx_recovers_with_eth_account():
    import random

    acct = pytest.importorskip("eth_account")
    key = bench_evm.new_key()
    fields = bench_evm.make_fields(1, random.Random(4))
    raw = bench_evm.sign_once(fields, key)
    assert acct.Account.recover_transaction(raw) == key.public_key.to_checksum_address()


def test_bench_degrades_cleanly_without_library(monkeypatch, capsys):
    import builtins

    real = builtins.__import__

    def fake(name, *a, **k):
        if name.split(".")[0] in {"solders", "rlp", "eth_keys", "eth_hash"}:
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    assert cli.main(["bench", "solana", "--n", "2"]) == 3
    assert cli.main(["bench", "evm", "--n", "2"]) == 3
    err = capsys.readouterr().err
    assert "pip install" in err and "unavailable" in err


def test_python_dash_m_help():
    r = subprocess.run([sys.executable, "-m", "trade_latency_meter", "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "tlm" in r.stdout
