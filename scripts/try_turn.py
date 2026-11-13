"""First end-to-end test in the terminal: real Bedrock models, local KB, in-memory state.

Usage (needs AWS credentials with Bedrock model access):
    uv run python scripts/try_turn.py --offer "bolo de casamento" --audience "noivas" \\
        --sector confeitaria

Type the client's answers; an empty line or Ctrl-D ends. The guardrail is off unless
GUARDRAIL_ID is set. Each turn prints what every agent decided (scores, facts, decision, angle,
fallbacks, latency); --quiet hides it. --save LABEL writes docs/e2e-runs/<time>-<LABEL>.jsonl (every
step) and .md (readable transcript); that folder is not committed.

--scenario NAME (scripts/scenarios/NAME.yaml) loads the full onboarding, the baseline and scripted
answers, so the same client can be replayed before and after a change; when the script ends, you
keep answering by hand.
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from vv_chat.agents.llm import StrandsLLM, StructuredLLM
from vv_chat.business import opening_question
from vv_chat.conductor.config import load_config
from vv_chat.gateway.mcp import connect_in_memory
from vv_chat.guardrails import from_env
from vv_chat.models import make_model
from vv_chat.pricing import cost_usd, load_prices
from vv_chat.turn import Role, TurnDeps, run_turn
from vv_contracts.state import OnboardingAnswers, Turn
from vv_contracts.tools import (
    CreateSessionIn,
    GetLayerSpecIn,
    SaveBaselineIn,
    SaveTurnIn,
    UpdateSessionIn,
)
from vv_contracts.ws import DeliverableEvent, ErrorEvent, MessageDoneEvent, StateEvent, TokenEvent
from vv_mcp.kb import load_knowledge_base
from vv_mcp.repo_memory import InMemoryStateRepository
from vv_mcp.server import build_server

RUNS = Path(__file__).resolve().parents[1] / "docs" / "e2e-runs"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenario as scenarios  # noqa: E402


def describe(step: str, d: dict[str, Any]) -> list[str]:
    """Human-readable lines for one turn step (pt-BR labels)."""
    fb = " [FALLBACK]" if d.get("used_fallback") else ""
    sec = f" {d['ms'] / 1000:.1f}s" if "ms" in d else ""
    if step == "guardrail_input":
        return [
            f"guardrail entrada{sec}: {'ok' if d['allowed'] else 'BLOQUEADO'}"
            + (" (mascarado)" if d.get("masked") else "")
        ]
    if step == "interpreter":
        r = d["result"]
        lines = [
            f"intérprete{sec}{fb}: concretude {r['concreteness']} · relevância {r['relevance']}"
            f" · defensabilidade {r['defensibility']} · domínio {r['domain_fit']}"
        ]
        for f in r["facts"]:
            where = f"{f['finding_area']}, {f['kind']}, {f['origin']}"
            lines.append(f'   fato ({where}): "{f["source_excerpt"]}"')
        if d.get("dropped_facts"):
            lines.append(f"   fatos descartados (trecho fora da mensagem): {d['dropped_facts']}")
        for label, key in (
            ("lacunas", "gaps"),
            ("genéricos", "generic_claims"),
            ("dificuldade", "difficulty_signals"),
        ):
            if r[key]:
                lines.append(f"   {label}: " + "; ".join(r[key]))
        if r.get("rationale"):
            lines.append(f"   por quê: {r['rationale']}")
        return lines
    if step == "conductor":
        dec = d["decision"]
        target = dec.get("next_stage_id") or "-"
        line = f"condutor: {dec['action']} → {target} (tentativa {dec['attempt']}"
        line += ", ABC)" if dec.get("offer_abc_options") else ")"
        if "stage_status" in d:
            line += f" | etapa {d['stage_id']}: {d['stage_status']}, respostas {d['attempts']}"
        if d.get("create_gap"):
            line += f" | lacuna: {d.get('gap_reason')}"
        if "gap_status" in d:
            line += f" | lacuna retomada → {d['gap_status']}"
        return [line]
    if step == "investigator":
        dr = d["draft"]
        retry = " [REPETIDA→NOVA TENTATIVA]" if d.get("retried") else ""
        refs = dr["references_fact_ids"]
        return [
            f"investigador{sec}{fb}{retry}: ângulo {dr['angle']}, fatos {refs}",
            f"   rascunho: {dr['question']}",
        ]
    if step == "moderator":
        extra = " [ABC DESCARTADO]" if d.get("abc_dropped") else ""
        if d.get("removed"):
            extra += f" [REMOVIDO PELAS CHECAGENS: {', '.join(d['removed'])}]"
        return [f"moderador{sec}{fb}{extra}"]
    if step == "synthesizer":
        syn = d["synthesis"]
        return [
            f"sintetizador{sec}{fb}: {len(syn['fact_refs'])} fatos citados, lacunas: {syn['gaps']}"
        ]
    if step == "guardrail_output":
        return [f"guardrail saída{sec}: {'ok' if d['allowed'] else 'BLOQUEADO → âncora segura'}"]
    if step == "turn":
        return [
            f"turno {d['seq']}{sec} · decisão {d['decision']} · modo {d.get('mode') or 'normal'}"
        ]
    return [f"{step}: {d}"]


async def main(args: argparse.Namespace) -> None:
    server = build_server(InMemoryStateRepository(), load_knowledge_base())
    async with connect_in_memory(server) as gw:
        sid = (await gw.create_session(CreateSessionIn())).session_id
        layer = await gw.get_layer_spec(GetLayerSpecIn(layer_id="clarity"))
        stage = layer.stages[0]
        script = scenarios.load(scenarios.resolve(args.scenario)) if args.scenario else None
        onboarding = (
            script.onboarding
            if script
            else OnboardingAnswers(
                business_type=args.sector, offer=args.offer, audience=args.audience
            )
        )
        if script and script.baseline:
            await gw.save_baseline(SaveBaselineIn(session_id=sid, statement=script.baseline))
        scripted = list(script.answers) if script else []
        await gw.update_session(
            UpdateSessionIn(
                session_id=sid,
                status="in_layer",
                active_layer="clarity",
                active_stage=stage.stage_id,
                onboarding=onboarding,
            )
        )
        first = opening_question(onboarding, stage.anchors[0].question)
        await gw.save_turn(
            SaveTurnIn(session_id=sid, turn=Turn(seq=1, user_message="", question_asked=first))
        )
        roles: tuple[Role, ...] = ("interpreter", "investigator", "moderator", "synthesizer")
        agents: dict[Role, StrandsLLM] = {
            role: StrandsLLM(make_model(role), label=role) for role in roles
        }
        prices = load_prices()

        def session_cost() -> str:
            usd = sum(
                cost_usd(a.usage.model_id, a.usage.input_tokens, a.usage.output_tokens, prices)
                or 0.0
                for a in agents.values()
            )
            tin = sum(a.usage.input_tokens for a in agents.values())
            tout = sum(a.usage.output_tokens for a in agents.values())
            return f"tokens da sessão: {tin:,} entrada, {tout:,} saída · US$ {usd:.4f}"

        deps = TurnDeps(
            gateway=gw,
            llms=dict[Role, StructuredLLM](agents),
            guardrails=from_env(),
            config=load_config(),
        )
        records: list[dict[str, Any]] = []
        transcript: list[str] = []
        current = {"turn": 1}

        def on_step(step: str, data: dict[str, Any]) -> None:
            records.append({"turn": current["turn"], "step": step, "data": data})
            if not args.quiet:
                for line in describe(step, data):
                    print(f"  · {line}")

        deps.on_step = on_step
        transcript.append(f"> {first}\n")
        last_abc: dict[str, str] = {}
        print(f"\nValor Visível (sessão {sid[:8]})\n\n> {first}\n")
        while True:
            if scripted:
                answer = scripted.pop(0)
                print(f"você (roteiro): {answer}")
            else:
                try:
                    answer = input("você: ").strip()
                except EOFError:
                    break
            if not answer:
                break
            choice = answer.strip().rstrip(").").lower()
            if choice in last_abc:  # as the UI does: a click sends the option text, not a letter
                answer = f"{choice.upper()}) {last_abc[choice]}"
                print(f"  (opção escolhida → {answer})")
            print()
            current["turn"] += 1
            records.append({"turn": current["turn"], "step": "user", "data": {"text": answer}})
            transcript.append(f"**você:** {answer}\n")
            if not args.quiet:
                print("  diagnóstico:")
            reply: list[str] = []
            async for event in run_turn(sid, answer, deps):
                if isinstance(event, TokenEvent):
                    if not reply:
                        print()
                    reply.append(event.text)
                    print(event.text, end="", flush=True)
                elif isinstance(event, MessageDoneEvent):
                    last_abc = {o.label.lower(): o.text for o in event.abc_options or []}
                    print("\n")  # options A/B/C are already part of the streamed text
                elif isinstance(event, DeliverableEvent):
                    print("\n--- síntese ---")
                    print(json.dumps(event.content, ensure_ascii=False, indent=2))
                    transcript.append(
                        "```json\n"
                        + json.dumps(event.content, ensure_ascii=False, indent=2)
                        + "\n```\n"
                    )
                elif isinstance(event, StateEvent):
                    print(f"[estado: {event.status}, camada {event.layer_index or '-'}]\n")
                elif isinstance(event, ErrorEvent):
                    print(f"[erro: {event.message}]\n")
            diag = [
                line
                for r in records
                if r["turn"] == current["turn"] and r["step"] != "user"
                for line in describe(r["step"], r["data"])
            ]
            transcript.append(
                "<details><summary>diagnóstico</summary>\n\n"
                + "\n".join(f"- {line}" for line in diag)
                + "\n\n</details>\n"
            )
            transcript.append(f"> {''.join(reply)}\n")
            print(f"  [{session_cost()}]\n")
        print(session_cost())
        for a in agents.values():
            u = a.usage
            print(f"  {u.label}: {u.calls} chamadas, {u.input_tokens:,} / {u.output_tokens:,}")
        transcript.append(f"\n---\n{session_cost()}\n")
        if args.save:
            RUNS.mkdir(parents=True, exist_ok=True)
            stem = RUNS / f"{datetime.now():%Y%m%d-%H%M}-{args.save}"
            stem.with_suffix(".jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in records),
                encoding="utf-8",
            )
            stem.with_suffix(".md").write_text(
                f"# try_turn · {args.save}\n\n" + "\n".join(transcript), encoding="utf-8"
            )
            print(f"\nsalvo em {stem}.md e .jsonl")


if __name__ == "__main__":
    # Quiet the in-process MCP server; keep the agents' fallback warnings visible.
    logging.basicConfig(level=logging.WARNING, format="  ⚠ %(name)s: %(message)s")
    for noisy in ("mcp", "mcp.server", "mcp.server.lowlevel.server"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offer", default="o que você oferece")
    parser.add_argument("--audience", default="quem compra de você")
    parser.add_argument("--sector", default="seu ramo")
    parser.add_argument("--quiet", action="store_true", help="hide per-turn diagnostics")
    parser.add_argument("--save", metavar="LABEL", help="save transcript and steps")
    parser.add_argument(
        "--scenario", metavar="NAME", help="scripts/scenarios/NAME.yaml (onboarding + answers)"
    )
    asyncio.run(main(parser.parse_args()))
