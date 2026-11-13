"""Agent outputs and tool inputs are part of the prompt: every field must explain itself.

The JSON Schema of these models is sent to the model (Strands structured output) and published
by the MCP server, so each field needs a `description` and each model a docstring.
"""

import inspect

import pytest
from pydantic import BaseModel
from vv_contracts import agents, tools


def models_in(module: object) -> list[type[BaseModel]]:
    return [
        obj
        for _, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, BaseModel)
        and obj is not BaseModel
        and obj.__module__ == getattr(module, "__name__", "")
    ]


AGENT_MODELS = models_in(agents)
TOOL_MODELS = models_in(tools)


@pytest.mark.parametrize("model", AGENT_MODELS + TOOL_MODELS, ids=lambda m: m.__name__)
def test_every_field_has_description(model: type[BaseModel]) -> None:
    missing = [name for name, f in model.model_fields.items() if not (f.description or "").strip()]
    assert missing == [], f"{model.__name__} fields without description: {missing}"


@pytest.mark.parametrize("model", AGENT_MODELS + TOOL_MODELS, ids=lambda m: m.__name__)
def test_every_model_has_docstring(model: type[BaseModel]) -> None:
    assert (model.__doc__ or "").strip(), f"{model.__name__} has no docstring"


@pytest.mark.parametrize("model", AGENT_MODELS, ids=lambda m: m.__name__)
def test_descriptions_reach_the_json_schema(model: type[BaseModel]) -> None:
    schema = model.model_json_schema()
    assert schema.get("description")
    for name, prop in schema["properties"].items():
        assert prop.get("description"), f"{model.__name__}.{name} missing in JSON Schema"


def test_enum_meanings_are_explained() -> None:
    kind = agents.ExtractedFact.model_fields["kind"].description or ""
    for value in ("characteristic", "benefit", "evidence", "hypothesis"):
        assert value in kind
    quadrant = agents.ExtractedFact.model_fields["finding_area"].description or ""
    for value in ("open", "hidden", "blind", "unknown"):
        assert value in quadrant
    angle = agents.QuestionDraft.model_fields["angle"].description or ""
    for value in ("routine", "limit", "avoided_error", "proof", "decision", "blind_spot"):
        assert value in angle
