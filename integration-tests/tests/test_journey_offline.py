"""Journey runner in process, offline: every agent model fails, so the heuristic fallbacks drive
the turn loop; the record must still hold the transcript and each agent's steps (A.05.01)."""

from vv_it.journey import FailingLLM, run_journey
from vv_it.persona import SCENARIOS, load_persona
from vv_it.simulator import SimulatedClient

PERSONA = load_persona(SCENARIOS / "pastelaria.yaml")


async def test_offline_journey_records_questions_answers_and_steps() -> None:
    record = await run_journey(
        PERSONA, SimulatedClient(PERSONA), agent_llm=FailingLLM(), max_turns=3
    )
    assert record.persona == "pastelaria"
    assert record.first_question.startswith(
        "Você disse que a dificuldade é “Clientes comparam só pelo preço”, ao passar orçamento."
    )
    assert 1 <= len(record.turns) <= 3
    first = record.turns[0]
    assert first.question == record.first_question
    assert first.answer == PERSONA.scripted_answers[0]
    assert first.reply
    steps = {s["step"] for s in first.steps}
    assert {"interpreter", "conductor"} <= steps


async def test_the_journey_stops_when_the_client_runs_out_of_answers() -> None:
    record = await run_journey(
        PERSONA, SimulatedClient(PERSONA), agent_llm=FailingLLM(), max_turns=50
    )
    assert len(record.turns) <= len(PERSONA.scripted_answers)
    assert record.ended in {"client_silent", "layer_closed"}
