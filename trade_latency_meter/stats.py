"""Percentiles, summaries and a text histogram (standard library only)."""
from __future__ import annotations

import math
from typing import Sequence

PERCENTILES = (50, 90, 99, 99.9)


def percentile(sorted_values: Sequence[float], p: float) -> float:
    """Linear interpolation between closest ranks (the same as numpy's default).

    `sorted_values` must be sorted ascending. p is in [0, 100].
    """
    if not sorted_values:
        raise ValueError("no samples")
    if not 0 <= p <= 100:
        raise ValueError("p must be in [0, 100]")
    pos = (len(sorted_values) - 1) * p / 100.0
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(sorted_values[lo])
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def summarize(values: Sequence[float]) -> dict:
    """count, min, p50, p90, p99, p99.9, max, mean for a list of samples."""
    s = sorted(values)
    out = {"count": len(s)}
    if not s:
        return out
    out["min"] = float(s[0])
    for p in PERCENTILES:
        out["p" + format(p, "g")] = round(percentile(s, p), 3)
    out["max"] = float(s[-1])
    out["mean"] = round(sum(s) / len(s), 3)
    return out


def format_ns(ns: float) -> str:
    """Human-readable duration from nanoseconds."""
    a = abs(ns)
    if a < 1_000:
        return f"{ns:.0f} ns"
    if a < 1_000_000:
        return f"{ns / 1_000:.2f} us"
    if a < 1_000_000_000:
        return f"{ns / 1_000_000:.2f} ms"
    return f"{ns / 1_000_000_000:.2f} s"


def histogram(values: Sequence[float], bins: int = 10, width: int = 30) -> list[str]:
    """Text histogram with log-spaced bins (latency is skewed). Returns lines."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if lo <= 0:
        lo = 1.0
    if hi <= lo:
        return [f"  {format_ns(lo):>10}  {'#' * width} {len(values)}"]
    edges = [lo * (hi / lo) ** (i / bins) for i in range(bins + 1)]
    counts = [0] * bins
    for v in values:
        v = max(v, lo)
        idx = min(bins - 1, int(math.log(v / lo) / math.log(hi / lo) * bins))
        counts[idx] += 1
    peak = max(counts)
    lines = []
    for i, c in enumerate(counts):
        bar = "#" * (round(c / peak * width) if c else 0)
        if c and not bar:
            bar = "#"
        lines.append(f"  {format_ns(edges[i]):>10} - {format_ns(edges[i + 1]):>10} |{bar:<{width}} {c}")
    return lines
