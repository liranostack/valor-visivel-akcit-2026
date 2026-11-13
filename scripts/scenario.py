"""Scripted scenarios for try_turn (scripts/scenarios/*.yaml): onboarding, baseline and answers."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from vv_contracts.state import OnboardingAnswers

SCENARIOS = Path(__file__).resolve().parent / "scenarios"


@dataclass(frozen=True)
class Scenario:
    onboarding: OnboardingAnswers
    baseline: str
    answers: list[str] = field(default_factory=list[str])


def load(path: Path) -> Scenario:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Scenario(
        onboarding=OnboardingAnswers.model_validate(data["onboarding"]),
        baseline=str(data.get("baseline", "")).strip(),
        answers=[str(a).strip() for a in data.get("answers", [])],
    )


def resolve(name: str) -> Path:
    """A scenario name ("pastelaria") or a path to a YAML file."""
    path = Path(name)
    return path if path.suffix in (".yaml", ".yml") else SCENARIOS / f"{name}.yaml"
