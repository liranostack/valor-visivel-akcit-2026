"""State tools (ERD 'Ferramentas MCP'): contract tests through the MCP client."""

from vv_contracts.agents import ApplicationOutputs, BeforeAfter
from vv_contracts.state import EssentialCore, PreCore, SessionState, StageProgress, Turn
from vv_contracts.tools import (
    Ack,
    GetSessionStateIn,
    SaveCoreIn,
    SavePreCoreIn,
    SaveReviewIn,
    SaveTurnIn,
    SaveTurnOut,
    UpdateStageProgressIn,
)
from vv_mcp.repo_memory import InMemoryStateRepository

from .conftest import SID, call, connect, error_text

CORE = EssentialCore(
    content={},
    final_statement="f",
    before_after=BeforeAfter(
        said_before="a", sustained_discovery="b", now_able_to="c", fact_refs=[]
    ),
    action_plan_7d=[f"Dia {i}" for i in range(1, 8)],
    outputs=ApplicationOutputs(
        bio="Ajudo clientes a resolver o problema porque faço X.",
        narrativa="Trabalho com Y. Faço Z. O cliente percebe W.",
        checklist=[
            "Prioridade alta: testar narrativa",
            "Prioridade média: coletar prova",
            "Prioridade baixa: documentar",
        ],
        whatsapp_pitch_curto="Oi! Trabalho com Y e entrego Z.",
        whatsapp_pitch_prova="Oi! Trabalho com Y e entrego Z. Prova: W.",
        instagram_bio="Como faço Z. Impacto: W.",
        instagram_legenda_curta="Bastidor real: X. Resultado: W.",
        instagram_story_roteiro=["Problema: ...", "Rotina: ...", "Prova: ..."],
    ),
)


async def test_tools_are_listed(repo: InMemoryStateRepository) -> None:
    async with connect(repo) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert {
            "get_session_state",
            "save_turn",
            "update_stage_progress",
            "save_review",
            "save_pre_core",
            "save_core",
        } <= names


async def test_get_session_state(repo: InMemoryStateRepository) -> None:
    async with connect(repo) as client:
        result = await call(client, "get_session_state", GetSessionStateIn(session_id=SID))
        state = SessionState.model_validate(result.structuredContent)
        assert state.session.active_layer == "clarity"


async def test_get_unknown_session_is_tool_error(repo: InMemoryStateRepository) -> None:
    async with connect(repo) as client:
        result = await call(client, "get_session_state", GetSessionStateIn(session_id="nope"))
        assert "unknown session" in error_text(result)


async def test_invalid_input_is_tool_error(repo: InMemoryStateRepository) -> None:
    async with connect(repo) as client:
        result = await call(client, "get_session_state", {"session_id": ""})
        assert result.isError


async def test_save_turn(repo: InMemoryStateRepository) -> None:
    async with connect(repo) as client:
        req = SaveTurnIn(session_id=SID, turn=Turn(seq=3, user_message="oi", question_asked="Q?"))
        out = SaveTurnOut.model_validate((await call(client, "save_turn", req)).structuredContent)
        assert out.seq == 3
        state = repo.get_state(SID)
        assert state is not None and state.asked_questions == ["Q?"]


async def test_save_turn_unknown_session(repo: InMemoryStateRepository) -> None:
    async with connect(repo) as client:
        req = SaveTurnIn(session_id="nope", turn=Turn(seq=1, user_message="x"))
        assert "unknown session" in error_text(await call(client, "save_turn", req))


async def test_update_stage_progress(repo: InMemoryStateRepository) -> None:
    async with connect(repo) as client:
        progress = StageProgress(stage_id="clarity.a", layer_id="clarity", attempts=1)
        req = UpdateStageProgressIn(session_id=SID, progress=progress)
        assert Ack.model_validate(
            (await call(client, "update_stage_progress", req)).structuredContent
        )
        state = repo.get_state(SID)
        assert state is not None and state.progress[0].attempts == 1


async def test_save_review_pre_core_and_core(repo: InMemoryStateRepository) -> None:
    async with connect(repo) as client:
        await call(
            client,
            "save_review",
            SaveReviewIn(session_id=SID, target="pre_core", intent="adjust", notes="trocar termo"),
        )
        await call(client, "save_pre_core", SavePreCoreIn(session_id=SID, pre_core=PreCore()))
        result = await call(client, "save_core", SaveCoreIn(session_id=SID, core=CORE))
        assert not result.isError
        assert repo.reviews(SID)[0].notes == "trocar termo"
        assert repo.pre_core(SID) is not None
        assert repo.core(SID) == CORE
