from pathlib import Path

import pytest
from vv_chat.models import ModelsConfig, load_models_config, make_model, model_id_for
from vv_chat.prompts import load_prompt

CONFIG = Path(__file__).resolve().parents[1] / "config" / "models.yaml"


class TestModels:
    def test_yaml_roles_follow_adr_011(self) -> None:
        cfg = load_models_config(CONFIG)
        assert cfg.roles["interpreter"] == "large"
        assert cfg.roles["investigator"] == "large"
        assert cfg.roles["moderator"] == "large"
        assert cfg.roles["synthesizer"] == "large"
        assert cfg.roles["public_researcher"] == "small"

    def test_model_id_by_size(self) -> None:
        cfg = load_models_config(CONFIG)
        assert "sonnet" in model_id_for("interpreter", cfg)
        assert "haiku" in model_id_for("public_researcher", cfg)

    def test_env_overrides_model_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MODEL_LARGE", "us.anthropic.claude-x")
        monkeypatch.setenv("MODEL_SMALL", "us.anthropic.claude-y")
        cfg = load_models_config(CONFIG)
        assert model_id_for("interpreter", cfg) == "us.anthropic.claude-x"
        assert model_id_for("public_researcher", cfg) == "us.anthropic.claude-y"

    def test_unknown_role(self) -> None:
        with pytest.raises(KeyError):
            model_id_for("poet", ModelsConfig())

    def test_make_model_builds_bedrock_model(self) -> None:
        model = make_model("interpreter", load_models_config(CONFIG))
        expected = model_id_for("interpreter", load_models_config(CONFIG))
        assert model.get_config().get("model_id") == expected


class TestPrompts:
    def test_base_is_included_and_version_tracks_content(self, tmp_path: Path) -> None:
        (tmp_path / "_base.md").write_text("BASE")
        (tmp_path / "interpreter.md").write_text("ROLE v1")
        first = load_prompt("interpreter", tmp_path)
        assert first.text.startswith("BASE") and "ROLE v1" in first.text
        assert len(first.version) == 12
        (tmp_path / "interpreter.md").write_text("ROLE v2")
        assert load_prompt("interpreter", tmp_path).version != first.version

    def test_works_without_base(self, tmp_path: Path) -> None:
        (tmp_path / "moderator.md").write_text("ROLE")
        assert load_prompt("moderator", tmp_path).text == "ROLE"

    def test_missing_prompt(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_prompt("nope", tmp_path)
