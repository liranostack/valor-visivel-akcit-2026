"""StrandsLLM records the tokens of every call, per role and model (A.04.04)."""

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from pydantic import BaseModel
from vv_chat.agents.llm import StrandsLLM


class Out(BaseModel):
    answer: str


class FakeModel:
    """Yields the events Strands' Bedrock structured_output yields: stream events, the stop
    tuple (reason, message, usage, metrics), then the output."""

    def __init__(self, *, output: bool = True, model_id: str = "us.anthropic.test") -> None:
        self.output = output
        self.model_id = model_id
        self.calls: list[tuple[Any, ...]] = []

    def get_config(self) -> dict[str, Any]:
        return {"model_id": self.model_id}

    async def structured_output(
        self, output_model: type[BaseModel], prompt: Any, system_prompt: str | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        self.calls.append((output_model, prompt, system_prompt))
        yield {"event": {"contentBlockDelta": {}}}
        yield {"stop": ("tool_use", {}, {"inputTokens": 120, "outputTokens": 30}, {})}
        if self.output:
            yield {"output": output_model(answer="ok")}


async def test_returns_the_output_and_sends_system_and_prompt() -> None:
    model = FakeModel()
    llm = StrandsLLM(model, label="interpreter")  # type: ignore[arg-type]
    out = await llm.generate("sys", "hello", Out)
    assert out == Out(answer="ok")
    _, messages, system = model.calls[0]
    assert system == "sys"
    assert messages == [{"role": "user", "content": [{"text": "hello"}]}]


async def test_usage_accumulates_per_instance() -> None:
    llm = StrandsLLM(FakeModel(), label="interpreter")  # type: ignore[arg-type]
    await llm.generate("s", "p", Out)
    await llm.generate("s", "p", Out)
    assert llm.usage.label == "interpreter"
    assert llm.usage.model_id == "us.anthropic.test"
    assert (llm.usage.calls, llm.usage.input_tokens, llm.usage.output_tokens) == (2, 240, 60)


async def test_no_output_raises_but_tokens_still_count() -> None:
    llm = StrandsLLM(FakeModel(output=False))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await llm.generate("s", "p", Out)
    assert llm.usage.input_tokens == 120
