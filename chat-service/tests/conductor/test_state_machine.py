"""Session state machine (ERD: onboarding → baseline → in_layer ×4 → [layer_review] →
pre_core_review → core_generation → completed)."""

import pytest
from vv_chat.conductor.state_machine import InvalidTransitionError, Position, next_position

LAYERS = ["clarity", "singularity", "translation", "sustainment"]


def at(status: str, layer: str | None = None) -> Position:
    return Position.model_validate({"status": status, "active_layer": layer})


def step(pos: Position, event: str, review: bool = True) -> Position:
    return next_position(pos, event, layer_review_enabled=review)  # type: ignore[arg-type]


class TestHappyPath:
    def test_full_journey_with_layer_review(self) -> None:
        pos = at("onboarding")
        pos = step(pos, "consent_given")
        assert pos == at("onboarding")
        pos = step(pos, "onboarding_done")
        assert pos == at("baseline")
        pos = step(pos, "baseline_saved")
        assert pos == at("in_layer", "clarity")
        for i, layer in enumerate(LAYERS):
            pos = step(pos, "layer_synthesized")
            assert pos == at("layer_review", layer)
            pos = step(pos, "review_approved")
            expected = at("in_layer", LAYERS[i + 1]) if i < 3 else at("pre_core_review")
            assert pos == expected
        pos = step(pos, "review_approved")
        assert pos == at("core_generation")
        pos = step(pos, "core_generated")
        assert pos == at("completed")

    def test_without_layer_review_goes_straight_to_next_layer(self) -> None:
        pos = at("in_layer", "clarity")
        pos = step(pos, "layer_synthesized", review=False)
        assert pos == at("in_layer", "singularity")

    def test_last_layer_without_review_goes_to_pre_core(self) -> None:
        pos = step(at("in_layer", "sustainment"), "layer_synthesized", review=False)
        assert pos == at("pre_core_review")


class TestAdjust:
    def test_adjust_keeps_layer_review(self) -> None:
        pos = at("layer_review", "translation")
        assert step(pos, "review_adjust") == pos

    def test_adjust_keeps_pre_core_review(self) -> None:
        assert step(at("pre_core_review"), "review_adjust") == at("pre_core_review")


class TestInvalid:
    @pytest.mark.parametrize(
        ("pos", "event"),
        [
            (at("onboarding"), "baseline_saved"),
            (at("baseline"), "layer_synthesized"),
            (at("in_layer", "clarity"), "review_approved"),
            (at("layer_review", "clarity"), "layer_synthesized"),
            (at("pre_core_review"), "core_generated"),
            (at("completed"), "review_approved"),
            (at("core_generation"), "review_adjust"),
        ],
    )
    def test_invalid_transitions_raise(self, pos: Position, event: str) -> None:
        with pytest.raises(InvalidTransitionError):
            step(pos, event)

    def test_in_layer_requires_active_layer(self) -> None:
        with pytest.raises(ValueError):
            at("in_layer")

    def test_status_outside_layers_has_no_layer(self) -> None:
        with pytest.raises(ValueError):
            at("pre_core_review", "clarity")


def test_layer_index_for_progress_indicator() -> None:
    assert at("in_layer", "translation").layer_index == 3
    assert at("pre_core_review").layer_index is None
