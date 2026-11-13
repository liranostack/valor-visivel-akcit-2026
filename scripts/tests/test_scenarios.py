"""Scripted scenarios for try_turn: same answers before and after a change (A.06.10)."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("scenario", ROOT / "scenario.py")
assert SPEC and SPEC.loader
scenario = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scenario)

FILES = sorted((ROOT / "scenarios").glob("*.yaml"))


def test_pastelaria_scenario_exists() -> None:
    assert any(f.stem == "pastelaria" for f in FILES)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_scenario_loads(path: Path) -> None:
    s = scenario.load(path)
    assert s.onboarding.offer
    assert s.baseline
    assert len(s.answers) >= 3 and all(a.strip() for a in s.answers)
