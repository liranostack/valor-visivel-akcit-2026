"""Moderator: frames the Investigator's question for her (context, voice, ABC options).

Large model (ADR-011). Deterministic guards after the model: options appear only when the
Conductor asked for them and A/B must cite facts of this session; anything flagged by
check_output (e.g. an unsourced percentage) is removed; a reply with more than one question
falls back to the draft. Any model failure sends the Investigator's draft as is.
Source: PRD MOD-01..05, reference/ts-engine/conversation.ts (modes and ABC).
"""

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass

from pydantic import BaseModel, Field
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process
from vv_contracts.agents import AbcOption, FramedMessage, QuestionDraft
from vv_contracts.common import LayerId, NonEmptyStr
from vv_contracts.ports import ToolGateway
from vv_contracts.state import Fact
from vv_contracts.tools import CheckOutputIn, ListFactsIn

from vv_chat.agents.llm import StructuredLLM
from vv_chat.agents.modes import INSTRUCTIONS, Mode, mode_for, opener
from vv_chat.prompts import load_prompt
from vv_chat.style import no_em_dash, one_question

log = logging.getLogger(__name__)

PROMPT = "moderator"
LOCAL_NUMBER_CHECK = re.compile(r"\d+\s*%|\d+\s*(vezes|x)\b", re.IGNORECASE)
BACK_TO_TOPIC = "Isso é importante, mas agora quero voltar para {stage}."


class ModerateContext(BaseModel):
    session_id: NonEmptyStr
    layer_id: LayerId
    stage_title: str
    draft: QuestionDraft
    attempt: int = Field(ge=0)
    offer_abc_options: bool
    last_answer: str = ""
    sector: str = ""
    off_topic: bool = False
    difficulty_signals: list[str] = Field(default_factory=list[str])
    progress: str | None = None
    mode: Mode = "advance"


@dataclass(frozen=True)
class Moderation:
    message: FramedMessage
    used_fallback: bool
    prompt_version: str
    abc_dropped: bool = False
    removed: tuple[str, ...] = ()
    fallback_reason: str | None = None


async def moderate(
    context: ModerateContext, gateway: ToolGateway, llm: StructuredLLM
) -> Moderation:
    facts = (
        await gateway.list_facts(
            ListFactsIn(session_id=context.session_id, layer_id=context.layer_id)
        )
    ).facts
    prompt = load_prompt(PROMPT)
    try:
        framed = await llm.generate(prompt.text, _user_prompt(context, facts), FramedMessage)
        used_fallback, fallback_reason = False, None
    except Exception as exc:  # the draft is a safe message on its own
        fallback_reason = f"{type(exc).__name__}: {str(exc)[:300]}"
        log.warning("moderator fallback: %s", fallback_reason)
        framed = FramedMessage(
            context_line=opener(context.mode, context.attempt, context.layer_id),
            question=context.draft.question,
        )
        used_fallback = True

    if framed.question.count("?") != 1:
        framed = framed.model_copy(update={"question": context.draft.question})
    # The draft itself may carry two questions or end in an instruction (round 4, A.06.17).
    framed = framed.model_copy(update={"question": one_question(framed.question)})

    abc_dropped = False
    known = {f.fact_id for f in facts}
    if not context.offer_abc_options:
        framed = framed.model_copy(update={"abc_options": None})
    elif (
        framed.abc_options is not None
        and not all(set(o.references_fact_ids) <= known for o in framed.abc_options)
        or framed.abc_options is not None
        and not _grounded(framed.abc_options, facts)
    ):
        framed = framed.model_copy(update={"abc_options": None})
        abc_dropped = True

    framed, removed = await _drop_flagged(framed, context, gateway)
    if removed and "options" in removed:
        abc_dropped = True
    framed = _voice(framed)
    # vv rhythm (A.06.16): every turn acknowledges the useful part of her answer and shows the
    # gap before the question; a missing line gets the vv opener for this mode.
    if not framed.context_line:
        line = (
            BACK_TO_TOPIC.format(stage=context.stage_title)
            if context.off_topic
            else opener(context.mode, context.attempt, context.layer_id)
        )
        framed = framed.model_copy(update={"context_line": line})
    return Moderation(framed, used_fallback, prompt.version, abc_dropped, removed, fallback_reason)


def _voice(framed: FramedMessage) -> FramedMessage:
    """No long dash in anything she reads (voice guide)."""
    options = (
        [o.model_copy(update={"text": no_em_dash(o.text)}) for o in framed.abc_options]
        if framed.abc_options
        else None
    )
    return framed.model_copy(
        update={
            "question": no_em_dash(framed.question),
            "context_line": no_em_dash(framed.context_line) if framed.context_line else None,
            "abc_options": options,
        }
    )


# A and B must reword what the cited facts say. Calibrated on the simulated runs: rewordings
# score 71-95, options that add a motive, step or technique score 41-54 (A.06.11).
ABC_GROUNDING_MIN = 65


def _grounded(options: list[AbcOption], facts: list[Fact]) -> bool:
    by_id = {f.fact_id: f for f in facts}
    for option in options:
        if option.label == "C":
            continue
        cited = [by_id[i] for i in option.references_fact_ids if i in by_id]
        if not cited:
            return False
        source = " ".join(f"{f.text} {f.source_excerpt}" for f in cited)
        score = fuzz.token_set_ratio(option.text, source, processor=default_process)
        if score < ABC_GROUNDING_MIN:
            return False
    return True


def render_text(message: FramedMessage) -> str:
    return "".join(iter_text(message))


def iter_text(message: FramedMessage) -> Iterator[str]:
    """Pieces in reading order, for the turn loop to stream after the output guardrail."""
    if message.context_line:
        yield message.context_line
        yield "\n\n"
    yield message.question
    if message.abc_options:
        yield "\n\n"
        yield "\n".join(f"{o.label}) {o.text}" for o in message.abc_options)


async def _drop_flagged(
    framed: FramedMessage, context: ModerateContext, gateway: ToolGateway
) -> tuple[FramedMessage, tuple[str, ...]]:
    removed: list[str] = []
    if framed.context_line and await _flagged(framed.context_line, context.sector, gateway):
        framed = framed.model_copy(update={"context_line": None})
        removed.append("context_line")
    if await _flagged(framed.question, context.sector, gateway):
        framed = framed.model_copy(update={"question": context.draft.question})
        removed.append("question")
    if framed.abc_options:
        options = "\n".join(o.text for o in framed.abc_options)
        if await _flagged(options, context.sector, gateway):
            framed = framed.model_copy(update={"abc_options": None})
            removed.append("options")
    return framed, tuple(removed)


async def _flagged(text: str, sector: str, gateway: ToolGateway) -> bool:
    try:
        out = await gateway.check_output(CheckOutputIn(text=text, sector=sector))
    except Exception as exc:  # checks unavailable: keep the strictest local rule
        log.warning("check_output unavailable: %s", type(exc).__name__)
        return bool(LOCAL_NUMBER_CHECK.search(text))
    return any(v.excerpt and v.excerpt in text for v in out.violations)


def _user_prompt(context: ModerateContext, facts: list[Fact]) -> str:
    fact_lines = "\n".join(f"- [{f.fact_id}] {f.text}" for f in facts) or "(none yet)"
    signals = ", ".join(context.difficulty_signals) or "none"
    turn = [
        f"Mode: {context.mode}. {INSTRUCTIONS[context.mode]}",
        f"Stage: {context.stage_title}",
        f"Attempt: {context.attempt}",
        f"Progress: {context.progress or 'unknown'}",
        f"Difficulty signals: {signals}",
        f"Options A, B, C required: {'yes' if context.offer_abc_options else 'no'}",
    ]
    if context.off_topic:
        turn.append("She drifted away from the topic in her last answer: bring her back.")
    return "\n\n".join(
        [
            f"<draft>\nAngle: {context.draft.angle}\nQuestion: {context.draft.question}\n</draft>",
            "<turn>\n" + "\n".join(turn) + "\n</turn>",
            f"<facts>\n{fact_lines}\n</facts>",
            f"<client_message>\n{context.last_answer}\n</client_message>",
        ]
    )


__all__ = ["ModerateContext", "Moderation", "mode_for", "moderate", "render_text"]
