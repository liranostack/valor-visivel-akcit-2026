"""Open the ToolGateway chosen by the environment, once per turn.

TOOL_GATEWAY=inprocess (default locally): builds the mcp-server in this process
  (STATE_BACKEND=memory|dynamodb, TABLE_NAME) and talks to it over the in-memory MCP transport.
TOOL_GATEWAY=mcp: streamable HTTP to the mcp-server AgentCore runtime (MCP_RUNTIME_ARN, SigV4).
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import cache

from vv_mcp.kb import load_knowledge_base
from vv_mcp.repo_dynamo import DynamoStateRepository
from vv_mcp.repo_memory import InMemoryStateRepository
from vv_mcp.server import ValorVisivelServer, build_server

from vv_chat.gateway.mcp import McpToolGateway, connect_in_memory, connect_remote


@cache
def _local_server() -> ValorVisivelServer:  # pragma: no cover - wiring
    if os.environ.get("STATE_BACKEND", "memory") == "dynamodb":
        return build_server(DynamoStateRepository(os.environ["TABLE_NAME"]), load_knowledge_base())
    return build_server(InMemoryStateRepository(), load_knowledge_base())


@asynccontextmanager
async def open_gateway() -> AsyncIterator[McpToolGateway]:  # pragma: no cover - wiring
    kind = os.environ.get("TOOL_GATEWAY", "inprocess")
    if kind == "inprocess":
        async with connect_in_memory(_local_server()) as gateway:
            yield gateway
        return
    if kind == "mcp":
        import boto3

        from vv_chat.gateway.sigv4 import SigV4Auth, runtime_invocation_url

        region = os.environ.get("AWS_REGION", "us-east-1")
        credentials = boto3.Session().get_credentials()
        if credentials is None:
            raise RuntimeError("no AWS credentials for the MCP runtime call")
        url = runtime_invocation_url(os.environ["MCP_RUNTIME_ARN"], region)
        auth = SigV4Auth(credentials.get_frozen_credentials(), region)  # type: ignore[arg-type]
        async with connect_remote(url, auth=auth) as gateway:
            yield gateway
        return
    raise RuntimeError(f"unknown TOOL_GATEWAY={kind!r} (use inprocess or mcp)")
