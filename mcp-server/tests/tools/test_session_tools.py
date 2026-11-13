"""Session lifecycle tools: create, patch position, baseline and public context."""

from vv_contracts.state import SessionState
from vv_contracts.tools import (
    CreateSessionIn,
    CreateSessionOut,
    GetSessionStateIn,
    SaveBaselineIn,
    SavePublicContextIn,
    UpdateSessionIn,
)
from vv_mcp.repo_memory import InMemoryStateRepository

from .conftest import SID, call, connect, error_text


async def state(client, sid: str = SID) -> SessionState:  # type: ignore[no-untyped-def]
    res = await call(client, "get_session_state", GetSessionStateIn(session_id=sid))
    return SessionState.model_validate(res.structuredContent)


async def test_create_session_starts_in_onboarding_with_retention() -> None:
    repo = InMemoryStateRepository()
    async with connect(repo) as client:
        res = await call(client, "create_session", CreateSessionIn())
        sid = CreateSessionOut.model_validate(res.structuredContent).session_id
        s = (await state(client, sid)).session
    assert s.status == "onboarding" and s.retention_until is not None


async def test_update_session_patches_only_given_fields(repo: InMemoryStateRepository) -> None:
    async with connect(repo) as client:
        await call(
            client,
            "update_session",
            UpdateSessionIn(session_id=SID, active_stage="clarity.routine", pending_gap_id="g1"),
        )
        s = (await state(client)).session
        assert (s.active_layer, s.active_stage, s.pending_gap_id) == (
            "clarity",
            "clarity.routine",
            "g1",
        )
        await call(
            client, "update_session", UpdateSessionIn(session_id=SID, clear=["pending_gap_id"])
        )
        assert (await state(client)).session.pending_gap_id is None


async def test_update_unknown_session_is_tool_error(repo: InMemoryStateRepository) -> None:
    async with connect(repo) as client:
        res = await call(client, "update_session", UpdateSessionIn(session_id="nope"))
        assert "unknown session" in error_text(res)


async def test_baseline_and_public_context(repo: InMemoryStateRepository) -> None:
    async with connect(repo) as client:
        await call(
            client, "save_baseline", SaveBaselineIn(session_id=SID, statement="Faço bolo com amor")
        )
        await call(
            client,
            "save_public_context",
            SavePublicContextIn(
                session_id=SID,
                source="https://ex.com",
                summary="Site de bolos",
                claims_to_verify=[],
            ),
        )
        st = await state(client)
    assert st.baseline is not None and st.baseline.statement == "Faço bolo com amor"
    assert st.public_context is not None and st.public_context.source == "https://ex.com"


async def test_save_synthesis_assigns_versions(repo: InMemoryStateRepository) -> None:
    from vv_contracts.agents import LayerSynthesis
    from vv_contracts.tools import SaveSynthesisIn, SaveSynthesisOut

    syn = LayerSynthesis(layer_id="clarity", content={"A": "x [fact:f1]"}, fact_refs=["f1"])
    async with connect(repo) as client:
        first = await call(client, "save_synthesis", SaveSynthesisIn(session_id=SID, synthesis=syn))
        second = await call(
            client, "save_synthesis", SaveSynthesisIn(session_id=SID, synthesis=syn)
        )
    assert SaveSynthesisOut.model_validate(first.structuredContent).version == 1
    assert SaveSynthesisOut.model_validate(second.structuredContent).version == 2


async def test_every_contract_tool_is_served_except_the_pending_card() -> None:
    from vv_contracts.tools import TOOL_INPUTS
    from vv_mcp.server import build_server

    server = build_server(InMemoryStateRepository(), None)
    served = {t.name for t in await server.list_tools()}
    pending = {"check_output", "read_public_site"}  # A.03.04
    assert set(TOOL_INPUTS) - served == pending
