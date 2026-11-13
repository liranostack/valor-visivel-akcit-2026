"""ToolGateway over MCP: remote (AgentCore MCP runtime) or in-process (in-memory transport).

Convention with the mcp-server tool cards: every tool takes one argument `req` (input model from
vv_contracts.tools) and returns the output model, delivered as MCP structured content.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent
from pydantic import BaseModel
from vv_contracts.kb import LayerSpec
from vv_contracts.state import SessionState
from vv_contracts.tools import (
    Ack,
    CheckOutputIn,
    CheckOutputOut,
    CreateSessionIn,
    CreateSessionOut,
    GetLayerSpecIn,
    GetMethodGuideIn,
    GetMethodGuideOut,
    GetQuestionFromPoolIn,
    GetQuestionFromPoolOut,
    GetSessionStateIn,
    GetSynthesisTemplateIn,
    GetSynthesisTemplateOut,
    ListFactsIn,
    ListFactsOut,
    ListGapsIn,
    ListGapsOut,
    ReadPublicSiteIn,
    ReadPublicSiteOut,
    SaveBaselineIn,
    SaveCoreIn,
    SaveFactIn,
    SaveFactOut,
    SaveGapIn,
    SaveGapOut,
    SavePreCoreIn,
    SavePublicContextIn,
    SaveReviewIn,
    SaveSynthesisIn,
    SaveSynthesisOut,
    SaveTurnIn,
    SaveTurnOut,
    UpdateGapIn,
    UpdateSessionIn,
    UpdateStageProgressIn,
)

TIMEOUT = timedelta(seconds=30)


class ToolCallError(RuntimeError):
    """A tool returned an error (validation, storage, policy)."""


class McpToolGateway:
    """Implements vv_contracts.ports.ToolGateway on top of an initialized MCP ClientSession."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def _call[T: BaseModel](self, name: str, req: BaseModel, out: type[T]) -> T:
        result = await self._session.call_tool(
            name, {"req": req.model_dump(mode="json")}, read_timeout_seconds=TIMEOUT
        )
        if result.isError or result.structuredContent is None:
            detail = " ".join(c.text for c in result.content if isinstance(c, TextContent))
            raise ToolCallError(f"{name}: {detail or 'no structured content'}")
        return out.model_validate(result.structuredContent)

    async def create_session(self, req: CreateSessionIn) -> CreateSessionOut:
        return await self._call("create_session", req, CreateSessionOut)

    async def update_session(self, req: UpdateSessionIn) -> Ack:
        return await self._call("update_session", req, Ack)

    async def save_baseline(self, req: SaveBaselineIn) -> Ack:
        return await self._call("save_baseline", req, Ack)

    async def save_public_context(self, req: SavePublicContextIn) -> Ack:
        return await self._call("save_public_context", req, Ack)

    async def get_session_state(self, req: GetSessionStateIn) -> SessionState:
        return await self._call("get_session_state", req, SessionState)

    async def save_turn(self, req: SaveTurnIn) -> SaveTurnOut:
        return await self._call("save_turn", req, SaveTurnOut)

    async def update_stage_progress(self, req: UpdateStageProgressIn) -> Ack:
        return await self._call("update_stage_progress", req, Ack)

    async def save_fact(self, req: SaveFactIn) -> SaveFactOut:
        return await self._call("save_fact", req, SaveFactOut)

    async def list_facts(self, req: ListFactsIn) -> ListFactsOut:
        return await self._call("list_facts", req, ListFactsOut)

    async def save_gap(self, req: SaveGapIn) -> SaveGapOut:
        return await self._call("save_gap", req, SaveGapOut)

    async def list_gaps(self, req: ListGapsIn) -> ListGapsOut:
        return await self._call("list_gaps", req, ListGapsOut)

    async def update_gap(self, req: UpdateGapIn) -> Ack:
        return await self._call("update_gap", req, Ack)

    async def get_layer_spec(self, req: GetLayerSpecIn) -> LayerSpec:
        return await self._call("get_layer_spec", req, LayerSpec)

    async def get_question_from_pool(self, req: GetQuestionFromPoolIn) -> GetQuestionFromPoolOut:
        return await self._call("get_question_from_pool", req, GetQuestionFromPoolOut)

    async def get_synthesis_template(self, req: GetSynthesisTemplateIn) -> GetSynthesisTemplateOut:
        return await self._call("get_synthesis_template", req, GetSynthesisTemplateOut)

    async def get_method_guide(self, req: GetMethodGuideIn) -> GetMethodGuideOut:
        return await self._call("get_method_guide", req, GetMethodGuideOut)

    async def save_synthesis(self, req: SaveSynthesisIn) -> SaveSynthesisOut:
        return await self._call("save_synthesis", req, SaveSynthesisOut)

    async def save_review(self, req: SaveReviewIn) -> Ack:
        return await self._call("save_review", req, Ack)

    async def save_pre_core(self, req: SavePreCoreIn) -> Ack:
        return await self._call("save_pre_core", req, Ack)

    async def save_core(self, req: SaveCoreIn) -> Ack:
        return await self._call("save_core", req, Ack)

    async def check_output(self, req: CheckOutputIn) -> CheckOutputOut:
        return await self._call("check_output", req, CheckOutputOut)

    async def read_public_site(self, req: ReadPublicSiteIn) -> ReadPublicSiteOut:
        return await self._call("read_public_site", req, ReadPublicSiteOut)


@asynccontextmanager
async def connect_in_memory(server: FastMCP) -> AsyncIterator[McpToolGateway]:
    """TOOL_GATEWAY=inprocess: same MCP tools, in-memory transport, no network."""
    async with create_connected_server_and_client_session(server) as session:
        yield McpToolGateway(session)


@asynccontextmanager
async def connect_remote(
    url: str, auth: httpx.Auth | None = None, headers: dict[str, Any] | None = None
) -> AsyncIterator[McpToolGateway]:  # pragma: no cover - exercised against AWS at H.D2
    """TOOL_GATEWAY=mcp: streamable HTTP to the mcp-server runtime (SigV4 when on AgentCore)."""
    async with (
        streamablehttp_client(url, headers=headers, auth=auth) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield McpToolGateway(session)
