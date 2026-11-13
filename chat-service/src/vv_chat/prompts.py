"""System prompts are code: versioned files in chat-service/prompts, hashed into prompt_version."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
BASE = "_base"


@dataclass(frozen=True)
class Prompt:
    name: str
    text: str
    version: str  # first 12 hex chars of sha256(text)


def load_prompt(name: str, directory: Path = PROMPTS_DIR) -> Prompt:
    """Load `<name>.md`, prefixed by `_base.md` when it exists."""
    path = directory / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(path)
    parts = []
    base = directory / f"{BASE}.md"
    if name != BASE and base.exists():
        parts.append(base.read_text(encoding="utf-8").strip())
    parts.append(path.read_text(encoding="utf-8").strip())
    text = "\n\n".join(parts)
    return Prompt(name=name, text=text, version=hashlib.sha256(text.encode()).hexdigest()[:12])
