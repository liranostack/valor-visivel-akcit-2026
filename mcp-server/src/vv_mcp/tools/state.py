"""State tools: session lifecycle and state, turns, stage progress, reviews, Pre-Core, Core."""

import uuid

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from vv_contracts.ports import StateRepository
from vv_contracts.state import (
    Baseline,
    PublicContextRecord,
    Review,
    Session,
    SessionState,
    StoredSynthesis,
    retention_until,
)
from vv_contracts.tools import (
    Ack,
    CreateSessionIn,
    CreateSessionOut,
    GetSessionStateIn,
    SaveBaselineIn,
    SaveCoreIn,
    SavePreCoreIn,
    SavePublicContextIn,
    SaveReviewIn,
    SaveSynthesisIn,
    SaveSynthesisOut,
    SaveTurnIn,
    SaveTurnOut,
    UpdateSessionIn,
    UpdateStageProgressIn,
)

from vv_mcp.telemetry import tool_span
from vv_mcp.tools import guarded


def register(server: FastMCP, repo: StateRepository) -> None:
    def _require(session_id: str) -> SessionState:
        state = repo.get_state(session_id)
        if state is None:
            raise ToolError(f"unknown session {session_id!r}")
        return state

    @server.tool(description=CreateSessionIn.__doc__)
    def create_session(req: CreateSessionIn) -> CreateSessionOut:  # pyright: ignore[reportUnusedFunction]
        session_id = uuid.uuid4().hex
        with tool_span("create_session", session_id):
            session = Session(
                session_id=session_id, status="onboarding", retention_until=retention_until()
            )
            guarded(lambda: repo.put_session(session))
            return CreateSessionOut(session_id=session_id)

    @server.tool(description=UpdateSessionIn.__doc__)
    def update_session(req: UpdateSessionIn) -> Ack:  # pyright: ignore[reportUnusedFunction]
        with tool_span("update_session", req.session_id):
            current = _require(req.session_id).session
            updated = Session.model_validate(current.model_dump() | req.patch())
            guarded(lambda: repo.put_session(updated))
            return Ack()

    @server.tool(description=SaveBaselineIn.__doc__)
    def save_baseline(req: SaveBaselineIn) -> Ack:  # pyright: ignore[reportUnusedFunction]
        with tool_span("save_baseline", req.session_id):
            _require(req.session_id)
            guarded(lambda: repo.save_baseline(req.session_id, Baseline(statement=req.statement)))
            return Ack()

    @server.tool(description=SavePublicContextIn.__doc__)
    def save_public_context(req: SavePublicContextIn) -> Ack:  # pyright: ignore[reportUnusedFunction]
        with tool_span("save_public_context", req.session_id):
            _require(req.session_id)
            record = PublicContextRecord(
                source=req.source, summary=req.summary, claims_to_verify=req.claims_to_verify
            )
            guarded(lambda: repo.save_public_context(req.session_id, record))
            return Ack()

    @server.tool(description=GetSessionStateIn.__doc__)
    def get_session_state(req: GetSessionStateIn) -> SessionState:  # pyright: ignore[reportUnusedFunction]
        with tool_span("get_session_state", req.session_id):
            state = repo.get_state(req.session_id)
            if state is None:
                raise ToolError(f"unknown session {req.session_id!r}")
            return state

    @server.tool(description=SaveTurnIn.__doc__)
    def save_turn(req: SaveTurnIn) -> SaveTurnOut:  # pyright: ignore[reportUnusedFunction]
        with tool_span("save_turn", req.session_id):
            return SaveTurnOut(seq=guarded(lambda: repo.save_turn(req.session_id, req.turn)))

    @server.tool(description=UpdateStageProgressIn.__doc__)
    def update_stage_progress(req: UpdateStageProgressIn) -> Ack:  # pyright: ignore[reportUnusedFunction]
        with tool_span("update_stage_progress", req.session_id):
            guarded(lambda: repo.update_stage_progress(req.session_id, req.progress))
            return Ack()

    @server.tool(description=SaveSynthesisIn.__doc__)
    def save_synthesis(req: SaveSynthesisIn) -> SaveSynthesisOut:  # pyright: ignore[reportUnusedFunction]
        with tool_span("save_synthesis", req.session_id):
            _require(req.session_id)
            stored = StoredSynthesis(version=1, **req.synthesis.model_dump())
            version = guarded(lambda: repo.save_synthesis(req.session_id, stored))
            return SaveSynthesisOut(version=version)

    @server.tool(description=SaveReviewIn.__doc__)
    def save_review(req: SaveReviewIn) -> Ack:  # pyright: ignore[reportUnusedFunction]
        with tool_span("save_review", req.session_id):
            review = Review(target=req.target, intent=req.intent, notes=req.notes)
            guarded(lambda: repo.save_review(req.session_id, review))
            return Ack()

    @server.tool(description=SavePreCoreIn.__doc__)
    def save_pre_core(req: SavePreCoreIn) -> Ack:  # pyright: ignore[reportUnusedFunction]
        with tool_span("save_pre_core", req.session_id):
            guarded(lambda: repo.save_pre_core(req.session_id, req.pre_core))
            return Ack()

    @server.tool(description=SaveCoreIn.__doc__)
    def save_core(req: SaveCoreIn) -> Ack:  # pyright: ignore[reportUnusedFunction]
        with tool_span("save_core", req.session_id):
            guarded(lambda: repo.save_core(req.session_id, req.core))
            return Ack()
