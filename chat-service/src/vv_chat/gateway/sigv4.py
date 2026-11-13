"""SigV4 signing for calls to an AgentCore Runtime (used by the remote MCP gateway).

To be validated against AWS at checkpoint H.D2; if inbound auth blocks it, fall back to
TOOL_GATEWAY=inprocess (see the deploy-demo skill).
"""

from collections.abc import Generator
from urllib.parse import quote

import httpx
from botocore.auth import SigV4Auth as BotoSigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

SERVICE = "bedrock-agentcore"


def runtime_invocation_url(runtime_arn: str, region: str, qualifier: str = "DEFAULT") -> str:
    encoded = quote(runtime_arn, safe="")
    return (
        f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded}"
        f"/invocations?qualifier={qualifier}"
    )


class SigV4Auth(httpx.Auth):
    requires_request_body = True

    def __init__(self, credentials: Credentials, region: str, service: str = SERVICE) -> None:
        self._signer = BotoSigV4Auth(credentials, service, region)

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        aws_request = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content,
            headers={"Content-Type": request.headers.get("Content-Type", "application/json")},
        )
        self._signer.add_auth(aws_request)
        for key, value in aws_request.headers.items():
            request.headers[key] = value
        yield request
