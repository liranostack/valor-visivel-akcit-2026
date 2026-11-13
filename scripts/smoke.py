"""Smoke test against the deployed WebSocket (A.04.08). Human-run at the deploy checkpoints.

Opens a session, accepts the consent, answers the onboarding, gives the baseline and two answers
(one vague, one concrete), and checks each step: a reply arrives in time, it asks something, and
no error event shows up. Prints OK/FALHA per step and exits 1 on any failure.
ERD 'Disponibilidade na demo': the session must pass 3 times in a row (--runs 3).

    uv run python scripts/smoke.py --ws-url wss://<api>/prod --code '<access code>' --runs 3

The WebSocket does not expose the Conductor's decision (deepen/advance); check it in the
session export (scripts/export_session.py) when a run looks wrong.
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

BASELINE = "Faço atendimento com carinho e qualidade, cada cliente é único."
VAGUE = "Ah, eu faço tudo com muito cuidado e atenção, sabe?"
CONCRETE = (
    "Ontem uma cliente chegou com dor nas costas. Antes de começar eu perguntei como ela dormiu "
    "e onde doía mais, e mudei a pressão no lado esquerdo porque ela disse que ali estava pior."
)
FREE_TEXT = {
    "offer": "Massoterapia relaxante e terapêutica",
    "audience": "Mulheres que trabalham sentadas o dia todo",
    "perceived_difficulty": "Explicar por que meu preço é maior",
    "difficulty_when": "quando a pessoa pergunta o preço pelo WhatsApp",
}
STEP_NAMES = ["conexão", "consentimento", "onboarding", "primeira pergunta", "resposta vaga",
              "resposta concreta"]  # fmt: skip


@dataclass
class StepResult:
    name: str
    ok: bool
    seconds: float
    detail: str = ""
    first_token_s: float | None = None


class SmokeFailure(Exception):
    pass


def with_code(url: str, code: str | None) -> str:
    if not url.startswith(("ws://", "wss://")):
        raise ValueError("--ws-url must start with ws:// or wss://")
    if not code:
        return url
    return f"{url}{'&' if '?' in url else '?'}code={quote(code.strip())}"


async def _send(ws: ClientConnection, **msg: Any) -> None:
    await ws.send(json.dumps({"action": "sendMessage", **msg}, ensure_ascii=False))


async def _next(ws: ClientConnection, timeout: float) -> dict[str, Any]:
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    except TimeoutError as exc:
        raise SmokeFailure(f"sem resposta em {timeout:.0f} s (tempo esgotado)") from exc
    event = json.loads(raw)
    if event.get("type") == "error":
        raise SmokeFailure(f"evento de erro: {event.get('message')}")
    return event


async def _until(ws: ClientConnection, types: set[str], timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        event = await _next(ws, max(deadline - time.monotonic(), 0.01))
        if event.get("type") in types:
            return event


async def _reply(ws: ClientConnection, timeout: float) -> tuple[str, float | None]:
    """Waits for the message_done; returns its text and the time to the first token."""
    start = time.monotonic()
    first: float | None = None
    deadline = start + timeout
    while True:
        event = await _next(ws, max(deadline - time.monotonic(), 0.01))
        if event.get("type") == "token" and first is None:
            first = time.monotonic() - start
        if event.get("type") == "message_done":
            return str(event.get("message", "")), first


def _asks(text: str) -> None:
    if "?" not in text:
        raise SmokeFailure(f"a resposta não pergunta nada: {text[:80]!r}")


async def _onboarding(ws: ClientConnection, sid: str, step: dict[str, Any], timeout: float) -> str:
    """Answers each onboarding step until the first layer question; returns that question."""
    while step.get("type") == "onboarding_step":
        field, options = str(step["field"]), list(step.get("options") or [])
        if field == "baseline":
            await _send(ws, type="user_message", session_id=sid, text=BASELINE)
        else:
            value: str | list[str] = (
                FREE_TEXT.get(field, "Atendo sozinha, com hora marcada")
                if step.get("free_text") or not options
                else ([options[0]] if step.get("multiple") else options[0])
            )
            await _send(ws, type="onboarding_answer", session_id=sid, field=field, value=value)
        step = await _until(ws, {"onboarding_step", "message_done"}, timeout)
    return str(step.get("message", ""))


async def run_smoke(url: str, *, code: str | None = None, timeout: float = 60) -> list[StepResult]:
    results: list[StepResult] = []

    async def timed(name: str, coro: Any) -> Any:
        t0 = time.monotonic()
        try:
            value = await coro
        except (SmokeFailure, ConnectionClosed, InvalidStatus, OSError) as exc:
            detail = str(exc) or type(exc).__name__
            results.append(StepResult(name, False, time.monotonic() - t0, detail))
            raise SmokeFailure(detail) from exc
        first = value[1] if name.startswith("resposta") else None
        results.append(StepResult(name, True, time.monotonic() - t0, first_token_s=first))
        return value

    try:
        ws = await timed("conexão", connect(with_code(url, code), open_timeout=timeout))
    except SmokeFailure:
        return results
    async with ws:
        try:

            async def consent() -> tuple[str, dict[str, Any]]:
                await _send(ws, type="start_session")
                first = await _until(ws, {"onboarding_step"}, timeout)
                sid = str(first["session_id"])
                await _send(ws, type="consent", session_id=sid, accepted=True)
                return sid, await _until(ws, {"onboarding_step", "message_done"}, timeout)

            sid, step = await timed("consentimento", consent())

            async def onboarding() -> str:
                return await _onboarding(ws, sid, step, timeout)

            question = await timed("onboarding", onboarding())

            async def first_question() -> str:
                _asks(question)
                return question

            await timed("primeira pergunta", first_question())

            async def answer(text: str) -> tuple[str, float | None]:
                await _send(ws, type="user_message", session_id=sid, text=text)
                reply, first = await _reply(ws, timeout)
                _asks(reply)
                return reply, first

            await timed("resposta vaga", answer(VAGUE))
            await timed("resposta concreta", answer(CONCRETE))
        except SmokeFailure:
            pass
    return results


def passed(results: list[StepResult]) -> bool:
    return len(results) == len(STEP_NAMES) and all(r.ok for r in results)


def report(results: list[StepResult]) -> list[str]:
    lines: list[str] = []
    for r in results:
        first = f", primeiro token em {r.first_token_s:.1f} s" if r.first_token_s else ""
        status = "OK   " if r.ok else "FALHA"
        lines.append(
            f"{status} {r.name} ({r.seconds:.1f} s{first}){' · ' + r.detail if r.detail else ''}"
        )
    return lines


async def main_async(args: argparse.Namespace) -> int:
    failures = 0
    for run in range(1, args.runs + 1):
        print(f"\n== execução {run} de {args.runs}")
        results = await run_smoke(args.ws_url, code=args.code, timeout=args.timeout)
        print("\n".join(report(results)))
        if not passed(results):
            failures += 1
    print(f"\n{args.runs - failures} de {args.runs} execuções passaram")
    return 1 if failures else 0


def main() -> None:  # pragma: no cover - CLI
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--ws-url", required=True, help="wss://… (ApiStack output WebSocketUrl)")
    parser.add_argument("--code", help="access code, when the API requires one")
    parser.add_argument("--runs", type=int, default=1, help="sessions in a row (ERD: 3)")
    parser.add_argument("--timeout", type=float, default=60, help="seconds per step")
    sys.exit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":  # pragma: no cover
    main()
