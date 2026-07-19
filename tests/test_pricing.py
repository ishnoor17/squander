from pathlib import Path

import pytest

from squander.pricing import load_prices

REPO_PRICES = Path(__file__).parent.parent / "prices.yaml"


@pytest.fixture
def prices():
    return load_prices(REPO_PRICES)


def test_loads_known_model(prices):
    # claude-sonnet-5 at its introductory pricing (through 2026-08-31).
    sonnet = prices.get("claude-sonnet-5")
    assert sonnet is not None
    assert sonnet.input == 2.00
    assert sonnet.output == 10.00
    assert sonnet.cache_read == 0.20
    assert sonnet.cache_write_5m == 2.50
    assert sonnet.cache_write_1h == 4.00


def test_unknown_model_returns_none(prices):
    assert prices.get("some-future-model") is None
    assert prices.cost("some-future-model", input_tokens=1000) is None


def test_cost_is_per_million_tokens(prices):
    # 1M input tokens on fable at $10.00/M is exactly $10.00.
    assert prices.cost("claude-fable-5", input_tokens=1_000_000) == pytest.approx(10.00)


def test_cost_combines_all_token_kinds(prices):
    cost = prices.cost(
        "claude-fable-5",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_tokens=1_000_000,
        cache_write_5m_tokens=1_000_000,
        cache_write_1h_tokens=1_000_000,
    )
    assert cost == pytest.approx(10.00 + 50.00 + 1.00 + 12.50 + 20.00)


def test_cache_write_ttls_priced_differently(prices):
    five_min = prices.cost("claude-fable-5", cache_write_5m_tokens=1_000_000)
    one_hour = prices.cost("claude-fable-5", cache_write_1h_tokens=1_000_000)
    assert five_min == pytest.approx(12.50)
    assert one_hour == pytest.approx(20.00)


def test_zero_tokens_cost_zero(prices):
    assert prices.cost("claude-sonnet-5") == 0.0


def test_chars_per_token_default_loaded(prices):
    assert prices.chars_per_token == pytest.approx(3.8)


def test_custom_prices_file(tmp_path):
    custom = tmp_path / "prices.yaml"
    custom.write_text(
        "models:\n"
        "  test-model:\n"
        "    input: 1.00\n"
        "    output: 2.00\n"
        "    cache_read: 0.10\n"
        "    cache_write_5m: 1.25\n"
        "    cache_write_1h: 2.00\n"
    )
    book = load_prices(custom)
    assert book.cost("test-model", output_tokens=500_000) == pytest.approx(1.00)
