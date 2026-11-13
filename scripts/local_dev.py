"""Local WebSocket bridge for browser dev without deploying to AWS.

Runs a WebSocket server on ws://localhost:8765. The frontend connects to it via
NEXT_PUBLIC_WS_URL=ws://localhost:8765. The access code check is skipped (type anything in the UI).
State is kept in memory for the process lifetime (one browser session per server run).

Usage:
    uv run python scripts/local_dev.py

Then in another terminal:
    cd frontend && NEXT_PUBLIC_WS_URL=ws://localhost:8765 npm run dev

Open http://localhost:3000, type any access code, and start the conversation.
Requires AWS credentials with Bedrock model access (uses the default profile).
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Local KB and in-memory state — no DynamoDB needed
os.environ.setdefault("TOOL_GATEWAY", "inprocess")
os.environ.setdefault("STATE_BACKEND", "memory")
os.environ.setdefault("KB_SOURCE", "local")
os.environ.setdefault("KB_PATH", str(Path(__file__).resolve().parents[1] / "knowledge-base"))

import websockets
from vv_chat.app import turn_handler
from vv_contracts.ws import CLIENT_MESSAGE_ADAPTER, dump_server_event
from websockets.asyncio.server import ServerConnection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("local_dev")

# Suppress noisy Strands/Bedrock SDK logs
for noisy in ("strands", "botocore", "boto3", "httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


async def handle(ws: ServerConnection) -> None:
    peer = ws.remote_address
    log.info("connected: %s", peer)
    try:
        async for raw in ws:
            try:
                msg = CLIENT_MESSAGE_ADAPTER.validate_json(raw)
            except Exception as exc:
                log.warning("bad message from %s: %s", peer, exc)
                await ws.send(
                    '{"type":"error","code":"bad_request","message":"Mensagem inválida."}'
                )
                continue
            log.info("→ %s", msg.type)
            try:
                async for event in turn_handler(msg):
                    payload = dump_server_event(event)
                    await ws.send(payload)
                    if event.type not in ("token",):
                        log.info("← %s", event.type)
            except Exception:
                log.exception("turn failed")
                await ws.send(
                    '{"type":"error","code":"turn_failed",'
                    '"message":"Tive um problema. Pode repetir?"}'
                )
    except websockets.exceptions.ConnectionClosedOK:
        pass
    except websockets.exceptions.ConnectionClosedError as exc:
        log.warning("connection closed with error: %s", exc)
    finally:
        log.info("disconnected: %s", peer)


async def main() -> None:
    host, port = "localhost", 8765
    log.info("starting local WebSocket bridge on ws://%s:%d", host, port)
    log.info("frontend: cd frontend && NEXT_PUBLIC_WS_URL=ws://localhost:%d npm run dev", port)
    log.info("access code: type anything in the UI (not checked locally)")
    async with websockets.serve(handle, host, port):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
