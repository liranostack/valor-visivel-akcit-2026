"""Worker: invoke the chat-service runtime and relay its SSE events to the WebSocket connection.

The chat-service streams one ServerEvent per SSE `data:` line. Any runtime failure becomes a safe
pt-BR ErrorEvent; a closed connection (GoneException) stops the relay quietly.
"""

import json
import logging
import os
from collections.abc import Iterator
from typing import Any

import boto3

from vv_backend.relay import (
    TURN_FAILED,
    ConnectionGone,
    error_event,
    management_client,
    post,
    post_raw,
)

log = logging.getLogger(__name__)
MIN_SESSION_ID = 33  # AgentCore runtimeSessionId minimum length


def runtime_session_id(session_id: str | None, connection_id: str) -> str:
    """Same journey → same runtime session (warm container, AgentCore session affinity)."""
    base = f"vv-session-{session_id}" if session_id else f"vv-connection-{connection_id}"
    return base.ljust(MIN_SESSION_ID, "0")


def sse_data(stream: Any) -> Iterator[bytes]:
    for raw in stream.iter_lines():
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        if line.startswith("data:"):
            data = line[len("data:") :].strip()
            if data:
                yield data.encode("utf-8")


def handle(
    job: dict[str, Any],
    context: object,
    *,
    runtime_client: Any = None,
    api_client: Any = None,
    sent: list[bytes] | None = None,
) -> None:
    connection_id: str = job["connection_id"]
    message: dict[str, Any] = job["message"]
    session_id = message.get("session_id")
    api = api_client or management_client(job["endpoint"])
    runtime = runtime_client or boto3.client("bedrock-agentcore")
    try:
        try:
            res = runtime.invoke_agent_runtime(
                agentRuntimeArn=os.environ["CHAT_RUNTIME_ARN"],
                runtimeSessionId=runtime_session_id(session_id, connection_id),
                payload=json.dumps(message).encode(),
                contentType="application/json",
                accept="text/event-stream",
            )
            for data in sse_data(res["response"]):
                _relay_json(api, connection_id, data, sent)
        except ConnectionGone:
            raise
        except Exception:
            log.exception("runtime call failed")
            post(api, connection_id, error_event(session_id, "turn_failed", TURN_FAILED), sent)
    except ConnectionGone:
        log.info("connection %s closed", connection_id)


def _relay_json(api: Any, connection_id: str, data: bytes, sent: list[bytes] | None) -> None:
    try:
        json.loads(data)
    except ValueError:
        log.warning("skipping non-JSON SSE line")
        return
    post_raw(api, connection_id, data, sent)
