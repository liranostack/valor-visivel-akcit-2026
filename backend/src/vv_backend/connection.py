"""$connect and $disconnect: nothing to store (the session lives in the chat-service).

$connect checks the access code (A.04.10): the front sends it as ?code=…, the Lambda only knows
its SHA-256 (ACCESS_CODE_SHA256, set at deploy time from `cdk deploy -c accessCode=…`). Without
the variable the API stays open, as in local runs.
"""

import hashlib
import hmac
import os
from typing import Any


def code_hash(code: str) -> str:
    return hashlib.sha256(code.strip().lower().encode()).hexdigest()


def on_connect(event: dict[str, Any], context: object) -> dict[str, Any]:
    expected = os.environ.get("ACCESS_CODE_SHA256", "")
    if not expected:
        return {"statusCode": 200}
    code = str((event.get("queryStringParameters") or {}).get("code") or "")
    if code and hmac.compare_digest(code_hash(code), expected):
        return {"statusCode": 200}
    return {"statusCode": 401}


def on_disconnect(event: dict[str, Any], context: object) -> dict[str, Any]:
    return {"statusCode": 200}
