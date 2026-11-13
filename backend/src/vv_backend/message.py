"""sendMessage route: validate the ClientMessage and hand it to the worker asynchronously.

API Gateway waits at most 29 s for a route; a turn can take longer, so the work happens in the
worker Lambda, which streams the events back to the connection.
"""

import contextlib
import json
import logging
import os
from typing import Any

import boto3
from pydantic import ValidationError
from vv_contracts.ws import CLIENT_MESSAGE_ADAPTER

from vv_backend.relay import (
    INVALID_MESSAGE,
    ConnectionGone,
    endpoint_of,
    error_event,
    management_client,
    post,
)

log = logging.getLogger(__name__)


def handle(
    event: dict[str, Any],
    context: object,
    *,
    lambda_client: Any = None,
    api_client: Any = None,
    sent: list[bytes] | None = None,
) -> dict[str, Any]:
    connection_id = event["requestContext"]["connectionId"]
    endpoint = endpoint_of(event)
    try:
        body = json.loads(event.get("body") or "{}")
        body.pop("action", None)
        msg = CLIENT_MESSAGE_ADAPTER.validate_python(body)
    except (ValueError, ValidationError):
        api = api_client or management_client(endpoint)
        with contextlib.suppress(ConnectionGone):
            post(api, connection_id, error_event(None, "bad_request", INVALID_MESSAGE), sent)
        return {"statusCode": 200}

    job = {
        "connection_id": connection_id,
        "endpoint": endpoint,
        "message": msg.model_dump(mode="json"),
    }
    (lambda_client or boto3.client("lambda")).invoke(
        FunctionName=os.environ["WORKER_FUNCTION_NAME"],
        InvocationType="Event",
        Payload=json.dumps(job).encode(),
    )
    return {"statusCode": 200}
