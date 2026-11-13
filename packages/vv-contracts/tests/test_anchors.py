"""Anchors: one generic question per method angle (stage × angle), reference and fallback only."""

import pytest
from pydantic import ValidationError
from vv_contracts.kb import ANCHOR_PLACEHOLDERS, Anchor, StageSpec, fill_placeholders


def anchors(*angles: str) -> list[dict[str, str]]:
    return [{"angle": a, "question": f"Pergunta sobre {a} no {{seu_trabalho}}?"} for a in angles]


def stage(**overrides: object) -> StageSpec:
    data: dict[str, object] = {
        "stage_id": "clarity.routine",
        "title": "Rotina Operacional",
        "objective": "o",
        "extraction_focus": "f",
        "anchors": anchors("routine", "limit", "decision", "blind_spot"),
        "rescue_angles": ["routine", "limit"],
    }
    data.update(overrides)
    return StageSpec.model_validate(data)


def test_anchor_has_angle_and_question() -> None:
    a = Anchor(angle="proof", question="Como você sabe que o {seu_trabalho} funcionou?")
    assert a.angle == "proof"
    assert "fallback" in (Anchor.__doc__ or "")


def test_by_angle() -> None:
    s = stage()
    assert [a.angle for a in s.anchors_for("limit")] == ["limit"]
    assert s.anchors_for("proof") == []


def test_one_anchor_per_angle() -> None:
    with pytest.raises(ValidationError, match="duplicated"):
        stage(anchors=anchors("routine", "routine", "limit", "blind_spot"))


def test_every_rescue_angle_has_an_anchor() -> None:
    with pytest.raises(ValidationError, match="proof"):
        stage(rescue_angles=["proof"])


def test_blind_spot_anchor_required() -> None:
    with pytest.raises(ValidationError, match="blind_spot"):
        stage(anchors=anchors("routine", "limit", "decision"))


def test_unknown_placeholder_rejected() -> None:
    bad = anchors("routine", "limit", "blind_spot")
    bad[0]["question"] = "Como foi o último {nome_inventado}?"
    with pytest.raises(ValidationError, match="nome_inventado"):
        stage(anchors=bad)


def test_fill_placeholders_with_session_vocabulary() -> None:
    text = "O que acontece entre o pedido e o resultado do {seu_trabalho}?"
    assert fill_placeholders(text, {"seu_trabalho": "bolo de casamento"}).endswith(
        "do bolo de casamento?"
    )


def test_fill_placeholders_falls_back_to_defaults() -> None:
    text = " ".join("{" + p + "}" for p in ANCHOR_PLACEHOLDERS)
    filled = fill_placeholders(text, {})
    assert "{" not in filled
    assert filled == " ".join(ANCHOR_PLACEHOLDERS.values())
