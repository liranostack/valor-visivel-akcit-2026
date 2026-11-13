"""Moderator: frames the Investigator's question; ABC grounded in facts; back to topic; no
invented numbers."""

from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel
from vv_chat.agents.moderator import ModerateContext, moderate, render_text
from vv_chat.gateway.fake import FakeToolGateway
from vv_contracts.agents import ExtractedFact, InterpretationScores, QuestionDraft
from vv_contracts.tools import SaveFactIn, Violation

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "moderator"
T = TypeVar("T", bound=BaseModel)
DRAFT = QuestionDraft(
    question="O que a confirmação por escrito evita no seu trabalho?", angle="avoided_error"
)


class StubLLM:
    def __init__(
        self, fixture: str | None = None, fact_id: str = "", error: Exception | None = None
    ):
        self.text = (
            (FIXTURES / f"{fixture}.json").read_text(encoding="utf-8").replace("{F1}", fact_id)
            if fixture
            else ""
        )
        self.error = error
        self.system = ""
        self.prompt = ""

    async def generate(self, system: str, prompt: str, output: type[T]) -> T:
        self.system, self.prompt = system, prompt
        if self.error:
            raise self.error
        return output.model_validate_json(self.text)


async def gateway(violations: list[Violation] | None = None) -> tuple[FakeToolGateway, str]:
    gw = FakeToolGateway(violations=violations)
    gw.start_session("s1")
    out = await gw.save_fact(
        SaveFactIn(
            session_id="s1",
            turn_seq=1,
            layer_id="clarity",
            stage_id="clarity.routine",
            fact=ExtractedFact(
                text="Ela confirma por escrito o que a pessoa espera receber.",
                source_excerpt="confirmo por escrito",
                kind="characteristic",
                origin="client_statement",
                finding_area="hidden",
            ),
            scores=InterpretationScores(concreteness=4, relevance=4, defensibility=3, domain_fit=5),
        )
    )
    return gw, out.fact_id


def ctx(**overrides: object) -> ModerateContext:
    data: dict[str, object] = {
        "session_id": "s1",
        "layer_id": "clarity",
        "stage_title": "Rotina Operacional",
        "draft": DRAFT.model_dump(),
        "attempt": 1,
        "offer_abc_options": False,
        "last_answer": "Ah, sei lá, faço do jeito de sempre.",
        "sector": "confeitaria",
    }
    data.update(overrides)
    return ModerateContext.model_validate(data)


class TestAbcOptions:
    async def test_second_vague_attempt_offers_abc_grounded_in_her_facts(self) -> None:
        gw, fid = await gateway()
        out = await moderate(ctx(attempt=2, offer_abc_options=True), gw, StubLLM("abc", fid))
        options = out.message.abc_options
        assert options is not None
        assert [o.label for o in options] == ["A", "B", "C"]
        assert options[0].references_fact_ids == [fid]
        assert options[1].references_fact_ids == [fid]

    async def test_option_c_cites_no_facts(self) -> None:
        gw, fid = await gateway()
        out = await moderate(ctx(attempt=2, offer_abc_options=True), gw, StubLLM("abc", fid))
        assert out.message.abc_options is not None
        assert out.message.abc_options[2].references_fact_ids == []

    async def test_options_citing_unknown_facts_are_dropped(self) -> None:
        gw, fid = await gateway()
        out = await moderate(
            ctx(attempt=2, offer_abc_options=True), gw, StubLLM("abc_bad_refs", fid)
        )
        assert out.message.abc_options is None
        assert out.abc_dropped

    async def test_no_abc_when_the_conductor_did_not_ask_for_it(self) -> None:
        gw, fid = await gateway()
        out = await moderate(ctx(offer_abc_options=False), gw, StubLLM("abc", fid))
        assert out.message.abc_options is None


class TestBackToTopic:
    async def test_off_topic_answer_gets_a_way_back(self) -> None:
        gw, fid = await gateway()
        llm = StubLLM("back_to_topic", fid)
        out = await moderate(ctx(off_topic=True), gw, llm)
        assert out.message.context_line
        assert "drifted away" in llm.prompt

    async def test_off_topic_without_context_line_gets_the_default_return(self) -> None:
        gw, fid = await gateway()
        out = await moderate(ctx(off_topic=True), gw, StubLLM("plain_no_context", fid))
        assert out.message.context_line and "Rotina Operacional" in out.message.context_line


class TestNoInventedNumbers:
    async def test_context_line_with_unsourced_percentage_is_removed(self) -> None:
        bad = Violation(kind="unsourced_number", excerpt="80%", message="sem fonte")
        gw, fid = await gateway([bad])
        out = await moderate(
            ctx(attempt=2, offer_abc_options=True), gw, StubLLM("abc_percent", fid)
        )
        assert "80%" not in (out.message.context_line or "")
        assert "80%" not in render_text(out.message)
        assert "check_output" in gw.calls
        assert out.message.abc_options is not None  # the clean parts stay


class TestKeepsTheInvestigatorsIntent:
    async def test_two_questions_fall_back_to_the_draft(self) -> None:
        gw, fid = await gateway()
        out = await moderate(ctx(), gw, StubLLM("two_questions", fid))
        assert out.message.question == DRAFT.question

    async def test_a_draft_with_a_trailing_instruction_keeps_only_its_question(self) -> None:
        # Round 4 (A.06.17): the limit draft carried a second sentence after the question.
        draft = QuestionDraft(
            question="O que você recusa, mesmo perdendo a venda? Me conta a última vez.",
            angle="limit",
        )
        gw, _ = await gateway()
        out = await moderate(ctx(draft=draft.model_dump()), gw, StubLLM(error=TimeoutError()))
        assert out.message.question == "O que você recusa, mesmo perdendo a venda?"

    async def test_model_failure_sends_the_draft_as_is(self) -> None:
        gw, _ = await gateway()
        out = await moderate(ctx(), gw, StubLLM(error=TimeoutError()))
        assert out.used_fallback
        assert out.message.question == DRAFT.question
        assert out.message.abc_options is None


async def test_prompt_carries_draft_attempt_signals_and_progress() -> None:
    gw, fid = await gateway()
    llm = StubLLM("plain_no_context", fid)
    await moderate(
        ctx(difficulty_signals=["respondeu 'não sei'"], progress="etapa 2 de 3 da Nitidez"),
        gw,
        llm,
    )
    assert "Moderator" in llm.system and "Valor Visível" in llm.system
    for expected in (
        DRAFT.question,
        "avoided_error",
        "Attempt: 1",
        "respondeu 'não sei'",
        "etapa 2 de 3 da Nitidez",
        f"[{fid}]",
        "<client_message>\nAh, sei lá, faço do jeito de sempre.\n</client_message>",
    ):
        assert expected in llm.prompt


def test_render_text_for_streaming() -> None:
    from vv_contracts.agents import AbcOption, FramedMessage

    msg = FramedMessage(
        context_line="Faz sentido olhar isso agora.",
        question="O que você confere antes de entregar?",
        abc_options=[
            AbcOption(label="A", text="Opção a", references_fact_ids=["f1"]),
            AbcOption(label="B", text="Opção b", references_fact_ids=["f1"]),
            AbcOption(label="C", text="Outra coisa"),
        ],
    )
    assert render_text(msg) == (
        "Faz sentido olhar isso agora.\n\nO que você confere antes de entregar?\n\n"
        "A) Opção a\nB) Opção b\nC) Outra coisa"
    )


class TestVvRhythm:
    """Every turn follows the vv rhythm (orchestrator v2): acknowledge the useful part of her
    answer, show the concrete gap, then one short question (A.06.16)."""

    async def test_every_turn_keeps_the_acknowledgment(self) -> None:
        gw, fid = await gateway()
        out = await moderate(ctx(attempt=2, offer_abc_options=True), gw, StubLLM("abc", fid))
        assert out.message.context_line
        assert out.message.abc_options is not None

    async def test_the_mode_instruction_from_vv_reaches_the_model(self) -> None:
        gw, fid = await gateway()
        llm = StubLLM("abc", fid)
        await moderate(ctx(mode="retry_low"), gw, llm)
        assert "evite tom corretivo" in llm.prompt
        assert "reconhecer o que a resposta trouxe" in llm.prompt

    async def test_model_failure_still_acknowledges_with_the_vv_opener(self) -> None:
        gw, _ = await gateway()
        out = await moderate(ctx(mode="retry_low"), gw, StubLLM(error=RuntimeError("x")))
        assert out.message.context_line == (
            "Isso ajuda a entender o seu trabalho. Agora preciso de um exemplo de como acontece "
            "no dia a dia."
        )

    async def test_second_attempt_uses_the_second_vv_opener(self) -> None:
        gw, _ = await gateway()
        out = await moderate(
            ctx(mode="retry_medium", attempt=2), gw, StubLLM(error=RuntimeError("x"))
        )
        assert out.message.context_line is not None
        assert out.message.context_line.startswith("Você já trouxe algo concreto.")


def test_mode_follows_the_conductor_and_the_answer_quality() -> None:
    from vv_chat.agents.moderator import mode_for

    assert mode_for("deepen", concreteness=2, relevance=4) == "retry_low"
    assert mode_for("deepen", concreteness=3, relevance=4) == "retry_medium"
    assert mode_for("advance", concreteness=4, relevance=4) == "advance"
    assert mode_for("force_advance", concreteness=2, relevance=2) == "force_advance"
    assert mode_for("resume_gap", concreteness=3, relevance=3) == "rescue_prompt"


class TestAbcGrounding:
    """A and B must reword what the cited facts say; an option that adds a motive, step or
    technique is leading, so the options are dropped (A.06.11)."""

    async def test_options_that_reword_the_fact_stay(self) -> None:
        gw, fid = await gateway()
        out = await moderate(ctx(attempt=2, offer_abc_options=True), gw, StubLLM("abc", fid))
        assert out.message.abc_options is not None
        assert not out.abc_dropped

    async def test_options_that_add_what_she_never_said_are_dropped(self) -> None:
        gw, fid = await gateway()
        out = await moderate(
            ctx(attempt=2, offer_abc_options=True), gw, StubLLM("abc_leading", fid)
        )
        assert out.message.abc_options is None
        assert out.abc_dropped
        assert out.message.question  # the plain question still goes out


class TestFallbackReason:
    async def test_the_reason_is_kept_for_the_turn_log(self) -> None:
        gw, _ = await gateway()
        out = await moderate(ctx(), gw, StubLLM(error=ValueError("bad options")))
        assert out.used_fallback
        assert out.fallback_reason == "ValueError: bad options"


class TestVoice:
    async def test_long_dashes_never_reach_her(self) -> None:
        gw, fid = await gateway()
        out = await moderate(ctx(), gw, StubLLM("em_dash", fid))
        assert "—" not in render_text(out.message)
