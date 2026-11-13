"""Knowledge base (the method as data): local directory or S3 under kb/<version>/.

Layout (ERD, 'Schema da knowledge base'): layers/<layer_id>.yaml, guide/guide.md,
templates/*.md, kb_version.txt. Files are read once and cached for the process lifetime.
"""

import os
from pathlib import Path
from typing import Any

import boto3
import yaml
from pydantic import ValidationError
from vv_contracts.common import FindingArea, LayerId, TemplateKind
from vv_contracts.kb import LayerSpec

TEMPLATE_FILES: dict[TemplateKind, str] = {
    "clarity": "templates/clarity_map.md",
    "singularity": "templates/differentiation_map.md",
    "translation": "templates/verbal_platform.md",
    "sustainment": "templates/consistency_guide.md",
    "pre_core": "templates/pre_core.md",
    "core": "templates/essential_core.md",
    "action_plan": "templates/action_plan_7d.md",
}
GUIDE_FILE = "guide/guide.md"


class KnowledgeBaseError(LookupError):
    """Missing or invalid method content."""


class _BaseKnowledgeBase:
    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    def _fetch(self, relative: str) -> str:  # pragma: no cover - implemented by subclasses
        raise NotImplementedError

    def _read(self, relative: str) -> str:
        if relative not in self._cache:
            self._cache[relative] = self._fetch(relative)
        return self._cache[relative]

    def get_layer_spec(self, layer_id: LayerId) -> LayerSpec:
        raw = self._read(f"layers/{layer_id}.yaml")
        try:
            data: Any = yaml.safe_load(raw)
            return LayerSpec.model_validate(data)
        except (yaml.YAMLError, ValidationError) as exc:
            raise KnowledgeBaseError(f"invalid layer spec {layer_id!r}: {exc}") from exc

    def get_synthesis_template(self, kind: TemplateKind) -> str:
        return self._read(TEMPLATE_FILES[kind])

    def get_method_guide(self, quadrant: FindingArea | None = None) -> str:
        guide = self._read(GUIDE_FILE)
        if quadrant is None:
            return guide
        heading = f"## {quadrant}"
        lines = guide.splitlines()
        try:
            start = next(i for i, line in enumerate(lines) if line.strip() == heading)
        except StopIteration:
            raise KnowledgeBaseError(f"guide guide has no section {heading!r}") from None
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines)
        )
        # The preamble (classification rule and pitfalls) travels with every slice.
        first = next((i for i, line in enumerate(lines) if line.startswith("## ")), start)
        preamble = "\n".join(lines[:first]).strip()
        section = "\n".join(lines[start:end]).strip()
        return f"{preamble}\n\n{section}" if preamble else section


class LocalKnowledgeBase(_BaseKnowledgeBase):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root
        version_file = root / "kb_version.txt"
        self._version = version_file.read_text().strip() if version_file.exists() else "local"

    @property
    def version(self) -> str:
        return self._version

    def _fetch(self, relative: str) -> str:
        path = self._root / relative
        if not path.exists():
            raise KnowledgeBaseError(f"missing knowledge-base file {relative!r}")
        return path.read_text(encoding="utf-8")


class S3KnowledgeBase(_BaseKnowledgeBase):
    def __init__(self, bucket: str, version: str, s3_client: Any | None = None) -> None:
        super().__init__()
        self._bucket = bucket
        self._version = version
        self._s3: Any = s3_client if s3_client is not None else boto3.client("s3")

    @property
    def version(self) -> str:
        return self._version

    def _fetch(self, relative: str) -> str:
        key = f"kb/{self._version}/{relative}"
        try:
            obj = self._s3.get_object(Bucket=self._bucket, Key=key)
        except self._s3.exceptions.NoSuchKey as exc:
            raise KnowledgeBaseError(f"missing knowledge-base file {relative!r}") from exc
        return obj["Body"].read().decode("utf-8")


DEFAULT_LOCAL_PATH = Path(__file__).resolve().parents[3] / "knowledge-base"


def load_knowledge_base() -> LocalKnowledgeBase | S3KnowledgeBase:  # pragma: no cover - env wiring
    """KB_SOURCE=local (KB_PATH, default ./knowledge-base) or s3 (KB_BUCKET, KB_VERSION)."""
    if os.environ.get("KB_SOURCE", "local") == "s3":
        return S3KnowledgeBase(os.environ["KB_BUCKET"], os.environ.get("KB_VERSION", "v1"))
    return LocalKnowledgeBase(Path(os.environ.get("KB_PATH", DEFAULT_LOCAL_PATH)))
