from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from squander.detectors import detect_context_resend
from squander.parser import UsageRecord
from squander.pricing import load_prices

REPO_PRICES = Path(__file__).parent.parent / "prices.yaml"

T0 = datetime(2026, 7, 16, 14, 45, 0, tzinfo=timezone.utc)


def make_record(
    i,
    cache_read=0,
    cache_write=0,
    input_tokens=2,
    model="claude-sonnet-5",
    sidechain=False,
):
    return UsageRecord(
        session_id="sess-1",
        message_id=f"msg_{i:03d}",
        request_id=f"req_{i:03d}",
        timestamp=T0 + timedelta(seconds=10 * i),
        model=model,
        input_tokens=input_tokens,
        output_tokens=100,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        cache_write_5m_tokens=None,
        cache_write_1h_tokens=None,
        reasoning_tokens=None,
        is_sidechain=sidechain,
    )


@pytest.fixture
def prices():
    return load_prices(REPO_PRICES)


def review_loop_records(n=5, context=38_000):
    # n calls each re-reading ~the same large context, growing slightly.
    return [
        make_record(i, cache_read=context + 500 * i, cache_write=500)
        for i in range(n)
    ]


def test_detects_review_loop(prices):
    findings = detect_context_resend(review_loop_records(5), prices)
    assert len(findings) == 1
    f = findings[0]
    assert f.calls == 5
    assert f.session_id == "sess-1"
    # Redundant tokens: cache reads of calls 2..5.
    expected = sum(38_000 + 500 * i for i in range(1, 5))
    assert f.redundant_tokens == expected
    # Priced at sonnet's cache-read rate ($0.20/M at intro pricing).
    assert f.redundant_cost_usd == pytest.approx(expected * 0.20 / 1_000_000)


def test_short_run_not_reported(prices):
    findings = detect_context_resend(review_loop_records(2), prices)
    assert findings == []


def test_small_context_not_reported(prices):
    records = [make_record(i, cache_read=5_000, cache_write=100) for i in range(6)]
    assert detect_context_resend(records, prices) == []


def test_context_reset_breaks_run(prices):
    # 3 large calls, then a fresh small-context call, then 3 more large:
    # two separate runs of 3, not one run of 7.
    records = review_loop_records(3)
    records.append(make_record(10, cache_read=1_000, cache_write=200))
    records.extend(
        make_record(20 + i, cache_read=40_000 + 500 * i, cache_write=500)
        for i in range(3)
    )
    findings = detect_context_resend(records, prices)
    assert [f.calls for f in findings] == [3, 3]


def test_sidechain_records_excluded(prices):
    # Subagent calls interleaved mid-run must not break the main chain.
    records = review_loop_records(4)
    records.insert(2, make_record(50, cache_read=100, sidechain=True))
    findings = detect_context_resend(records, prices)
    assert len(findings) == 1
    assert findings[0].calls == 4


def test_unpriced_model_reports_tokens_without_cost(prices):
    records = review_loop_records(4)
    records = [
        UsageRecord(**{**r.__dict__, "model": "mystery-model"}) for r in records
    ]
    findings = detect_context_resend(records, prices)
    assert len(findings) == 1
    assert findings[0].redundant_cost_usd is None
    assert findings[0].redundant_tokens > 0


def test_low_overlap_breaks_run(prices):
    # Each call's cache read covers well under 80% of the previous
    # call's context -- not the same context being re-sent.
    records = [
        make_record(i, cache_read=30_000, cache_write=50_000) for i in range(5)
    ]
    assert detect_context_resend(records, prices) == []


def test_empty_records(prices):
    assert detect_context_resend([], prices) == []
