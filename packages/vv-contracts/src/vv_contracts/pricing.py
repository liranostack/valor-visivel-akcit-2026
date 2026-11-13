"""Model prices (USD per 1M tokens) used for cost_usd in traces and the dashboard.

List prices on Amazon Bedrock as recorded in docs/source/viabilidade.md.
Cache reads cost 10% of input.
Model ids may carry an inference-profile prefix (us., eu., global.); it is ignored.
"""

PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "anthropic.claude-haiku-4-5": (1.0, 5.0),
    "anthropic.claude-sonnet-4-5": (3.0, 15.0),
}
CACHE_READ_FACTOR = 0.1
_PROFILE_PREFIXES = ("us.", "eu.", "apac.", "global.")


class UnknownModelError(KeyError):
    pass


def _normalize(model_id: str) -> str:
    for prefix in _PROFILE_PREFIXES:
        if model_id.startswith(prefix):
            return model_id[len(prefix) :]
    return model_id


def price_for(model_id: str) -> tuple[float, float]:
    base = _normalize(model_id)
    for key, price in PRICES_PER_MILLION.items():
        if base.startswith(key):
            return price
    raise UnknownModelError(model_id)


def cost_usd(
    model_id: str, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0
) -> float:
    if min(input_tokens, output_tokens, cache_read_tokens) < 0:
        raise ValueError("token counts must be non-negative")
    price_in, price_out = price_for(model_id)
    return (
        input_tokens * price_in
        + cache_read_tokens * price_in * CACHE_READ_FACTOR
        + output_tokens * price_out
    ) / 1_000_000
