"""ApplyGuardrail client: pass, mask and block on input and output; off mode for local runs."""

from typing import Any

import boto3
import pytest
from botocore.stub import ANY, Stubber
from vv_chat.guardrails import BLOCKED_INPUT_MESSAGE, GuardrailClient, from_env


def client() -> Any:
    return boto3.client(
        "bedrock-runtime",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def response(
    action: str, text: str | None = None, assessments: list[Any] | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "usage": {
            "topicPolicyUnits": 1,
            "contentPolicyUnits": 1,
            "wordPolicyUnits": 0,
            "sensitiveInformationPolicyUnits": 1,
            "sensitiveInformationPolicyFreeUnits": 0,
            "contextualGroundingPolicyUnits": 0,
        },
        "action": action,
        "outputs": [{"text": text}] if text is not None else [],
        "assessments": assessments or [],
    }
    return out


def expected(source: str, text: str) -> dict[str, Any]:
    return {
        "guardrailIdentifier": "gr-1",
        "guardrailVersion": "1",
        "source": source,
        "content": [{"text": {"text": text}}],
        "outputScope": ANY,
    }


PII = [
    {
        "sensitiveInformationPolicy": {
            "piiEntities": [{"match": "123.456.789-00", "type": "CPF", "action": "ANONYMIZED"}],
            "regexes": [],
        }
    }
]
TOPIC = [{"topicPolicy": {"topics": [{"name": "medical", "type": "DENY", "action": "BLOCKED"}]}}]
ATTACK = [
    {
        "contentPolicy": {
            "filters": [{"type": "PROMPT_ATTACK", "confidence": "HIGH", "action": "BLOCKED"}]
        }
    }
]


def stubbed() -> tuple[GuardrailClient, Stubber]:
    c = client()
    return GuardrailClient("gr-1", "1", c), Stubber(c)


class TestInput:
    async def test_clean_text_passes_unchanged(self) -> None:
        g, stub = stubbed()
        stub.add_response("apply_guardrail", response("NONE"), expected("INPUT", "Faço bolos."))
        with stub:
            out = await g.check_input("Faço bolos.")
        assert out.allowed and out.text == "Faço bolos." and out.message_if_blocked is None

    async def test_pii_is_masked_and_the_masked_text_moves_on(self) -> None:
        g, stub = stubbed()
        text = "Meu CPF é 123.456.789-00"
        stub.add_response(
            "apply_guardrail",
            response("GUARDRAIL_INTERVENED", "Meu CPF é {CPF}", PII),
            expected("INPUT", text),
        )
        with stub:
            out = await g.check_input(text)
        assert out.allowed
        assert out.text == "Meu CPF é {CPF}"
        assert out.masked

    @pytest.mark.parametrize("assessments", [TOPIC, ATTACK])
    async def test_blocked_input_returns_a_way_back_to_the_question(
        self, assessments: list[Any]
    ) -> None:
        g, stub = stubbed()
        stub.add_response(
            "apply_guardrail",
            response("GUARDRAIL_INTERVENED", "bloqueado", assessments),
            expected("INPUT", "x"),
        )
        with stub:
            out = await g.check_input("x", current_question="O que você confere antes?")
        assert not out.allowed
        assert out.message_if_blocked == f"{BLOCKED_INPUT_MESSAGE} O que você confere antes?"
        assert out.text == ""  # blocked text never goes to the state


class TestOutput:
    async def test_clean_output_passes(self) -> None:
        g, stub = stubbed()
        stub.add_response("apply_guardrail", response("NONE"), expected("OUTPUT", "Pergunta?"))
        with stub:
            out = await g.check_output("Pergunta?")
        assert out.allowed and out.text == "Pergunta?"

    async def test_blocked_output_is_not_allowed(self) -> None:
        g, stub = stubbed()
        stub.add_response(
            "apply_guardrail",
            response("GUARDRAIL_INTERVENED", "bloqueado", TOPIC),
            expected("OUTPUT", "Tome este remédio?"),
        )
        with stub:
            out = await g.check_output("Tome este remédio?")
        assert not out.allowed


async def test_service_error_fails_closed_on_output_and_open_on_input() -> None:
    g, stub = stubbed()
    stub.add_client_error("apply_guardrail", "ThrottlingException")
    stub.add_client_error("apply_guardrail", "ThrottlingException")
    with stub:
        inp = await g.check_input("Faço bolos.")
        out = await g.check_output("Pergunta?")
    assert inp.allowed and inp.text == "Faço bolos."  # the loop still runs its own checks
    assert not out.allowed  # the loop sends the safe anchor instead


class TestFromEnv:
    def test_off_without_guardrail_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GUARDRAIL_ID", raising=False)
        assert from_env().enabled is False

    async def test_off_mode_passes_everything(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GUARDRAIL_ID", "gr-1")
        monkeypatch.setenv("GUARDRAIL_MODE", "off")
        g = from_env()
        assert not g.enabled
        assert (await g.check_input("oi")).allowed
        assert (await g.check_output("oi?")).allowed

    def test_on_with_id_and_version(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GUARDRAIL_ID", "gr-1")
        monkeypatch.setenv("GUARDRAIL_VERSION", "3")
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        monkeypatch.delenv("GUARDRAIL_MODE", raising=False)
        g = from_env()
        assert g.enabled and g.guardrail_id == "gr-1" and g.version == "3"
