"""AgentCore Runtime HTTP app: POST /invocations streams ServerEvents as SSE; GET /ping."""

import json
from collections.abc import AsyncIterator

from starlette.testclient import TestClient
from vv_chat.app import build_app, placeholder_handler
from vv_contracts.ws import ClientMessage, ServerEvent, TokenEvent, parse_server_event


def events(response_text: str) -> list[ServerEvent]:
    return [
        parse_server_event(line.removeprefix("data: "))
        for line in response_text.splitlines()
        if line.startswith("data: ")
    ]


def test_ping() -> None:
    client = TestClient(build_app(placeholder_handler))
    assert client.get("/ping").json()["status"] == "Healthy"


def test_placeholder_streams_tokens_then_done() -> None:
    client = TestClient(build_app(placeholder_handler))
    body = {"type": "user_message", "session_id": "s1", "text": "oi"}
    out = events(client.post("/invocations", json=body).text)
    assert [e.type for e in out][-1] == "message_done"
    assert any(e.type == "token" for e in out)


def test_invalid_message_returns_error_event_in_pt_br() -> None:
    client = TestClient(build_app(placeholder_handler))
    out = events(client.post("/invocations", json={"type": "hack"}).text)
    assert len(out) == 1 and out[0].type == "error"
    assert out[0].code == "bad_request"
    assert "mensagem" in out[0].message.lower()


def test_handler_failure_never_leaks_stack_trace() -> None:
    async def broken(msg: ClientMessage) -> AsyncIterator[ServerEvent]:
        yield TokenEvent(session_id="s1", text="ini")
        raise RuntimeError("secret internal detail")

    client = TestClient(build_app(broken))
    body = {"type": "user_message", "session_id": "s1", "text": "oi"}
    text = client.post("/invocations", json=body).text
    out = events(text)
    assert out[-1].type == "error"
    assert "secret internal detail" not in text
    assert json.loads(text.splitlines()[0].removeprefix("data: "))["type"] == "token"
