"""Method-content tools (KB) through the MCP client."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session
from vv_contracts.kb import LayerSpec
from vv_contracts.tools import (
    GetLayerSpecIn,
    GetMethodGuideIn,
    GetMethodGuideOut,
    GetQuestionFromPoolIn,
    GetQuestionFromPoolOut,
    GetSynthesisTemplateIn,
    GetSynthesisTemplateOut,
)
from vv_mcp.kb import LocalKnowledgeBase
from vv_mcp.repo_memory import InMemoryStateRepository
from vv_mcp.server import build_server

from .conftest import call, error_text

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "kb"


@asynccontextmanager
async def connect_kb(with_kb: bool = True) -> AsyncIterator[ClientSession]:
    kb = LocalKnowledgeBase(FIXTURE) if with_kb else None
    server = build_server(InMemoryStateRepository(), kb)
    async with create_connected_server_and_client_session(server) as session:
        yield session


async def test_get_layer_spec() -> None:
    async with connect_kb() as client:
        res = await call(client, "get_layer_spec", GetLayerSpecIn(layer_id="clarity"))
    assert LayerSpec.model_validate(res.structuredContent).order == 1


async def test_missing_layer_is_tool_error() -> None:
    async with connect_kb() as client:
        res = await call(client, "get_layer_spec", GetLayerSpecIn(layer_id="sustainment"))
    assert "sustainment" in error_text(res)


async def test_question_pool_by_stage_and_blind_spot_angle() -> None:
    async with connect_kb() as client:
        res = await call(
            client, "get_question_from_pool", GetQuestionFromPoolIn(stage_id="clarity.real_context")
        )
        pool = GetQuestionFromPoolOut.model_validate(res.structuredContent)
        assert pool.anchors[0].question.startswith("Como é um {seu_trabalho}")
        assert pool.rescue_angles == ["routine", "limit"]
        res = await call(
            client,
            "get_question_from_pool",
            GetQuestionFromPoolIn(stage_id="clarity.real_context", angle="blind_spot"),
        )
        only = GetQuestionFromPoolOut.model_validate(res.structuredContent).anchors
        assert [(a.angle, a.question) for a in only] == [
            ("blind_spot", "O que {as_clientes} mais elogiam?")
        ]


async def test_unknown_stage() -> None:
    async with connect_kb() as client:
        res = await call(
            client, "get_question_from_pool", GetQuestionFromPoolIn(stage_id="clarity.nope")
        )
        assert "clarity.nope" in error_text(res)
        res = await call(client, "get_question_from_pool", GetQuestionFromPoolIn(stage_id="bad"))
        assert res.isError


async def test_templates_and_guide() -> None:
    async with connect_kb() as client:
        res = await call(client, "get_synthesis_template", GetSynthesisTemplateIn(kind="clarity"))
        assert GetSynthesisTemplateOut.model_validate(res.structuredContent).markdown.startswith(
            "# Mapa"
        )
        res = await call(client, "get_method_guide", GetMethodGuideIn(quadrant="hidden"))
        assert "rotina" in GetMethodGuideOut.model_validate(res.structuredContent).markdown


async def test_without_kb_tools_fail_clearly() -> None:
    async with connect_kb(with_kb=False) as client:
        res = await call(client, "get_layer_spec", GetLayerSpecIn(layer_id="clarity"))
    assert "knowledge base" in error_text(res)
