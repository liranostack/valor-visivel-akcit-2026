"""Cost per journey from the measured simulation runs (docs/source/viabilidade.md).

Measured: layer 1 (Nitidez) in the in-process journey runner, product agents only, prices from
chat-service/config/pricing.yaml. The full journey (4 layers + Pré-Núcleo + Núcleo) is projected
from the measured cost per conversation turn; every parameter that was not measured is marked
HIPÓTESE in the doc.

    uv run python scripts/cost_model.py
"""

from dataclasses import dataclass

FX_BRL = 5.50  # R$ per US$ (reference rate in the doc)
SONNET = (3.30, 16.50)  # US$ per 1M tokens, input / output
HAIKU = (1.10, 5.50)
CACHE_READ = 0.10  # cache reads cost 10% of the input price


@dataclass(frozen=True)
class Run:
    name: str
    turns: int
    calls: int
    input_tokens: int
    output_tokens: int


# Product agents only (Interpreter, Investigator, Moderator, Synthesizer), all on Sonnet 4.6.
RUNS = (
    Run("round 3 (87cae07d)", turns=16, calls=49, input_tokens=210_602, output_tokens=19_362),
    Run("round 4 (9dcf0451)", turns=14, calls=44, input_tokens=246_339, output_tokens=22_474),
)
BASE = RUNS[-1]  # the latest prompts are the most expensive: use them as the base


@dataclass(frozen=True)
class Scenario:
    name: str
    turns: int  # conversation turns in the whole journey
    context_growth: float  # average input per turn relative to layer 1 (facts accumulate)
    other_usd: float  # guardrails + AWS infra + 1% online evaluation, per journey
    fixed_month_usd: float


SCENARIOS = (
    Scenario("otimista", 24, 1.0, 0.10, 15),
    Scenario("realista", 36, 1.3, 0.15, 35),
    Scenario("pessimista", 55, 1.8, 0.20, 80),
)

# Levers: Interpreter and Moderator on Haiku (share of the tokens they use) and prompt cache.
SMALL_MODEL_SHARE = 0.55
CACHE_HIT = 0.40


def per_turn(run: Run) -> tuple[float, float]:
    """US$ per conversation turn on Sonnet 4.6 (input, output), synthesis share included."""
    return (
        run.input_tokens / run.turns * SONNET[0] / 1e6,
        run.output_tokens / run.turns * SONNET[1] / 1e6,
    )


def journey(s: Scenario, *, levers: bool) -> float:
    inp, out = per_turn(BASE)
    if levers:
        model = (1 - SMALL_MODEL_SHARE) + SMALL_MODEL_SHARE * HAIKU[0] / SONNET[0]
        inp *= model * ((1 - CACHE_HIT) + CACHE_HIT * CACHE_READ)
        out *= model
    return s.turns * (inp * s.context_growth + out) + s.other_usd


def main() -> None:
    print("| medição | turnos | chamadas | entrada/chamada | saída/chamada | US$/turno |")
    print("| --- | --- | --- | --- | --- | --- |")
    for r in RUNS:
        i, o = per_turn(r)
        print(
            f"| {r.name} | {r.turns} | {r.calls} | {r.input_tokens // r.calls:,} | "
            f"{r.output_tokens // r.calls:,} | {i + o:.4f} |"
        )
    print()
    print(
        "| cenário | turnos | atual (US$) | atual (R$) | com alavancas (US$) | com alavancas (R$) |"
    )
    print("| --- | --- | --- | --- | --- | --- |")
    for s in SCENARIOS:
        now, lev = journey(s, levers=False), journey(s, levers=True)
        print(
            f"| {s.name} | {s.turns} | {now:.2f} | {now * FX_BRL:.2f} | {lev:.2f} | "
            f"{lev * FX_BRL:.2f} |"
        )
    print()
    print("| jornadas/mês | " + " | ".join(s.name for s in SCENARIOS) + " |")
    print("| --- | --- | --- | --- |")
    for n in (100, 1_000, 10_000):
        cells = []
        for s in SCENARIOS:
            usd = journey(s, levers=False) * n + s.fixed_month_usd
            cells.append(f"US$ {usd:,.0f} (R$ {usd * FX_BRL:,.0f})")
        print(f"| {n:,} | " + " | ".join(cells) + " |")
    print()
    for s in SCENARIOS:
        now, lev = journey(s, levers=False), journey(s, levers=True)
        print(
            f"preço mínimo (margem 80%) {s.name}: R$ {5 * now * FX_BRL:.0f} atual, "
            f"R$ {5 * lev * FX_BRL:.0f} com alavancas; margem a R$ 97: "
            f"{1 - now * FX_BRL / 97:.0%} atual, {1 - lev * FX_BRL / 97:.0%} com alavancas"
        )


if __name__ == "__main__":
    main()
