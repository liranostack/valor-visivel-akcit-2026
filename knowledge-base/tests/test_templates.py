"""Synthesis templates: structure only (sections, fact markers, gaps section)."""

import re
from pathlib import Path

import pytest

TEMPLATES = sorted((Path(__file__).resolve().parents[1] / "templates").glob("*.md"))


def test_clarity_map_exists() -> None:
    assert any(t.name == "clarity_map.md" for t in TEMPLATES)


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.stem)
def test_template_structure(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    sections = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    assert len(sections) >= 3
    assert sections[-1] == "Lacunas e hipóteses"
    assert "[fact:" in text, "instructions must require [fact:<id>] on every claim"
    for name in sections:
        body = text.split(f"## {name}", 1)[1].split("\n## ", 1)[0]
        assert "<!--" in body, f"section {name!r} needs instructions for the Synthesizer"


def test_clarity_map_opens_with_a_reading_to_confirm() -> None:
    """The map opens
    with one reading built from cited facts, framed as a question to her (A.06.13)."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "templates" / "clarity_map.md").read_text(
        encoding="utf-8"
    )
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings[0] == "## Uma leitura para você conferir"


def test_method_reference_from_the_lead_is_in_the_kb() -> None:
    from pathlib import Path

    method = Path(__file__).resolve().parents[1] / "method"
    for name in ("concepts.md", "voice.md"):
        assert (method / name).exists()
    voice = (method / "voice.md").read_text(encoding="utf-8")
    assert voice.strip()
