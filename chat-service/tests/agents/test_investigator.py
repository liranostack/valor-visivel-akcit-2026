"""Investigator: one new question per turn, never a repeat; anchors from the pool as fallback."""

from pathlib import Path
from typing import TypeVar

import pytest
from pydantic import BaseModel
from vv_chat.agents.investigator import InvestigateContext, investigate, is_repeat
from vv_chat.gateway.fake import FakeToolGateway
from vv_contracts.agents import ExtractedFact, InterpretationScores
from vv_contracts.kb import LayerSpec
from vv_contracts.tools import SaveFactIn

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "investigator"
T = TypeVar("T", bound=BaseModel)
ASKED = "O que acontece, passo a passo, entre o pedido e a entrega?"


class ScriptLLM:
    """Replays recorded answers in order; an Exception in the script is raised instead."""

    def __init__(self, *script: str | Exception) -> None:
        self.script = list(script)
        self.prompts: list[str] = []
        self.system = ""

    async def generate(self, system: str, prompt: str, output: type[T]) -> T:
        self.system = system
        self.prompts.append(prompt)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return output.model_validate_json((FIXTURES / f"{step}.json").read_text(encoding="utf-8"))


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
                        {
                            "angle": "routine",
                            "question": ASKED,
                        },
                        {
                            "angle": "limit",
                            "question": "O que você se recusa a fazer no {seu_trabalho}?",
                        },
                        {
                            "angle": "blind_spot",
                            "question": "O que {as_clientes} já disseram sobre o {seu_trabalho}?",
                        },
                    ],
                    "rescue_angles": ["routine", "limit"],
                }
            ],
        }
    )


async def gateway_with_fact() -> FakeToolGateway:
    gw = FakeToolGateway(layers={"clarity": layer()})
    gw.start_session("s1")
    scores = InterpretationScores(concreteness=4, relevance=4, defensibility=3, domain_fit=5)
    fact = ExtractedFact(
        text="Ela confirma por escrito o que a cliente espera.",
        source_excerpt="confirmo por escrito",
        kind="characteristic",
        origin="client_statement",
        finding_area="hidden",
    )
    out = await gw.save_fact(
        SaveFactIn(
            session_id="s1",
            turn_seq=1,
            layer_id="clarity",
            stage_id="clarity.routine",
            fact=fact,
            scores=scores,
        )
    )
    assert out.fact_id
    gw.fact_id = out.fact_id  # type: ignore[attr-defined]
    return gw


def ctx(**overrides: object) -> InvestigateContext:
    data: dict[str, object] = {
        "session_id": "s1",
        "layer_id": "clarity",
        "stage_id": "clarity.routine",
        "attempt": 1,
        "asked_questions": [ASKED],
        "vocabulary": {"seu_trabalho": "bolo de casamento", "as_clientes": "as noivas"},
    }
    data.update(overrides)
    return InvestigateContext.model_validate(data)


class TestIsRepeat:
    def test_same_question_with_other_case_and_punctuation(self) -> None:
        assert is_repeat("o que acontece passo a passo entre o pedido e a entrega", [ASKED])

    def test_accents_do_not_hide_a_repeat(self) -> None:
        assert is_repeat("Como voce sabe que funcionou?", ["Como você sabe que funcionou?"])

    def test_different_question_is_not_a_repeat(self) -> None:
        assert not is_repeat("O que você se recusa a fazer?", [ASKED])


async def test_new_question_passes() -> None:
    gw = await gateway_with_fact()
    out = await investigate(ctx(), gw, ScriptLLM("new"))
    assert not out.used_fallback and not out.retried
    assert out.draft.angle == "decision"


async def test_repeat_is_retried_once_then_accepted_when_new() -> None:
    gw = await gateway_with_fact()
    llm = ScriptLLM("repeat", "new")
    out = await investigate(ctx(), gw, llm)
    assert out.retried and not out.used_fallback
    assert not is_repeat(out.draft.question, [ASKED])
    assert "too similar" in llm.prompts[1]


async def test_repeat_twice_falls_back_to_an_unused_anchor_filled_with_her_words() -> None:
    gw = await gateway_with_fact()
    out = await investigate(ctx(), gw, ScriptLLM("repeat", "repeat_reworded"))
    assert out.used_fallback  # no external perception yet → blind spot first (A.03.16)
    assert out.draft.question == "O que as noivas já disseram sobre o bolo de casamento?"
    assert out.draft.angle == "blind_spot"


async def test_model_failure_falls_back_to_anchor() -> None:
    gw = await gateway_with_fact()
    out = await investigate(ctx(), gw, ScriptLLM(TimeoutError("slow")))
    assert out.used_fallback
    assert out.draft.angle == "blind_spot"


async def test_fallback_skips_anchors_already_asked() -> None:
    gw = await gateway_with_fact()
    asked = [ASKED, "O que as noivas já disseram sobre o bolo de casamento?"]
    out = await investigate(ctx(asked_questions=asked), gw, ScriptLLM(RuntimeError()))
    assert out.draft.question == "O que você se recusa a fazer no bolo de casamento?"


@pytest.mark.parametrize(
    "script",
    [("repeat", "repeat"), ("repeat", "repeat_reworded"), (RuntimeError(),)],
)
async def test_a_repeated_question_never_leaves_even_when_every_anchor_was_asked(
    script: tuple[str | Exception, ...],
) -> None:
    gw = await gateway_with_fact()
    asked = [
        ASKED,
        "O que você se recusa a fazer no bolo de casamento?",
        "O que as noivas já disseram sobre o bolo de casamento?",
    ]
    out = await investigate(ctx(asked_questions=asked), gw, ScriptLLM(*script))
    assert not is_repeat(out.draft.question, asked)
    assert out.draft.question.endswith("?")


async def test_unknown_fact_ids_are_dropped() -> None:
    gw = await gateway_with_fact()
    llm = ScriptLLM("unknown_fact")
    out = await investigate(ctx(), gw, llm)
    assert out.draft.references_fact_ids == []  # f1/f999 are not ids of this session


async def test_prompt_has_anchors_facts_asked_questions_and_vocabulary() -> None:
    gw = await gateway_with_fact()
    llm = ScriptLLM("new")
    out = await investigate(ctx(gap="Não disse como confere o resultado."), gw, llm)
    prompt = llm.prompts[0]
    assert "Investigator" in llm.system and "Valor Visível" in llm.system
    for expected in (
        "Transformar a atividade em mecanismo repetível.",
        "limit: O que você se recusa a fazer no {seu_trabalho}?",
        "Ela confirma por escrito o que a cliente espera.",
        gw.fact_id,  # type: ignore[attr-defined]
        ASKED,
        "seu_trabalho = bolo de casamento",
        "Não disse como confere o resultado.",
        "Attempt: 1",
    ):
        assert expected in prompt
    assert len(out.prompt_version) == 12


async def test_when_nothing_new_is_left_the_loop_is_told_to_advance() -> None:
    from vv_chat.agents.investigator import LAST_RESORT, NoNewQuestionError
    from vv_contracts.kb import fill_placeholders

    gw = await gateway_with_fact()
    vocab = {"seu_trabalho": "bolo de casamento", "as_clientes": "as noivas"}
    asked = [
        ASKED,
        "O que você se recusa a fazer no bolo de casamento?",
        "O que as noivas já disseram sobre o bolo de casamento?",
    ] + [fill_placeholders(q, vocab) for _, q in LAST_RESORT]
    with pytest.raises(NoNewQuestionError):
        await investigate(ctx(asked_questions=asked), gw, ScriptLLM(RuntimeError()))


async def test_fact_ids_never_appear_in_the_question_text() -> None:
    from vv_chat.agents.investigator import clean_question

    assert clean_question("Depois que você envia a foto [6a8d1e651c64], o que elas dizem?") == (
        "Depois que você envia a foto, o que elas dizem?"
    )
    assert clean_question("Como foi [fact:abc] o último?") == "Como foi o último?"


class TestQuadrantCoverage:
    async def test_prompt_shows_coverage_and_asks_for_blind_spot_when_missing(self) -> None:
        gw = await gateway_with_fact()  # one hidden fact, no external perception
        llm = ScriptLLM("new")
        await investigate(ctx(), gw, llm)
        prompt = llm.prompts[0]
        assert "<coverage>" in prompt and "hidden: 1" in prompt and "blind: 0" in prompt
        assert "prefer the blind_spot angle" in prompt

    async def test_blind_counts_only_reports_from_someone_else(self) -> None:
        gw = await gateway_with_fact()
        await gw.save_fact(
            SaveFactIn(
                session_id="s1",
                turn_seq=2,
                layer_id="clarity",
                stage_id="clarity.routine",
                fact=ExtractedFact(
                    text="Ela observa que muitas opções confundem.",
                    source_excerpt="com mais opções ela fica indecisa",
                    kind="evidence",
                    origin="client_statement",
                    finding_area="blind",  # mislabelled: her own observation
                ),
                scores=InterpretationScores(
                    concreteness=4, relevance=4, defensibility=3, domain_fit=5
                ),
            )
        )
        llm = ScriptLLM("new")
        await investigate(ctx(), gw, llm)
        assert "blind: 0" in llm.prompts[0]

    async def test_fallback_prefers_blind_spot_when_no_external_perception(self) -> None:
        gw = await gateway_with_fact()
        out = await investigate(ctx(asked_questions=[]), gw, ScriptLLM(RuntimeError()))
        assert out.draft.angle == "blind_spot"


async def test_prompt_has_her_business_and_the_difficulty_she_named() -> None:
    gw = await gateway_with_fact()
    llm = ScriptLLM("new")
    profile = {"ob-pain": "difficulty she named: Clientes comparam só pelo preço"}
    await investigate(ctx(profile=profile), gw, llm)
    assert "<business>" in llm.prompts[0]
    assert "Clientes comparam só pelo preço" in llm.prompts[0]


async def test_pain_focus_asks_for_the_last_episode_of_the_difficulty() -> None:
    gw = await gateway_with_fact()
    llm = ScriptLLM("new")
    profile = {"ob-pain": "difficulty she named: Clientes comparam só pelo preço"}
    await investigate(ctx(profile=profile, focus="pain_episode"), gw, llm)
    assert "<priority>" in llm.prompts[0]
    assert "No report yet of what other people perceive" not in llm.prompts[0]


async def test_limit_focus_asks_for_a_limit_she_keeps() -> None:
    gw = await gateway_with_fact()
    llm = ScriptLLM("new")
    await investigate(ctx(focus="limit"), gw, llm)
    assert "<priority>" in llm.prompts[0] and "limit" in llm.prompts[0]


def test_last_resort_questions_are_not_the_broad_one() -> None:
    from vv_chat.agents.investigator import LAST_RESORT

    assert all("do começo ao fim" not in q for _, q in LAST_RESORT)
