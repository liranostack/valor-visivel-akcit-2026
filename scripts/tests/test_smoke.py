"""smoke.py against a local fake WebSocket server (A.04.08): the same protocol as API Gateway."""

import asyncio
import importlib.util
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve
from websockets.http11 import Request, Response

SPEC = importlib.util.spec_from_file_location(
    "smoke", Path(__file__).resolve().parents[1] / "smoke.py"
)
assert SPEC and SPEC.loader
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)

SID = "s-smoke"


def step(field: str, options: list[str], free_text: bool) -> dict[str, Any]:
    return {
        "type": "onboarding_step",
        "session_id": SID,
        "field": field,
        "question": f"{field}?",
        "options": options,
        "multiple": False,
        "free_text": free_text,
        "step": 1,
        "total": 3,
    }


def say(text: str, seq: int) -> list[dict[str, Any]]:
    tokens = [{"type": "token", "session_id": SID, "text": w + " "} for w in text.split()]
    return [*tokens, {"type": "message_done", "session_id": SID, "message": text, "turn_seq": seq}]


def fake_server(*, fail_on_answer: int | None = None):
    async def handler(ws: ServerConnection) -> None:
        answers = 0
        async for raw in ws:
            msg = json.loads(raw)
            assert msg.pop("action") == "sendMessage"
            out: list[dict[str, Any]] = []
            kind = msg["type"]
            if kind == "start_session":
                out = [{"type": "state", "session_id": SID, "status": "onboarding"}]
                out.append(step("consent", ["Concordo", "Não concordo"], False))
            elif kind == "consent":
                out = [step("offer", [], True)]
            elif kind == "onboarding_answer":
                out = [step("business_structure", ["MEI", "Autônoma"], False)]
                if msg["field"] == "business_structure":
                    out = [step("baseline", [], True)]
            elif kind == "user_message" and answers == 0 and msg["text"] == smoke.BASELINE:
                answers = -1
                out = [
                    {"type": "state", "session_id": SID, "status": "in_layer", "layer_index": 1},
                    *say("Como foi o último atendimento?", 1),
                ]
            elif kind == "user_message":
                answers = max(answers, 0) + 1
                if fail_on_answer == answers:
                    out = [{"type": "error", "session_id": SID, "code": "x", "message": "falhou"}]
                else:
                    out = [
                        {"type": "progress", "session_id": SID, "message": "Lendo…"},
                        *say("Você contou isso. O que vem depois?", answers + 1),
                    ]
            for event in out:
                await ws.send(json.dumps(event))

    return handler


@asynccontextmanager
async def running(code: str | None = None, **kwargs: Any) -> AsyncIterator[str]:
    def check_code(connection: ServerConnection, request: Request) -> Response | None:
        # Like $connect on API Gateway: the handshake itself is refused (401).
        if code is not None and f"code={code}" not in request.path:
            return connection.respond(401, "Unauthorized")
        return None

    async with serve(fake_server(**kwargs), "127.0.0.1", 0, process_request=check_code) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        yield f"ws://127.0.0.1:{port}"


async def test_a_full_run_passes_every_step() -> None:
    async with running() as url:
        results = await smoke.run_smoke(url, timeout=5)
    assert [r.name for r in results] == smoke.STEP_NAMES
    assert all(r.ok for r in results), [r for r in results if not r.ok]
    vague = next(r for r in results if r.name == "resposta vaga")
    assert vague.first_token_s is not None
    # Only the answers carry a first-token time; the report must format every step.
    assert all(r.first_token_s is None for r in results if not r.name.startswith("resposta"))
    assert len(smoke.report(results)) == len(results)


async def test_an_error_event_fails_the_step() -> None:
    async with running(fail_on_answer=1) as url:
        results = await smoke.run_smoke(url, timeout=5)
    vague = next(r for r in results if r.name == "resposta vaga")
    assert not vague.ok
    assert "falhou" in vague.detail
    assert not smoke.passed(results)


async def test_access_code_goes_in_the_url() -> None:
    async with running(code="abc") as url:
        assert smoke.passed(await smoke.run_smoke(url, code="abc", timeout=5))
        refused = await smoke.run_smoke(url, code="errado", timeout=5)
    assert refused[0].name == "conexão" and not refused[0].ok


async def test_silence_is_a_timeout_not_a_hang() -> None:
    async def mute(ws: ServerConnection) -> None:
        async for _ in ws:
            pass

    async with serve(mute, "127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        results = await asyncio.wait_for(
            smoke.run_smoke(f"ws://127.0.0.1:{port}", timeout=0.5), timeout=5
        )
    assert not results[-1].ok
    assert "tempo" in results[-1].detail


def test_report_lines() -> None:
    results = [smoke.StepResult("conexão", True, 0.1), smoke.StepResult("x", False, 1, "boom")]
    lines = smoke.report(results)
    assert lines[0].startswith("OK") and lines[1].startswith("FALHA")


@pytest.mark.parametrize("url", ["https://x", "ftp://x"])
def test_only_websocket_urls(url: str) -> None:
    with pytest.raises(ValueError):
        smoke.with_code(url, None)
