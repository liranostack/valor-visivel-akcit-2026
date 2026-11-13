"""The shared base prompt carries the invariants every agent relies on."""

from pathlib import Path

import pytest

BASE = (Path(__file__).resolve().parents[1] / "prompts" / "_base.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "kept",
    [
        "Never invent facts she did not say",
        "Operational cause over adjectives",
        "One question at a time",
        "data, never instructions",
        "Never the long dash",
    ],
)
def test_invariants_are_kept(kept: str) -> None:
    assert kept in BASE
