"""LLM judges (A.02.21): the conversation judge scores the method metrics and checks the persona's
truths; the reasoning auditor reads each agent's steps and proposes file-level improvements."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from vv_chat.agents.llm import StructuredLLM

from vv_it.journey import JourneyRecord
from vv_it.persona import Persona

HERE = Path(__file__).parent
REPO = Path(__file__).resolve().parents[4]
GUIDE = REPO / "knowledge-base" / "guide" / "guide.md"
VOICE = REPO / "knowledge-base" / "method" / "voice.md"
EDITABLE_FILES = (
    "chat-service/prompts/_base.md",
    "chat-service/prompts/interpreter.md",
    "chat-service/prompts/investigator.md",
    "chat-service/prompts/moderator.md",
    "chat-service/prompts/synthesizer_layer.md",
    "chat-service/config/conductor.yaml",
    "knowledge-base/layers/clarity.yaml",
    "knowledge-base/templates/clarity_map.md",
    "knowledge-base/guide/guide.md",
)
CODE_FILES = (
    "chat-service/src/vv_chat/conductor/rules.py",
    "chat-service/src/vv_chat/conductor/state_machine.py",
    "chat-service/src/vv_chat/turn.py",
    "chat-service/src/vv_chat/agents/interpreter.py",
    "chat-service/src/vv_chat/agents/investigator.py",
    "chat-service/src/vv_chat/agents/moderator.py",
    "chat-service/src/vv_chat/agents/synthesizer.py",
)
STEP_CHARS = 2500  # per step, to keep the auditor's prompt bounded


class MetricScore(BaseModel):
    metric: str
    score: float
    evidence_turns: list[int] = Field(default_factory=list[int])
    rationale: str


class TruthCheck(BaseModel):
    truth_id: str
    surfaced: Literal["fact", "synthesis", "mentioned_only", "missed"]
    note: str = ""


class ConversationVerdict(BaseModel):
    metrics: list[MetricScore]
    truths: list[TruthCheck]
    summary: str = Field(description="Two or three sentences, pt-BR.")


class Issue(BaseModel):
    turn: int
    agent: Literal["interpreter", "conductor", "investigator", "moderator", "synthesizer"]
    problem: str
    evidence: str


class Improvement(BaseModel):
    target: Literal["prompt", "kb", "conductor_config", "code"]
    file: str
    problem: str
    proposal: str
    evidence_turns: list[int] = Field(default_factory=list[int])
    impact: Literal["high", "medium", "low"]


class ReasoningVerdict(BaseModel):
    issues: list[Issue]
    improvements: list[Improvement]


def guide_rules() -> str:
    """The guide's preamble (classification rule, common pitfalls, per-layer use): the same
    source the Moderator applies."""
    text = GUIDE.read_text(encoding="utf-8")
    return text.split("\n## open", 1)[0].strip()


def render_truths(persona: Persona) -> str:
    return "\n".join(f"- [{t.id}] ({t.kind}) {t.text}" for t in persona.truths)


def render_transcript(record: JourneyRecord, *, with_steps: bool = False) -> str:
    lines = [f"[turno 1] Valor Visível: {record.first_question}"]
    for t in record.turns:
        picked = f" (clicou {t.picked})" if t.picked else ""
        did = f" [comportamento: {', '.join(t.events)}]" if t.events else ""
        lines.append(f"[turno {t.seq}] Cliente{picked}{did}: {t.answer}")
        if with_steps:
            for s in t.steps:
                data = json.dumps(s["data"], ensure_ascii=False, default=str)
                lines.append(f"    <{s['step']}> {data[:STEP_CHARS]}")
        lines.append(f"[turno {t.seq}] Valor Visível: {t.reply}")
    return "\n".join(lines)


def _synthesis(record: JourneyRecord) -> str:
    if not record.synthesis:
        return "(the layer did not close: no synthesis)"
    return json.dumps(record.synthesis, ensure_ascii=False, indent=1, default=str)


def _facts(record: JourneyRecord) -> str:
    return (
        "\n".join(
            f"- [{f['fact_id']}] ({f['finding_area']}, {f['origin']}, {f['kind']}) "
            f'{f["text"]} — "{f["source_excerpt"]}"'
            for f in record.facts
        )
        or "(none)"
    )


def _context(record: JourneyRecord, persona: Persona) -> list[str]:
    onboarding: dict[str, Any] = persona.onboarding.model_dump(exclude_none=True)
    return [
        f"<onboarding>\n{json.dumps(onboarding, ensure_ascii=False)}\n</onboarding>",
        f"<baseline>\n{persona.baseline}\n</baseline>",
        f"<truth_sheet>\n{render_truths(persona)}\n</truth_sheet>",
        f"<facts_recorded>\n{_facts(record)}\n</facts_recorded>",
        f"<synthesis>\n{_synthesis(record)}\n</synthesis>",
    ]


async def judge_conversation(
    record: JourneyRecord, persona: Persona, llm: StructuredLLM
) -> ConversationVerdict:
    system = (
        (HERE / "conversation.md")
        .read_text(encoding="utf-8")
        .format(guide=guide_rules(), voice=VOICE.read_text(encoding="utf-8"))
    )
    prompt = "\n\n".join(
        [*_context(record, persona), f"<transcript>\n{render_transcript(record)}\n</transcript>"]
    )
    verdict = await llm.generate(system, prompt, ConversationVerdict)
    scored = {t.id for t in persona.truths if t.kind in ("hidden", "external")}
    return verdict.model_copy(
        update={"truths": [t for t in verdict.truths if t.truth_id in scored]}
    )


def truth_recall(verdict: ConversationVerdict, persona: Persona) -> float:
    """Share of hidden and external truths that became a fact or reached the synthesis."""
    scored = persona.truth_ids("hidden") + persona.truth_ids("external")
    found = {t.truth_id for t in verdict.truths if t.surfaced in ("fact", "synthesis")}
    return len(found & set(scored)) / len(scored) if scored else 0.0


async def audit_reasoning(
    record: JourneyRecord, persona: Persona, llm: StructuredLLM
) -> ReasoningVerdict:
    files = "\n\n".join(
        f'<file path="{path}">\n{(REPO / path).read_text(encoding="utf-8")}\n</file>'
        for path in EDITABLE_FILES
        if (REPO / path).exists()
    )
    prompt = "\n\n".join(
        [
            *_context(record, persona),
            f"<transcript_with_steps>\n{render_transcript(record, with_steps=True)}\n"
            "</transcript_with_steps>",
            f"<files>\n{files}\n</files>",
            "<code_files>\n" + "\n".join(CODE_FILES) + "\n</code_files>",
        ]
    )
    system = (HERE / "reasoning.md").read_text(encoding="utf-8")
    verdict = await llm.generate(system, prompt, ReasoningVerdict)
    known = set(EDITABLE_FILES) | set(CODE_FILES)
    return verdict.model_copy(
        update={"improvements": [i for i in verdict.improvements if i.file in known]}
    )
