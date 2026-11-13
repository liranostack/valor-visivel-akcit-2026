"""ApiStack: WebSocket API with $connect, $disconnect and sendMessage, async worker, wss output."""

import json
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk import aws_lambda as lambda_
from aws_cdk.assertions import Template
from vv_infra.stacks.api_stack import ApiStack

ENV = cdk.Environment(account="000000000000", region="us-east-1")
CHAT_ARN = "arn:aws:bedrock-agentcore:us-east-1:000000000000:runtime/valorvisivel_chat-abc"


@pytest.fixture(scope="module")
def template() -> Template:
    stack = ApiStack(
        cdk.App(),
        "Api",
        env=ENV,
        chat_runtime_arn=CHAT_ARN,
        code=lambda_.Code.from_inline("def handler(e, c): return None"),
    )
    return Template.from_stack(stack)


def test_three_routes(template: Template) -> None:
    keys = {
        r["Properties"]["RouteKey"]
        for r in template.find_resources("AWS::ApiGatewayV2::Route").values()
    }
    assert keys == {"$connect", "$disconnect", "sendMessage"}


def test_wss_url_output(template: Template) -> None:
    outputs = template.find_outputs("WebSocketUrl")
    assert outputs
    assert "wss://" in json.dumps(outputs)


def functions(template: Template) -> dict[str, dict[str, Any]]:
    return {
        r["Properties"]["Handler"]: r["Properties"]
        for r in template.find_resources("AWS::Lambda::Function").values()
        if "Handler" in r["Properties"]
    }


def test_handlers_and_worker_timeout(template: Template) -> None:
    fns = functions(template)
    assert {
        "vv_backend.connection.on_connect",
        "vv_backend.connection.on_disconnect",
        "vv_backend.message.handle",
        "vv_backend.worker.handle",
    } <= set(fns)
    worker = fns["vv_backend.worker.handle"]
    assert worker["Timeout"] == 120
    assert worker["Environment"]["Variables"]["CHAT_RUNTIME_ARN"] == CHAT_ARN
    assert "WORKER_FUNCTION_NAME" in fns["vv_backend.message.handle"]["Environment"]["Variables"]


def test_permissions(template: Template) -> None:
    doc = json.dumps(
        [
            p["Properties"]["PolicyDocument"]
            for p in template.find_resources("AWS::IAM::Policy").values()
        ]
    )
    assert "bedrock-agentcore:InvokeAgentRuntime" in doc and CHAT_ARN in doc
    assert "execute-api:ManageConnections" in doc
    assert "lambda:InvokeFunction" in doc


def test_access_code_hash_and_throttle() -> None:
    # A.04.10: the code reaches $connect only as a hash; the stage caps the message rate.
    stack = ApiStack(
        cdk.App(),
        "ApiCode",
        env=ENV,
        chat_runtime_arn=CHAT_ARN,
        code=lambda_.Code.from_inline("def handler(e, c): return None"),
        access_code_sha256="ab" * 32,
    )
    t = Template.from_stack(stack)
    connect = functions(t)["vv_backend.connection.on_connect"]
    assert connect["Environment"]["Variables"]["ACCESS_CODE_SHA256"] == "ab" * 32
    stage = next(iter(t.find_resources("AWS::ApiGatewayV2::Stage").values()))["Properties"]
    limits = stage["DefaultRouteSettings"]
    assert limits["ThrottlingRateLimit"] <= 5
    assert limits["ThrottlingBurstLimit"] <= 10
