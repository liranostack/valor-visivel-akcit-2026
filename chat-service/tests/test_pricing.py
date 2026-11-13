"""Model prices (USD per 1M tokens) for cost estimates (A.04.04)."""

from vv_chat.models import load_models_config
from vv_chat.pricing import cost_usd, load_prices


def test_every_configured_model_has_a_price() -> None:
    prices = load_prices()
    for model_id in load_models_config().sizes.values():
        assert model_id in prices


def test_cost_is_per_million_tokens() -> None:
    prices = {"m": {"input": 3.0, "output": 15.0}}
    assert cost_usd("m", 1_000_000, 100_000, prices) == 4.5


def test_unknown_model_has_no_cost() -> None:
    assert cost_usd("unknown", 10, 10, {}) is None
