import json

import pytest

from trade_latency_meter import report


def recs():
    return [
        {"id": i, "stages": [["parse", 10 * (i + 1)], ["sign", 100]], "total_ns": 10 * (i + 1) + 150}
        for i in range(10)
    ]


def lines(rs):
    return [json.dumps(r) for r in rs]


def test_load_skips_blank_and_rejects_garbage():
    assert len(report.load(lines(recs()) + ["", "  "])) == 10
    with pytest.raises(report.ReportError, match="line 2"):
        report.load([lines(recs())[0], "{not json"])
    with pytest.raises(report.ReportError):
        report.load(['{"stages": "x", "total_ns": 1}'])


def test_stage_order_is_first_seen_then_end_to_end():
    rep = report.build(report.load(lines(recs())), info=_info())
    assert list(rep["stages"]) == ["parse", "sign", "end-to-end"]
    assert rep["stages"]["parse"]["p50"] == 55
    assert rep["stages"]["sign"]["max"] == 100


def _info():
    return {"cpu": "test cpu", "cores": 2, "os": "test-os", "python": "3.x", "implementation": "CPython",
            "tlm": "0", "libs": {"solders": "1.0"}}


def test_text_report_has_header_columns_and_histograms():
    rs = recs()
    rs[0]["age_ns"] = 1_000_000
    text = report.render_text(report.build(report.load(lines(rs)), info=_info()))
    assert "cpu:    test cpu (2 cores)" in text
    assert "solders 1.0" in text
    for col in ("p50", "p90", "p99", "p99.9", "max"):
        assert col in text
    assert "event age" in text and "clock sync" in text
    assert "parse histogram" in text
    assert "fewer than 1000 samples" in text
    no_hist = report.render_text(report.build(report.load(lines(rs)), info=_info()), histograms=False)
    assert "histogram" not in no_hist


def test_json_report_is_valid_and_has_no_private_fields():
    out = json.loads(report.render_json(report.build(report.load(lines(recs())), info=_info())))
    assert out["events"] == 10
    assert out["unit"] == "ns"
    assert set(out) == {"system", "events", "unit", "stages"}
    assert out["stages"]["end-to-end"]["count"] == 10
