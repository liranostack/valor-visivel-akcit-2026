"""Suite report (pt-BR): summary table, improvements grouped by file, then each journey with its
metrics, truths, reasoning issues and the transcript with the agents' steps."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from vv_chat.agents.llm import Usage
from vv_chat.pricing import Prices, cost_usd, load_prices

from vv_it.fidelity import Check
from vv_it.journey import JourneyRecord
from vv_it.judges.judge import ConversationVerdict, ReasoningVerdict, render_transcript

IMPACT_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class RunResult:
    persona: str
    run: int
    record: JourneyRecord
    checks: list[Check]
    conversation: ConversationVerdict | None = None
    reasoning: ReasoningVerdict | None = None
    failed: list[str] = field(default_factory=list[str])
    error: str | None = None
    usage: list[Usage] = field(default_factory=list[Usage])


# Roles that are the product (what a real session costs); the rest is the test harness.
PRODUCT_ROLES = ("interpreter", "investigator", "moderator", "synthesizer")


def cost_rows(usages: list[Usage], prices: Prices) -> tuple[list[dict[str, Any]], float, float]:
    """One row per role and model, the product's cost (agents only) and the run's total."""
    rows: list[dict[str, Any]] = []
    product = total = 0.0
    for u in usages:
        usd = cost_usd(u.model_id, u.input_tokens, u.output_tokens, prices) or 0.0
        rows.append(
            {
                "role": u.label,
                "model": u.model_id,
                "calls": u.calls,
                "input": u.input_tokens,
                "output": u.output_tokens,
                "usd": usd,
            }
        )
        total += usd
        product += usd if u.label in PRODUCT_ROLES else 0.0
    return rows, product, total


def _cost_markdown(results: list["RunResult"]) -> list[str]:
    prices = load_prices()
    runs = [r for r in results if r.usage]
    if not runs:
        return []
    md = [
        "",
        "## Custo",
        "",
        "Preços em `chat-service/config/pricing.yaml` (USD por 1M tokens). "
        "**Sessão** = só os agentes do produto; **rodada** = sessão + cliente simulada + juízes.",
        "",
        "| rodada | turnos | tokens entrada | tokens saída | sessão (US$) | por turno (US$) "
        "| rodada (US$) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    by_model: dict[tuple[str, str], list[int]] = {}
    grand = 0.0
    sessions: list[float] = []
    for r in runs:
        rows, product, total = cost_rows(r.usage, prices)
        grand += total
        sessions.append(product)
        tokens_in = sum(x["input"] for x in rows if x["role"] in PRODUCT_ROLES)
        tokens_out = sum(x["output"] for x in rows if x["role"] in PRODUCT_ROLES)
        turns = len(r.record.turns) or 1
        md.append(
            f"| {r.persona} #{r.run} | {len(r.record.turns)} | {tokens_in:,} | {tokens_out:,} "
            f"| {product:.4f} | {product / turns:.4f} | {total:.4f} |"
        )
        for x in rows:
            key = ("produto" if x["role"] in PRODUCT_ROLES else x["role"], x["model"])
            acc = by_model.setdefault(key, [0, 0, 0])
            acc[0] += x["calls"]
            acc[1] += x["input"]
            acc[2] += x["output"]
    md += [
        "",
        f"Sessão média: **US$ {sum(sessions) / len(sessions):.4f}**. "
        f"Total desta execução (com cliente e juízes): **US$ {grand:.4f}**.",
        "",
        "| quem | modelo | chamadas | tokens entrada | tokens saída | US$ |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for (who, model), (calls, tin, tout) in sorted(by_model.items()):
        usd = cost_usd(model, tin, tout, prices)
        shown = "sem preço" if usd is None else f"{usd:.4f}"
        md.append(f"| {who} | `{model}` | {calls} | {tin:,} | {tout:,} | {shown} |")
    return md


def _fmt(value: float) -> str:
    return f"{value:g}"


def render_markdown(results: list[RunResult], rules: dict[str, dict[str, float]]) -> str:
    md = ["# Jornadas simuladas", ""]
    metrics = list(dict.fromkeys(c.metric for r in results for c in r.checks))
    md += ["| métrica | limite | " + " | ".join(f"{r.persona} #{r.run}" for r in results) + " |"]
    md += ["| --- | --- | " + " | ".join("---" for _ in results) + " |"]
    for metric in metrics:
        rule = rules.get(metric, {})
        limit = (f"≥ {_fmt(rule['min'])}" if "min" in rule else "") + (
            f"≤ {_fmt(rule['max'])}" if "max" in rule else ""
        )
        cells = []
        for r in results:
            value = next((c.value for c in r.checks if c.metric == metric), None)
            mark = " ✗" if metric in r.failed else ""
            cells.append("-" if value is None else f"{_fmt(value)}{mark}")
        md.append(f"| {metric} | {limit or '-'} | " + " | ".join(cells) + " |")

    md += _cost_markdown(results)

    improvements = [
        (r.persona, i) for r in results if r.reasoning for i in r.reasoning.improvements
    ]
    if improvements:
        md += ["", "## Melhorias propostas", ""]
        by_file: dict[str, list[tuple[str, Any]]] = {}
        for persona, imp in sorted(improvements, key=lambda x: IMPACT_ORDER[x[1].impact]):
            by_file.setdefault(imp.file, []).append((persona, imp))
        for path, items in by_file.items():
            md += [f"### `{path}`", ""]
            for persona, imp in items:
                turns = ", ".join(str(t) for t in imp.evidence_turns) or "-"
                md += [
                    f"- **{imp.impact}** ({persona}, turnos {turns}): {imp.problem}",
                    f"  - proposta: {imp.proposal}",
                ]
            md.append("")

    for r in results:
        md += ["", f"## {r.persona} #{r.run} — {r.record.ended}", ""]
        if r.error:
            md += [f"Erro: {r.error}", ""]
        if r.conversation:
            md += [r.conversation.summary, ""]
            for m in r.conversation.metrics:
                turns = ", ".join(str(t) for t in m.evidence_turns)
                md.append(f"- {m.metric} = {_fmt(m.score)} (turnos {turns or '-'}): {m.rationale}")
            md += ["", "Verdades da persona:", ""]
            md += [f"- {t.truth_id}: {t.surfaced} {t.note}".rstrip() for t in r.conversation.truths]
        if r.reasoning and r.reasoning.issues:
            md += ["", "Raciocínio dos agentes:", ""]
            md += [
                f"- turno {i.turn}, {i.agent}: {i.problem} — {i.evidence}"
                for i in r.reasoning.issues
            ]
        details = [c for c in r.checks if c.detail]
        if details:
            md += ["", "Checagens:", ""] + [f"- {c.metric}: {c.detail}" for c in details]
        md += [
            "",
            "<details><summary>transcrição com os passos dos agentes</summary>",
            "",
            "```text",
            render_transcript(r.record, with_steps=True),
            "```",
            "",
            "</details>",
        ]
        if r.record.synthesis:
            md += ["", "<details><summary>síntese</summary>", ""]
            for title, text in (r.record.synthesis.get("content") or {}).items():
                md += [f"**{title}**", "", str(text), ""]
            md += ["</details>"]
    return "\n".join(md) + "\n"


def write_report(
    results: list[RunResult], rules: dict[str, dict[str, float]], out_dir: Path
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(render_markdown(results, rules), encoding="utf-8")
    data = [
        {
            "persona": r.persona,
            "run": r.run,
            "failed": r.failed,
            "error": r.error,
            "usage": [asdict(u) for u in r.usage],
            "checks": [c.model_dump() for c in r.checks],
            "conversation": r.conversation.model_dump() if r.conversation else None,
            "reasoning": r.reasoning.model_dump() if r.reasoning else None,
            "record": asdict(r.record),
        }
        for r in results
    ]
    (out_dir / "report.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    return out_dir / "report.md"
