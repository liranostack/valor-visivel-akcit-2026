"""AgentCoreStack: 2 runtimes (MCP + HTTP), 1 memory, least-privilege roles."""

import json
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template
from vv_infra.stacks.agentcore_stack import AgentCoreStack, ModelIds
from vv_infra.stacks.data_stack import DataStack
from vv_infra.stacks.guardrail_stack import GuardrailStack

ENV = cdk.Environment(account="000000000000", region="us-east-1")
MODELS = ModelIds(
    large="us.anthropic.claude-sonnet-5-5",
    small="us.anthropic.claude-haiku-4-5-20251001-v1:0",
)
IMAGES = {
    "chat": "000000000000.dkr.ecr.us-east-1.amazonaws.com/chat:test",
    "mcp": "000000000000.dkr.ecr.us-east-1.amazonaws.com/mcp:test",
}


def synth(tool_gateway: str = "mcp", **kwargs: str) -> Template:
    app = cdk.App()
    data = DataStack(app, "Data", env=ENV)
    guardrail = GuardrailStack(app, "Guardrail", env=ENV)
    stack = AgentCoreStack(
        app,
        "AgentCore",
        env=ENV,
        data=data,
        guardrail=guardrail,
        models=MODELS,
        images=IMAGES,
        tool_gateway=tool_gateway,
        **kwargs,
    )
    return Template.from_stack(stack)


@pytest.fixture(scope="module")
def template() -> Template:
    return synth()


def runtimes(t: Template) -> dict[str, dict[str, Any]]:
    found = t.find_resources("AWS::BedrockAgentCore::Runtime")
    return {r["Properties"]["AgentRuntimeName"]: r["Properties"] for r in found.values()}


def role_statements(t: Template, role_fragment: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for logical_id, res in t.find_resources("AWS::IAM::Policy").items():
        roles = json.dumps(res["Properties"]["Roles"])
        if role_fragment in roles or role_fragment in logical_id:
            out += res["Properties"]["PolicyDocument"]["Statement"]
    return out


def actions(statements: list[dict[str, Any]]) -> set[str]:
    acts: set[str] = set()
    for s in statements:
        a = s["Action"]
        acts |= set(a if isinstance(a, list) else [a])
    return acts


def test_two_runtimes_and_one_memory(template: Template) -> None:
    rts = runtimes(template)
    assert set(rts) == {"valorvisivel_chat", "valorvisivel_mcp"}
    assert rts["valorvisivel_mcp"]["ProtocolConfiguration"] == "MCP"
    assert rts["valorvisivel_chat"]["ProtocolConfiguration"] == "HTTP"
    template.resource_count_is("AWS::BedrockAgentCore::Memory", 1)
    memory = next(iter(template.find_resources("AWS::BedrockAgentCore::Memory").values()))
    assert memory["Properties"]["EventExpiryDuration"] == 30


def test_runtime_environment(template: Template) -> None:
    rts = runtimes(template)
    chat = rts["valorvisivel_chat"]["EnvironmentVariables"]
    assert chat["TOOL_GATEWAY"] == "mcp"
    assert chat["MODEL_LARGE"] == MODELS.large and chat["MODEL_SMALL"] == MODELS.small
    for key in ("MCP_RUNTIME_ARN", "GUARDRAIL_ID", "GUARDRAIL_VERSION", "AGENTCORE_MEMORY_ID"):
        assert key in chat
    mcp = rts["valorvisivel_mcp"]["EnvironmentVariables"]
    assert mcp["STATE_BACKEND"] == "dynamodb" and mcp["KB_SOURCE"] == "s3"
    for key in ("TABLE_NAME", "KB_BUCKET", "KB_VERSION"):
        assert key in mcp


def test_chat_can_call_models_guardrail_mcp_and_memory_only(template: Template) -> None:
    stmts = role_statements(template, "ChatRuntimeRole")
    acts = actions(stmts)
    assert {"bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"} <= acts
    assert "bedrock:ApplyGuardrail" in acts
    assert "bedrock-agentcore:InvokeAgentRuntime" in acts
    assert not any(a.startswith("dynamodb:") or a.startswith("s3:") for a in acts)
    model_resources = json.dumps(
        [s["Resource"] for s in stmts if "bedrock:InvokeModel" in json.dumps(s["Action"])]
    )
    assert "inference-profile/us.anthropic.claude-sonnet-5-5" in model_resources
    assert "foundation-model/anthropic.claude-sonnet-5-5" in model_resources
    assert "foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0" in model_resources


def test_mcp_can_reach_data_only(template: Template) -> None:
    acts = actions(role_statements(template, "McpRuntimeRole"))
    assert any(a.startswith("dynamodb:") for a in acts)
    assert "s3:GetObject" in acts
    assert not any(a.startswith("bedrock:") for a in acts)


def test_no_wildcard_resource_without_justification(template: Template) -> None:
    allowed = {
        "ecr:GetAuthorizationToken",  # the service does not support resource-level permissions
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
        "cloudwatch:PutMetricData",  # scoped by namespace condition instead
    }
    for res in template.find_resources("AWS::IAM::Policy").values():
        for s in res["Properties"]["PolicyDocument"]["Statement"]:
            if s["Resource"] == "*":
                a = s["Action"]
                assert set(a if isinstance(a, list) else [a]) <= allowed, s


def test_inprocess_gateway_moves_data_permissions_to_chat() -> None:
    t = synth("inprocess")
    chat = runtimes(t)["valorvisivel_chat"]["EnvironmentVariables"]
    assert chat["TOOL_GATEWAY"] == "inprocess" and chat["STATE_BACKEND"] == "dynamodb"
    acts = actions(role_statements(t, "ChatRuntimeRole"))
    assert any(a.startswith("dynamodb:") for a in acts) and "s3:GetObject" in acts


def test_name_prefix_makes_account_unique_names_distinct() -> None:
    """A second deploy (-c prefix=ValorVisivelV2) must not collide with the first."""
    t = synth(name_prefix="valorvisivelv2")
    assert set(runtimes(t)) == {"valorvisivelv2_chat", "valorvisivelv2_mcp"}
    t.has_resource_properties("AWS::BedrockAgentCore::Memory", {"Name": "valorvisivelv2_history"})


def test_invalid_name_prefix_is_an_error() -> None:
    with pytest.raises(ValueError, match="name_prefix"):
        synth(name_prefix="valor-visivel")
