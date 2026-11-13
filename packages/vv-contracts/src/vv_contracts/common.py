"""Literal types shared by every contract (ERD glossary)."""

from typing import Annotated, Literal

from pydantic import Field

LayerId = Literal["clarity", "singularity", "translation", "sustainment"]
LAYERS_ORDER: tuple[LayerId, ...] = ("clarity", "singularity", "translation", "sustainment")

FindingArea = Literal["open", "hidden", "blind", "unknown"]
FactKind = Literal["characteristic", "benefit", "evidence", "hypothesis"]
FactOrigin = Literal["client_statement", "public_source", "external_perception", "inference"]
Angle = Literal["routine", "limit", "avoided_error", "proof", "decision", "blind_spot"]
DecisionAction = Literal["deepen", "advance", "force_advance", "resume_gap", "synthesize"]
ReviewIntent = Literal["approve", "adjust", "doubt"]
ReviewTarget = Literal["clarity", "singularity", "translation", "sustainment", "pre_core"]
TemplateKind = Literal[
    "clarity", "singularity", "translation", "sustainment", "pre_core", "core", "action_plan"
]

Score = Annotated[int, Field(ge=1, le=5)]
NonEmptyStr = Annotated[str, Field(min_length=1)]
