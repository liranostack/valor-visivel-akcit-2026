"""Knowledge base backends (local disk and S3 kb/v<n>/)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws
from vv_mcp.kb import TEMPLATE_FILES, KnowledgeBaseError, LocalKnowledgeBase, S3KnowledgeBase

FIXTURE = Path(__file__).parent / "fixtures" / "kb"


def test_local_version_and_layer() -> None:
    kb = LocalKnowledgeBase(FIXTURE)
    assert kb.version == "v7"
    spec = kb.get_layer_spec("clarity")
    assert spec.stages[0].stage_id == "clarity.real_context"


def test_local_missing_layer() -> None:
    with pytest.raises(KnowledgeBaseError, match="singularity"):
        LocalKnowledgeBase(FIXTURE).get_layer_spec("singularity")


def test_invalid_yaml_is_reported(tmp_path: Path) -> None:
    (tmp_path / "layers").mkdir()
    (tmp_path / "layers" / "clarity.yaml").write_text("layer_id: clarity\norder: 9\n")
    with pytest.raises(KnowledgeBaseError, match="clarity"):
        LocalKnowledgeBase(tmp_path).get_layer_spec("clarity")


def test_templates_map_to_files() -> None:
    kb = LocalKnowledgeBase(FIXTURE)
    assert kb.get_synthesis_template("clarity").startswith("# Mapa de Clareza")
    assert kb.get_synthesis_template("action_plan").startswith("# Plano")
    assert TEMPLATE_FILES["core"] == "templates/essential_core.md"
    with pytest.raises(KnowledgeBaseError):
        kb.get_synthesis_template("core")


def test_guide_whole_and_by_quadrant() -> None:
    kb = LocalKnowledgeBase(FIXTURE)
    assert "## blind" in kb.get_method_guide()
    hidden = kb.get_method_guide("hidden")
    assert "## hidden" in hidden and "rotina" in hidden and "## blind" not in hidden
    unknown = kb.get_method_guide("unknown")
    assert unknown.startswith("# Guia de áreas") and "Intro." in unknown  # rules travel with it
    assert "## unknown" in unknown and "## blind" not in unknown


def test_guide_missing_section(tmp_path: Path) -> None:
    (tmp_path / "guide").mkdir()
    (tmp_path / "guide" / "guide.md").write_text("## open\nx\n")
    with pytest.raises(KnowledgeBaseError, match="blind"):
        LocalKnowledgeBase(tmp_path).get_method_guide("blind")


def test_local_without_version_file(tmp_path: Path) -> None:
    assert LocalKnowledgeBase(tmp_path).version == "local"


def test_local_files_are_cached(tmp_path: Path) -> None:
    (tmp_path / "guide").mkdir()
    guide = tmp_path / "guide" / "guide.md"
    guide.write_text("## open\nv1\n")
    kb = LocalKnowledgeBase(tmp_path)
    assert "v1" in kb.get_method_guide()
    guide.write_text("## open\nv2\n")
    assert "v1" in kb.get_method_guide()


@pytest.fixture
def s3() -> Iterator[Any]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="kb-bucket")
        for path in FIXTURE.rglob("*"):
            if path.is_file():
                key = f"kb/v7/{path.relative_to(FIXTURE).as_posix()}"
                client.put_object(Bucket="kb-bucket", Key=key, Body=path.read_bytes())
        yield client


def test_s3_backend(s3: Any) -> None:
    kb = S3KnowledgeBase("kb-bucket", "v7", s3_client=s3)
    assert kb.version == "v7"
    assert kb.get_layer_spec("clarity").name == "Nitidez de Marca"
    assert "Oculto" in kb.get_method_guide("hidden")


def test_s3_missing_key(s3: Any) -> None:
    kb = S3KnowledgeBase("kb-bucket", "v7", s3_client=s3)
    with pytest.raises(KnowledgeBaseError, match="translation"):
        kb.get_layer_spec("translation")
