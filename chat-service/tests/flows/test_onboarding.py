"""Onboarding: consent first, quick choices, verbatim baseline, then the first question."""

from typing import Any

from vv_chat.flows.onboarding import OnboardingFlow, load_onboarding
from vv_chat.gateway.fake import FakeToolGateway
from vv_contracts.kb import LayerSpec
from vv_contracts.tools import GetSessionStateIn
from vv_contracts.ws import (
    Consent,
    ErrorEvent,
    MessageDoneEvent,
    OnboardingAnswer,
    OnboardingStepEvent,
    StartSession,
    StateEvent,
    UserMessage,
)

LAYER = LayerSpec.model_validate(
    {
        "layer_id": "clarity",
        "order": 1,
        "name": "Nitidez de Marca",
        "objective": "o",
        "pain_to_solve": "p",
        "success_signal": "s",
        "closure_criteria": "c",
        "synthesis_template": "templates/clarity_map.md",
        "stages": [
            {
                "stage_id": "clarity.real_context",
                "title": "Contexto Real",
                "objective": "o",
                "extraction_focus": "f",
                "anchors": [
                    {"angle": "routine", "question": "Como foi a última vez com {seu_trabalho}?"},
                    {"angle": "blind_spot", "question": "O que {as_clientes} dizem?"},
                ],
                "rescue_angles": ["routine"],
            }
        ],
    }
)
CFG = load_onboarding()


async def run(flow: OnboardingFlow, msg: Any) -> list[Any]:
    return [e async for e in flow.handle(msg)]


def steps(events: list[Any]) -> list[OnboardingStepEvent]:
    return [e for e in events if isinstance(e, OnboardingStepEvent)]


async def start() -> tuple[FakeToolGateway, OnboardingFlow, str]:
    gw = FakeToolGateway(layers={"clarity": LAYER})
    flow = OnboardingFlow(gw, CFG)
    events = await run(flow, StartSession())
    step = steps(events)[0]
    assert step.field == "consent"
    return gw, flow, step.session_id


ANSWERS: dict[str, str | list[str]] = {
    "business_type": "confeitaria",
    "business_structure": "MEI",
    "offer": "bolo de casamento",
    "audience": "noivas",
    "channels": ["Indicação", "Instagram"],
    "goal": "Me diferenciar de quem faz parecido",
    "perceived_difficulty": "Quando falo, parece igual a todo mundo",
    "difficulty_context": "Ao passar orçamento",
    "declared_links": [],
}


async def complete_onboarding(gw: FakeToolGateway, flow: OnboardingFlow, sid: str) -> list[Any]:
    events = await run(flow, Consent(session_id=sid, accepted=True))
    for field in [s["field"] for s in CFG["steps"]]:
        events = await run(
            flow, OnboardingAnswer(session_id=sid, field=field, value=ANSWERS[field])
        )
    return events


async def test_start_asks_for_consent_and_stores_nothing_about_her() -> None:
    gw, _, sid = await start()
    state = await gw.get_session_state(GetSessionStateIn(session_id=sid))
    assert state.session.consent_at is None and state.session.onboarding is None


async def test_without_consent_no_answer_is_stored() -> None:
    gw, flow, sid = await start()
    events = await run(flow, OnboardingAnswer(session_id=sid, field="offer", value="bolo"))
    assert isinstance(events[-1], ErrorEvent)
    state = await gw.get_session_state(GetSessionStateIn(session_id=sid))
    assert state.session.onboarding is None and state.baseline is None


async def test_refusing_consent_ends_without_data() -> None:
    gw, flow, sid = await start()
    events = await run(flow, Consent(session_id=sid, accepted=False))
    assert isinstance(events[-1], MessageDoneEvent)
    state = await gw.get_session_state(GetSessionStateIn(session_id=sid))
    assert state.session.consent_at is None


async def test_each_step_is_asked_in_order_and_stored() -> None:
    gw, flow, sid = await start()
    events = await run(flow, Consent(session_id=sid, accepted=True))
    asked = [steps(events)[0].field]
    for field in [s["field"] for s in CFG["steps"]][:-1]:
        events = await run(
            flow, OnboardingAnswer(session_id=sid, field=field, value=ANSWERS[field])
        )
        asked.append(steps(events)[0].field)
    assert asked == [s["field"] for s in CFG["steps"]]
    state = await gw.get_session_state(GetSessionStateIn(session_id=sid))
    assert state.session.consent_at is not None
    assert (
        state.session.onboarding is not None
        and state.session.onboarding.offer == "bolo de casamento"
    )
    assert state.session.onboarding.channels == ["Indicação", "Instagram"]


async def test_after_the_last_step_the_baseline_is_asked() -> None:
    gw, flow, sid = await start()
    events = await complete_onboarding(gw, flow, sid)
    assert steps(events)[0].field == "baseline" and steps(events)[0].free_text
    state = await gw.get_session_state(GetSessionStateIn(session_id=sid))
    assert state.session.status == "baseline"


async def test_baseline_is_stored_byte_for_byte_then_the_first_question_comes() -> None:
    gw, flow, sid = await start()
    await complete_onboarding(gw, flow, sid)
    text = "  faço bolo com amor e qualidade,, sem erro de digitação corrigido  "
    events = await run(flow, UserMessage(session_id=sid, text=text))
    state = await gw.get_session_state(GetSessionStateIn(session_id=sid))
    assert state.baseline is not None and state.baseline.statement == text
    assert (
        state.session.status == "in_layer" and state.session.active_stage == "clarity.real_context"
    )
    done = [e for e in events if isinstance(e, MessageDoneEvent)][-1]
    # She named a difficulty: the journey opens on its last episode, in her words (A.06.12).
    assert done.message == (
        "Você disse que a dificuldade é “Quando falo, parece igual a todo mundo”, ao passar "
        "orçamento. Pensa na última vez que isso aconteceu: o que você disse, o que a pessoa "
        "respondeu e como terminou?"
    )
    assert state.asked_questions == [done.message]
    assert any(isinstance(e, StateEvent) and e.layer_index == 1 for e in events)


async def test_unknown_field_is_rejected() -> None:
    gw, flow, sid = await start()
    await run(flow, Consent(session_id=sid, accepted=True))
    events = await run(flow, OnboardingAnswer(session_id=sid, field="hack", value="x"))
    assert isinstance(events[-1], ErrorEvent)
