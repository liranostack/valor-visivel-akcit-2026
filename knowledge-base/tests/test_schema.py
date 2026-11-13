"""Every layer YAML validates against the contract (structure only).

Neutrality is not tested with word lists: it is judged by the lead's review and by the
LLM-as-judge scenarios across different business models (see the change-kb-content skill).
"""

import re
from pathlib import Path

import pytest
import yaml
from vv_contracts.kb import LayerSpec

KB = Path(__file__).resolve().parents[1]
LAYER_FILES = sorted((KB / "layers").glob("*.yaml"))


def load(path: Path) -> LayerSpec:
    return LayerSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_there_is_at_least_one_layer() -> None:
    assert LAYER_FILES, "knowledge-base/layers/*.yaml is empty"


@pytest.mark.parametrize("path", LAYER_FILES, ids=lambda p: p.stem)
def test_layer_validates_and_matches_file_name(path: Path) -> None:
    assert load(path).layer_id == path.stem


@pytest.mark.parametrize("path", LAYER_FILES, ids=lambda p: p.stem)
def test_every_stage_covers_at_least_four_angles(path: Path) -> None:
    for stage in load(path).stages:
        assert len(stage.anchors) >= 4, stage.stage_id
        assert stage.rescue_angles, stage.stage_id


@pytest.mark.parametrize("path", LAYER_FILES, ids=lambda p: p.stem)
def test_anchors_are_single_questions_without_numbers(path: Path) -> None:
    for stage in load(path).stages:
        for a in stage.anchors:
            assert a.question.strip().endswith("?"), a.question
            assert a.question.count("?") == 1, f"one question at a time: {a.question}"
            assert not re.search(r"\d|%", a.question), f"no numbers: {a.question}"


@pytest.mark.parametrize("path", LAYER_FILES, ids=lambda p: p.stem)
def test_synthesis_template_path_points_to_templates(path: Path) -> None:
    assert load(path).synthesis_template.startswith("templates/")


def test_clarity_has_the_erd_stages() -> None:
    spec = load(KB / "layers" / "clarity.yaml")
    assert [s.title for s in spec.stages] == [
        "Contexto Real",
        "Rotina Operacional",
        "Evidência de Execução",
    ]


def test_the_opening_anchor_is_a_small_concrete_episode() -> None:
    """Lead (12/11): "Como foi a última vez que você fez seu trabalho, do começo ao fim?" is too
    broad and showed up too often. The opening anchor asks about one recent client and does not
    depend on her vocabulary."""
    from pathlib import Path

    import yaml

    spec = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "layers" / "clarity.yaml").read_text(
            encoding="utf-8"
        )
    )
    first = spec["stages"][0]["anchors"][0]["question"]
    assert "{" not in first
    assert "do começo ao fim" not in first
