"""Investigator: the next question, built from the pool's anchors and the facts she gave.

Large model (ADR-011). Deterministic guard: a question similar to one already asked
(rapidfuzz token-set ratio >= 80, accents and punctuation ignored) gets one retry; then an
unused anchor from the pool, filled with her vocabulary, is asked instead. The same fallback
covers any model failure. Ported from reference/ts-engine/conversation.ts (question part).
"""

import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process
from vv_contracts.agents import QuestionDraft
from vv_contracts.common import Angle, LayerId, NonEmptyStr
from vv_contracts.kb import Anchor, StageSpec, fill_placeholders
from vv_contracts.ports import ToolGateway
from vv_contracts.state import Fact
from vv_contracts.tools import GetLayerSpecIn, GetQuestionFromPoolIn, ListFactsIn

from vv_chat.agents.llm import StructuredLLM
from vv_chat.business import render_profile
from vv_chat.prompts import load_prompt

log = logging.getLogger(__name__)

PROMPT = "investigator"
REPEAT_THRESHOLD = 80.0
# Last resort when every anchor of the stage was already asked (neutral, any business model).
LAST_RESORT: tuple[tuple[Angle, str], ...] = (
    ("routine", "No último atendimento, o que a pessoa pediu e o que você fez primeiro?"),
    ("proof", "O que você viu acontecer depois, que mostra que deu certo?"),
    ("blind_spot", "O que eu ainda não perguntei sobre o {seu_trabalho} e você acha importante?"),
)


class NoNewQuestionError(RuntimeError):
    """Every candidate question was already asked: the turn loop should advance the stage."""


class InvestigateContext(BaseModel):
    session_id: NonEmptyStr
    layer_id: LayerId
    stage_id: NonEmptyStr
    attempt: int = Field(ge=0)
    asked_questions: list[str] = Field(default_factory=list[str])
    vocabulary: dict[str, str] = Field(default_factory=dict[str, str])
    gap: str | None = Field(default=None, description="Open gap to resume, if any.")
    profile: dict[str, str] = Field(
        default_factory=dict[str, str],
        description="What she said before the layers (onboarding, baseline): id -> line.",
    )
    focus: Literal["pain_episode", "limit"] | None = Field(
        default=None, description="Set by the turn loop: what this question must go after."
    )


@dataclass(frozen=True)
class Investigation:
    draft: QuestionDraft
    used_fallback: bool
    retried: bool
    prompt_version: str


FACT_ID_IN_TEXT = re.compile(r"\s*\[(?:fact:)?[0-9A-Za-z_-]{3,}\]")


def clean_question(text: str) -> str:
    """Remove fact ids the model sometimes writes inside the question."""
    cleaned = FACT_ID_IN_TEXT.sub("", text)
    return re.sub(r"\s+([,.;:?!])", r"\1", cleaned).strip()


def is_repeat(question: str, asked: Sequence[str]) -> bool:
    candidate = _normalize(question)
    return any(
        fuzz.token_set_ratio(candidate, _normalize(previous)) >= REPEAT_THRESHOLD
        for previous in asked
    )


async def investigate(
    context: InvestigateContext, gateway: ToolGateway, llm: StructuredLLM
) -> Investigation:
    layer = await gateway.get_layer_spec(GetLayerSpecIn(layer_id=context.layer_id))
    stage = next(s for s in layer.stages if s.stage_id == context.stage_id)
    pool = await gateway.get_question_from_pool(GetQuestionFromPoolIn(stage_id=stage.stage_id))
    facts = (
        await gateway.list_facts(
            ListFactsIn(session_id=context.session_id, layer_id=context.layer_id)
        )
    ).facts
    prompt = load_prompt(PROMPT)
    coverage = quadrant_coverage(facts)
    user = _user_prompt(context, stage, pool.anchors, facts, coverage)
    known_ids = {f.fact_id for f in facts}

    retried = False
    for attempt in range(2):
        try:
            draft = await llm.generate(prompt.text, user, QuestionDraft)
        except Exception as exc:  # any model failure falls back to the pool
            log.warning("investigator fallback: %s", type(exc).__name__)
            break
        draft = draft.model_copy(update={"question": clean_question(draft.question)})
        if not is_repeat(draft.question, context.asked_questions):
            refs = [i for i in draft.references_fact_ids if i in known_ids]
            draft = draft.model_copy(update={"references_fact_ids": refs})
            return Investigation(draft, False, retried, prompt.version)
        if attempt == 0:
            retried = True
            user += (
                f"\n\nYour previous question was too similar to one already asked: "
                f"{draft.question!r}. Ask something different, from another angle."
            )
    draft = fallback(context, stage, pool.anchors, prefer_blind=coverage["blind"] == 0)
    return Investigation(draft, True, retried, prompt.version)


def quadrant_coverage(facts: list[Fact]) -> dict[str, int]:
    """Facts of the layer per quadrant. 'blind' counts only reports with someone else as source
    (external_perception): her own observation about clients is not a blind-spot fact."""
    counts = {"open": 0, "hidden": 0, "blind": 0, "unknown": 0}
    for f in facts:
        if f.finding_area == "blind" and f.origin != "external_perception":
            continue
        counts[f.finding_area] += 1
    return counts


def fallback(
    context: InvestigateContext,
    stage: StageSpec,
    anchors: list[Anchor],
    prefer_blind: bool = False,
) -> QuestionDraft:
    """First unused anchor (blind spot first when the layer has no external perception, then the
    rescue angles), filled with her vocabulary."""
    by_angle = {a.angle: a for a in anchors}
    first: list[Angle] = ["blind_spot"] if prefer_blind else []
    ordered = [by_angle[a] for a in [*first, *stage.rescue_angles] if a in by_angle]
    ordered += [a for a in anchors if a not in ordered]
    candidates: list[tuple[Angle, str]] = [(a.angle, a.question) for a in ordered]
    candidates += LAST_RESORT
    for angle, text in candidates:
        question = fill_placeholders(text, context.vocabulary)
        if not is_repeat(question, context.asked_questions):
            return QuestionDraft(question=question, angle=angle)
    raise NoNewQuestionError(stage.stage_id)


def _user_prompt(
    context: InvestigateContext,
    stage: StageSpec,
    anchors: list[Anchor],
    facts: list[Fact],
    coverage: dict[str, int],
) -> str:
    anchor_lines = "\n".join(f"- {a.angle}: {a.question}" for a in anchors)
    fact_lines = "\n".join(f"- [{f.fact_id}] {f.text}" for f in facts) or "(none yet)"
    asked = "\n".join(f"- {q}" for q in context.asked_questions) or "(none yet)"
    vocab = "\n".join(f"- {k} = {v}" for k, v in context.vocabulary.items()) or "(not known yet)"
    parts = [
        f"<business>\n{render_profile(context.profile)}\n</business>",
        f"<stage>\n{stage.title}\nObjective: {stage.objective}\n"
        f"Extraction focus: {stage.extraction_focus}\nAttempt: {context.attempt}\n"
        f"Rescue angles: {', '.join(stage.rescue_angles)}\n</stage>",
        f"<anchors>\n{anchor_lines}\n</anchors>",
        f"<facts>\n{fact_lines}\n</facts>",
    ]
    if context.focus == "pain_episode":
        parts.append(
            "<priority>\nThis is the first question after the opening one. Ask for the last real "
            "episode of the difficulty she named ([ob-pain], in the situation [ob-pain-when]): "
            "what she said or sent, what the other person answered, how it ended. Use her words; "
            "one question, no examples of possible answers.\n</priority>"
        )
    if context.focus == "limit":
        parts.append(
            "<priority>\nAsk about a limit she keeps to protect the delivery (angle limit, target "
            "commitments): something she refuses, never skips, or always demands, even when it "
            "costs her a sale or time. Write ONE question, one sentence ending in '?', about the "
            "last time someone asked her for what she does not do, e.g. 'Qual foi a última vez "
            "que alguém te pediu algo que você não faz, e o que você respondeu?'. No second "
            "sentence, no examples of possible answers.\n</priority>"
        )
    cover = ", ".join(f"{k}: {v}" for k, v in coverage.items())
    if coverage["blind"] == 0 and context.focus is None:
        cover += (
            "\nNo report yet of what other people perceive (blind spot): prefer the blind_spot "
            "angle if the stage allows."
        )
    parts.append(f"<coverage>\n{cover}\n</coverage>")
    if context.gap:
        parts.append(f"<gap>\n{context.gap}\n</gap>")
    parts += [f"<vocabulary>\n{vocab}\n</vocabulary>", f"<asked>\n{asked}\n</asked>"]
    return "\n\n".join(parts)


def _normalize(text: str) -> str:
    stripped = "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )
    return default_process(stripped)
