"""Post ServerEvents to a WebSocket connection (API Gateway Management API)."""

import logging
from typing import Any

import boto3
from vv_contracts.ws import ErrorEvent, ServerEvent, dump_server_event

log = logging.getLogger(__name__)

TURN_FAILED = "Tive um problema agora. Pode repetir sua última resposta?"
INVALID_MESSAGE = "Não entendi essa mensagem. Pode tentar de novo?"


class ConnectionGone(Exception):
    """The browser closed the connection; stop sending."""


def management_client(endpoint: str) -> Any:
    return boto3.client("apigatewaymanagementapi", endpoint_url=endpoint)


def endpoint_of(event: dict[str, Any]) -> str:
    ctx = event["requestContext"]
    return f"https://{ctx['domainName']}/{ctx['stage']}"


def post_raw(api: Any, connection_id: str, data: bytes, sent: list[bytes] | None = None) -> None:
    try:
        api.post_to_connection(ConnectionId=connection_id, Data=data)
    except api.exceptions.GoneException as exc:
        raise ConnectionGone(connection_id) from exc
    if sent is not None:
        sent.append(data)


def post(api: Any, connection_id: str, event: ServerEvent, sent: list[bytes] | None = None) -> None:
    post_raw(api, connection_id, dump_server_event(event).encode(), sent)


def error_event(session_id: str | None, code: str, message: str) -> ErrorEvent:
    return ErrorEvent(session_id=session_id, code=code, message=message)
