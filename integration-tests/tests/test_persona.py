"""Personas: who the simulated client is and what is true about her business (A.02.20)."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from vv_it.persona import SCENARIOS, Persona, load_all, load_persona

FILES = sorted(SCENARIOS.glob("*.yaml"))


def test_at_least_four_scenarios_plus_the_real_pastelaria() -> None:
    slugs = {p.stem for p in FILES}
    assert len(slugs) >= 5 and "pastelaria" in slugs


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_every_scenario_is_valid(path: Path) -> None:
    persona = load_persona(path)
    assert persona.slug == path.stem
    assert persona.onboarding.offer and persona.baseline
    assert persona.truth_ids("hidden") and persona.truth_ids("external")
    assert len(persona.scripted_answers) >= 3


def test_load_all_filters_by_slug() -> None:
    assert [p.slug for p in load_all(["pastelaria"])] == ["pastelaria"]


def test_truth_ids_must_be_unique() -> None:
    data = load_persona(SCENARIOS / "pastelaria.yaml").model_dump()
    data["truths"].append(dict(data["truths"][0]))
    with pytest.raises(ValidationError):
        Persona.model_validate(data)


def test_a_persona_needs_hidden_and_external_truths() -> None:
    data = load_persona(SCENARIOS / "pastelaria.yaml").model_dump()
    data["truths"] = [t for t in data["truths"] if t["kind"] != "external"]
    with pytest.raises(ValidationError):
        Persona.model_validate(data)


def test_behavior_defaults_are_neutral() -> None:
    from vv_it.persona import Behavior

    b = Behavior()
    assert b.confidence == "medium" and b.confusion == 0 and b.digression == 0


def test_behavior_chances_are_probabilities() -> None:
    from vv_it.persona import Behavior

    with pytest.raises(ValidationError):
        Behavior(confusion=1.5)


def test_scenarios_cover_different_behaviors() -> None:
    personas = load_all()
    assert {p.behavior.confidence for p in personas} == {"low", "medium", "high"}
    assert any(p.behavior.confusion >= 0.3 for p in personas)
    assert any(p.behavior.irritation > 0 for p in personas)
