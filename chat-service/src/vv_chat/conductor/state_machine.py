"""Session state machine (ERD, 'Máquina de estados do Conductor').

onboarding → baseline → in_layer (clarity → singularity → translation → sustainment)
→ layer_review after each layer (if enabled) → pre_core_review → core_generation → completed.
Pure Python: no I/O, no model calls.
"""

from typing import Literal, Self

from pydantic import BaseModel, model_validator
from vv_contracts.common import LAYERS_ORDER, LayerId
from vv_contracts.state import SessionStatus

Event = Literal[
    "consent_given",
    "onboarding_done",
    "baseline_saved",
    "layer_synthesized",
    "review_approved",
    "review_adjust",
    "core_generated",
]

_LAYER_STATUSES: frozenset[SessionStatus] = frozenset({"in_layer", "layer_review"})


class InvalidTransitionError(ValueError):
    pass


class Position(BaseModel, frozen=True):
    status: SessionStatus
    active_layer: LayerId | None = None

    @model_validator(mode="after")
    def _layer_matches_status(self) -> Self:
        if self.status in _LAYER_STATUSES and self.active_layer is None:
            raise ValueError(f"status {self.status} requires active_layer")
        if self.status not in _LAYER_STATUSES and self.active_layer is not None:
            raise ValueError(f"status {self.status} has no active layer")
        return self

    @property
    def layer_index(self) -> int | None:
        """1..4 for the progress indicator ("camada n de 4")."""
        if self.active_layer is None:
            return None
        return LAYERS_ORDER.index(self.active_layer) + 1


def _after_layer(layer: LayerId) -> Position:
    i = LAYERS_ORDER.index(layer)
    if i + 1 < len(LAYERS_ORDER):
        return Position(status="in_layer", active_layer=LAYERS_ORDER[i + 1])
    return Position(status="pre_core_review")


def next_position(pos: Position, event: Event, *, layer_review_enabled: bool) -> Position:
    status, layer = pos.status, pos.active_layer
    match (status, event):
        case ("onboarding", "consent_given"):
            return pos
        case ("onboarding", "onboarding_done"):
            return Position(status="baseline")
        case ("baseline", "baseline_saved"):
            return Position(status="in_layer", active_layer=LAYERS_ORDER[0])
        case ("in_layer", "layer_synthesized") if layer is not None:
            if layer_review_enabled:
                return Position(status="layer_review", active_layer=layer)
            return _after_layer(layer)
        case ("layer_review", "review_approved") if layer is not None:
            return _after_layer(layer)
        case ("layer_review" | "pre_core_review", "review_adjust"):
            return pos
        case ("pre_core_review", "review_approved"):
            return Position(status="core_generation")
        case ("core_generation", "core_generated"):
            return Position(status="completed")
        case _:
            raise InvalidTransitionError(f"event {event!r} is not valid in status {status!r}")


# Name used by the backlog card interface (A.02.09).
next_status = next_position
