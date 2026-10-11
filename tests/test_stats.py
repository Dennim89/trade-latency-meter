import pytest

from trade_latency_meter import stats


def test_percentile_known_samples():
    v = list(range(1, 101))
    assert stats.percentile(v, 0) == 1
    assert stats.percentile(v, 50) == 50.5
    assert stats.percentile(v, 90) == pytest.approx(90.1)
    assert stats.percentile(v, 99) == pytest.approx(99.01)
    assert stats.percentile(v, 100) == 100


def test_percentile_single_and_errors():
    assert stats.percentile([7], 99.9) == 7
    with pytest.raises(ValueError):
        stats.percentile([], 50)
    with pytest.raises(ValueError):
        stats.percentile([1], 101)


def test_summarize_unsorted_input():
    s = stats.summarize([5, 1, 3, 2, 4])
    assert (s["count"], s["min"], s["p50"], s["max"], s["mean"]) == (5, 1, 3, 5, 3)
    assert "p99.9" in s
    assert stats.summarize([]) == {"count": 0}


def test_format_ns():
    assert stats.format_ns(950) == "950 ns"
    assert stats.format_ns(1500) == "1.50 us"
    assert stats.format_ns(2_500_000) == "2.50 ms"
    assert stats.format_ns(3_000_000_000) == "3.00 s"


def test_histogram_counts_add_up():
    vals = [100] * 50 + [1000] * 30 + [100_000] * 5
    lines = stats.histogram(vals, bins=5)
    assert len(lines) == 5
    assert sum(int(line.rsplit(" ", 1)[1]) for line in lines) == len(vals)
    assert len(stats.histogram([42, 42], bins=5)) == 1
    assert stats.histogram([]) == []
