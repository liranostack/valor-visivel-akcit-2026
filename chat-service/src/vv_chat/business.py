"""What she said about her business before the layers (onboarding and baseline), as lines the
agents can read and the Synthesizer can cite as [fact:<id>] (A.06.10).

Without this, the Investigator ignored the difficulty she named and the synthesis wrote "Ainda não
sabemos" about who buys from her, even though she had said it.
"""

import re
from collections.abc import Mapping
from typing import Literal

from vv_contracts.kb import fill_placeholders
from vv_contracts.state import Baseline, OnboardingAnswers, Session

BASELINE_ID = "baseline"

# id -> (English label for the prompts, OnboardingAnswers field)
_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("ob-sector", "sector", "business_type"),
    ("ob-structure", "business structure", "business_structure"),
    ("ob-offer", "what she sells", "offer"),
    ("ob-audience", "who buys, as she described it", "audience"),
    ("ob-channels", "how clients reach her", "channels"),
    ("ob-goal", "what she wants now", "goal"),
    ("ob-pain", "difficulty she named", "perceived_difficulty"),
    ("ob-pain-when", "when that difficulty shows up", "difficulty_context"),
)


def business_profile(session: Session, baseline: Baseline | None) -> dict[str, str]:
    """id -> "label: her words", only for what she answered."""
    profile: dict[str, str] = {}
    answers = session.onboarding
    if answers is not None:
        for pid, label, field in _FIELDS:
            value = getattr(answers, field)
            text = ", ".join(value) if isinstance(value, list) else (value or "")
            if text.strip():
                profile[pid] = f"{label}: {text.strip()}"
    if baseline is not None and baseline.statement.strip():
        profile[BASELINE_ID] = (
            "how she presents her business today, in her words before the conversation: "
            + baseline.statement.strip()
        )
    return profile


def render_profile(profile: dict[str, str]) -> str:
    return "\n".join(f"- [{pid}] {line}" for pid, line in profile.items()) or "(not known yet)"


def _mid_sentence(text: str) -> str:
    """Her words as they fit after "Você disse que": no trailing punctuation, no capital on the
    first word (acronyms keep theirs)."""
    word = text.strip().rstrip(".;:!?, ").strip()
    if len(word) > 1 and word[0].isupper() and not word[1].isupper():
        word = word[0].lower() + word[1:]
    return word


def opening_question(answers: OnboardingAnswers | None, anchor: str) -> str:
    """The first question of the journey. When she named a difficulty, it asks for its last
    episode, with her words: the generic routine anchor confused service businesses ("a última vez
    que você fez massagem") and spent a turn in every simulated run (A.06.12). Otherwise the
    layer's first anchor, filled with her vocabulary."""
    pain = (answers.perceived_difficulty or "").strip().rstrip(".;:!?, ") if answers else ""
    if not pain:
        return fill_placeholders(anchor, vocabulary(answers))
    # Quoted as she typed it: her words are often first person ("comparam meu preço…").
    when = _mid_sentence(answers.difficulty_context or "") if answers else ""
    said = f"“{pain}”" + (f", {when}" if when else "")
    return (
        f"Você disse que a dificuldade é {said}. Pensa na última vez que isso aconteceu: "
        "o que você disse, o que a pessoa respondeu e como terminou?"
    )


def vocabulary(answers: OnboardingAnswers | None) -> dict[str, str]:
    """Her words for the anchor placeholders (same mapping as the turn loop)."""
    if answers is None:
        return {}
    pairs = {
        "seu_trabalho": answers.offer,
        "sua_oferta": answers.offer,
        "a_cliente": answers.audience,
        "as_clientes": answers.audience,
        "setor": answers.business_type,
    }
    return {k: v for k, v in pairs.items() if v}


Focus = Literal["limit"]


def entry_focus(
    focus_by_stage: Mapping[str, Focus], stage_id: str, attempt: int, gap: str | None
) -> Focus | None:
    """What the first question of a stage must go after, from conductor.yaml
    (focus_on_stage_entry). The lead's pedido de limites asks every journey for the limits
    that protect the delivery; left to the Investigator, it was never asked (A.06.13)."""
    if gap is not None or attempt != 1:
        return None
    return focus_by_stage.get(stage_id)


READING_SECTION = "Uma leitura para você conferir"
LAYER_DONE = (
    "Fechamos esta parte. Leia a síntese ao lado e me diga se ela está fiel ao que você contou."
)
_FACT_REF = re.compile(r"\s*\[fact:[^\]\s]+\]")


CLOSING_TAIL = (
    "O mapa completo está ao lado. Ele está fiel ao que você vive, ou tem algo para ajustar?"
)


def map_reading(content: dict[str, str]) -> str | None:
    """The map's reading without citations, or None when the map has none."""
    reading = _FACT_REF.sub("", content.get(READING_SECTION, "")).strip()
    if not reading or reading.startswith("Ainda não"):
        return None
    return f"{READING_SECTION}: {reading}"


def closing_message(content: dict[str, str]) -> str:
    """The message that closes the layer brings the map's reading into the conversation, where
    she reads it first; without a reading, the usual closing line."""
    reading = map_reading(content)
    return f"{reading}\n\n{CLOSING_TAIL}" if reading else LAYER_DONE
