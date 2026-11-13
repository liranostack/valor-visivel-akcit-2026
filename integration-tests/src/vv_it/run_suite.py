"""Simulated journeys + judges (A.05.01).

Real mode (Bedrock: agents, simulated client and judges):
    uv run python -m vv_it.run_suite --persona pastelaria
    uv run python -m vv_it.run_suite --all --runs 2
Offline (no network: scripted answers, heuristic agents, no LLM judges; never fails):
    uv run python -m vv_it.run_suite --offline --all

Reports go to docs/e2e-runs/sim-<timestamp>/report.md (+ report.json); not committed.
Real mode exits 1 when a metric misses its limit in config/thresholds.yaml.
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel
from vv_chat.agents.llm import StrandsLLM, StructuredLLM
from vv_chat.pricing import load_prices
from vv_chat.turn import Role

from vv_it.fidelity import Check, deterministic_checks
from vv_it.journey import AGENTS, FailingLLM, run_journey
from vv_it.judges.judge import audit_reasoning, judge_conversation, truth_recall
from vv_it.persona import Persona, load_all
from vv_it.report import RunResult, cost_rows, write_report
from vv_it.simulator import SimulatedClient

PACKAGE = Path(__file__).resolve().parents[2]
REPO = PACKAGE.parent
THRESHOLDS = PACKAGE / "config" / "thresholds.yaml"
RUNS = REPO / "docs" / "e2e-runs"
log = logging.getLogger("vv_it")


class Thresholds(BaseModel):
    rules: dict[str, dict[str, float]]


def load_thresholds(path: Path = THRESHOLDS) -> Thresholds:
    return Thresholds.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def failures(checks: list[Check], thresholds: Thresholds) -> list[Check]:
    out: list[Check] = []
    for c in checks:
        rule = thresholds.rules.get(c.metric)
        if rule is None or ("na" in rule and c.value == rule["na"]):
            continue
        if ("min" in rule and c.value < rule["min"]) or ("max" in rule and c.value > rule["max"]):
            out.append(c)
    return out


def enforce(offline: bool) -> bool:
    return not offline


def _bedrock(size: str, label: str) -> StrandsLLM:
    from strands.models import BedrockModel
    from vv_chat.models import load_models_config

    cfg = load_models_config()
    model = BedrockModel(model_id=cfg.sizes[size], region_name=cfg.region)  # type: ignore[index]
    return StrandsLLM(model, label=label)


def _agent_llms() -> dict[Role, StrandsLLM]:
    from vv_chat.models import make_model

    return {role: StrandsLLM(make_model(role), label=role) for role in AGENTS}


async def _one(
    persona: Persona, run: int, args: argparse.Namespace, thresholds: Thresholds
) -> RunResult:
    meters: list[StrandsLLM] = []
    if args.offline:
        client = SimulatedClient(persona)
        record = await run_journey(
            persona, client, agent_llm=FailingLLM(), max_turns=args.max_turns
        )
    else:
        client_llm = _bedrock(args.client_size, "cliente simulada")
        agents = _agent_llms()
        client = SimulatedClient(persona, client_llm, seed=run)
        llms: dict[Role, StructuredLLM] = dict(agents)
        record = await run_journey(persona, client, llms=llms, max_turns=args.max_turns)
        meters = [*agents.values(), client_llm]
    result = RunResult(persona=persona.slug, run=run, record=record, checks=[])
    result.checks = deterministic_checks(record)
    if not args.offline and not args.no_judge:
        judge = _bedrock(args.judge_size, "juiz")
        meters.append(judge)
        try:
            conversation, reasoning = await asyncio.gather(
                judge_conversation(record, persona, judge), audit_reasoning(record, persona, judge)
            )
            result.conversation, result.reasoning = conversation, reasoning
            result.checks += [Check(metric=m.metric, value=m.score) for m in conversation.metrics]
            result.checks.append(
                Check(
                    metric="truth_recall",
                    value=round(truth_recall(conversation, persona), 2),
                )
            )
        except Exception as exc:  # a judge failure must not lose the journey
            result.error = f"juiz falhou: {exc}"
    if not args.offline:
        result.usage = [m.usage for m in meters]
        _, product, total = cost_rows(result.usage, load_prices())
        result.checks += [
            Check(metric="cost_session_usd", value=round(product, 4)),
            Check(metric="cost_run_usd", value=round(total, 4)),
        ]
    result.failed = [c.metric for c in failures(result.checks, thresholds)]
    log.warning(
        "%s #%d: %s, %d turnos, falhas: %s",
        persona.slug,
        run,
        record.ended,
        len(record.turns),
        ", ".join(result.failed) or "nenhuma",
    )
    return result


async def run_suite(args: argparse.Namespace) -> list[RunResult]:
    thresholds = load_thresholds()
    personas = load_all(args.persona or None)
    if not personas:
        raise SystemExit(f"nenhuma persona encontrada: {args.persona}")
    limit = asyncio.Semaphore(args.concurrency)

    async def guarded(p: Persona, run: int) -> RunResult:
        async with limit:
            return await _one(p, run, args, thresholds)

    jobs = [guarded(p, run) for p in personas for run in range(1, args.runs + 1)]
    return list(await asyncio.gather(*jobs))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--persona", action="append", help="slug in integration-tests/scenarios (repeat)"
    )
    parser.add_argument(
        "--all", action="store_true", help="every persona (default when none given)"
    )
    parser.add_argument("--runs", type=int, default=1, help="runs per persona")
    parser.add_argument("--max-turns", type=int, default=14)
    parser.add_argument("--offline", action="store_true", help="no network, never fails")
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM judges")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--client-size", choices=["large", "small"], default="small")
    parser.add_argument("--judge-size", choices=["large", "small"], default="large")
    parser.add_argument("--out", type=Path, default=RUNS)
    args = parser.parse_args(argv)
    if args.all:
        args.persona = None

    results = asyncio.run(run_suite(args))
    out_dir = args.out / f"sim-{datetime.now():%Y%m%d-%H%M%S}"
    report = write_report(results, load_thresholds().rules, out_dir)
    print(f"relatório: {report}")
    failed = [r for r in results if r.failed]
    if failed and enforce(args.offline):
        for r in failed:
            print(f"✗ {r.persona} #{r.run}: {', '.join(r.failed)}")
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    for noisy in ("mcp", "mcp.server", "mcp.server.lowlevel.server", "vv_chat"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    sys.exit(main())
