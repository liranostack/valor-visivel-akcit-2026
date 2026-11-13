"""LLM judges with a stub model: conversation metrics, truth recall, reasoning audit (A.02.21)."""

from typing import Any, TypeVar

from pydantic import BaseModel
from vv_it.journey import JourneyRecord, TurnRecord
from vv_it.judges.judge import (
    ConversationVerdict,
    ReasoningVerdict,
    audit_reasoning,
    judge_conversation,
    truth_recall,
)
from vv_it.persona import SCENARIOS, load_persona

T = TypeVar("T", bound=BaseModel)
PERSONA = load_persona(SCENARIOS / "pastelaria.yaml")
HIDDEN = PERSONA.truth_ids("hidden")
EXTERNAL = PERSONA.truth_ids("external")
RECORD = JourneyRecord(
    persona="pastelaria",
    session_id="s",
    first_question="Como foi a última vez?",
    turns=[
        TurnRecord(
            seq=2,
            question="Como foi a última vez?",
            answer="normal",
            reply="E o que vocês conferem?",
            steps=[{"step": "conductor", "data": {"decision": {"action": "deepen"}}}],
        )
    ],
    facts=[],
    gaps=[],
    synthesis=None,
    ended="max_turns",
)


class StubLLM:
    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.systems: list[str] = []
        self.prompts: list[str] = []

    async def generate(self, system: str, prompt: str, output: type[T]) -> T:
        self.systems.append(system)
        self.prompts.append(prompt)
        return output.model_validate(self.reply)


CONVERSATION = {
    "metrics": [
        {"metric": "question_quality", "score": 3, "evidence_turns": [2], "rationale": "ok"}
    ],
    "truths": [
        {"truth_id": HIDDEN[0], "surfaced": "fact", "note": ""},
        {"truth_id": EXTERNAL[0], "surfaced": "missed", "note": ""},
    ],
    "summary": "resumo",
}


async def test_conversation_judge_sees_transcript_truths_and_the_method_pitfalls() -> None:
    llm = StubLLM(CONVERSATION)
    verdict = await judge_conversation(RECORD, PERSONA, llm)
    assert isinstance(verdict, ConversationVerdict)
    prompt = llm.prompts[0]
    assert "E o que vocês conferem?" in prompt and "normal" in prompt
    assert PERSONA.truths[0].text in prompt
    assert "Armadilhas comuns" in llm.systems[0]


async def test_unknown_truth_ids_from_the_judge_are_dropped() -> None:
    reply = CONVERSATION | {
        "truths": CONVERSATION["truths"] + [{"truth_id": "x", "surfaced": "fact", "note": ""}]
    }
    verdict = await judge_conversation(RECORD, PERSONA, StubLLM(reply))
    assert {t.truth_id for t in verdict.truths} == {HIDDEN[0], EXTERNAL[0]}


def test_truth_recall_counts_hidden_and_external_surfaced_as_fact_or_synthesis() -> None:
    verdict = ConversationVerdict.model_validate(CONVERSATION)
    expected = 1 / (len(HIDDEN) + len(EXTERNAL))
    assert truth_recall(verdict, PERSONA) == expected


async def test_reasoning_auditor_reads_the_steps_and_the_editable_files() -> None:
    llm = StubLLM(
        {
            "issues": [{"turn": 2, "agent": "conductor", "problem": "p", "evidence": "e"}],
            "improvements": [
                {
                    "target": "prompt",
                    "file": "chat-service/prompts/investigator.md",
                    "problem": "p",
                    "proposal": "q",
                    "evidence_turns": [2],
                    "impact": "high",
                }
            ],
        }
    )
    verdict = await audit_reasoning(RECORD, PERSONA, llm)
    assert isinstance(verdict, ReasoningVerdict)
    assert '"action": "deepen"' in llm.prompts[0]
    assert "chat-service/prompts/investigator.md" in llm.prompts[0]


async def test_improvements_pointing_to_unknown_files_are_dropped() -> None:
    llm = StubLLM(
        {
            "issues": [],
            "improvements": [
                {
                    "target": "code",
                    "file": "nowhere.py",
                    "problem": "p",
                    "proposal": "q",
                    "evidence_turns": [],
                    "impact": "low",
                }
            ],
        }
    )
    verdict = await audit_reasoning(RECORD, PERSONA, llm)
    assert verdict.improvements == []


async def test_the_judge_sees_what_the_client_did_on_each_turn() -> None:
    from dataclasses import replace

    turn = replace(RECORD.turns[0], events=["confused"])
    record = replace(RECORD, turns=[turn])
    llm = StubLLM(CONVERSATION)
    await judge_conversation(record, PERSONA, llm)
    assert "confused" in llm.prompts[0]
    assert "difficulty_handling" in llm.systems[0]


async def test_conversation_judge_applies_the_voice_guide() -> None:
    llm = StubLLM(CONVERSATION)
    await judge_conversation(RECORD, PERSONA, llm)
    assert "tone" in llm.systems[0]
    assert "Oralidade" in llm.systems[0]


async def test_conversation_judge_measures_acknowledgment_and_corrective_tone() -> None:
    llm = StubLLM(CONVERSATION)
    await judge_conversation(RECORD, PERSONA, llm)
    assert "acknowledgment" in llm.systems[0] and "corrective_tone" in llm.systems[0]
