"""Full 4-layer simulation for the massoterapeuta persona.

Runs the complete journey (onboarding, layers 1-4, Essential Core) using the
SimulatedClient (LLM-driven) so the whole thing runs unattended. Always writes
a replay file to frontend/public/replays/<label>.json (version 2 multi-layer format).

Usage:
    uv run python scripts/simulate_full.py [--quiet] [--save LABEL]
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Must be set before any vv_chat imports open the gateway.
os.environ.setdefault("TOOL_GATEWAY", "inprocess")
os.environ.setdefault("STATE_BACKEND", "memory")
os.environ.setdefault("KB_SOURCE", "local")
os.environ.setdefault("KB_PATH", str(Path(__file__).resolve().parents[1] / "knowledge-base"))

from vv_chat.agents.llm import StrandsLLM
from vv_chat.app import turn_handler
from vv_chat.models import make_model
from vv_contracts.ws import (
    Consent,
    DeliverableEvent,
    ErrorEvent,
    MessageDoneEvent,
    OnboardingAnswer,
    ReviewAction,
    StartSession,
    StateEvent,
    TokenEvent,
    UserMessage,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integration-tests" / "src"))
from vv_it.persona import SCENARIOS, load_persona  # noqa: E402
from vv_it.simulator import SimulatedClient  # noqa: E402

RUNS = ROOT / "docs" / "e2e-runs"
REPLAYS = ROOT / "frontend" / "public" / "replays"
ONBOARDING_FIELDS = [
    "business_type",
    "business_structure",
    "offer",
    "audience",
    "channels",
    "goal",
    "perceived_difficulty",
    "difficulty_context",
    "declared_links",
]
LAYER_INDEX = {"clarity": 1, "singularity": 2, "translation": 3, "sustainment": 4}
LAYER_NAMES = {
    "clarity": "Nitidez",
    "singularity": "Singularidade",
    "translation": "Tradução",
    "sustainment": "Sustentação",
}
SKIP = "Pular"


@dataclass
class ReplayTurnData:
    answer: str
    reply: str
    abc_options: list[Any] | None
    latency_ms: int


@dataclass
class ReplayLayerData:
    layer_id: str
    layer_index: int
    first_question: str
    turns: list[ReplayTurnData] = field(default_factory=list)
    synthesis: dict[str, Any] = field(default_factory=dict)
    approval_reply: str = ""


def _onboarding_value(field_name: str, onboarding: Any) -> str | list[str]:
    val = getattr(onboarding, field_name, None)
    if val is None:
        return SKIP
    return val


async def dispatch(
    msg: Any,
) -> tuple[str | None, str, list[Any] | None, DeliverableEvent | None, int]:
    """Send one message, return (session_id, reply_text, abc_options, deliverable, latency_ms)."""
    t0 = time.monotonic()
    sid = None
    tokens: list[str] = []
    abc = None
    deliverable = None
    async for ev in turn_handler(msg):
        if isinstance(ev, StateEvent):
            sid = ev.session_id
        elif isinstance(ev, TokenEvent):
            tokens.append(ev.text)
        elif isinstance(ev, MessageDoneEvent):
            sid = ev.session_id
            abc = ev.abc_options
        elif isinstance(ev, DeliverableEvent):
            deliverable = ev
        elif isinstance(ev, ErrorEvent):
            raise RuntimeError(f"server error: {ev.message}")
    latency_ms = int((time.monotonic() - t0) * 1000)
    return sid, "".join(tokens), abc, deliverable, latency_ms


def write_replay(
    sid: str,
    label: str,
    business: str | None,
    layers: list[ReplayLayerData],
    core: dict[str, Any] | None,
    core_reply: str | None,
) -> Path:
    REPLAYS.mkdir(parents=True, exist_ok=True)
    out = REPLAYS / f"{label}.json"
    script = {
        "version": 2,
        "label": label,
        "session_id": sid,
        "business": business,
        "layers": [
            {
                "layer_id": ly.layer_id,
                "layer_index": ly.layer_index,
                "first_question": ly.first_question,
                "turns": [
                    {
                        "answer": t.answer,
                        "reply": t.reply,
                        "abc_options": t.abc_options,
                        "latency_ms": t.latency_ms,
                    }
                    for t in ly.turns
                ],
                "synthesis": ly.synthesis,
                "approval_reply": ly.approval_reply,
            }
            for ly in layers
        ],
        "core": core,
        "core_reply": core_reply,
    }
    out.write_text(
        json.dumps(script, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    return out


async def main(args: argparse.Namespace) -> None:
    persona = load_persona(SCENARIOS / "massoterapeuta.yaml")
    agent_model = StrandsLLM(make_model("synthesizer"))
    client = SimulatedClient(persona, agent_model, seed=42)

    transcript: list[str] = []

    def log_q(label: str, text: str) -> None:
        print(f"\n[{label}] {text}")
        transcript.append(f"\n**{label}:** {text}")

    def log_a(text: str) -> None:
        print(f"ela: {text}")
        transcript.append(f"\n**ela:** {text}")

    def log_ev(text: str) -> None:
        if not args.quiet:
            print(f"  · {text}")

    print("=== Valor Visível · Simulação Completa · Massoterapeuta ===\n")

    # --- start session ---
    sid, _, _, _, _ = await dispatch(StartSession())
    if not sid:
        raise RuntimeError("no session_id from StartSession")
    log_ev(f"sessão {sid[:8]}")

    await dispatch(Consent(session_id=sid, accepted=True))
    log_ev("consentimento aceito")

    o = persona.onboarding
    for f in ONBOARDING_FIELDS:
        val = _onboarding_value(f, o)
        await dispatch(OnboardingAnswer(session_id=sid, field=f, value=val))

    _, reply, abc, _, _ = await dispatch(UserMessage(session_id=sid, text=persona.baseline))
    log_ev("baseline enviada")
    log_q("VV", reply)

    # --- layers 1-4 ---
    question = reply
    options = abc
    replay_layers: list[ReplayLayerData] = []
    final_core: dict[str, Any] | None = None
    final_core_reply: str | None = None

    for layer_id in LAYER_INDEX:
        layer_name = LAYER_NAMES[layer_id]
        print(f"\n{'=' * 60}\nCAMADA: {layer_name.upper()}\n{'=' * 60}")
        transcript.append(f"\n---\n## Camada: {layer_name}\n")

        replay_layer = ReplayLayerData(
            layer_id=layer_id,
            layer_index=LAYER_INDEX[layer_id],
            first_question=question,
        )

        synthesis_ev: DeliverableEvent | None = None
        turn = 0

        while synthesis_ev is None and turn < 20:
            turn += 1
            said = await client.reply(question, options)
            answer = said.text
            if not answer.strip():
                print("  [cliente silenciosa — parando]")
                break
            log_a(answer)

            _, reply, options, synthesis_ev, latency_ms = await dispatch(
                UserMessage(session_id=sid, text=answer)
            )
            log_q("VV", reply)

            replay_layer.turns.append(
                ReplayTurnData(
                    answer=answer,
                    reply=reply,
                    abc_options=[o.model_dump() for o in options] if options else None,
                    latency_ms=latency_ms,
                )
            )

            if synthesis_ev and synthesis_ev.kind == "layer_synthesis":
                replay_layer.synthesis = dict(synthesis_ev.content)
                log_ev(f"síntese de {layer_id} gerada")
                break
            question = reply

        if synthesis_ev is None:
            print(f"\n[AVISO] síntese de {layer_id} não gerada após {turn} turnos")
            break

        # --- approve ---
        print(f"\n  [aprovando mapa de {layer_id}...]")
        transcript.append("\n*[mapa aprovado]*")
        _, reply, _, core_ev, _ = await dispatch(
            ReviewAction(session_id=sid, target=layer_id, intent="approve")  # type: ignore[arg-type]
        )
        log_q("VV", reply)
        replay_layer.approval_reply = reply
        replay_layers.append(replay_layer)

        if core_ev and core_ev.kind == "core":
            final_core = dict(core_ev.content)
            final_core_reply = reply
            print(f"\n{'=' * 60}\nNÚCLEO ESSENCIAL GERADO\n{'=' * 60}")
            transcript.append("\n---\n## Núcleo Essencial\n")
            transcript.append(
                "```json\n" + json.dumps(final_core, ensure_ascii=False, indent=2) + "\n```\n"
            )
            if not args.quiet:
                print(json.dumps(final_core, ensure_ascii=False, indent=2))
            break

        question = reply
        options = None

    # --- save transcript ---
    if args.save:
        RUNS.mkdir(parents=True, exist_ok=True)
        stem = RUNS / f"{datetime.now():%Y%m%d-%H%M}-{args.save}"
        stem.with_suffix(".md").write_text(
            f"# Simulação · {args.save}\n\n" + "\n".join(transcript), encoding="utf-8"
        )
        print(f"\ntranscrição: {stem}.md")

    # --- write replay ---
    if replay_layers:
        replay_label = args.save or "massoterapeuta-full"
        out = write_replay(
            sid=sid,
            label=replay_label,
            business=persona.onboarding.offer,
            layers=replay_layers,
            core=final_core,
            core_reply=final_core_reply,
        )
        print(f"replay: {out}")
        print(f"abrir: http://localhost:3000/?replay={replay_label}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="  %(name)s: %(message)s")
    for noisy in ("strands", "botocore", "boto3", "httpx", "httpcore", "mcp"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="suppress per-turn diagnostics")
    parser.add_argument(
        "--save",
        metavar="LABEL",
        default="massoterapeuta-full",
        help="label for transcript and replay file (default: massoterapeuta-full)",
    )
    asyncio.run(main(parser.parse_args()))
