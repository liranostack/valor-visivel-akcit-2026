"""Facts and gaps tools (ERD 'Ferramentas MCP'): contract tests through the MCP client."""

from vv_contracts.agents import ExtractedFact, InterpretationScores
from vv_contracts.tools import (
    ListFactsIn,
    ListFactsOut,
    ListGapsIn,
    ListGapsOut,
    SaveFactIn,
    SaveFactOut,
    SaveGapIn,
    SaveGapOut,
    UpdateGapIn,
)
from vv_mcp.repo_memory import InMemoryStateRepository

from .conftest import SID, call, connect, error_text

SCORES = InterpretationScores(concreteness=4, relevance=4, defensibility=3, domain_fit=5)


def fact_req(layer: str = "clarity", quadrant: str = "open", kind: str = "evidence") -> SaveFactIn:
    fact = ExtractedFact.model_validate(
        {
            "text": "Ajusta a pressão pela respiração",
            "source_excerpt": "vou sentindo pela respiração",
            "kind": kind,
            "origin": "client_statement",
            "finding_area": quadrant,
        }
    )
    return SaveFactIn.model_validate(
        {
            "session_id": SID,
            "turn_seq": 2,
            "layer_id": layer,
            "stage_id": f"{layer}.real_context",
            "fact": fact.model_dump(),
            "scores": SCORES.model_dump(),
        }
    )


def gap_req(layer: str = "clarity") -> SaveGapIn:
    return SaveGapIn.model_validate(
        {
            "session_id": SID,
            "layer_id": layer,
            "stage_id": f"{layer}.real_context",
            "description": "Sem rotina concreta",
            "origin": "client_statement",
            "reason": "Duas respostas vagas",
        }
    )


async def test_save_and_list_facts(repo: InMemoryStateRepository) -> None:
    async with connect(repo) as client:
        a = SaveFactOut.model_validate(
            (await call(client, "save_fact", fact_req())).structuredContent
        )
        await call(client, "save_fact", fact_req("singularity", "hidden", "benefit"))
        res = await call(client, "list_facts", ListFactsIn(session_id=SID, layer_id="clarity"))
        facts = ListFactsOut.model_validate(res.structuredContent).facts
    assert [f.fact_id for f in facts] == [a.fact_id]
    stored = facts[0]
    assert stored.source_turn == 2 and stored.stage_id == "clarity.real_context"
    assert stored.source_excerpt == "vou sentindo pela respiração"
    assert stored.scores == SCORES


async def test_fact_ids_are_unique(repo: InMemoryStateRepository) -> None:
    async with connect(repo) as client:
        ids = {
            SaveFactOut.model_validate(
                (await call(client, "save_fact", fact_req())).structuredContent
            ).fact_id
            for _ in range(5)
        }
    assert len(ids) == 5


async def test_list_facts_filters(repo: InMemoryStateRepository) -> None:
    async with connect(repo) as client:
        await call(client, "save_fact", fact_req())
        await call(client, "save_fact", fact_req("singularity", "blind", "benefit"))
        res = await call(client, "list_facts", ListFactsIn(session_id=SID, finding_area="blind"))
        assert len(ListFactsOut.model_validate(res.structuredContent).facts) == 1
        res = await call(client, "list_facts", ListFactsIn(session_id=SID, kind="evidence"))
        assert len(ListFactsOut.model_validate(res.structuredContent).facts) == 1


async def test_fact_without_excerpt_is_rejected(repo: InMemoryStateRepository) -> None:
    payload = fact_req().model_dump(mode="json")
    payload["fact"]["source_excerpt"] = ""
    async with connect(repo) as client:
        assert (await call(client, "save_fact", payload)).isError


async def test_unknown_session(repo: InMemoryStateRepository) -> None:
    req = fact_req().model_copy(update={"session_id": "nope"})
    async with connect(repo) as client:
        assert "unknown session" in error_text(await call(client, "save_fact", req))


async def test_gap_lifecycle(repo: InMemoryStateRepository) -> None:
    async with connect(repo) as client:
        gap = SaveGapOut.model_validate(
            (await call(client, "save_gap", gap_req())).structuredContent
        )
        await call(client, "save_gap", gap_req("translation"))
        res = await call(client, "list_gaps", ListGapsIn(session_id=SID, layer_id="clarity"))
        assert [g.gap_id for g in ListGapsOut.model_validate(res.structuredContent).gaps] == [
            gap.gap_id
        ]
        fact = SaveFactOut.model_validate(
            (await call(client, "save_fact", fact_req())).structuredContent
        )
        upd = UpdateGapIn(
            session_id=SID, gap_id=gap.gap_id, status="resolved", fact_id=fact.fact_id
        )
        assert not (await call(client, "update_gap", upd)).isError
        res = await call(client, "list_gaps", ListGapsIn(session_id=SID, status="resolved"))
        resolved = ListGapsOut.model_validate(res.structuredContent).gaps
    assert resolved[0].resolved_by_fact == fact.fact_id


async def test_gap_never_resolved_by_missing_fact(repo: InMemoryStateRepository) -> None:
    async with connect(repo) as client:
        gap = SaveGapOut.model_validate(
            (await call(client, "save_gap", gap_req())).structuredContent
        )
        upd = UpdateGapIn(session_id=SID, gap_id=gap.gap_id, status="resolved", fact_id="ghost")
        assert "unknown fact" in error_text(await call(client, "update_gap", upd))
        no_fact = {"session_id": SID, "gap_id": gap.gap_id, "status": "resolved"}
        assert (await call(client, "update_gap", no_fact)).isError


async def test_update_unknown_gap(repo: InMemoryStateRepository) -> None:
    upd = UpdateGapIn(session_id=SID, gap_id="ghost", status="kept_as_hypothesis")
    async with connect(repo) as client:
        assert "unknown gap" in error_text(await call(client, "update_gap", upd))
