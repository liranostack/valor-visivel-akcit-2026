"""revisão do mapa (lead, 12/11): at the end of each layer the journey pauses until she
approves the factual map or asks for an adjustment (A.06.15)."""

from typing import Any, TypeVar

from pydantic import BaseModel
from vv_chat.flows.review import (
    ADJUST_ASK,
    ADJUSTED_TAIL,
    APPROVED,
    NOTHING_TO_REVIEW,
    ReviewFlow,
)
from vv_chat.gateway.fake import FakeToolGateway
from vv_chat.guardrails import InputCheck, OutputCheck
from vv_contracts.agents import ExtractedFact, InterpretationScores
from vv_contracts.state import OnboardingAnswers, Session
from vv_contracts.tools import SaveFactIn
from vv_contracts.ws import DeliverableEvent, MessageDoneEvent, ReviewAction, StateEvent

T = TypeVar("T", bound=BaseModel)
SID = "s1"


class Guard:
    async def check_input(self, text: str, current_question: str = "") -> InputCheck:
        return InputCheck(True, text)

    async def check_output(self, text: str) -> OutputCheck:
        return OutputCheck(True, text)


class SynthLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, system: str, prompt: str, output: type[T]) -> T:
        self.prompts.append(prompt)
        fid = prompt.split("[", 2)[2].split("]")[0] if "<facts>" in prompt else "x"
        data: dict[str, Any] = {
            "sections": [
                {
                    "title": "Uma leitura para você conferir",
                    "markdown": f"Pai e filho [fact:{fid}]?",
                },
                {"title": "O que você faz", "markdown": f"Corta cabelo [fact:{fid}]."},
            ],
            "gaps": [],
            "hypotheses": [],
        }
        return output.model_validate(data)


async def gateway(status: str = "layer_review") -> tuple[FakeToolGateway, str]:
    gw = FakeToolGateway(templates={"clarity": "## Uma leitura para você conferir"})
    gw.repo.put_session(
        Session(
            session_id=SID,
            status=status,  # type: ignore[arg-type]
            active_layer="clarity",
            onboarding=OnboardingAnswers(offer="corte de cabelo"),
        )
    )
    out = await gw.save_fact(
        SaveFactIn(
            session_id=SID,
            turn_seq=2,
            layer_id="clarity",
            stage_id="clarity.routine",
            fact=ExtractedFact(
                text="Fez o primeiro corte de um menino de 3 anos sem choro.",
                source_excerpt="foi o primeiro corte dele",
                kind="evidence",
                origin="client_statement",
                finding_area="hidden",
            ),
            scores=InterpretationScores(concreteness=4, relevance=4, defensibility=3, domain_fit=5),
        )
    )
    return gw, out.fact_id


async def run(flow: ReviewFlow, msg: ReviewAction) -> list[Any]:
    return [e async for e in flow.handle(msg)]


def text(events: list[Any]) -> str:
    return next(e.message for e in events if isinstance(e, MessageDoneEvent))


async def test_approve_records_the_review_and_confirms() -> None:
    gw, _ = await gateway()
    events = await run(
        ReviewFlow(gw, SynthLLM(), Guard()),
        ReviewAction(session_id=SID, target="clarity", intent="approve"),
    )
    assert "save_review" in gw.calls
    assert text(events) == APPROVED


async def test_adjust_rewrites_the_map_with_her_correction_and_stays_in_review() -> None:
    gw, _ = await gateway()
    llm = SynthLLM()
    events = await run(
        ReviewFlow(gw, llm, Guard()),
        ReviewAction(session_id=SID, target="clarity", intent="adjust", notes="não atendo só pais"),
    )
    assert "não atendo só pais" in llm.prompts[0]
    assert any(isinstance(e, DeliverableEvent) for e in events)
    assert "save_synthesis" in gw.calls and "save_review" in gw.calls
    states = [e for e in events if isinstance(e, StateEvent)]
    assert states and states[-1].status == "layer_review"


async def test_adjusted_map_has_the_same_shape_as_the_first_one() -> None:
    # Manual test 12/11: the side panel went blank after an adjustment because the review sent
    # only the sections while the turn sends the whole Synthesis (the front reads content.content).
    gw, _ = await gateway()
    events = await run(
        ReviewFlow(gw, SynthLLM(), Guard()),
        ReviewAction(session_id=SID, target="clarity", intent="adjust", notes="não atendo só pais"),
    )
    deliverable = next(e for e in events if isinstance(e, DeliverableEvent))
    assert isinstance(deliverable.content.get("content"), dict)
    assert deliverable.content["content"]
    assert "gaps" in deliverable.content


async def test_adjusted_message_asks_once() -> None:
    # The reading came with the closing tail and the adjust tail: two requests in a row.
    gw, _ = await gateway()
    events = await run(
        ReviewFlow(gw, SynthLLM(), Guard()),
        ReviewAction(session_id=SID, target="clarity", intent="adjust", notes="não atendo só pais"),
    )
    message = text(events)
    assert "O mapa completo está ao lado" not in message
    assert message.endswith(ADJUSTED_TAIL)


async def test_adjust_without_notes_asks_what_to_change() -> None:
    gw, _ = await gateway()
    events = await run(
        ReviewFlow(gw, SynthLLM(), Guard()),
        ReviewAction(session_id=SID, target="clarity", intent="adjust"),
    )
    assert text(events) == ADJUST_ASK
    assert "save_synthesis" not in gw.calls


async def test_nothing_to_review_outside_the_pause() -> None:
    gw, _ = await gateway(status="in_layer")
    events = await run(
        ReviewFlow(gw, SynthLLM(), Guard()),
        ReviewAction(session_id=SID, target="clarity", intent="approve"),
    )
    assert text(events) == NOTHING_TO_REVIEW
    assert "save_review" not in gw.calls


async def test_free_text_during_the_pause_is_an_adjustment() -> None:
    gw, _ = await gateway()
    flow = ReviewFlow(gw, SynthLLM(), Guard())
    action = await flow.from_text(SID, "faltou falar da música")
    assert action is not None and action.intent == "adjust" and action.target == "clarity"
    assert action.notes == "faltou falar da música"
