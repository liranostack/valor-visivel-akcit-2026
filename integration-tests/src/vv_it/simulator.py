"""Simulated client (A.02.20): a model plays the persona, or scripted answers replay without
network (deterministic mode for CI)."""

import random
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process
from vv_chat.agents.llm import StructuredLLM
from vv_contracts.agents import AbcOption

from vv_it.persona import Behavior, Persona

REPEAT_SIMILARITY = 70  # a question this close to an earlier one feels repeated to her
CONFIDENCE = {
    "low": "You are insecure about your business: you hedge ('acho que', 'não sei se é isso'), "
    "undervalue what you do and apologise for simple answers.",
    "medium": "You talk about your business plainly, without boasting or undervaluing it.",
    "high": "You are very sure of yourself: you answer with confident generic claims "
    "('somos os melhores', 'qualidade total') before any concrete detail, and dislike being "
    "asked for proof.",
}
VERBOSITY = {
    "short": "Keep answers short: one sentence, sometimes a few words.",
    "medium": "Answers of one to three sentences.",
    "long": "Long answers: you tell stories with details, sometimes beyond what was asked.",
}
EVENT_INSTRUCTIONS = {
    "confused": "In this answer, misunderstand the question: answer a nearby but different "
    "question, or ask what it means ('como assim?', 'não entendi') instead of answering.",
    "digress": "In this answer, drift into an unrelated story about your day or your family "
    "before (or instead of) answering.",
    "irritated": "This question feels like one you already answered: show mild impatience "
    "('já falei isso', 'é o que eu disse') and answer briefly.",
}


def draw_events(behavior: Behavior, rng: random.Random) -> list[str]:
    """What happens in her next answer, drawn from the persona's chances (irritation is
    decided by the question, see SimulatedClient)."""
    events: list[str] = []
    if rng.random() < behavior.confusion:
        events.append("confused")
    if rng.random() < behavior.digression:
        events.append("digress")
    return events


PROMPT = Path(__file__).with_name("simulator.md")


class ClientReply(BaseModel):
    text: str = Field(description="Her answer in pt-BR; empty when she only clicked A or B.")
    picked: Literal["A", "B", "C"] | None = Field(
        default=None, description="Option clicked, when the message offered A/B/C."
    )
    revealed: list[str] = Field(
        default_factory=list[str], description="Ids of the true facts this answer tells."
    )


class SimulatedClient:
    def __init__(
        self, persona: Persona, llm: StructuredLLM | None = None, *, seed: int = 0
    ) -> None:
        self.persona = persona
        self.llm = llm
        self.history: list[tuple[str, str]] = []
        self.last_events: list[str] = []
        self._script = list(persona.scripted_answers)
        self._rng = random.Random(f"{persona.slug}:{seed}")

    def system_prompt(self) -> str:
        truths = "\n".join(
            f"- [{t.id}] ({t.kind}) {t.text}"
            + (f" — reveal when: {t.reveal_when}" if t.reveal_when else "")
            for t in self.persona.truths
        )
        b = self.persona.behavior
        style = f"{self.persona.style.strip()} {CONFIDENCE[b.confidence]} {VERBOSITY[b.verbosity]}"
        return PROMPT.read_text(encoding="utf-8").format(
            who=self.persona.who.strip(), style=style, truths=truths
        )

    async def reply(self, question: str, options: list[AbcOption] | None = None) -> ClientReply:
        if self.llm is None:
            self.last_events = []
            text = self._script.pop(0) if self._script else ""
            reply = ClientReply(text=text)
        else:
            self.last_events = self._events(question)
            reply = await self.llm.generate(
                self.system_prompt(), self._prompt(question, options), ClientReply
            )
            known = {t.id for t in self.persona.truths}
            reply = reply.model_copy(update={"revealed": [r for r in reply.revealed if r in known]})
            reply = self._as_sent(reply, options)
        self.history.append((question, reply.text))
        return reply

    def _events(self, question: str) -> list[str]:
        events = draw_events(self.persona.behavior, self._rng)
        repeated = any(
            fuzz.token_set_ratio(question, before, processor=default_process) >= REPEAT_SIMILARITY
            for before, _ in self.history
        )
        if repeated and self._rng.random() < self.persona.behavior.irritation:
            events.append("irritated")
        return events

    def _prompt(self, question: str, options: list[AbcOption] | None) -> str:
        past = "\n\n".join(f"Assistente: {q}\nVocê: {a}" for q, a in self.history) or "(início)"
        shown = "\n".join(f"{o.label}) {o.text}" for o in options or [])
        n = len(self.history)
        vague = (
            f"\n\nThis is answer {n + 1}: keep it vague and generic, the way people start "
            "(no concrete episode, no hidden fact), unless the question is very concrete."
            if n < self.persona.vague_answers
            else ""
        )
        now = "".join(f"\n\n{EVENT_INSTRUCTIONS[e]}" for e in self.last_events)
        return (
            f"<conversation>\n{past}\n</conversation>\n\n"
            f"<last_message>\n{question}\n{shown}\n</last_message>{vague}{now}"
        )

    @staticmethod
    def _as_sent(reply: ClientReply, options: list[AbcOption] | None) -> ClientReply:
        """A click on A or B sends the option text, as the UI does."""
        if reply.picked in ("A", "B") and options and not reply.text.strip():
            chosen = next((o for o in options if o.label == reply.picked), None)
            if chosen is not None:
                return reply.model_copy(update={"text": f"{chosen.label}) {chosen.text}"})
        return reply
