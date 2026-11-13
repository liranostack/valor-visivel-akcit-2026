"""Interpreter: scores the client's answer, extracts facts with her literal words, lists gaps.

Large model (ADR-011). Any model failure (error, timeout, invalid JSON) falls back to structural
heuristics so the turn never stops. Ported from reference/ts-engine: rubric.ts (classifyMessage,
heuristicClassification) and fact-selector.ts (literal excerpt check). The TS word lists of
"mechanism" and "effect" words were not ported: the fallback stays sector-neutral and never
invents facts.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Self

from pydantic import BaseModel, Field, ValidationError, model_validator
from vv_contracts.agents import ExtractedFact, InterpretationResult
from vv_contracts.common import LayerId, NonEmptyStr
from vv_contracts.kb import LayerSpec, StageSpec
from vv_contracts.ports import ToolGateway
from vv_contracts.tools import GetLayerSpecIn, GetMethodGuideIn

from vv_chat.agents.llm import StructuredLLM
from vv_chat.prompts import load_prompt

log = logging.getLogger(__name__)

PROMPT = "interpreter"
SEQUENCE = re.compile(r"\b(primeiro|depois|antes|em seguida|por fim|no final|quando|sempre que)\b")
DONT_KNOW = re.compile(r"\bn[aã]o sei\b")
MIN_DETAILED_WORDS = 12
MUCH_SHORTER = 3  # an answer this many times shorter than the previous one is a signal


class LenientFact(ExtractedFact):
    """Same schema for the model; an 'unknown' fact becomes a hypothesis instead of failing."""

    @model_validator(mode="after")
    def _unknown_is_hypothesis(self) -> Self:
        if self.finding_area == "unknown" and self.kind != "hypothesis":
            self.kind = "hypothesis"
        return self


class LenientInterpretation(InterpretationResult):
    """What the model fills; converted to the strict contract after small repairs."""

    facts: list[LenientFact] = Field(  # pyright: ignore[reportIncompatibleVariableOverride]
        default_factory=list[LenientFact],
        description="Facts found in this answer only. Empty when the answer is vague.",
    )

    def to_result(self) -> InterpretationResult:
        return InterpretationResult.model_validate(self.model_dump())


class InterpretContext(BaseModel):
    """What the Interpreter needs about the turn (the gateway supplies the method content)."""

    layer_id: LayerId
    stage_id: NonEmptyStr
    question: str = Field(default="", description="Question she was answering.")
    previous_answer_words: int | None = Field(default=None, ge=0)


@dataclass(frozen=True)
class Interpretation:
    result: InterpretationResult
    used_fallback: bool
    prompt_version: str
    dropped_facts: int = 0


async def interpret(
    message: str, context: InterpretContext, gateway: ToolGateway, llm: StructuredLLM
) -> Interpretation:
    layer = await gateway.get_layer_spec(GetLayerSpecIn(layer_id=context.layer_id))
    stage = _stage(layer, context.stage_id)
    guide = await _guide(gateway)
    prompt = load_prompt(PROMPT)
    user = _user_prompt(message, context, layer, stage, guide)
    raw: InterpretationResult | None = None
    for attempt in range(2):
        try:
            raw = (await llm.generate(prompt.text, user, LenientInterpretation)).to_result()
            break
        except ValidationError as exc:  # one retry with the validation error as feedback
            log.warning(
                "interpreter invalid output (attempt %d): %s", attempt + 1, exc.errors()[:1]
            )
            user += f"\n\nYour previous output was invalid: {exc.errors()[:3]}. Fix it."
        except Exception as exc:  # any other model failure keeps the turn alive
            log.warning("interpreter fallback: %s", type(exc).__name__)
            break
    if raw is None:
        return Interpretation(heuristic(message, context, stage), True, prompt.version)
    facts = [f for f in (_anchor_in_message(f, message) for f in raw.facts) if f]
    result = raw.model_copy(update={"facts": facts})
    return Interpretation(result, False, prompt.version, dropped_facts=len(raw.facts) - len(facts))


def heuristic(message: str, context: InterpretContext, stage: StageSpec) -> InterpretationResult:
    """Conservative, sector-neutral reading used when the model is unavailable. No facts."""
    text = _fold(message)
    words = len(message.split())
    dont_know = bool(DONT_KNOW.search(text))
    detailed = words >= MIN_DETAILED_WORDS and (
        bool(SEQUENCE.search(text)) or bool(re.search(r"\d", message))
    )
    if dont_know or words < 4:
        concreteness = 1
    elif detailed:
        concreteness = 3
    else:
        concreteness = 2
    signals: list[str] = []
    if dont_know:
        signals.append("respondeu 'não sei'")
    previous = context.previous_answer_words
    if previous and words * MUCH_SHORTER <= previous:
        signals.append("resposta bem mais curta que a anterior")
    return InterpretationResult(
        concreteness=concreteness,
        relevance=2 if concreteness < 3 else 3,  # structure cannot tell 'off topic'
        defensibility=1 if concreteness < 3 else 2,
        domain_fit=3,
        facts=[],
        gaps=[] if concreteness >= 3 else [stage.extraction_focus],
        generic_claims=[],
        difficulty_signals=signals,
        rationale="Heuristic fallback: model output unavailable; structure-only reading.",
    )


def _anchor_in_message(fact: ExtractedFact, message: str) -> ExtractedFact | None:
    """Keep a fact only if its excerpt is in the message; store the message's own characters."""
    tokens = fact.source_excerpt.split()
    if not tokens:
        return None
    pattern = r"\s+".join(re.escape(t) for t in tokens)
    match = re.search(pattern, message, flags=re.IGNORECASE)
    if match is None:
        return None
    return fact.model_copy(update={"source_excerpt": match.group(0)})


def _stage(layer: LayerSpec, stage_id: str) -> StageSpec:
    for stage in layer.stages:
        if stage.stage_id == stage_id:
            return stage
    raise KeyError(f"stage {stage_id!r} not in layer {layer.layer_id!r}")


async def _guide(gateway: ToolGateway) -> str:
    try:
        return (await gateway.get_method_guide(GetMethodGuideIn())).markdown.strip()
    except Exception as exc:  # the guide enriches the prompt; its absence must not stop the turn
        log.warning("guide guide unavailable: %s", type(exc).__name__)
        return ""


def _user_prompt(
    message: str, context: InterpretContext, layer: LayerSpec, stage: StageSpec, guide: str
) -> str:
    parts = [
        f"<layer>\n{layer.name}\nObjective: {layer.objective}\n"
        f"Success signal: {layer.success_signal}\n</layer>",
        f"<stage>\n{stage.title}\nObjective: {stage.objective}\n"
        f"Extraction focus: {stage.extraction_focus}\n</stage>",
        f"<question>\n{context.question}\n</question>",
    ]
    if guide:
        parts.append(f"<method_guide>\n{guide}\n</method_guide>")
    parts.append(f"<client_message>\n{message}\n</client_message>")
    return "\n\n".join(parts)


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()
