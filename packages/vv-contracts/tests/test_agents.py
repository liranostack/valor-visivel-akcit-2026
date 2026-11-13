import pytest
from pydantic import ValidationError
from vv_contracts.agents import (
    AbcOption,
    ApplicationOutputs,
    BeforeAfter,
    Decision,
    EssentialCoreOutput,
    ExtractedFact,
    FramedMessage,
    InterpretationResult,
    LayerSynthesis,
    PublicContext,
    QuestionDraft,
)

_OUTPUTS = ApplicationOutputs(
    bio="Ajudo clientes a resolver o problema porque faço X.",
    narrativa="Trabalho com Y. Faço Z. O cliente percebe W.",
    checklist=[
        "Prioridade alta: testar narrativa",
        "Prioridade media: coletar prova",
        "Prioridade baixa: documentar",
    ],
    whatsapp_pitch_curto="Oi! Trabalho com Y e entrego Z.",
    whatsapp_pitch_prova="Oi! Trabalho com Y e entrego Z. Prova: W.",
    instagram_bio="Como faco Z. Impacto: W.",
    instagram_legenda_curta="Bastidor real: X. Resultado: W.",
    instagram_story_roteiro=["Problema: ...", "Rotina: ...", "Prova: ..."],
)


def fact(**overrides: object) -> ExtractedFact:
    data: dict[str, object] = {
        "text": "Ajusta a pressão conforme a respiração da cliente",
        "source_excerpt": "eu vou sentindo pela respiração",
        "kind": "characteristic",
        "origin": "client_statement",
        "finding_area": "hidden",
    }
    data.update(overrides)
    return ExtractedFact.model_validate(data)


def interpretation(**overrides: object) -> InterpretationResult:
    data: dict[str, object] = {
        "concreteness": 4,
        "relevance": 3,
        "defensibility": 2,
        "domain_fit": 5,
        "facts": [fact().model_dump()],
        "gaps": [],
        "generic_claims": ["atendimento humanizado"],
        "difficulty_signals": [],
        "rationale": "Concrete routine described.",
    }
    data.update(overrides)
    return InterpretationResult.model_validate(data)


class TestInterpretation:
    def test_valid(self) -> None:
        result = interpretation()
        assert result.facts[0].finding_area == "hidden"

    @pytest.mark.parametrize("field", ["concreteness", "relevance", "defensibility", "domain_fit"])
    @pytest.mark.parametrize("value", [0, 6])
    def test_scores_are_1_to_5(self, field: str, value: int) -> None:
        with pytest.raises(ValidationError):
            interpretation(**{field: value})

    def test_unknown_quadrant_must_be_hypothesis(self) -> None:
        with pytest.raises(ValidationError):
            fact(finding_area="unknown", kind="evidence")
        assert fact(finding_area="unknown", kind="hypothesis").kind == "hypothesis"

    def test_excerpt_required(self) -> None:
        with pytest.raises(ValidationError):
            fact(source_excerpt="")

    def test_json_round_trip(self) -> None:
        result = interpretation()
        assert InterpretationResult.model_validate_json(result.model_dump_json()) == result


class TestDecision:
    def test_resume_gap_requires_gap_id(self) -> None:
        with pytest.raises(ValidationError):
            Decision(action="resume_gap", next_stage_id=None, attempt=0, offer_abc_options=False)
        ok = Decision(
            action="resume_gap", next_stage_id=None, attempt=0, offer_abc_options=False, gap_id="g1"
        )
        assert ok.gap_id == "g1"

    def test_attempt_not_negative(self) -> None:
        with pytest.raises(ValidationError):
            Decision(action="deepen", next_stage_id=None, attempt=-1, offer_abc_options=False)


class TestQuestionAndFraming:
    def test_question_draft(self) -> None:
        q = QuestionDraft(
            question="Como você decide?", angle="decision", references_fact_ids=["f1"]
        )
        assert q.angle == "decision"
        with pytest.raises(ValidationError):
            QuestionDraft(question="", angle="decision", references_fact_ids=[])

    def test_abc_a_and_b_need_facts_c_has_none(self) -> None:
        with pytest.raises(ValidationError):
            AbcOption(label="A", text="x", references_fact_ids=[])
        with pytest.raises(ValidationError):
            AbcOption(label="C", text="Outra coisa", references_fact_ids=["f1"])
        assert AbcOption(label="C", text="Nenhuma", references_fact_ids=[]).label == "C"

    def test_framed_message_abc_must_be_a_b_c(self) -> None:
        a = AbcOption(label="A", text="a", references_fact_ids=["f1"])
        b = AbcOption(label="B", text="b", references_fact_ids=["f2"])
        c = AbcOption(label="C", text="c", references_fact_ids=[])
        ok = FramedMessage(context_line=None, question="?", abc_options=[a, b, c])
        assert ok.abc_options is not None
        with pytest.raises(ValidationError):
            FramedMessage(context_line=None, question="?", abc_options=[a, c])
        with pytest.raises(ValidationError):
            FramedMessage(context_line=None, question="?", abc_options=[b, a, c])
        assert FramedMessage(context_line="ctx", question="?", abc_options=None).abc_options is None


class TestSyntheses:
    def test_layer_synthesis(self) -> None:
        s = LayerSynthesis(
            layer_id="clarity",
            content={"negocio": "Massoterapia [fact:f1]"},
            fact_refs=["f1"],
            gaps=[],
            hypotheses=[],
        )
        assert s.layer_id == "clarity"
        with pytest.raises(ValidationError):
            LayerSynthesis(layer_id="other", content={}, fact_refs=[], gaps=[], hypotheses=[])  # type: ignore[arg-type]

    def test_essential_core_needs_seven_day_plan(self) -> None:
        ba = BeforeAfter(
            said_before="atendimento humanizado",
            sustained_discovery="lê a respiração",
            now_able_to="explicar o ajuste de pressão",
            fact_refs=["f1"],
        )
        plan = [f"Dia {i}" for i in range(1, 8)]
        core = EssentialCoreOutput(
            content={},
            final_statement="x",
            before_after=ba,
            action_plan_7d=plan,
            gaps=[],
            outputs=_OUTPUTS,
        )
        assert len(core.action_plan_7d) == 7
        with pytest.raises(ValidationError):
            EssentialCoreOutput(
                content={},
                final_statement="x",
                before_after=ba,
                action_plan_7d=plan[:6],
                gaps=[],
                outputs=_OUTPUTS,
            )

    def test_public_context_max_150_words(self) -> None:
        assert PublicContext(summary="curto", claims_to_verify=[]).summary == "curto"
        with pytest.raises(ValidationError):
            PublicContext(summary=" ".join(["palavra"] * 151), claims_to_verify=[])
