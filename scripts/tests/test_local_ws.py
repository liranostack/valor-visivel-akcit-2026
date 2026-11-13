"""local_ws.py: the WebSocket the frontend talks to, served from this machine (open-source demo)."""

import importlib.util
import json
from collections.abc import AsyncIterator
from pathlib import Path

from vv_contracts.ws import ClientMessage, MessageDoneEvent, ServerEvent, StartSession, TokenEvent
from websockets.asyncio.client import connect

SPEC = importlib.util.spec_from_file_location(
    "local_ws", Path(__file__).resolve().parents[1] / "local_ws.py"
)
assert SPEC and SPEC.loader
local_ws = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local_ws)


async def echo(msg: ClientMessage) -> AsyncIterator[ServerEvent]:
    kind = "start" if isinstance(msg, StartSession) else msg.type
    yield TokenEvent(session_id="s", text=kind)
    yield MessageDoneEvent(session_id="s", message=kind, turn_seq=1)


async def test_relays_each_message_to_the_handler_and_streams_back() -> None:
    async with local_ws.serve_local(echo, port=0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}?code=ignored") as ws:
            await ws.send(json.dumps({"action": "sendMessage", "type": "start_session"}))
            events = [json.loads(await ws.recv()) for _ in range(2)]
    assert [e["type"] for e in events] == ["token", "message_done"]
    assert events[1]["message"] == "start"


async def test_a_bad_message_gets_an_error_event_not_a_dropped_socket() -> None:
    async with local_ws.serve_local(echo, port=0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}") as ws:
            await ws.send(json.dumps({"action": "sendMessage", "type": "hack"}))
            error = json.loads(await ws.recv())
            await ws.send(json.dumps({"type": "start_session"}))
            again = json.loads(await ws.recv())
    assert error["type"] == "error" and error["code"] == "bad_request"
    assert again["type"] == "token"


async def test_a_handler_failure_becomes_an_error_event() -> None:
    async def broken(msg: ClientMessage) -> AsyncIterator[ServerEvent]:
        raise RuntimeError("no credentials")
        yield  # pragma: no cover

    async with local_ws.serve_local(broken, port=0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}") as ws:
            await ws.send(json.dumps({"type": "start_session"}))
            error = json.loads(await ws.recv())
    assert error["type"] == "error"
    assert "no credentials" in error["message"]
