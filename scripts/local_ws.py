"""Run the whole Valor Visível locally: the agents, the method and the state in this process, and
the same WebSocket protocol API Gateway serves, on ws://localhost:8765.

Needs AWS credentials with Bedrock access (Claude Sonnet 4.6 and Haiku 4.5, us-east-1). Nothing is
created in the account: state lives in memory and ends with the process; guardrails are off unless
GUARDRAIL_ID is set.

    make demo-local
    cd frontend && NEXT_PUBLIC_WS_URL=ws://localhost:8765 npm run dev
"""

import argparse
import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from pydantic import ValidationError
from vv_contracts.ws import (
    ClientMessage,
    ErrorEvent,
    ServerEvent,
    dump_server_event,
    parse_client_message,
)
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed

Handler = Callable[[ClientMessage], AsyncIterator[ServerEvent]]
log = logging.getLogger("local_ws")


def _parse(raw: str | bytes) -> ClientMessage:
    data = json.loads(raw)
    data.pop("action", None)  # API Gateway route key, sent by the frontend
    return parse_client_message(json.dumps(data))


def _connection(handler: Handler) -> Callable[[ServerConnection], Awaitable[None]]:
    async def on_connection(ws: ServerConnection) -> None:
        async for raw in ws:
            try:
                msg = _parse(raw)
            except (ValidationError, ValueError):
                error = ErrorEvent(session_id=None, code="bad_request", message="Mensagem inválida")
                await ws.send(dump_server_event(error))
                continue
            stream = handler(msg)
            try:
                async for event in stream:
                    await ws.send(dump_server_event(event))
            except ConnectionClosed:
                return  # the browser left mid-turn; nothing to send
            except Exception as exc:  # show it on screen instead of a silent dead chat
                log.exception("turn failed")
                error = ErrorEvent(session_id=None, code="internal", message=f"Erro local: {exc}")
                await ws.send(dump_server_event(error))
            finally:
                # Close the turn here, in this task: the in-process MCP session must exit where it
                # entered.
                await stream.aclose()  # pyright: ignore[reportAttributeAccessIssue]

    return on_connection


@asynccontextmanager
async def serve_local(
    handler: Handler, *, host: str = "127.0.0.1", port: int = 8765
) -> AsyncIterator[Server]:
    async with serve(_connection(handler), host, port) as server:
        yield server


async def main_async(port: int) -> None:  # pragma: no cover - needs AWS
    os.environ.setdefault("TOOL_GATEWAY", "inprocess")
    os.environ.setdefault("STATE_BACKEND", "memory")
    os.environ.setdefault("KB_SOURCE", "local")
    if not os.environ.get("GUARDRAIL_ID"):
        os.environ.setdefault("GUARDRAIL_MODE", "off")
    from vv_chat.app import turn_handler

    async with serve_local(turn_handler, port=port):
        print(f"Valor Visível local em ws://localhost:{port}")
        print(f"Front: cd frontend && NEXT_PUBLIC_WS_URL=ws://localhost:{port} npm run dev")
        await asyncio.Future()


def main() -> None:  # pragma: no cover - CLI
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--port", type=int, default=8765)
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main_async(parser.parse_args().port))


if __name__ == "__main__":  # pragma: no cover
    main()
