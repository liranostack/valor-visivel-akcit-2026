"""ApplyGuardrail on the client's input and on the final answer (ADR-007).

Input: blocked (prompt attack, denied topic) -> a short pt-BR reply that returns to the current
question, and the text never reaches the state; masked (PII) -> the masked text moves on.
Output: blocked -> not allowed, and the turn loop sends the stage's safe anchor instead.
A service error fails open on input (the agents and checks still run) and closed on output.
Off when GUARDRAIL_ID is unset or GUARDRAIL_MODE=off (local runs and tests).
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Literal

import boto3

log = logging.getLogger(__name__)

BLOCKED_INPUT_MESSAGE = "Esse assunto fica fora do que a gente está construindo aqui. Voltando:"
Source = Literal["INPUT", "OUTPUT"]


@dataclass(frozen=True)
class InputCheck:
    allowed: bool
    text: str
    message_if_blocked: str | None = None
    masked: bool = False


@dataclass(frozen=True)
class OutputCheck:
    allowed: bool
    text: str


class GuardrailClient:
    def __init__(
        self,
        guardrail_id: str | None,
        version: str = "DRAFT",
        client: Any = None,
        enabled: bool = True,
    ) -> None:
        self.guardrail_id = guardrail_id
        self.version = version
        self.enabled = enabled and bool(guardrail_id)
        self._client = client

    async def check_input(self, text: str, current_question: str = "") -> InputCheck:
        if not self.enabled:
            return InputCheck(True, text)
        try:
            res = await self._apply("INPUT", text)
        except Exception as exc:
            log.warning("guardrail input unavailable: %s", type(exc).__name__)
            return InputCheck(True, text)
        if _blocked(res):
            message = f"{BLOCKED_INPUT_MESSAGE} {current_question}".strip()
            return InputCheck(False, "", message_if_blocked=message)
        if res.get("action") == "GUARDRAIL_INTERVENED" and res.get("outputs"):
            return InputCheck(True, res["outputs"][0]["text"], masked=True)
        return InputCheck(True, text)

    async def check_output(self, text: str) -> OutputCheck:
        if not self.enabled:
            return OutputCheck(True, text)
        try:
            res = await self._apply("OUTPUT", text)
        except Exception as exc:
            log.warning("guardrail output unavailable: %s", type(exc).__name__)
            return OutputCheck(False, text)
        return OutputCheck(not _blocked(res), text)

    async def _apply(self, source: Source, text: str) -> dict[str, Any]:
        client = self._client or boto3.client("bedrock-runtime")
        self._client = client
        return await asyncio.to_thread(
            client.apply_guardrail,
            guardrailIdentifier=self.guardrail_id,
            guardrailVersion=self.version,
            source=source,
            content=[{"text": {"text": text}}],
            outputScope="INTERVENTIONS",
        )


def from_env() -> GuardrailClient:
    guardrail_id = os.environ.get("GUARDRAIL_ID")
    enabled = os.environ.get("GUARDRAIL_MODE", "on").lower() != "off"
    return GuardrailClient(
        guardrail_id, os.environ.get("GUARDRAIL_VERSION", "DRAFT"), enabled=enabled
    )


def _blocked(res: dict[str, Any]) -> bool:
    if res.get("action") != "GUARDRAIL_INTERVENED":
        return False
    return any(_has_blocked_action(a) for a in res.get("assessments", []))


def _has_blocked_action(node: Any) -> bool:
    if isinstance(node, dict):
        if node.get("action") == "BLOCKED":
            return True
        return any(_has_blocked_action(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_blocked_action(v) for v in node)
    return False
