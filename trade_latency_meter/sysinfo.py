"""Where the numbers came from: CPU, OS, Python and library versions."""
from __future__ import annotations

import os
import platform
from importlib import metadata


def cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine() or "unknown"


def lib_versions(names=("solders", "eth-keys", "eth-hash", "rlp", "coincurve", "eth-account")) -> dict:
    out = {}
    for n in names:
        try:
            out[n] = metadata.version(n)
        except metadata.PackageNotFoundError:
            pass
    return out


def collect() -> dict:
    try:
        tlm = metadata.version("trade-latency-meter")
    except metadata.PackageNotFoundError:
        from . import __version__ as tlm
    return {
        "cpu": cpu_model(),
        "cores": os.cpu_count(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "tlm": tlm,
        "libs": lib_versions(),
    }


def header_lines(info: dict | None = None) -> list[str]:
    info = info or collect()
    libs = ", ".join(f"{k} {v}" for k, v in info["libs"].items()) or "none of the optional libraries"
    return [
        f"cpu:    {info['cpu']} ({info['cores']} cores)",
        f"os:     {info['os']}",
        f"python: {info['implementation']} {info['python']}",
        f"libs:   tlm {info['tlm']}; {libs}",
    ]
