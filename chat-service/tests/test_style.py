"""Voice guide rules enforced in code (leader's 'Guia de tom de voz', A.06.13)."""

from pathlib import Path

import pytest
from vv_chat.style import no_em_dash

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Você confere tudo — massa e recheio.", "Você confere tudo, massa e recheio."),
        ("o caixa—e o estoque", "o caixa, e o estoque"),
        ("— Começa assim", "Começa assim"),
        ("termina assim —", "termina assim"),
        ("de 3–4 semanas", "de 3–4 semanas"),  # an en dash in a range is not the long dash
        ("sem nada", "sem nada"),
    ],
)
def test_long_dash_becomes_a_comma(text: str, expected: str) -> None:
    assert no_em_dash(text) == expected


def test_no_double_comma() -> None:
    assert no_em_dash("isso, — aquilo") == "isso, aquilo"


def _user_facing_files() -> list[Path]:
    return [
        *sorted((ROOT / "chat-service" / "prompts").glob("*.md")),
        ROOT / "chat-service" / "config" / "onboarding.yaml",
        *sorted((ROOT / "knowledge-base" / "layers").glob("*.yaml")),
        *sorted((ROOT / "knowledge-base" / "templates").glob("*.md")),
        ROOT / "frontend" / "src" / "components" / "chat-shell.tsx",
    ]


@pytest.mark.parametrize("path", _user_facing_files(), ids=lambda p: p.name)
def test_our_own_texts_and_prompts_have_no_long_dash(path: Path) -> None:
    """The models imitate the style of their prompts and templates."""
    assert "—" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Round 4 (A.06.17): an instruction after the question.
        (
            "Tem algo que você se recusa a fazer? Me conta a última vez: o que você fez.",
            "Tem algo que você se recusa a fazer?",
        ),
        ("O que você recusa? Quando foi a última vez?", "O que você recusa?"),
        ("Me conta a última vez que isso aconteceu.", "Me conta a última vez que isso aconteceu?"),
        ("O que ela respondeu?", "O que ela respondeu?"),
    ],
)
def test_one_question_ending_in_a_question_mark(text: str, expected: str) -> None:
    from vv_chat.style import one_question

    assert one_question(text) == expected
