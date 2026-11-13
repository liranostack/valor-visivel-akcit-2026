"""Simulated client: scripted mode without network, model mode with a stub (A.02.20)."""

from typing import Any, TypeVar

from pydantic import BaseModel
from vv_contracts.agents import AbcOption
from vv_it.persona import SCENARIOS, load_persona
from vv_it.simulator import ClientReply, SimulatedClient

T = TypeVar("T", bound=BaseModel)
PERSONA = load_persona(SCENARIOS / "pastelaria.yaml")
OPTIONS = [
    AbcOption(label="A", text="Vocês conferem cada empanada.", references_fact_ids=["f1"]),
    AbcOption(
        label="B", text="Vocês fecham a massa de um jeito só seu.", references_fact_ids=["f1"]
    ),
    AbcOption(label="C", text="Explique com suas palavras.", references_fact_ids=[]),
]


class StubLLM:
    def __init__(self, *replies: dict[str, Any]) -> None:
        self.replies = list(replies)
        self.systems: list[str] = []
        self.prompts: list[str] = []

    async def generate(self, system: str, prompt: str, output: type[T]) -> T:
        self.systems.append(system)
        self.prompts.append(prompt)
        return output.model_validate(self.replies.pop(0))


async def test_scripted_mode_replays_the_answers_then_runs_out() -> None:
    client = SimulatedClient(PERSONA)
    answers = [(await client.reply("pergunta?")).text for _ in PERSONA.scripted_answers]
    assert answers == PERSONA.scripted_answers
    assert (await client.reply("mais uma?")).text == ""


async def test_model_mode_sees_the_persona_the_question_and_the_history() -> None:
    llm = StubLLM(
        {"text": "normal, a gente faz tudo", "revealed": []}, {"text": "ok", "revealed": []}
    )
    client = SimulatedClient(PERSONA, llm)
    await client.reply("Como foi a última vez?")
    await client.reply("E o que vocês conferem?")
    assert PERSONA.truths[0].text in llm.systems[0]
    assert "E o que vocês conferem?" in llm.prompts[1]
    assert "normal, a gente faz tudo" in llm.prompts[1]  # history


async def test_a_picked_option_is_sent_like_the_ui_does() -> None:
    llm = StubLLM({"text": "", "picked": "B", "revealed": []})
    reply = await SimulatedClient(PERSONA, llm).reply("O que é a finalização?", OPTIONS)
    assert reply.text == "B) Vocês fecham a massa de um jeito só seu."
    assert "B) Vocês fecham" in llm.prompts[0]


async def test_unknown_truth_ids_are_dropped() -> None:
    hidden = PERSONA.truth_ids("hidden")[0]
    llm = StubLLM({"text": "x", "revealed": [hidden, "nope"]})
    reply = await SimulatedClient(PERSONA, llm).reply("?")
    assert reply.revealed == [hidden]


async def test_first_answers_are_asked_to_be_vague() -> None:
    llm = StubLLM(*({"text": "x", "revealed": []} for _ in range(PERSONA.vague_answers + 1)))
    client = SimulatedClient(PERSONA, llm)
    for _ in range(PERSONA.vague_answers + 1):
        await client.reply("?")
    assert "vague" in llm.prompts[0].lower()
    assert "vague" not in llm.prompts[-1].lower()


def test_client_reply_defaults() -> None:
    assert ClientReply(text="oi").revealed == []


def confused(confusion: float = 1.0, **extra: Any):
    from vv_it.persona import Behavior

    return PERSONA.model_copy(
        update={"behavior": Behavior(confusion=confusion, **extra), "vague_answers": 0}
    )


async def test_a_drawn_confusion_is_told_to_the_model_and_recorded() -> None:
    llm = StubLLM({"text": "como assim?", "revealed": []})
    client = SimulatedClient(confused(1.0), llm, seed=1)
    await client.reply("O que você confere antes de fechar?")
    assert "misunderstand" in llm.prompts[0].lower()
    assert client.last_events == ["confused"]


async def test_no_chance_means_no_event() -> None:
    llm = StubLLM({"text": "ok", "revealed": []})
    client = SimulatedClient(confused(0.0), llm, seed=1)
    await client.reply("?")
    assert client.last_events == []


def test_the_same_seed_draws_the_same_events() -> None:
    import random

    from vv_it.persona import Behavior
    from vv_it.simulator import draw_events

    b = Behavior(confusion=0.5, digression=0.5)
    r1, r2 = random.Random(7), random.Random(7)
    assert [draw_events(b, r1) for _ in range(10)] == [draw_events(b, r2) for _ in range(10)]


async def test_confidence_and_verbosity_shape_the_system_prompt() -> None:
    from vv_it.persona import Behavior

    low = PERSONA.model_copy(update={"behavior": Behavior(confidence="low", verbosity="short")})
    system = SimulatedClient(low, StubLLM()).system_prompt()
    assert "insecure" in system.lower() and "short" in system.lower()


async def test_irritation_only_fires_on_a_repeated_question() -> None:
    from vv_it.persona import Behavior

    angry = PERSONA.model_copy(update={"behavior": Behavior(irritation=1.0), "vague_answers": 0})
    llm = StubLLM(*({"text": "x", "revealed": []} for _ in range(2)))
    client = SimulatedClient(angry, llm, seed=1)
    await client.reply("Como foi a última entrega para um café?")
    assert client.last_events == []
    await client.reply("Como foi a última entrega para o café?")
    assert client.last_events == ["irritated"]
