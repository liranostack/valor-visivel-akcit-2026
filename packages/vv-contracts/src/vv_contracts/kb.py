"""Knowledge-base schema (ERD, "Schema da knowledge base"). Content is pt-BR; keys are English."""

from string import Formatter
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

from vv_contracts.common import Angle, LayerId, NonEmptyStr

STAGE_ID_PATTERN = r"^(clarity|singularity|translation|sustainment)\.[a-z][a-z0-9_]*$"

# Placeholders keep anchors sector-neutral. The Investigator replaces them with the client's own
# words; the fallback path fills them from the session vocabulary or these neutral defaults.
ANCHOR_PLACEHOLDERS: dict[str, str] = {
    "a_cliente": "quem compra de você",
    "as_clientes": "as pessoas que compram de você",
    "seu_trabalho": "seu trabalho",
    "sua_oferta": "o que você oferece",
    "seu_negocio": "seu negócio",
    "setor": "seu ramo",
}


def placeholders_in(text: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(text) if name}


MAX_PLACEHOLDER_CHARS = 40  # a longer answer is a description, not a name to put mid-sentence


def placeholder_value(value: str) -> str | None:
    """Her word as it fits mid-sentence: no trailing punctuation, no capital on the first word
    (acronyms such as "TI" keep theirs); None when it is too long to read as a name."""
    word = value.strip().rstrip(".;:!?, ").strip()
    if not word or len(word) > MAX_PLACEHOLDER_CHARS:
        return None
    if len(word) > 1 and word[0].isupper() and not word[1].isupper():
        word = word[0].lower() + word[1:]
    return word


def fill_placeholders(text: str, vocabulary: dict[str, str]) -> str:
    """Fill anchor placeholders with the session vocabulary, falling back to neutral defaults."""
    hers = {k: placeholder_value(v) for k, v in vocabulary.items() if v}
    values = ANCHOR_PLACEHOLDERS | {k: v for k, v in hers.items() if v}
    return text.format_map(values)


class Anchor(BaseModel):
    """One generic question for one method angle: the method's reference and the safe fallback.

    Not a script: the Investigator formulates the real question from what the client said.
    Written for any business model (product, service, B2B, online), without presupposing a
    differential, using only the placeholders in ANCHOR_PLACEHOLDERS.
    """

    angle: Angle = Field(description="Method angle this anchor explores.")
    question: NonEmptyStr = Field(description="One generic question in pt-BR, with placeholders.")

    @field_validator("question")
    @classmethod
    def _known_placeholders(cls, question: str) -> str:
        unknown = placeholders_in(question) - ANCHOR_PLACEHOLDERS.keys()
        if unknown:
            raise ValueError(f"unknown placeholders {sorted(unknown)} in {question!r}")
        return question


class StageSpec(BaseModel):
    """One stage of a layer: what to find out, plus one anchor per method angle."""

    stage_id: str = Field(pattern=STAGE_ID_PATTERN, description="'<layer_id>.<snake_case>'.")
    title: NonEmptyStr = Field(description="Stage name in pt-BR.")
    objective: NonEmptyStr = Field(description="What this stage must find out, pt-BR.")
    extraction_focus: NonEmptyStr = Field(description="The kind of fact to extract, pt-BR.")
    anchors: list[Anchor] = Field(
        min_length=1,
        description="At most one anchor per angle; blind_spot is mandatory (method blind area).",
    )
    rescue_angles: list[Angle] = Field(
        default_factory=list[Angle],
        description="Angles to try, in order, when answers stay vague. Each must have an anchor.",
    )

    @model_validator(mode="after")
    def _angles(self) -> Self:
        angles = [a.angle for a in self.anchors]
        duplicated = sorted({a for a in angles if angles.count(a) > 1})
        if duplicated:
            raise ValueError(f"duplicated anchor angles {duplicated} in {self.stage_id}")
        if "blind_spot" not in angles:
            raise ValueError(f"{self.stage_id} needs a blind_spot anchor")
        missing = [a for a in self.rescue_angles if a not in angles]
        if missing:
            raise ValueError(f"rescue angles without anchor {missing} in {self.stage_id}")
        return self

    def anchors_for(self, angle: Angle) -> list[Anchor]:
        return [a for a in self.anchors if a.angle == angle]


class LayerSpec(BaseModel):
    layer_id: LayerId
    order: int = Field(ge=1, le=4)
    name: NonEmptyStr
    objective: NonEmptyStr
    pain_to_solve: NonEmptyStr
    success_signal: NonEmptyStr
    closure_criteria: NonEmptyStr
    synthesis_template: NonEmptyStr
    stages: list[StageSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _stages_belong_and_unique(self) -> Self:
        ids = [s.stage_id for s in self.stages]
        if len(ids) != len(set(ids)):
            raise ValueError("stage ids must be unique")
        wrong = [i for i in ids if not i.startswith(f"{self.layer_id}.")]
        if wrong:
            raise ValueError(f"stages {wrong} do not belong to layer {self.layer_id}")
        return self
