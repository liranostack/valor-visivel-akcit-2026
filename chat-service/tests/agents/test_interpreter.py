"""Interpreter: model output validated against the message, heuristic fallback on failure."""

from pathlib import Path
from typing import TypeVar

import pytest
from pydantic import BaseModel
from vv_chat.agents.interpreter import InterpretContext, interpret
from vv_chat.gateway.fake import FakeToolGateway
from vv_contracts.kb import LayerSpec

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "interpreter"
T = TypeVar("T", bound=BaseModel)

CONCRETE = (
    "Antes de fechar, eu confirmo por escrito o que a pessoa espera receber. "
    "Depois entrego tudo em 48 horas."
)
VAGUE = "Eu trabalho com muita qualidade."


class StubLLM:
    """Replays a recorded model answer (JSON text) and records what it was asked."""

    def __init__(self, fixture: str | None = None, error: Exception | None = None) -> None:
        self.text = (FIXTURES / f"{fixture}.json").read_text(encoding="utf-8") if fixture else ""
        self.error = error
        self.system = ""
        self.prompt = ""

    async def generate(self, system: str, prompt: str, output: type[T]) -> T:
        self.system, self.prompt = system, prompt
        if self.error:
            raise self.error
        return output.model_validate_json(self.text)


def layer() -> LayerSpec:
    return LayerSpec.model_validate(
        {
            "layer_id": "clarity",
            "order": 1,
            "name": "Nitidez de Marca",
            "objective": "Mapear com fatos o que o negócio faz.",
            "pain_to_solve": "Fala genérica.",
            "success_signal": "Fato operacional observável.",
            "closure_criteria": "Síntese com trechos dela.",
            "synthesis_template": "templates/clarity_map.md",
            "stages": [
                {
                    "stage_id": "clarity.routine",
                    "title": "Rotina Operacional",
                    "objective": "Transformar a atividade em mecanismo repetível.",
                    "extraction_focus": "regra, etapa ou decisão que se repete",
                    "anchors": [
                        {"angle": "routine", "question": "O que acontece, passo a passo?"},
                        {"angle": "limit", "question": "O que você se recusa a fazer?"},
                        {"angle": "blind_spot", "question": "O que dizem de você?"},
                    ],
                    "rescue_angles": ["routine"],
                }
            ],
        }
    )


def ctx(**overrides: object) -> InterpretContext:
    data: dict[str, object] = {
        "layer_id": "clarity",
        "stage_id": "clarity.routine",
        "question": "O que acontece, passo a passo, entre o pedido e a entrega?",
    }
    data.update(overrides)
    return InterpretContext.model_validate(data)


def gateway() -> FakeToolGateway:
    return FakeToolGateway(
        layers={"clarity": layer()}, guide="## hidden\nRotinas que parecem óbvias."
    )


async def test_concrete_answer_keeps_facts_with_literal_excerpt() -> None:
    out = await interpret(CONCRETE, ctx(), gateway(), StubLLM("concrete"))
    assert not out.used_fallback
    assert out.result.concreteness >= 3
    assert [f.source_excerpt for f in out.result.facts] == [
        "confirmo por escrito o que a pessoa espera receber",
        "entrego tudo em 48 horas",
    ]
    assert all(f.source_excerpt in CONCRETE for f in out.result.facts)


async def test_fact_whose_excerpt_is_not_in_the_message_is_dropped() -> None:
    message = "Antes de fechar, eu confirmo por escrito o que a pessoa espera receber."
    out = await interpret(message, ctx(), gateway(), StubLLM("concrete"))
    assert [f.source_excerpt for f in out.result.facts] == [
        "confirmo por escrito o que a pessoa espera receber"
    ]
    assert out.dropped_facts == 1


async def test_excerpt_match_tolerates_whitespace_and_case() -> None:
    message = "Antes de fechar eu CONFIRMO  por escrito o que a pessoa\nespera receber."
    out = await interpret(message, ctx(), gateway(), StubLLM("concrete"))
    assert len(out.result.facts) == 1


async def test_vague_answer_scores_low() -> None:
    out = await interpret(VAGUE, ctx(), gateway(), StubLLM("vague"))
    assert out.result.concreteness < 3
    assert out.result.facts == []
    assert out.result.generic_claims == ["qualidade"]


async def test_unknown_quadrant_fact_is_kept_as_hypothesis_instead_of_failing() -> None:
    from vv_chat.agents.interpreter import LenientInterpretation

    raw = (
        (FIXTURES / "concrete.json")
        .read_text(encoding="utf-8")
        .replace('"finding_area": "open"', '"finding_area": "unknown"')
    )
    out = LenientInterpretation.model_validate_json(raw).to_result()
    unknown = [f for f in out.facts if f.finding_area == "unknown"]
    assert unknown and all(f.kind == "hypothesis" for f in unknown)


async def test_validation_error_is_retried_once_before_the_fallback() -> None:
    class Flaky(StubLLM):
        def __init__(self) -> None:
            super().__init__("concrete")
            self.calls = 0

        async def generate(self, system: str, prompt: str, output: type[T]) -> T:
            self.calls += 1
            if self.calls == 1:
                return output.model_validate_json('{"concreteness": 9}')
            return await super().generate(system, prompt, output)

    llm = Flaky()
    out = await interpret(CONCRETE, ctx(), gateway(), llm)
    assert llm.calls == 2 and not out.used_fallback


async def test_invalid_json_triggers_fallback() -> None:
    out = await interpret(CONCRETE, ctx(), gateway(), StubLLM("invalid"))
    assert out.used_fallback
    assert out.result.facts == []  # the fallback never invents facts


@pytest.mark.parametrize("error", [TimeoutError("slow"), RuntimeError("throttled")])
async def test_model_error_triggers_fallback(error: Exception) -> None:
    out = await interpret(VAGUE, ctx(), gateway(), StubLLM(error=error))
    assert out.used_fallback
    assert out.result.concreteness < 3


class TestFallbackHeuristics:
    async def test_vague_answer_is_low_and_records_the_stage_focus_as_gap(self) -> None:
        out = await interpret(VAGUE, ctx(), gateway(), StubLLM(error=RuntimeError()))
        assert out.result.concreteness <= 2
        assert out.result.gaps == ["regra, etapa ou decisão que se repete"]

    async def test_sequenced_answer_with_detail_is_usable(self) -> None:
        out = await interpret(CONCRETE, ctx(), gateway(), StubLLM(error=RuntimeError()))
        assert out.result.concreteness >= 3
        assert out.result.gaps == []

    async def test_fallback_never_reads_an_answer_as_off_topic(self) -> None:
        out = await interpret("Não sei.", ctx(), gateway(), StubLLM(error=RuntimeError()))
        assert out.result.relevance >= 2

    async def test_dont_know_is_a_difficulty_signal(self) -> None:
        out = await interpret("Não sei.", ctx(), gateway(), StubLLM(error=RuntimeError()))
        assert out.result.difficulty_signals
        assert out.result.concreteness == 1

    async def test_much_shorter_than_previous_answer_is_a_difficulty_signal(self) -> None:
        out = await interpret(
            "Faço igual sempre.",
            ctx(previous_answer_words=40),
            gateway(),
            StubLLM(error=RuntimeError()),
        )
        assert out.result.difficulty_signals


class TestPrompt:
    async def test_prompt_carries_method_context_and_message_as_data(self) -> None:
        llm = StubLLM("vague")
        out = await interpret(VAGUE, ctx(), gateway(), llm)
        assert "Valor Visível" in llm.system  # _base.md is included
        assert "Interpreter" in llm.system
        for expected in (
            "Mapear com fatos o que o negócio faz.",
            "Transformar a atividade em mecanismo repetível.",
            "regra, etapa ou decisão que se repete",
            "entre o pedido e a entrega",
            "Rotinas que parecem óbvias.",
            f"<client_message>\n{VAGUE}\n</client_message>",
        ):
            assert expected in llm.prompt
        assert len(out.prompt_version) == 12

    async def test_missing_method_guide_does_not_break_the_turn(self) -> None:
        gw = FakeToolGateway(layers={"clarity": layer()})
        llm = StubLLM("vague")
        out = await interpret(VAGUE, ctx(), gw, llm)
        assert not out.used_fallback
        assert "<method_guide>" not in llm.prompt
