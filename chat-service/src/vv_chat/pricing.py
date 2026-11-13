"""Model prices (config/pricing.yaml) and the cost of a token count, for estimates (A.04.04)."""

from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "pricing.yaml"
Prices = dict[str, dict[str, float]]


def load_prices(path: Path = DEFAULT_PATH) -> Prices:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def cost_usd(model_id: str, input_tokens: int, output_tokens: int, prices: Prices) -> float | None:
    price = prices.get(model_id)
    if price is None:
        return None
    return (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000
