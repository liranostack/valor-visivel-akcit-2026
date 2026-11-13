"""Method guide: structure only (headings the tool slices by, the same subsections everywhere)."""

import re
from pathlib import Path

GUIDE = Path(__file__).resolve().parents[1] / "guide" / "guide.md"
QUADRANTS = ["open", "hidden", "blind", "unknown"]
SUBSECTIONS = [
    "No negócio",
    "Como reconhecer numa resposta",
    "Como chegar nele",
    "O que conta como evidência",
    "Armadilhas",
    "Na síntese",
]


def text() -> str:
    return GUIDE.read_text(encoding="utf-8")


def test_quadrant_headings_are_exact_and_ordered() -> None:
    assert re.findall(r"^## (\S+)$", text(), flags=re.MULTILINE) == QUADRANTS


def test_preamble_has_classification_rule_and_pitfalls() -> None:
    preamble = text().split("\n## ", 1)[0]
    assert "### Regra de classificação" in preamble
    assert "### Armadilhas comuns" in preamble
    assert "### Aplicação por camada" in preamble


def test_every_quadrant_has_the_six_subsections() -> None:
    body = text()
    for i, quadrant in enumerate(QUADRANTS):
        start = body.index(f"## {quadrant}\n")
        end = body.index(f"## {QUADRANTS[i + 1]}\n") if i + 1 < len(QUADRANTS) else len(body)
        found = re.findall(r"^### (.+)$", body[start:end], flags=re.MULTILINE)
        assert found == SUBSECTIONS, quadrant
