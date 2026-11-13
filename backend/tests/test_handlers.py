"""WebSocket Lambdas: connect/disconnect, message hand-off and the worker relaying SSE events."""

import io
import json
from typing import Any

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber
from vv_backend import connection, message, worker
from vv_contracts.ws import parse_server_event

ENDPOINT = "https://abc.execute-api.us-east-1.amazonaws.com/prod"
CONN = "conn-1"
ARN = "arn:aws:bedrock-agentcore:us-east-1:000000000000:runtime/valorvisivel_chat-xyz"


def client(name: str) -> Any:
    return boto3.client(
        name,
        region_name="us-east-1",
        aws_access_key_id="t",
        aws_secret_access_key="t",
        **({"endpoint_url": ENDPOINT} if name == "apigatewaymanagementapi" else {}),
    )


def ws_event(body: object) -> dict[str, Any]:
    return {
        "requestContext": {
            "connectionId": CONN,
            "domainName": "abc.execute-api.us-east-1.amazonaws.com",
            "stage": "prod",
        },
        "body": json.dumps(body) if not isinstance(body, str) else body,
    }


def sse(*events: dict[str, Any]) -> StreamingBody:
    raw = "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()
    return StreamingBody(io.BytesIO(raw), len(raw))


def posted(stub_calls: list[bytes]) -> list[str]:
    return [parse_server_event(b).type for b in stub_calls]


class TestConnection:
    def test_connect_and_disconnect_accept(self) -> None:
        assert connection.on_connect(ws_event(""), None)["statusCode"] == 200
        assert connection.on_disconnect(ws_event(""), None)["statusCode"] == 200


class TestMessage:
    def test_valid_message_is_handed_to_the_worker_asynchronously(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WORKER_FUNCTION_NAME", "vv-worker")
        lam = client("lambda")
        body = {"action": "sendMessage", "type": "user_message", "session_id": "s1", "text": "oi"}
        with Stubber(lam) as stub:
            stub.add_response(
                "invoke",
                {"StatusCode": 202},
                {"FunctionName": "vv-worker", "InvocationType": "Event", "Payload": ANY},
            )
            res = message.handle(ws_event(body), None, lambda_client=lam)
        assert res["statusCode"] == 200

    def test_invalid_message_returns_a_safe_error_to_the_connection(self) -> None:
        api = client("apigatewaymanagementapi")
        sent: list[bytes] = []
        with Stubber(api) as stub:
            stub.add_response("post_to_connection", {}, {"ConnectionId": CONN, "Data": ANY})
            res = message.handle(
                ws_event({"action": "sendMessage", "type": "nope"}),
                None,
                lambda_client=client("lambda"),
                api_client=api,
                sent=sent,
            )
        assert res["statusCode"] == 200
        assert posted(sent) == ["error"]
        assert "Traceback" not in sent[0].decode()


class TestWorker:
    def job(self) -> dict[str, Any]:
        return {
            "connection_id": CONN,
            "endpoint": ENDPOINT,
            "message": {"type": "user_message", "session_id": "s1", "text": "oi"},
        }

    def test_relays_every_event_from_the_runtime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CHAT_RUNTIME_ARN", ARN)
        rt, api = client("bedrock-agentcore"), client("apigatewaymanagementapi")
        sent: list[bytes] = []
        events = [
            {"type": "token", "session_id": "s1", "text": "Olá "},
            {"type": "message_done", "session_id": "s1", "message": "Olá", "turn_seq": 1},
        ]
        with Stubber(rt) as rs, Stubber(api) as aps:
            rs.add_response(
                "invoke_agent_runtime",
                {"response": sse(*events), "contentType": "text/event-stream", "statusCode": 200},
                {
                    "agentRuntimeArn": ARN,
                    "runtimeSessionId": worker.runtime_session_id("s1", CONN),
                    "payload": ANY,
                    "contentType": "application/json",
                    "accept": "text/event-stream",
                },
            )
            for _ in events:
                aps.add_response("post_to_connection", {}, {"ConnectionId": CONN, "Data": ANY})
            worker.handle(self.job(), None, runtime_client=rt, api_client=api, sent=sent)
        assert posted(sent) == ["token", "message_done"]

    def test_runtime_error_becomes_a_pt_br_error_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CHAT_RUNTIME_ARN", ARN)
        rt, api = client("bedrock-agentcore"), client("apigatewaymanagementapi")
        sent: list[bytes] = []
        with Stubber(rt) as rs, Stubber(api) as aps:
            rs.add_client_error("invoke_agent_runtime", "ThrottlingException", "slow down")
            aps.add_response("post_to_connection", {}, {"ConnectionId": CONN, "Data": ANY})
            worker.handle(self.job(), None, runtime_client=rt, api_client=api, sent=sent)
        assert posted(sent) == ["error"]
        text = sent[0].decode()
        assert "ThrottlingException" not in text and "Tive um problema" in text

    def test_closed_connection_stops_quietly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CHAT_RUNTIME_ARN", ARN)
        rt, api = client("bedrock-agentcore"), client("apigatewaymanagementapi")
        events = [{"type": "token", "session_id": "s1", "text": f"{i} "} for i in range(3)]
        with Stubber(rt) as rs, Stubber(api) as aps:
            rs.add_response(
                "invoke_agent_runtime",
                {"response": sse(*events), "contentType": "text/event-stream", "statusCode": 200},
                {
                    "agentRuntimeArn": ARN,
                    "runtimeSessionId": ANY,
                    "payload": ANY,
                    "contentType": "application/json",
                    "accept": "text/event-stream",
                },
            )
            aps.add_client_error("post_to_connection", "GoneException", "gone")
            worker.handle(self.job(), None, runtime_client=rt, api_client=api)  # no raise

    def test_runtime_session_id_meets_the_minimum_length(self) -> None:
        assert len(worker.runtime_session_id("s1", CONN)) >= 33
        assert worker.runtime_session_id("s1", "x") == worker.runtime_session_id("s1", "y")
        assert len(worker.runtime_session_id(None, CONN)) >= 33


class TestAccessCode:
    """A.04.10: the WebSocket only opens with the access code (cost protection for the demo)."""

    @staticmethod
    def connect_with(code: str | None) -> int:
        event = ws_event("")
        if code is not None:
            event["queryStringParameters"] = {"code": code}
        return connection.on_connect(event, None)["statusCode"]

    def test_right_code_opens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ACCESS_CODE_SHA256", connection.code_hash("akcit-2026"))
        assert self.connect_with("akcit-2026") == 200

    def test_wrong_or_missing_code_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ACCESS_CODE_SHA256", connection.code_hash("akcit-2026"))
        assert self.connect_with("errado") == 401
        assert self.connect_with(None) == 401

    def test_code_ignores_spaces_and_case(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ACCESS_CODE_SHA256", connection.code_hash("akcit-2026"))
        assert self.connect_with(" AKCIT-2026 ") == 200

    def test_without_a_configured_code_it_stays_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ACCESS_CODE_SHA256", raising=False)
        assert self.connect_with(None) == 200
