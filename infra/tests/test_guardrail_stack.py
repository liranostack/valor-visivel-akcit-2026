"""GuardrailStack (ERD 'Guardrails'): prompt attack, denied topics, PII masking, grounding."""

import re
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template
from vv_infra.stacks.guardrail_stack import (
    BLOCKED_INPUT_MESSAGE,
    BLOCKED_OUTPUT_MESSAGE,
    CPF_REGEX,
    GuardrailStack,
)

ENV = cdk.Environment(account="000000000000", region="us-east-1")


@pytest.fixture(scope="module")
def props() -> dict[str, Any]:
    template = Template.from_stack(GuardrailStack(cdk.App(), "Guardrail", env=ENV))
    template.resource_count_is("AWS::Bedrock::Guardrail", 1)
    template.resource_count_is("AWS::Bedrock::GuardrailVersion", 1)
    resources = template.find_resources("AWS::Bedrock::Guardrail")
    return next(iter(resources.values()))["Properties"]


def test_prompt_attack_filter_on_input(props: dict[str, Any]) -> None:
    filters = props["ContentPolicyConfig"]["FiltersConfig"]
    attack = next(f for f in filters if f["Type"] == "PROMPT_ATTACK")
    assert attack["InputStrength"] == "HIGH"
    assert attack["OutputStrength"] == "NONE"


def test_denied_topics(props: dict[str, Any]) -> None:
    topics = props["TopicPolicyConfig"]["TopicsConfig"]
    names = {t["Name"] for t in topics}
    assert {
        "Aconselhamento juridico",
        "Aconselhamento medico",
        "Aconselhamento de investimento",
    } <= names
    for topic in topics:
        assert topic["Type"] == "DENY"
        assert re.fullmatch(r"[0-9a-zA-Z\-_ !?.]+", topic["Name"])
        assert len(topic["Definition"]) <= 200
        assert all(len(e) <= 100 for e in topic.get("Examples", []))


def test_pii_masked(props: dict[str, Any]) -> None:
    pii = props["SensitiveInformationPolicyConfig"]
    types = {e["Type"]: e["Action"] for e in pii["PiiEntitiesConfig"]}
    assert types["EMAIL"] == "ANONYMIZE"
    assert types["PHONE"] == "ANONYMIZE"
    regexes = {r["Name"]: r for r in pii["RegexesConfig"]}
    assert regexes["CPF"]["Action"] == "ANONYMIZE"


def test_cpf_regex_matches_formats() -> None:
    for cpf in ("123.456.789-09", "12345678909"):
        assert re.search(CPF_REGEX, f"meu cpf é {cpf}")
    assert not re.search(CPF_REGEX, "atendo 12 clientes por semana")


def test_grounding_filter(props: dict[str, Any]) -> None:
    grounding = props["ContextualGroundingPolicyConfig"]["FiltersConfig"]
    assert {g["Type"] for g in grounding} == {"GROUNDING", "RELEVANCE"}


def test_messages_in_pt_br_bring_back_to_topic(props: dict[str, Any]) -> None:
    assert props["BlockedInputMessaging"] == BLOCKED_INPUT_MESSAGE
    assert props["BlockedOutputsMessaging"] == BLOCKED_OUTPUT_MESSAGE
    assert "negócio" in BLOCKED_INPUT_MESSAGE


def test_outputs() -> None:
    template = Template.from_stack(GuardrailStack(cdk.App(), "G", env=ENV))
    outputs = template.find_outputs("*")
    assert {"GuardrailId", "GuardrailVersion"} <= set(outputs)
    template.has_resource_properties(
        "AWS::Bedrock::GuardrailVersion", {"GuardrailIdentifier": Match.any_value()}
    )
