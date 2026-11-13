"""Personas for the simulated client (integration-tests/scenarios/<slug>.yaml).

Each persona says who she is, how she writes, her onboarding answers, her baseline and the
`truths` about her business. Truths are the ground truth the judge checks the journey against:
`hidden` (she does and never tells clients), `external` (what clients told her: blind material),
`routine` (ordinary facts) and `contradiction` (what she says vs what happens).
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator
from vv_contracts.state import OnboardingAnswers

SCENARIOS = Path(__file__).resolve().parents[2] / "scenarios"
TruthKind = Literal["hidden", "external", "routine", "contradiction"]


class Truth(BaseModel):
    id: str = Field(min_length=1)
    kind: TruthKind
    text: str = Field(min_length=1)
    reveal_when: str = ""  # what kind of question makes her tell it


class Behavior(BaseModel):
    """How she behaves in the conversation. Chances are drawn per answer (seeded per run), so a
    run is reproducible and the judge knows what happened on each turn."""

    confidence: Literal["low", "medium", "high"] = (
        "medium"  # low: hedges, undervalues; high: overclaims
    )
    confusion: float = Field(default=0.0, ge=0, le=1)  # misreads the question or asks "como assim?"
    digression: float = Field(default=0.0, ge=0, le=1)  # drifts into an unrelated story
    irritation: float = Field(default=0.0, ge=0, le=1)  # impatient when a question feels repeated
    verbosity: Literal["short", "medium", "long"] = "medium"


class Persona(BaseModel):
    slug: str = Field(min_length=1)
    who: str
    style: str
    onboarding: OnboardingAnswers
    baseline: str
    truths: list[Truth]
    vague_answers: int = Field(default=2, ge=0)
    behavior: Behavior = Field(default_factory=Behavior)
    scripted_answers: list[str] = Field(default_factory=list[str])

    @model_validator(mode="after")
    def _truths_are_usable(self) -> "Persona":
        ids = [t.id for t in self.truths]
        if len(ids) != len(set(ids)):
            raise ValueError("truth ids must be unique")
        if not self.truth_ids("hidden") or not self.truth_ids("external"):
            raise ValueError("a persona needs at least one hidden and one external truth")
        return self

    def truth_ids(self, kind: TruthKind) -> list[str]:
        return [t.id for t in self.truths if t.kind == kind]


def load_persona(path: Path) -> Persona:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Persona.model_validate({**data, "slug": path.stem})


def load_all(slugs: Iterable[str] | None = None, directory: Path = SCENARIOS) -> list[Persona]:
    wanted = set(slugs or [])
    return [
        load_persona(p) for p in sorted(directory.glob("*.yaml")) if not wanted or p.stem in wanted
    ]
