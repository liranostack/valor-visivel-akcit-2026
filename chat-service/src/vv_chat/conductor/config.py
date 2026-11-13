"""Conductor configuration loaded from chat-service/config/conductor.yaml."""

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, Field, model_validator
from vv_contracts.common import LAYERS_ORDER, LayerId

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "config" / "conductor.yaml"


class ConductorConfig(BaseModel):
    max_attempts_per_stage: int = Field(default=2, ge=1)
    abc_options_on_attempt: int = Field(default=2, ge=1)
    deepen_below_score: int = Field(default=3, ge=1, le=5)
    advance_min_fact_score: int = Field(default=3, ge=1, le=5)
    resume_gaps_before_synthesis: bool = True
    layer_review_enabled: bool = True
    require_hidden_or_blind_fact: list[LayerId] = Field(default_factory=lambda: ["singularity"])
    layers_order: list[LayerId] = Field(default_factory=lambda: list(LAYERS_ORDER))
    # stage id -> what the first question of that stage must go after (Investigator focus)
    focus_on_stage_entry: dict[str, Literal["limit"]] = Field(
        default_factory=lambda: {"clarity.routine": "limit"}
    )

    @model_validator(mode="after")
    def _abc_within_attempts(self) -> Self:
        if self.abc_options_on_attempt > self.max_attempts_per_stage:
            raise ValueError("abc_options_on_attempt cannot exceed max_attempts_per_stage")
        return self


def load_config(path: Path = DEFAULT_PATH) -> ConductorConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ConductorConfig.model_validate(data.get("conductor", {}))
