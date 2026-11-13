"""Model factory: one Bedrock model per agent role, chosen in config/models.yaml."""

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from strands.models import BedrockModel

Size = Literal["large", "small"]
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "models.yaml"


class ModelsConfig(BaseModel):
    region: str = "us-east-1"
    sizes: dict[Size, str] = Field(
        default_factory=lambda: {
            "large": "us.anthropic.claude-sonnet-4-6",
            "small": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        }
    )
    roles: dict[str, Size] = Field(default_factory=dict[str, Size])


def load_models_config(path: Path = DEFAULT_PATH) -> ModelsConfig:
    cfg = ModelsConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    overrides: dict[Size, str] = {}
    if large := os.environ.get("MODEL_LARGE"):
        overrides["large"] = large
    if small := os.environ.get("MODEL_SMALL"):
        overrides["small"] = small
    region = os.environ.get("AWS_REGION", cfg.region)
    return cfg.model_copy(update={"sizes": cfg.sizes | overrides, "region": region})


def model_id_for(role: str, cfg: ModelsConfig) -> str:
    if role not in cfg.roles:
        raise KeyError(f"no model configured for role {role!r}")
    return cfg.sizes[cfg.roles[role]]


def make_model(role: str, cfg: ModelsConfig | None = None) -> BedrockModel:
    cfg = cfg or load_models_config()
    return BedrockModel(model_id=model_id_for(role, cfg), region_name=cfg.region)
