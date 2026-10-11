"""Command line: tlm report | bench | demo | overhead."""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import bench_evm, bench_solana, report, stats
from .meter import measure_overhead
from .sysinfo import collect, header_lines


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _overhead_line(o: dict) -> str:
    return (
        f"meter overhead: {o['per_call_ns']:.0f} ns per begin/mark/end call "
        f"(bare clock read: {o['clock_ns']:.0f} ns; {o['marks_per_event']} marks per event)"
    )


def _print_bench(res: dict, as_json: bool) -> None:
    info = collect()
    if as_json:
        print(json.dumps({"system": info, **res}, indent=2))
        return
    print("\n".join(header_lines(info)))
    extra = f", chain id {res['chain_id']}, backend {res['secp256k1_backend']}" if res["bench"] == "evm" else ""
    extra += f", {res['tx_bytes']} bytes" if "tx_bytes" in res else ""
    print(f"bench {res['bench']}: n={res['n']}{extra}; fresh in-memory key; nothing is sent")
    print()
    cols = ["min", "p50", "p90", "p99", "p99.9", "max"]
    w = max(len(k) for k in res["stages"])
    print(f"{'step':<{w}}  " + "  ".join(f"{c:>9}" for c in cols))
    for name, s in res["stages"].items():
        print(f"{name:<{w}}  " + "  ".join(f"{stats.format_ns(s[c]):>9}" for c in cols))
    if res["n"] < 1000:
        print("\nnote: with fewer than 1000 samples p99.9 is interpolated close to max.")


def cmd_report(a: argparse.Namespace) -> int:
    try:
        with open(a.file, encoding="utf-8") as f:
            recs = report.load(f)
    except OSError as e:
        print(f"tlm: cannot read {a.file}: {e.strerror}", file=sys.stderr)
        return 2
    except report.ReportError as e:
        print(f"tlm: {a.file}: {e}", file=sys.stderr)
        return 2
    if not recs:
        print(f"tlm: {a.file}: no records", file=sys.stderr)
        return 2
    rep = report.build(recs)
    print(report.render_json(rep) if a.json else report.render_text(rep, bins=a.bins))
    return 0


def cmd_bench(a: argparse.Namespace) -> int:
    try:
        if a.target == "solana":
            res = bench_solana.run(n=a.n, seed=a.seed)
        else:
            res = bench_evm.run(n=a.n, chain_id=a.chain_id, seed=a.seed)
    except (bench_solana.Unavailable, bench_evm.Unavailable) as e:
        print(f"tlm: bench unavailable: {e}", file=sys.stderr)
        return 3
    _print_bench(res, a.json)
    return 0


def cmd_demo(a: argparse.Namespace) -> int:
    from . import demo

    meter = demo.run(n=a.n, seed=a.seed, out_path=a.out)
    rep = report.build(list(meter.records()))
    over = measure_overhead()
    if a.json:
        clean = json.loads(report.render_json(rep))
        clean["overhead"] = over
        print(json.dumps(clean, indent=2))
    else:
        print(report.render_text(rep, bins=a.bins, histograms=not a.no_hist))
        print()
        print(_overhead_line(over))
        print("demo pipeline is synthetic: placeholder decision, HMAC instead of a chain signature,")
        print("local socket pair instead of a network.")
    return 0


def cmd_overhead(a: argparse.Namespace) -> int:
    over = measure_overhead(iterations=a.iterations)
    if a.json:
        print(json.dumps({"system": collect(), **over}, indent=2))
    else:
        print("\n".join(header_lines()))
        print(_overhead_line(over))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tlm", description="Stage stopwatch and offline signing benchmarks. Sends nothing to a network."
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("report", help="summarize a timings JSONL file")
    r.add_argument("file")
    r.add_argument("--json", action="store_true", help="machine-readable output")
    r.add_argument("--bins", type=int, default=10, help="histogram bins (default 10)")
    r.set_defaults(func=cmd_report)

    b = sub.add_parser("bench", help="offline transaction build and sign benchmarks")
    bs = b.add_subparsers(dest="target", required=True)
    for name in ("solana", "evm"):
        s = bs.add_parser(name)
        s.add_argument("--n", type=int, default=_env_int("TLM_BENCH_N", 20000), help="iterations (env TLM_BENCH_N)")
        s.add_argument("--seed", type=int, default=1, help="seed for the fake transaction contents")
        s.add_argument("--json", action="store_true")
        if name == "evm":
            s.add_argument("--chain-id", type=int, default=_env_int("TLM_CHAIN_ID", 1), help="env TLM_CHAIN_ID")
        s.set_defaults(func=cmd_bench)

    d = sub.add_parser("demo", help="run a synthetic pipeline through the meter")
    d.add_argument("--n", type=int, default=_env_int("TLM_DEMO_N", 2000), help="events (env TLM_DEMO_N)")
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--out", help="also write the raw timings to this JSONL file")
    d.add_argument("--bins", type=int, default=8)
    d.add_argument("--no-hist", action="store_true", help="skip histograms")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_demo)

    o = sub.add_parser("overhead", help="measure the cost of the meter itself")
    o.add_argument("--iterations", type=int, default=50000)
    o.add_argument("--json", action="store_true")
    o.set_defaults(func=cmd_overhead)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for attr in ("n", "iterations"):
        if getattr(args, attr, 1) < 1:
            print(f"tlm: --{attr} must be >= 1", file=sys.stderr)
            return 2
    return args.func(args)
