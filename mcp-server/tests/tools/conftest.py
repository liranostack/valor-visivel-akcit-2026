"""Helpers to call tools through the MCP client, as the chat-service gateway does."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult
from pydantic import BaseModel
from vv_contracts.state import Session
from vv_mcp.repo_memory import InMemoryStateRepository
from vv_mcp.server import build_server

SID = "s1"


@pytest.fixture
def repo() -> InMemoryStateRepository:
    r = InMemoryStateRepository()
    r.put_session(Session(session_id=SID, status="in_layer", active_layer="clarity"))
    return r


@asynccontextmanager
async def connect(repo: InMemoryStateRepository) -> AsyncIterator[ClientSession]:
    """MCP client session to a server built on `repo` (opened inside each test's own task)."""
    async with create_connected_server_and_client_session(build_server(repo)) as session:
        yield session


async def call(client: ClientSession, name: str, req: BaseModel | dict[str, Any]) -> CallToolResult:
    payload = req.model_dump(mode="json") if isinstance(req, BaseModel) else req
    return await client.call_tool(name, {"req": payload})


def error_text(result: CallToolResult) -> str:
    assert result.isError, "expected a tool error"
    return " ".join(getattr(c, "text", "") for c in result.content)
