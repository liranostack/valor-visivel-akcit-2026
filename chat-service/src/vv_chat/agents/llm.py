"""StructuredLLM: the one thing an agent needs from a model (system + prompt -> typed output).

Agents depend on this protocol, so tests replay recorded answers and production uses Strands.
StrandsLLM also records the tokens of every call (A.04.04), per instance: one instance per role,
so a session's or a simulated run's cost can be reported per role and model.
"""

from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel
from strands.models import Model

T = TypeVar("T", bound=BaseModel)


class StructuredLLM(Protocol):
    async def generate(self, system: str, prompt: str, output: type[T]) -> T:
        """Return `output` filled by the model; raise on model failure or invalid output."""
        ...


@dataclass
class Usage:
    label: str
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0


class StrandsLLM:
    """StructuredLLM backed by a Strands model (Bedrock, from vv_chat.models.make_model).

    Calls the model's structured output directly (the Agent wrapper is deprecated for this and
    drops the usage), reading the token counts from the stream's stop event.
    """

    def __init__(self, model: Model, label: str = "") -> None:
        self.model = model
        config: dict[str, Any] = dict(model.get_config())  # type: ignore[arg-type]
        self.usage = Usage(label=label, model_id=str(config.get("model_id", "")))

    async def generate(self, system: str, prompt: str, output: type[T]) -> T:
        messages: Any = [{"role": "user", "content": [{"text": prompt}]}]
        result: T | None = None
        self.usage.calls += 1
        async for event in self.model.structured_output(output, messages, system_prompt=system):
            payload: dict[str, Any] = dict(event)
            if "stop" in payload:
                tokens: dict[str, int] = payload["stop"][2] or {}
                self.usage.input_tokens += int(tokens.get("inputTokens", 0))
                self.usage.output_tokens += int(tokens.get("outputTokens", 0))
            if "output" in payload:
                result = payload["output"]
        if result is None:
            raise ValueError("model returned no structured output")
        return result
