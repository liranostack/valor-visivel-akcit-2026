"""FakeToolGateway: in-memory ToolGateway for agent and turn-loop unit tests (no MCP, no AWS).

State goes to InMemoryStateRepository; method content comes from dictionaries given by the test.
Every call is recorded in `calls` so tests can assert which tools a component used.
"""

import uuid

from vv_contracts.kb import LayerSpec
from vv_contracts.state import (
    Baseline,
    Fact,
    Gap,
    PublicContextRecord,
    Review,
    Session,
    SessionState,
    StoredSynthesis,
    retention_until,
)
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
    Violation,
)
from vv_mcp.repo_memory import InMemoryStateRepository


class FakeToolGateway:
    def __init__(
        self,
        layers: dict[str, LayerSpec] | None = None,
        templates: dict[str, str] | None = None,
        guide: str = "",
        violations: list[Violation] | None = None,
    ) -> None:
        self.repo = InMemoryStateRepository()
        self.layers = layers or {}
        self.templates = templates or {}
        self.guide = guide
        self.violations = violations or []
        self.calls: list[str] = []

    def start_session(self, session_id: str) -> None:
        self.repo.put_session(Session(session_id=session_id, status="onboarding"))

    def _state(self, session_id: str) -> SessionState:
        state = self.repo.get_state(session_id)
        if state is None:
            raise KeyError(session_id)
        return state

    async def create_session(self, req: CreateSessionIn) -> CreateSessionOut:
        self.calls.append("create_session")
        session_id = uuid.uuid4().hex
        self.repo.put_session(
            Session(session_id=session_id, status="onboarding", retention_until=retention_until())
        )
        return CreateSessionOut(session_id=session_id)

    async def update_session(self, req: UpdateSessionIn) -> Ack:
        self.calls.append("update_session")
        current = self._state(req.session_id).session
        self.repo.put_session(Session.model_validate(current.model_dump() | req.patch()))
        return Ack()

    async def save_baseline(self, req: SaveBaselineIn) -> Ack:
        self.calls.append("save_baseline")
        self.repo.save_baseline(req.session_id, Baseline(statement=req.statement))
        return Ack()

    async def save_public_context(self, req: SavePublicContextIn) -> Ack:
        self.calls.append("save_public_context")
        record = PublicContextRecord(
            source=req.source, summary=req.summary, claims_to_verify=req.claims_to_verify
        )
        self.repo.save_public_context(req.session_id, record)
        return Ack()

    async def get_session_state(self, req: GetSessionStateIn) -> SessionState:
        self.calls.append("get_session_state")
        return self._state(req.session_id)

    async def save_turn(self, req: SaveTurnIn) -> SaveTurnOut:
        self.calls.append("save_turn")
        return SaveTurnOut(seq=self.repo.save_turn(req.session_id, req.turn))

    async def update_stage_progress(self, req: UpdateStageProgressIn) -> Ack:
        self.calls.append("update_stage_progress")
        self.repo.update_stage_progress(req.session_id, req.progress)
        return Ack()

    async def save_fact(self, req: SaveFactIn) -> SaveFactOut:
        self.calls.append("save_fact")
        fact = Fact(
            fact_id=uuid.uuid4().hex[:12],
            layer_id=req.layer_id,
            stage_id=req.stage_id,
            source_turn=req.turn_seq,
            scores=req.scores,
            **req.fact.model_dump(),
        )
        return SaveFactOut(fact_id=self.repo.save_fact(req.session_id, fact))

    async def list_facts(self, req: ListFactsIn) -> ListFactsOut:
        self.calls.append("list_facts")
        facts = self.repo.list_facts(req.session_id, req.layer_id, req.finding_area, req.kind)
        return ListFactsOut(facts=facts)

    async def save_gap(self, req: SaveGapIn) -> SaveGapOut:
        self.calls.append("save_gap")
        gap = Gap(
            gap_id=uuid.uuid4().hex[:12],
            layer_id=req.layer_id,
            source_stage=req.stage_id,
            description=req.description,
            origin=req.origin,
            reason=req.reason,
        )
        return SaveGapOut(gap_id=self.repo.save_gap(req.session_id, gap))

    async def list_gaps(self, req: ListGapsIn) -> ListGapsOut:
        self.calls.append("list_gaps")
        return ListGapsOut(gaps=self.repo.list_gaps(req.session_id, req.layer_id, req.status))

    async def update_gap(self, req: UpdateGapIn) -> Ack:
        self.calls.append("update_gap")
        self.repo.update_gap(req.session_id, req.gap_id, req.status, req.fact_id)
        return Ack()

    async def get_layer_spec(self, req: GetLayerSpecIn) -> LayerSpec:
        self.calls.append("get_layer_spec")
        return self.layers[req.layer_id]

    async def get_question_from_pool(self, req: GetQuestionFromPoolIn) -> GetQuestionFromPoolOut:
        self.calls.append("get_question_from_pool")
        for layer in self.layers.values():
            for stage in layer.stages:
                if stage.stage_id == req.stage_id:
                    anchors = stage.anchors_for(req.angle) if req.angle else stage.anchors
                    return GetQuestionFromPoolOut(
                        stage_id=stage.stage_id,
                        anchors=anchors,
                        rescue_angles=stage.rescue_angles,
                    )
        raise KeyError(req.stage_id)

    async def get_synthesis_template(self, req: GetSynthesisTemplateIn) -> GetSynthesisTemplateOut:
        self.calls.append("get_synthesis_template")
        return GetSynthesisTemplateOut(kind=req.kind, markdown=self.templates.get(req.kind, ""))

    async def get_method_guide(self, req: GetMethodGuideIn) -> GetMethodGuideOut:
        self.calls.append("get_method_guide")
        return GetMethodGuideOut(markdown=self.guide)

    async def save_synthesis(self, req: SaveSynthesisIn) -> SaveSynthesisOut:
        self.calls.append("save_synthesis")
        stored = StoredSynthesis(version=1, **req.synthesis.model_dump())
        return SaveSynthesisOut(version=self.repo.save_synthesis(req.session_id, stored))

    async def save_review(self, req: SaveReviewIn) -> Ack:
        self.calls.append("save_review")
        self.repo.save_review(
            req.session_id, Review(target=req.target, intent=req.intent, notes=req.notes)
        )
        return Ack()

    async def save_pre_core(self, req: SavePreCoreIn) -> Ack:
        self.calls.append("save_pre_core")
        self.repo.save_pre_core(req.session_id, req.pre_core)
        return Ack()

    async def save_core(self, req: SaveCoreIn) -> Ack:
        self.calls.append("save_core")
        self.repo.save_core(req.session_id, req.core)
        return Ack()

    async def check_output(self, req: CheckOutputIn) -> CheckOutputOut:
        self.calls.append("check_output")
        return CheckOutputOut(violations=list(self.violations))

    async def read_public_site(self, req: ReadPublicSiteIn) -> ReadPublicSiteOut:
        self.calls.append("read_public_site")
        return ReadPublicSiteOut(outcome="empty", url=req.url)
