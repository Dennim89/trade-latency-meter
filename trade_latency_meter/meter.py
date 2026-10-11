"""Per-event stage timing with a preallocated ring buffer.

Hot path (`begin`, `mark`, `end`) does a clock read and a few list writes. No logging, no I/O,
no locks, no allocation except the small `Handle` object returned by `begin`.

A mark closes a stage: its duration is the time since the previous mark (or since `begin`).
`Handle.stage(name)` is a context manager that times only its own block, so work done between
stages is not attributed to a stage; it still counts in the end-to-end total.

Limits (documented, not hidden):
- A handle must be ended before `capacity` newer events begin, or its slot is reused.
- One handle is meant for one thread. Different threads may use different handles.
- The background flusher reads slots without a lock. If the producer laps it, records are
  counted in `lost` instead of being written.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Callable, Iterator, Optional

MAX_MARKS = 16  # per event; extra marks are counted in `dropped_marks` and ignored


class Handle:
    __slots__ = ("_m", "_slot", "_seq", "_base", "_n", "_last", "_t0", "_ended")

    def __init__(self, meter: "Meter", slot: int, seq: int, t0: int):
        self._m = meter
        self._slot = slot
        self._seq = seq
        self._base = slot * MAX_MARKS
        self._n = 0
        self._t0 = t0
        self._last = t0
        self._ended = False

    def mark(self, name: str) -> None:
        now = self._m._clock()
        n = self._n
        if n < MAX_MARKS:
            i = self._base + n
            self._m._names[i] = name
            self._m._durs[i] = now - self._last
            self._n = n + 1
        else:
            self._m.dropped_marks += 1
        self._last = now

    def stage(self, name: str) -> "_Stage":
        return _Stage(self, name)

    def end(self) -> None:
        m = self._m
        now = m._clock()
        s = self._slot
        m._counts[s] = self._n
        m._totals[s] = now - self._t0
        m._done[s] = self._seq  # publishes the record: readers compare this with the slot's seq
        self._ended = True


class _Stage:
    __slots__ = ("_h", "_name")

    def __init__(self, handle: Handle, name: str):
        self._h = handle
        self._name = name

    def __enter__(self) -> "_Stage":
        self._h._last = self._h._m._clock()
        return self

    def __exit__(self, *exc) -> None:
        self._h.mark(self._name)


class Meter:
    """Ring buffer of per-event stage timings.

    clock:      callable returning integer nanoseconds (default `time.perf_counter_ns`).
    wall_clock: callable returning integer epoch nanoseconds, used only for event age.
    """

    def __init__(
        self,
        capacity: int = 4096,
        clock: Callable[[], int] = time.perf_counter_ns,
        wall_clock: Callable[[], int] = time.time_ns,
    ):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self._clock = clock
        self._wall = wall_clock
        n = capacity * MAX_MARKS
        self._names: list = [None] * n
        self._durs: list = [0] * n
        self._counts = [0] * capacity
        self._totals = [0] * capacity
        self._ids: list = [None] * capacity
        self._ages: list = [None] * capacity
        self._done = [-1] * capacity  # seq of the last finished event in the slot
        self._seq = 0  # number of events begun so far
        self._flushed = 0  # sequence numbers below this were already written
        self.dropped_marks = 0
        self.lost = 0  # records overwritten before they were flushed
        self._current: Optional[Handle] = None
        self._flush_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # ---- recording -------------------------------------------------------------------
    def begin(self, event_id=None, remote_ts_ns: Optional[int] = None) -> Handle:
        """Start timing an event.

        remote_ts_ns: epoch nanoseconds at which the event was produced remotely (exchange or
        chain timestamp). The event age (local wall clock minus this value) is stored separately
        from the in-process stages. It is only as good as the clock sync between the two
        machines; a negative age means the local clock is behind.
        """
        seq = self._seq
        self._seq = seq + 1
        slot = seq % self.capacity
        self._ids[slot] = event_id
        self._ages[slot] = None if remote_ts_ns is None else self._wall() - remote_ts_ns
        self._done[slot] = -1
        h = Handle(self, slot, seq, self._clock())
        self._current = h
        return h

    def stage(self, name: str) -> _Stage:
        """Time a block on the most recently begun event (single-threaded convenience)."""
        if self._current is None:
            raise RuntimeError("meter.stage() needs a begun event; call meter.begin() first")
        return _Stage(self._current, name)

    # ---- reading ---------------------------------------------------------------------
    def _record(self, seq: int) -> Optional[dict]:
        slot = seq % self.capacity
        if self._done[slot] != seq:
            return None
        base = slot * MAX_MARKS
        stages = [[self._names[base + i], self._durs[base + i]] for i in range(self._counts[slot])]
        rec = {"id": self._ids[slot], "stages": stages, "total_ns": self._totals[slot]}
        if self._ages[slot] is not None:
            rec["age_ns"] = self._ages[slot]
        if self._done[slot] != seq:  # overwritten while we copied
            return None
        return rec

    def records(self) -> Iterator[dict]:
        """Finished events still in the buffer, oldest first."""
        for seq in range(max(0, self._seq - self.capacity), self._seq):
            rec = self._record(seq)
            if rec is not None:
                yield rec

    def drain(self) -> list[dict]:
        """Finished events not returned by an earlier drain. Counts overwritten ones in `lost`."""
        with self._flush_lock:
            end = self._seq
            start = self._flushed
            oldest = max(0, end - self.capacity)
            if start < oldest:
                self.lost += oldest - start
                start = oldest
            out = []
            stop = end
            for seq in range(start, end):
                rec = self._record(seq)
                if rec is not None:
                    out.append(rec)
                elif seq < self._seq - self.capacity:
                    self.lost += 1  # lapped by newer events before it could be written
                else:
                    # Not finished yet. Stop here so nothing is skipped; the next drain
                    # picks it up. (An event whose end() is never called blocks the drain
                    # until the ring laps it, then counts as lost.)
                    stop = seq
                    break
            self._flushed = stop
            return out

    def flush(self, path: str, append: bool = True) -> int:
        """Write new finished events to a JSONL file. Returns the number of lines written."""
        recs = self.drain()
        if recs:
            with open(path, "a" if append else "w", encoding="utf-8") as f:
                for r in recs:
                    f.write(json.dumps(r, separators=(",", ":")) + "\n")
        return len(recs)

    def start_flusher(self, path: str, interval_s: float = 0.5) -> None:
        """Flush to `path` from a daemon thread every `interval_s` seconds."""
        if self._thread is not None:
            raise RuntimeError("flusher already running")
        self._stop.clear()

        def run() -> None:
            while not self._stop.wait(interval_s):
                self.flush(path)

        self._thread = threading.Thread(target=run, name="tlm-flusher", daemon=True)
        self._thread.start()

    def stop_flusher(self, path: Optional[str] = None) -> None:
        """Stop the thread; with `path`, do a final flush."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        if path is not None:
            self.flush(path)


def measure_overhead(iterations: int = 20000, marks_per_event: int = 4) -> dict:
    """Cost of the meter itself on this machine, in nanoseconds per call.

    Runs on a scratch Meter with the real clock. `clock_ns` is the cost of one bare
    `perf_counter_ns()` call, which is the floor for any mark.
    """
    clock = time.perf_counter_ns
    t = clock()
    for _ in range(iterations):
        clock()
    clock_ns = (clock() - t) / iterations

    m = Meter(capacity=256)
    events = max(1, iterations // marks_per_event)
    t = clock()
    for i in range(events):
        h = m.begin(i)
        for _ in range(marks_per_event):
            h.mark("x")
        h.end()
    elapsed = clock() - t
    # begin + end each cost about one mark; spread everything over the total number of calls.
    calls = events * (marks_per_event + 2)
    return {
        "clock_ns": clock_ns,
        "per_call_ns": elapsed / calls,
        "per_event_ns": elapsed / events,
        "marks_per_event": marks_per_event,
        "events": events,
    }
