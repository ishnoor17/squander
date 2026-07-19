from pathlib import Path

import pytest

from squander.parser import parse_session_file
from squander.pricing import load_prices
from squander.sessions import summarize_session

FIXTURE = Path(__file__).parent / "fixtures" / "sample_session.jsonl"
REPO_PRICES = Path(__file__).parent.parent / "prices.yaml"


@pytest.fixture
def prices():
    return load_prices(REPO_PRICES)


@pytest.fixture
def summary(prices):
    return summarize_session(parse_session_file(FIXTURE), prices, project="squander")


def test_empty_records_gives_none(prices):
    assert summarize_session([], prices) is None


def test_totals_sum_deduplicated_records(summary):
    # Fixture has 3 real API calls: msg_AAA111 (2/20/1000cr/500cw sonnet),
    # msg_BBB222 (15/40/1500cr/0cw sonnet), msg_CCC333 (800/10 haiku sidechain).
    assert summary.api_calls == 3
    assert summary.input_tokens == 2 + 15 + 800
    assert summary.output_tokens == 20 + 40 + 10
    assert summary.cache_read_tokens == 1000 + 1500
    assert summary.cache_write_tokens == 500
    assert summary.reasoning_tokens == 0


def test_sidechain_records_are_included(summary):
    # ccusage counts subagent calls; we must too or Phase 1 validation fails.
    assert any(r.is_sidechain for r in summary.records)


def test_models_listed_in_order_of_appearance(summary):
    assert summary.models == ["claude-sonnet-5", "claude-haiku-4-5"]


def test_cost_matches_hand_computed_value(summary):
    # msg_AAA111 (sonnet, intro pricing): 2 in, 20 out, 1000 cache-read,
    # cache writes split 100 @ 5m-TTL + 400 @ 1h-TTL.
    aaa = (2 * 2.00 + 20 * 10.00 + 1000 * 0.20 + 100 * 2.50 + 400 * 4.00) / 1_000_000
    # msg_BBB222 (sonnet): no TTL breakdown logged, so its 0 cache-write
    # tokens fall back to the 5m rate (which is 0 cost here anyway).
    bbb = (15 * 2.00 + 40 * 10.00 + 1500 * 0.20) / 1_000_000
    # msg_CCC333 (haiku sidechain): input/output only.
    ccc = (800 * 1.00 + 10 * 5.00) / 1_000_000
    assert summary.cost_usd == pytest.approx(aaa + bbb + ccc)


def test_unpriced_model_makes_cost_unknown(prices, tmp_path):
    records = parse_session_file(FIXTURE)
    sparse = tmp_path / "prices.yaml"
    sparse.write_text(
        "models:\n"
        "  claude-sonnet-5:\n"
        "    input: 2.00\n"
        "    output: 10.00\n"
        "    cache_read: 0.20\n"
        "    cache_write_5m: 2.50\n"
        "    cache_write_1h: 4.00\n"
    )
    summary = summarize_session(records, load_prices(sparse))
    assert summary.cost_usd is None
    assert summary.unpriced_models == ["claude-haiku-4-5"]


def test_timestamps_span_session(summary):
    assert summary.first_timestamp < summary.last_timestamp
    assert summary.first_timestamp == summary.records[0].timestamp
    assert summary.last_timestamp == summary.records[-1].timestamp
