"""ToolGateway implementations.

Convention shared with the MCP tool cards: every tool takes one argument named `req` (the input
model from vv_contracts.tools) and returns the output model (FastMCP structured content).
"""

import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from vv_chat.gateway.fake import FakeToolGateway
from vv_chat.gateway.mcp import McpToolGateway, ToolCallError, connect_in_memory
from vv_chat.gateway.sigv4 import SigV4Auth, runtime_invocation_url
from vv_contracts.agents import ExtractedFact, InterpretationScores
from vv_contracts.ports import ToolGateway
from vv_contracts.state import Session, SessionState
from vv_contracts.tools import (
    TOOL_INPUTS,
    GetSessionStateIn,
    ListFactsIn,
    SaveFactIn,
    SaveFactOut,
)

SCORES = InterpretationScores(concreteness=4, relevance=4, defensibility=3, domain_fit=5)
FACT = ExtractedFact(
    text="Ajusta a pressão",
    source_excerpt="vou sentindo",
    kind="characteristic",
    origin="client_statement",
    finding_area="hidden",
)


def tiny_server() -> FastMCP:
    server = FastMCP("test")

    @server.tool()
    def get_session_state(req: GetSessionStateIn) -> SessionState:  # pyright: ignore[reportUnusedFunction]
        return SessionState(session=Session(session_id=req.session_id, status="onboarding"))

    @server.tool()
    def save_fact(req: SaveFactIn) -> SaveFactOut:  # pyright: ignore[reportUnusedFunction]
        raise ValueError("storage unavailable")

    return server


def test_both_gateways_cover_every_tool() -> None:
    for cls in (McpToolGateway, FakeToolGateway):
        missing = [name for name in TOOL_INPUTS if not callable(getattr(cls, name, None))]
        assert missing == [], f"{cls.__name__} missing {missing}"


async def test_mcp_gateway_parses_structured_output() -> None:
    async with connect_in_memory(tiny_server()) as gateway:
        state = await gateway.get_session_state(GetSessionStateIn(session_id="s1"))
    assert isinstance(state, SessionState)
    assert state.session.session_id == "s1"


async def test_mcp_gateway_raises_tool_errors() -> None:
    req = SaveFactIn(
        session_id="s1",
        turn_seq=1,
        layer_id="clarity",
        stage_id="clarity.a",
        fact=FACT,
        scores=SCORES,
    )
    async with connect_in_memory(tiny_server()) as gateway:
        with pytest.raises(ToolCallError, match="save_fact"):
            await gateway.save_fact(req)


async def test_fake_gateway_round_trip() -> None:
    gateway: ToolGateway = FakeToolGateway()
    fake = gateway
    assert isinstance(fake, FakeToolGateway)
    fake.start_session("s1")
    out = await gateway.save_fact(
        SaveFactIn(
            session_id="s1",
            turn_seq=1,
            layer_id="clarity",
            stage_id="clarity.a",
            fact=FACT,
            scores=SCORES,
        )
    )
    facts = await gateway.list_facts(ListFactsIn(session_id="s1"))
    assert [f.fact_id for f in facts.facts] == [out.fact_id]
    assert facts.facts[0].source_excerpt == "vou sentindo"
    state = await gateway.get_session_state(GetSessionStateIn(session_id="s1"))
    assert state.session.status == "onboarding"
    assert fake.calls[0] == "save_fact"


class TestSigV4:
    def test_invocation_url_encodes_arn(self) -> None:
        arn = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/vv_mcp-abc"
        url = runtime_invocation_url(arn, "us-east-1")
        assert url.startswith(
            "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/arn%3Aaws"
        )
        assert url.endswith("/invocations?qualifier=DEFAULT")

    def test_signs_requests(self) -> None:
        from botocore.credentials import Credentials

        auth = SigV4Auth(Credentials("AKIDEXAMPLE", "secret"), "us-east-1")
        request = httpx.Request("POST", "https://example.com/mcp", content=b"{}")
        signed = next(auth.auth_flow(request))
        assert signed.headers["Authorization"].startswith("AWS4-HMAC-SHA256")
        assert "x-amz-date" in signed.headers
