"""Run one journey in process (A.05.01): the real turn loop, in-memory MCP tools and state, the
simulated client answering, and every agent step recorded for the judges.

Covers the first layer (the demo scope): onboarding and baseline are loaded from the persona,
then the conversation runs until the layer synthesis, the client stops answering, or max_turns.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

from pydantic import BaseModel
from vv_chat.agents.llm import StructuredLLM
from vv_chat.business import opening_question
from vv_chat.conductor.config import load_config
from vv_chat.gateway.mcp import connect_in_memory
from vv_chat.guardrails import GuardrailClient, from_env
from vv_chat.turn import Role, TurnDeps, run_turn
from vv_contracts.common import LayerId
from vv_contracts.state import Turn
from vv_contracts.tools import (
    CreateSessionIn,
    GetLayerSpecIn,
    SaveBaselineIn,
    SaveTurnIn,
    UpdateSessionIn,
)
from vv_contracts.ws import DeliverableEvent, ErrorEvent, MessageDoneEvent, TokenEvent
from vv_mcp.kb import load_knowledge_base
from vv_mcp.repo_memory import InMemoryStateRepository
from vv_mcp.server import build_server

from vv_it.persona import Persona
from vv_it.simulator import SimulatedClient

T = TypeVar("T", bound=BaseModel)
AGENTS: tuple[Role, ...] = ("interpreter", "investigator", "moderator", "synthesizer")
Ended = Literal["layer_closed", "client_silent", "max_turns", "error"]


class FailingLLM:
    """Offline mode: every model call fails, so each agent takes its heuristic fallback."""

    async def generate(self, system: str, prompt: str, output: type[T]) -> T:
        raise RuntimeError("offline: no model")


@dataclass
class TurnRecord:
    seq: int
    question: str  # what Valor Visível showed before her answer
    answer: str
    reply: str  # what Valor Visível answered
    abc_options: list[dict[str, Any]] | None = None
    picked: str | None = None
    revealed: list[str] = field(default_factory=list[str])
    events: list[str] = field(default_factory=list[str])  # what the simulated client did
    steps: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    latency_ms: int = 0
    error: str | None = None


@dataclass
class JourneyRecord:
    persona: str
    session_id: str
    first_question: str
    turns: list[TurnRecord]
    facts: list[dict[str, Any]]
    gaps: list[dict[str, Any]]
    synthesis: dict[str, Any] | None
    ended: Ended


async def run_journey(
    persona: Persona,
    client: SimulatedClient,
    *,
    agent_llm: StructuredLLM | None = None,
    llms: dict[Role, StructuredLLM] | None = None,
    guardrails: GuardrailClient | None = None,
    max_turns: int = 14,
    layer_id: LayerId = "clarity",
) -> JourneyRecord:
    if llms is None:
        if agent_llm is None:
            raise ValueError("pass llms or agent_llm")
        llms = {role: agent_llm for role in AGENTS}
    repo = InMemoryStateRepository()
    server = build_server(repo, load_knowledge_base())
    async with connect_in_memory(server) as gw:
        sid = (await gw.create_session(CreateSessionIn())).session_id
        layer = await gw.get_layer_spec(GetLayerSpecIn(layer_id=layer_id))
        stage = layer.stages[0]
        if persona.baseline:
            await gw.save_baseline(SaveBaselineIn(session_id=sid, statement=persona.baseline))
        await gw.update_session(
            UpdateSessionIn(
                session_id=sid,
                status="in_layer",
                active_layer=layer.layer_id,
                active_stage=stage.stage_id,
                onboarding=persona.onboarding,
            )
        )
        first = opening_question(persona.onboarding, stage.anchors[0].question)
        await gw.save_turn(
            SaveTurnIn(session_id=sid, turn=Turn(seq=1, user_message="", question_asked=first))
        )
        steps: list[dict[str, Any]] = []
        deps = TurnDeps(
            gateway=gw,
            llms=llms,
            guardrails=guardrails or from_env(),
            config=load_config(),
            on_step=lambda step, data: steps.append({"step": step, "data": data}),
        )

        turns: list[TurnRecord] = []
        synthesis: dict[str, Any] | None = None
        question, options = first, None
        ended: Ended = "max_turns"
        for seq in range(2, max_turns + 2):
            said = await client.reply(question, options)
            if not said.text.strip():
                ended = "client_silent"
                break
            steps.clear()
            record = TurnRecord(
                seq=seq,
                question=question,
                answer=said.text,
                reply="",
                picked=said.picked,
                revealed=said.revealed,
                events=list(client.last_events),
            )
            tokens: list[str] = []
            t0 = time.monotonic()
            async for event in run_turn(sid, said.text, deps):
                if isinstance(event, TokenEvent):
                    tokens.append(event.text)
                elif isinstance(event, MessageDoneEvent):
                    options = event.abc_options
                    record.abc_options = (
                        [o.model_dump() for o in event.abc_options] if event.abc_options else None
                    )
                elif isinstance(event, DeliverableEvent) and event.kind == "layer_synthesis":
                    synthesis = {"content": event.content}
                elif isinstance(event, ErrorEvent):
                    record.error = event.message
            record.latency_ms = int((time.monotonic() - t0) * 1000)
            record.reply = "".join(tokens)
            record.steps = list(steps)
            turns.append(record)
            question = record.reply
            if record.error:
                ended = "error"
                break
            if synthesis is not None:
                ended = "layer_closed"
                break

        stored = repo.latest_synthesis(sid, layer.layer_id)
        if stored is not None:
            synthesis = {
                "content": stored.content,
                "gaps": stored.gaps,
                "hypotheses": stored.hypotheses,
                "fact_refs": stored.fact_refs,
            }
        return JourneyRecord(
            persona=persona.slug,
            session_id=sid,
            first_question=first,
            turns=turns,
            facts=[f.model_dump(mode="json") for f in repo.list_facts(sid)],
            gaps=[g.model_dump(mode="json") for g in repo.list_gaps(sid)],
            synthesis=synthesis,
            ended=ended,
        )
