"""Facts and gaps tools. A gap is resolved only by an existing fact (never by assertion)."""

import uuid

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from vv_contracts.ports import StateRepository
from vv_contracts.state import Fact, Gap
from vv_contracts.tools import (
    Ack,
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

from vv_mcp.telemetry import tool_span
from vv_mcp.tools import guarded


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def register(server: FastMCP, repo: StateRepository) -> None:
    @server.tool(description=SaveFactIn.__doc__)
    def save_fact(req: SaveFactIn) -> SaveFactOut:  # pyright: ignore[reportUnusedFunction]
        with tool_span("save_fact", req.session_id) as span:
            fact = Fact(
                fact_id=new_id(),
                layer_id=req.layer_id,
                stage_id=req.stage_id,
                source_turn=req.turn_seq,
                scores=req.scores,
                **req.fact.model_dump(),
            )
            span.set_attribute("finding_area", fact.finding_area)
            return SaveFactOut(fact_id=guarded(lambda: repo.save_fact(req.session_id, fact)))

    @server.tool(description=ListFactsIn.__doc__)
    def list_facts(req: ListFactsIn) -> ListFactsOut:  # pyright: ignore[reportUnusedFunction]
        with tool_span("list_facts", req.session_id):
            facts = guarded(
                lambda: repo.list_facts(req.session_id, req.layer_id, req.finding_area, req.kind)
            )
            return ListFactsOut(facts=facts)

    @server.tool(description=SaveGapIn.__doc__)
    def save_gap(req: SaveGapIn) -> SaveGapOut:  # pyright: ignore[reportUnusedFunction]
        with tool_span("save_gap", req.session_id):
            gap = Gap(
                gap_id=new_id(),
                layer_id=req.layer_id,
                source_stage=req.stage_id,
                description=req.description,
                origin=req.origin,
                reason=req.reason,
            )
            return SaveGapOut(gap_id=guarded(lambda: repo.save_gap(req.session_id, gap)))

    @server.tool(description=ListGapsIn.__doc__)
    def list_gaps(req: ListGapsIn) -> ListGapsOut:  # pyright: ignore[reportUnusedFunction]
        with tool_span("list_gaps", req.session_id):
            gaps = guarded(lambda: repo.list_gaps(req.session_id, req.layer_id, req.status))
            return ListGapsOut(gaps=gaps)

    @server.tool(description=UpdateGapIn.__doc__)
    def update_gap(req: UpdateGapIn) -> Ack:  # pyright: ignore[reportUnusedFunction]
        with tool_span("update_gap", req.session_id):
            if req.status == "resolved":
                facts = guarded(lambda: repo.list_facts(req.session_id))
                if req.fact_id not in {f.fact_id for f in facts}:
                    raise ToolError(
                        f"unknown fact {req.fact_id!r}: a gap is resolved only by a fact"
                    )
            guarded(lambda: repo.update_gap(req.session_id, req.gap_id, req.status, req.fact_id))
            return Ack()
