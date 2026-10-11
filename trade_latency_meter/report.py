"""Turn recorded JSONL timings into a text or JSON report."""
from __future__ import annotations

import json
from typing import Iterable

from . import stats
from .sysinfo import collect, header_lines

E2E = "end-to-end"
AGE = "event age"


class ReportError(ValueError):
    pass


def load(lines: Iterable[str]) -> list[dict]:
    recs = []
    for no, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if not isinstance(rec["stages"], list) or not isinstance(rec["total_ns"], int):
                raise TypeError
            for name, dur in rec["stages"]:
                if not isinstance(name, str) or not isinstance(dur, int):
                    raise TypeError
        except (ValueError, KeyError, TypeError):
            raise ReportError(f"line {no}: not a timing record") from None
        recs.append(rec)
    return recs


def collect_samples(recs: list[dict]) -> dict[str, list[int]]:
    """Samples per stage in first-seen order, then end-to-end, then event age if present."""
    out: dict[str, list[int]] = {}
    for r in recs:
        for name, dur in r["stages"]:
            out.setdefault(name, []).append(dur)
    out[E2E] = [r["total_ns"] for r in recs]
    ages = [r["age_ns"] for r in recs if r.get("age_ns") is not None]
    if ages:
        out[AGE] = ages
    return out


def build(recs: list[dict], info: dict | None = None) -> dict:
    samples = collect_samples(recs)
    return {
        "system": info or collect(),
        "events": len(recs),
        "unit": "ns",
        "stages": {name: stats.summarize(v) for name, v in samples.items()},
        "_samples": samples,
    }


def render_text(rep: dict, bins: int = 10, histograms: bool = True) -> str:
    out = list(header_lines(rep["system"]))
    out.append(f"events: {rep['events']}")
    out.append("")
    cols = ["count", "p50", "p90", "p99", "p99.9", "max"]
    name_w = max(len(n) for n in rep["stages"])
    out.append(f"{'stage':<{name_w}}  " + "  ".join(f"{c:>9}" for c in cols))
    for name, s in rep["stages"].items():
        cells = [f"{s['count']:>9}"] + [f"{stats.format_ns(s[c]):>9}" for c in cols[1:]]
        out.append(f"{name:<{name_w}}  " + "  ".join(cells))
    small = [n for n, s in rep["stages"].items() if s["count"] < 1000]
    if small:
        out.append("")
        out.append("note: with fewer than 1000 samples p99.9 is interpolated close to max.")
    if AGE in rep["stages"]:
        out.append("note: event age compares the local wall clock with a remote timestamp; it is only")
        out.append("      as accurate as the clock sync between the two machines (can be negative).")
    if histograms:
        for name, v in rep["_samples"].items():
            out.append("")
            out.append(f"{name} histogram (log-spaced bins):")
            out.extend(stats.histogram(v, bins=bins))
    return "\n".join(out)


def render_json(rep: dict) -> str:
    clean = {k: v for k, v in rep.items() if not k.startswith("_")}
    return json.dumps(clean, indent=2)
