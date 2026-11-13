"""Every ToolGateway method, end to end: McpToolGateway → MCP (in-memory) → FakeToolGateway.

The server below registers every tool with the shared convention (one `req` argument, output
model returned), delegating to FakeToolGateway. It doubles as the reference for the real tool
cards (A.03.01–A.03.04).
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from vv_chat.gateway.fake import FakeToolGateway
from vv_chat.gateway.mcp import connect_in_memory
from vv_contracts.agents import (
    ApplicationOutputs,
    BeforeAfter,
    ExtractedFact,
    InterpretationScores,
    LayerSynthesis,
)
from vv_contracts.kb import Anchor, LayerSpec, StageSpec
from vv_contracts.state import EssentialCore, PreCore, StageProgress, Turn
from vv_contracts.tools import (
    TOOL_INPUTS,
    CheckOutputIn,
    CreateSessionIn,
    GetLayerSpecIn,
    GetMethodGuideIn,
    GetQuestionFromPoolIn,
    GetSessionStateIn,
    GetSynthesisTemplateIn,
    ListFactsIn,
    ListGapsIn,
    ReadPublicSiteIn,
    SaveBaselineIn,
    SaveCoreIn,
    SaveFactIn,
    SaveGapIn,
    SavePreCoreIn,
    SavePublicContextIn,
    SaveReviewIn,
    SaveSynthesisIn,
    SaveTurnIn,
    UpdateGapIn,
    UpdateSessionIn,
    UpdateStageProgressIn,
)

SID = "s1"
LAYER = LayerSpec(
    layer_id="clarity",
    order=1,
    name="Nitidez",
    objective="o",
    pain_to_solve="p",
    success_signal="s",
    closure_criteria="c",
    synthesis_template="templates/clarity_map.md",
    stages=[
        StageSpec(
            stage_id="clarity.real_context",
            title="Contexto Real",
            objective="o",
            extraction_focus="f",
            anchors=[
                Anchor(angle="routine", question="Como é um dia típico?"),
                Anchor(angle="blind_spot", question="O que dizem de você?"),
            ],
        )
    ],
)
SCORES = InterpretationScores(concreteness=4, relevance=4, defensibility=3, domain_fit=5)
FACT = ExtractedFact(
    text="t", source_excerpt="e", kind="evidence", origin="client_statement", finding_area="open"
)
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


def _delegate(method: Any, model: type) -> Any:
    async def tool(req: Any) -> Any:
        return await method(req)

    tool.__annotations__ = {"req": model, "return": method.__annotations__["return"]}
    return tool


def delegating_server(fake: FakeToolGateway) -> FastMCP:
    server = FastMCP("contract")
    for name, model in TOOL_INPUTS.items():
        server.add_tool(_delegate(getattr(fake, name), model), name=name)
    return server


async def test_every_method_round_trips_through_mcp() -> None:
    fake = FakeToolGateway(
        layers={"clarity": LAYER}, templates={"core": "# Núcleo"}, guide="## open"
    )
    fake.start_session(SID)
    async with connect_in_memory(delegating_server(fake)) as gw:
        await gw.save_turn(SaveTurnIn(session_id=SID, turn=Turn(seq=1, user_message="oi")))
        await gw.update_stage_progress(
            UpdateStageProgressIn(
                session_id=SID,
                progress=StageProgress(stage_id="clarity.real_context", layer_id="clarity"),
            )
        )
        fact = await gw.save_fact(
            SaveFactIn(
                session_id=SID,
                turn_seq=1,
                layer_id="clarity",
                stage_id="clarity.real_context",
                fact=FACT,
                scores=SCORES,
            )
        )
        assert (await gw.list_facts(ListFactsIn(session_id=SID))).facts[0].fact_id == fact.fact_id
        gap = await gw.save_gap(
            SaveGapIn(
                session_id=SID,
                layer_id="clarity",
                stage_id="clarity.real_context",
                description="d",
                origin="client_statement",
                reason="r",
            )
        )
        await gw.update_gap(
            UpdateGapIn(session_id=SID, gap_id=gap.gap_id, status="resolved", fact_id=fact.fact_id)
        )
        gaps = await gw.list_gaps(ListGapsIn(session_id=SID, status="resolved"))
        assert gaps.gaps[0].resolved_by_fact == fact.fact_id
        spec = await gw.get_layer_spec(GetLayerSpecIn(layer_id="clarity"))
        assert spec.stages[0].stage_id == "clarity.real_context"
        pool = await gw.get_question_from_pool(
            GetQuestionFromPoolIn(stage_id="clarity.real_context")
        )
        assert [a.question for a in pool.anchors][0] == "Como é um dia típico?"
        tpl = await gw.get_synthesis_template(GetSynthesisTemplateIn(kind="core"))
        assert tpl.markdown == "# Núcleo"
        assert (await gw.get_method_guide(GetMethodGuideIn())).markdown == "## open"
        synthesis = LayerSynthesis(layer_id="clarity", content={"a": "b"}, fact_refs=[])
        out = await gw.save_synthesis(SaveSynthesisIn(session_id=SID, synthesis=synthesis))
        assert out.version == 1
        await gw.save_review(SaveReviewIn(session_id=SID, target="pre_core", intent="approve"))
        await gw.save_pre_core(SavePreCoreIn(session_id=SID, pre_core=PreCore()))
        await gw.save_core(SaveCoreIn(session_id=SID, core=CORE))
        checks = await gw.check_output(CheckOutputIn(text="x", sector="bem-estar"))
        assert checks.violations == []
        site = await gw.read_public_site(ReadPublicSiteIn(session_id=SID, url="https://x.com"))
        assert site.outcome == "empty"
        created = await gw.create_session(CreateSessionIn())
        assert created.session_id != SID
        await gw.update_session(
            UpdateSessionIn(session_id=SID, active_stage="clarity.real_context")
        )
        await gw.save_baseline(SaveBaselineIn(session_id=SID, statement="Faço com amor"))
        await gw.save_public_context(
            SavePublicContextIn(session_id=SID, source="https://x.com", summary="s")
        )
        state = await gw.get_session_state(GetSessionStateIn(session_id=SID))
        assert state.last_turn_seq == 1
        assert state.session.active_stage == "clarity.real_context"
        assert state.baseline is not None and state.public_context is not None
    assert set(fake.calls) == set(TOOL_INPUTS)
