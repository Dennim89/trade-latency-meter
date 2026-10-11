import json

from conftest import FakeClock
from trade_latency_meter import Meter, measure_overhead


def test_stage_order_and_durations():
    # begin@0, parsed@10, decided@25, signed@45, end@50
    m = Meter(clock=FakeClock([0, 10, 25, 45, 50]))
    h = m.begin("e1")
    h.mark("parsed")
    h.mark("decided")
    h.mark("signed")
    h.end()
    (rec,) = list(m.records())
    assert rec["id"] == "e1"
    assert rec["stages"] == [["parsed", 10], ["decided", 15], ["signed", 20]]
    assert rec["total_ns"] == 50


def test_stage_context_manager_times_only_its_block():
    # begin@0, enter@100, exit@130, end@200
    m = Meter(clock=FakeClock([0, 100, 130, 200]))
    m.begin(1)
    with m.stage("sign"):
        pass
    m._current.end()
    (rec,) = list(m.records())
    assert rec["stages"] == [["sign", 30]]
    assert rec["total_ns"] == 200


def test_handle_stage_and_missing_begin():
    import pytest

    m = Meter(clock=FakeClock(step=10))
    with pytest.raises(RuntimeError):
        m.stage("x")
    h = m.begin(1)
    with h.stage("a"):
        pass
    h.end()
    assert list(m.records())[0]["stages"][0][0] == "a"


def test_ring_buffer_wraps_and_keeps_newest():
    m = Meter(capacity=3, clock=FakeClock(step=1))
    for i in range(7):
        h = m.begin(i)
        h.mark("a")
        h.end()
    assert [r["id"] for r in m.records()] == [4, 5, 6]


def test_drain_counts_lost_and_is_incremental():
    m = Meter(capacity=3, clock=FakeClock(step=1))
    for i in range(5):
        m.begin(i).end()
    got = m.drain()
    assert [r["id"] for r in got] == [2, 3, 4]
    assert m.lost == 2
    assert m.drain() == []
    m.begin(5).end()
    assert [r["id"] for r in m.drain()] == [5]


def test_drain_waits_for_unfinished_event():
    m = Meter(capacity=8, clock=FakeClock(step=1))
    a = m.begin("a")
    b = m.begin("b")
    b.end()
    assert m.drain() == []  # "a" is not finished, so nothing after it is skipped
    a.end()
    assert [r["id"] for r in m.drain()] == ["a", "b"]


def test_extra_marks_are_dropped_not_crashing():
    m = Meter(clock=FakeClock(step=1))
    h = m.begin(1)
    for i in range(20):
        h.mark(f"s{i}")
    h.end()
    assert len(list(m.records())[0]["stages"]) == 16
    assert m.dropped_marks == 4


def test_event_age_uses_wall_clock_and_can_be_negative():
    m = Meter(clock=FakeClock(step=1), wall_clock=lambda: 5_000)
    m.begin(1, remote_ts_ns=3_000).end()
    m.begin(2, remote_ts_ns=6_000).end()
    m.begin(3).end()
    ages = [r.get("age_ns") for r in m.records()]
    assert ages == [2000, -1000, None]


def test_flush_writes_jsonl_and_appends(tmp_path):
    p = tmp_path / "t.jsonl"
    m = Meter(clock=FakeClock(step=5))
    for i in range(3):
        h = m.begin(i)
        h.mark("x")
        h.end()
    assert m.flush(str(p)) == 3
    m.begin(9).end()
    assert m.flush(str(p)) == 1
    lines = p.read_text().splitlines()
    assert len(lines) == 4
    assert json.loads(lines[0])["stages"] == [["x", 5]]


def test_background_flusher(tmp_path):
    p = tmp_path / "bg.jsonl"
    m = Meter(clock=FakeClock(step=1))
    m.start_flusher(str(p), interval_s=0.01)
    for i in range(5):
        m.begin(i).end()
    m.stop_flusher(str(p))
    assert len(p.read_text().splitlines()) == 5


def test_overhead_is_positive_and_small():
    o = measure_overhead(iterations=4000)
    assert o["per_call_ns"] > 0
    assert o["clock_ns"] > 0
    assert o["per_call_ns"] < 100_000  # generous bound: 100 us per call would mean something is broken
