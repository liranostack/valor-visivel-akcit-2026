"""Structured outputs of the agents and of the Conductor (ERD, "Contratos dos agentes").

Field descriptions are part of the prompt: Strands sends this JSON Schema to the model as the
structured-output contract. Keep them short, in English, and explicit about pt-BR content.
"""

from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from vv_contracts.common import (
    Angle,
    DecisionAction,
    FactKind,
    FactOrigin,
    FindingArea,
    LayerId,
    NonEmptyStr,
    Score,
)

KIND_HELP = (
    "What the fact is. characteristic = something she does or how she works (a practice, "
    "a routine, a decision); benefit = what her client gains from it; evidence = proof that "
    "it happens (a number she reports, a client's words, recurrence, a result); hypothesis = "
    "plausible but not supported yet by what she said."
)
ORIGIN_HELP = (
    "Where it comes from. client_statement = she said it in this conversation; public_source "
    "= found on her public site (a clue, never proof); external_perception = what clients or "
    "others said about her, as she reported it; inference = your reading, to be confirmed."
)
QUADRANT_HELP = (
    "knowledge-area model. open = she already knows and communicates it; hidden = she knows it but "
    "does not communicate it because it seems ordinary (silent expertise: routines, criteria, "
    "care, backstage decisions); blind = others perceive it and she does not recognise it "
    "(praise, objections, client feedback); unknown = nobody has identified it yet, so it can "
    "only be a hypothesis."
)
SCORE_SCALE = "1 = absent, 2 = weak, 3 = enough to use, 4 = strong, 5 = excellent."
ANGLE_HELP = (
    "Angle of the question. routine = how a typical day or job unfolds; limit = what she "
    "refuses or will not do; avoided_error = a mistake she prevents and how; proof = how she "
    "knows it works; decision = how she chooses between options; blind_spot = what clients "
    "praise, ask for or complain about."
)


class ExtractedFact(BaseModel):
    """One fact the client stated about her business, kept with her exact words."""

    text: NonEmptyStr = Field(description="The fact as one short, concrete sentence in pt-BR.")
    source_excerpt: NonEmptyStr = Field(
        description=(
            "Exact words copied from the client's message that support the fact. "
            "Must be a literal substring of the message; never paraphrase."
        )
    )
    kind: FactKind = Field(description=KIND_HELP)
    origin: FactOrigin = Field(description=ORIGIN_HELP)
    finding_area: FindingArea = Field(description=QUADRANT_HELP)

    @model_validator(mode="after")
    def _unknown_is_hypothesis(self) -> Self:
        if self.finding_area == "unknown" and self.kind != "hypothesis":
            raise ValueError("facts in the 'unknown' quadrant can only be hypotheses")
        return self


class InterpretationScores(BaseModel):
    """Scores of the client's latest answer, judged against the active layer and stage."""

    concreteness: Score = Field(
        description=(
            "How concrete the answer is: observable actions, situations, examples instead of "
            f"adjectives like 'quality' or 'atendimento humanizado'. {SCORE_SCALE}"
        )
    )
    relevance: Score = Field(
        description=f"How well it answers the stage objective of the active layer. {SCORE_SCALE}"
    )
    defensibility: Score = Field(
        description=(
            "How hard it would be for a competitor to claim the same thing truthfully "
            f"(specific mechanism, proof, limit). {SCORE_SCALE}"
        )
    )
    domain_fit: Score = Field(
        description=f"How much it stays within her own business and sector. {SCORE_SCALE}"
    )


class InterpretationResult(InterpretationScores):
    """Interpreter output: scores, extracted facts and what is still missing."""

    facts: list[ExtractedFact] = Field(
        default_factory=list[ExtractedFact],
        description="Facts found in this answer only. Empty when the answer is vague.",
    )
    gaps: list[str] = Field(
        default_factory=list[str],
        description="What the stage needed and the answer did not give, one item each, pt-BR.",
    )
    generic_claims: list[str] = Field(
        default_factory=list[str],
        description="Generic expressions she used, copied verbatim (e.g. 'qualidade').",
    )
    difficulty_signals: list[str] = Field(
        default_factory=list[str],
        description=(
            "Signs of fatigue or difficulty in this answer: much shorter than before, "
            "'não sei' repeated, expressed irritation. Do not infer emotions beyond the text."
        ),
    )
    rationale: str = Field(
        default="", description="One or two sentences explaining the scores, in English."
    )


class Decision(BaseModel):
    """Produced by the Conductor (deterministic code), never by a model."""

    action: DecisionAction = Field(
        description=(
            "deepen = ask again on the same stage; advance = stage covered, move on; "
            "force_advance = attempts exhausted, move on and record a gap; resume_gap = one "
            "question to recover an open gap before the synthesis; synthesize = write the "
            "layer synthesis."
        )
    )
    next_stage_id: str | None = Field(description="Stage the next question belongs to, if any.")
    attempt: int = Field(ge=0, description="Attempt number of the next question on its stage.")
    offer_abc_options: bool = Field(
        description="True when the Moderator must offer options A, B and C."
    )
    gap_id: str | None = Field(default=None, description="Gap to resume (resume_gap only).")

    @model_validator(mode="after")
    def _resume_needs_gap(self) -> Self:
        if self.action == "resume_gap" and not self.gap_id:
            raise ValueError("resume_gap requires gap_id")
        return self


class QuestionDraft(BaseModel):
    """Investigator output: what to ask next (the Moderator decides how to say it)."""

    question: NonEmptyStr = Field(
        description=(
            "Exactly one question in pt-BR, in the client's vocabulary and sector, not "
            "equivalent to any question already asked."
        )
    )
    angle: Angle = Field(description=ANGLE_HELP)
    target: (
        Literal["hidden_practice", "external_perception", "operations", "commitments"] | None
    ) = Field(
        default=None,
        description=(
            "Decide before writing the question: what it goes after. hidden_practice = "
            "what she knows and does but never tells; external_perception = what others "
            "noticed and said; operations = how the business runs and sustains the delivery; "
            "commitments = limits and commitments that make the promise deliverable."
        ),
    )
    references_fact_ids: list[str] = Field(
        default_factory=list[str],
        description="Ids of facts she already gave that the question builds on.",
    )


class AbcOption(BaseModel):
    """One unblocking option offered after a vague answer."""

    label: Literal["A", "B", "C"] = Field(
        description="A and B = two plausible interpretations; C = answer freely or reject both."
    )
    text: NonEmptyStr = Field(
        description="The option in pt-BR, short, never suggesting facts she did not give."
    )
    references_fact_ids: list[str] = Field(
        default_factory=list[str],
        description="Facts that ground the option. Required for A and B, empty for C.",
    )

    @model_validator(mode="after")
    def _grounding(self) -> Self:
        if self.label in ("A", "B") and not self.references_fact_ids:
            raise ValueError("options A and B must be grounded in facts already given")
        if self.label == "C" and self.references_fact_ids:
            raise ValueError("option C is a free answer or rejection and cites no facts")
        return self


class FramedMessage(BaseModel):
    """Moderator output: the message the client reads (after the output guardrail)."""

    context_line: str | None = Field(
        default=None,
        description=(
            "Optional short sentence in pt-BR on why this question matters now, reusing what "
            "she said. No invented numbers, other users' opinions or promises."
        ),
    )
    question: NonEmptyStr = Field(
        description=(
            "The Investigator's question with adjusted clarity, tone and length, in pt-BR. "
            "Same intent, angle and facts; never a different question."
        )
    )
    abc_options: list[AbcOption] | None = Field(
        default=None,
        description="Exactly A, B, C in this order when offer_abc_options is true; else null.",
    )

    @field_validator("abc_options", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        return None if value == [] else value

    @model_validator(mode="after")
    def _abc_shape(self) -> Self:
        if self.abc_options is not None and [o.label for o in self.abc_options] != ["A", "B", "C"]:
            raise ValueError("abc_options must be exactly A, B, C in this order")
        return self


class LayerSynthesis(BaseModel):
    """Synthesizer output for one layer, following that layer's template."""

    layer_id: LayerId = Field(description="Layer this synthesis closes.")
    content: dict[str, str] = Field(
        description=(
            "Template section title -> Markdown in pt-BR. Every claim ends with [fact:<id>]."
        )
    )
    fact_refs: list[str] = Field(description="Ids of every fact cited in content.")
    gaps: list[str] = Field(
        default_factory=list[str], description="What remains unsupported, pt-BR."
    )
    hypotheses: list[str] = Field(
        default_factory=list[str],
        description="Plausible readings not yet supported by evidence, labelled as such.",
    )


class BeforeAfter(BaseModel):
    """The before/after comparison of the Essential Core (US08)."""

    said_before: NonEmptyStr = Field(description="Her baseline statement, exactly as typed.")
    sustained_discovery: NonEmptyStr = Field(
        description="What the investigation found and supported with facts, pt-BR."
    )
    now_able_to: NonEmptyStr = Field(
        description=(
            "What she can now explain, communicate or decide that she could not before. "
            "A merely stylistic rewrite of the sentence does not count."
        )
    )
    fact_refs: list[str] = Field(description="Facts that support the discovery.")


class ApplicationOutputs(BaseModel):
    """Ready-to-use copy formats derived from the full journey (all 4 layers)."""

    bio: str = Field(
        min_length=10,
        max_length=220,
        description=(
            "Professional bio in pt-BR, second person. Pattern: 'Ajudo {a_cliente} a {resultado} "
            "porque {mecanismo}', in her own words."
        ),
    )
    narrativa: str = Field(
        min_length=20,
        max_length=520,
        description=(
            "3-sentence sales narrative in pt-BR: (1) what she does and for whom, "
            "(2) the operational mechanism, (3) the perceived impact."
        ),
    )
    checklist: list[str] = Field(
        min_length=3,
        max_length=7,
        description="Priority actions, each 10-260 chars, pt-BR, based on the journey.",
    )
    whatsapp_pitch_curto: str = Field(
        min_length=10,
        max_length=300,
        description="Short informal pitch in pt-BR. Pattern: greeting + work + delivery + result.",
    )
    whatsapp_pitch_prova: str = Field(
        min_length=10,
        max_length=300,
        description=(
            "Pitch with proof sentence in pt-BR. Extends whatsapp_pitch_curto with evidence."
        ),
    )
    instagram_bio: str = Field(
        min_length=10,
        max_length=220,
        description="Instagram bio in pt-BR. Pattern: 'Como. Impacto.' — mechanism then effect.",
    )
    instagram_legenda_curta: str = Field(
        min_length=10,
        max_length=300,
        description=(
            "Short Instagram caption in pt-BR. Pattern: 'Bastidor real. Resultado.' "
            "— one backstage decision, one client result."
        ),
    )
    instagram_story_roteiro: list[str] = Field(
        min_length=3,
        max_length=5,
        description=(
            "Story cards in pt-BR, 3-5 items (10-260 chars each). "
            "Arc: Problema / Rotina real / Prova + Anti-cópia."
        ),
    )


class EssentialCoreOutput(BaseModel):
    """Synthesizer output for the Essential Core (final deliverable)."""

    content: dict[str, str] = Field(
        description="Template section title -> Markdown in pt-BR, with [fact:<id>] markers."
    )
    final_statement: NonEmptyStr = Field(
        description="Her new one-sentence value statement, reusing her own words, pt-BR."
    )
    before_after: BeforeAfter = Field(description="Comparison with the baseline.")
    action_plan_7d: list[NonEmptyStr] = Field(
        min_length=7,
        max_length=7,
        description="Exactly 7 small actions, one per day, applicable to her business, pt-BR.",
    )
    gaps: list[str] = Field(
        default_factory=list[str], description="Pending points she should still verify."
    )
    outputs: ApplicationOutputs = Field(
        description="Ready-to-use copy formats derived from the full journey."
    )


class PublicContext(BaseModel):
    """PublicResearcher output: how the business presents itself publicly. Clues, never proof."""

    summary: str = Field(description="At most 150 words in pt-BR, neutral, no judgement.")
    claims_to_verify: list[str] = Field(
        default_factory=list[str],
        description="Public claims to confirm or confront during the conversation, pt-BR.",
    )

    @model_validator(mode="after")
    def _max_words(self) -> Self:
        if len(self.summary.split()) > 150:
            raise ValueError("summary must have at most 150 words")
        return self
