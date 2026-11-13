"""In-memory StateRepository: used by tests, local runs and TOOL_GATEWAY=inprocess demos."""

from dataclasses import dataclass, field

from vv_contracts.common import FactKind, FindingArea, LayerId
from vv_contracts.state import (
    Baseline,
    EssentialCore,
    Evaluation,
    Fact,
    Gap,
    GapStatus,
    PreCore,
    PublicContextRecord,
    Review,
    Session,
    SessionState,
    StageProgress,
    StoredSynthesis,
    Turn,
)


@dataclass
class _SessionData:
    session: Session
    baseline: Baseline | None = None
    public_context: PublicContextRecord | None = None
    progress: dict[str, StageProgress] = field(default_factory=dict[str, StageProgress])
    turns: dict[int, Turn] = field(default_factory=dict[int, Turn])
    facts: dict[str, Fact] = field(default_factory=dict[str, Fact])
    gaps: dict[str, Gap] = field(default_factory=dict[str, Gap])
    syntheses: list[StoredSynthesis] = field(default_factory=list[StoredSynthesis])
    reviews: list[Review] = field(default_factory=list[Review])
    pre_core: PreCore | None = None
    core: EssentialCore | None = None
    evaluations: list[Evaluation] = field(default_factory=list[Evaluation])


class InMemoryStateRepository:
    """Implements vv_contracts.ports.StateRepository."""

    def __init__(self) -> None:
        self._data: dict[str, _SessionData] = {}

    def _get(self, session_id: str) -> _SessionData:
        try:
            return self._data[session_id]
        except KeyError:
            raise KeyError(f"unknown session {session_id!r}") from None

    # --- session ---------------------------------------------------------------------------
    def put_session(self, session: Session) -> None:
        current = self._data.get(session.session_id)
        if current is None:
            self._data[session.session_id] = _SessionData(session=session)
        else:
            current.session = session

    def get_state(self, session_id: str) -> SessionState | None:
        data = self._data.get(session_id)
        if data is None:
            return None
        turns = [data.turns[k] for k in sorted(data.turns)]
        return SessionState(
            session=data.session,
            baseline=data.baseline,
            public_context=data.public_context,
            progress=list(data.progress.values()),
            open_gaps=[g for g in data.gaps.values() if g.status == "open"],
            last_turn_seq=turns[-1].seq if turns else 0,
            asked_questions=[t.question_asked for t in turns if t.question_asked],
        )

    def save_baseline(self, session_id: str, baseline: Baseline) -> None:
        self._get(session_id).baseline = baseline

    def save_public_context(self, session_id: str, context: PublicContextRecord) -> None:
        self._get(session_id).public_context = context

    def save_turn(self, session_id: str, turn: Turn) -> int:
        self._get(session_id).turns[turn.seq] = turn
        return turn.seq

    def list_turns(self, session_id: str) -> list[Turn]:
        turns = self._get(session_id).turns
        return [turns[k] for k in sorted(turns)]

    def update_stage_progress(self, session_id: str, progress: StageProgress) -> None:
        self._get(session_id).progress[progress.stage_id] = progress

    # --- facts and gaps --------------------------------------------------------------------
    def save_fact(self, session_id: str, fact: Fact) -> str:
        self._get(session_id).facts[fact.fact_id] = fact
        return fact.fact_id

    def list_facts(
        self,
        session_id: str,
        layer_id: LayerId | None = None,
        finding_area: FindingArea | None = None,
        kind: FactKind | None = None,
    ) -> list[Fact]:
        return [
            f
            for f in self._get(session_id).facts.values()
            if (layer_id is None or f.layer_id == layer_id)
            and (finding_area is None or f.finding_area == finding_area)
            and (kind is None or f.kind == kind)
        ]

    def save_gap(self, session_id: str, gap: Gap) -> str:
        self._get(session_id).gaps[gap.gap_id] = gap
        return gap.gap_id

    def list_gaps(
        self, session_id: str, layer_id: LayerId | None = None, status: GapStatus | None = None
    ) -> list[Gap]:
        return [
            g
            for g in self._get(session_id).gaps.values()
            if (layer_id is None or g.layer_id == layer_id)
            and (status is None or g.status == status)
        ]

    def update_gap(
        self, session_id: str, gap_id: str, status: GapStatus, fact_id: str | None = None
    ) -> None:
        gaps = self._get(session_id).gaps
        if gap_id not in gaps:
            raise KeyError(f"unknown gap {gap_id!r}")
        updated = gaps[gap_id].model_dump() | {"status": status, "resolved_by_fact": fact_id}
        gaps[gap_id] = Gap.model_validate(updated)  # validation: resolved needs a fact

    # --- deliverables ----------------------------------------------------------------------
    def save_synthesis(self, session_id: str, synthesis: StoredSynthesis) -> int:
        data = self._get(session_id)
        latest = self.latest_synthesis(session_id, synthesis.layer_id)
        version = 1 if latest is None else latest.version + 1
        data.syntheses.append(synthesis.model_copy(update={"version": version}))
        return version

    def latest_synthesis(self, session_id: str, layer_id: LayerId) -> StoredSynthesis | None:
        same_layer = [s for s in self._get(session_id).syntheses if s.layer_id == layer_id]
        return max(same_layer, key=lambda s: s.version, default=None)

    def save_review(self, session_id: str, review: Review) -> None:
        self._get(session_id).reviews.append(review)

    def save_pre_core(self, session_id: str, pre_core: PreCore) -> None:
        self._get(session_id).pre_core = pre_core

    def save_core(self, session_id: str, core: EssentialCore) -> None:
        self._get(session_id).core = core

    def save_evaluation(self, session_id: str, evaluation: Evaluation) -> None:
        self._get(session_id).evaluations.append(evaluation)

    # --- read helpers for tests and replay -------------------------------------------------
    def reviews(self, session_id: str) -> list[Review]:
        return list(self._get(session_id).reviews)

    def pre_core(self, session_id: str) -> PreCore | None:
        return self._get(session_id).pre_core

    def core(self, session_id: str) -> EssentialCore | None:
        return self._get(session_id).core

    def evaluations(self, session_id: str) -> list[Evaluation]:
        return list(self._get(session_id).evaluations)
