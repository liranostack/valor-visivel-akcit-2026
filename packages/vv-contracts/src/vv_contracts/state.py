"""Session state persisted in the single DynamoDB table (ERD, "Modelo de dados")."""

from datetime import UTC, datetime, timedelta
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from vv_contracts.agents import (
    AbcOption,
    EssentialCoreOutput,
    InterpretationScores,
)
from vv_contracts.common import (
    DecisionAction,
    FactKind,
    FactOrigin,
    FindingArea,
    LayerId,
    NonEmptyStr,
    ReviewIntent,
    ReviewTarget,
)

RETENTION_DAYS = 30

SessionStatus = Literal[
    "onboarding",
    "baseline",
    "in_layer",
    "layer_review",
    "pre_core_review",
    "core_generation",
    "completed",
]
StageStatus = Literal["open", "covered", "forced"]
GapStatus = Literal["open", "resumed", "resolved", "kept_as_hypothesis"]
SynthesisStatus = Literal["proposed", "approved", "adjusted"]


def _now() -> datetime:
    return datetime.now(UTC)


def retention_until(now: datetime | None = None) -> datetime:
    return (now or _now()) + timedelta(days=RETENTION_DAYS)


class OnboardingAnswers(BaseModel):
    business_type: str | None = None
    business_structure: str | None = None
    offer: str | None = None
    audience: str | None = None
    channels: list[str] = Field(default_factory=list[str])
    goal: str | None = None
    perceived_difficulty: str | None = None
    difficulty_context: str | None = None
    declared_links: list[str] = Field(default_factory=list[str])  # site is read; Instagram is not


class Session(BaseModel):
    session_id: NonEmptyStr
    status: SessionStatus
    active_layer: LayerId | None = None
    active_stage: str | None = None
    pending_gap_id: str | None = None  # gap asked again by a resume_gap question, if any
    consent_at: datetime | None = None
    retention_until: datetime | None = None
    onboarding: OnboardingAnswers | None = None
    prompt_version: str | None = None
    kb_version: str | None = None
    created_at: datetime = Field(default_factory=_now)


class Baseline(BaseModel):
    statement: str  # stored exactly as typed, never corrected
    recorded_at: datetime = Field(default_factory=_now)


class PublicContextRecord(BaseModel):
    source: str
    summary: str
    claims_to_verify: list[str] = Field(default_factory=list[str])
    read_at: datetime = Field(default_factory=_now)


class StageProgress(BaseModel):
    stage_id: NonEmptyStr
    layer_id: LayerId
    attempts: int = Field(default=0, ge=0)
    status: StageStatus = "open"
    flagged_for_review: bool = False
    difficulty_signals: list[str] = Field(default_factory=list[str])


class Turn(BaseModel):
    seq: int = Field(ge=1)
    user_message: str
    question_asked: str | None = None
    decision: DecisionAction | None = None
    mode: str | None = None
    abc_options: list[AbcOption] | None = None
    abc_rejected: bool = False
    scores: InterpretationScores | None = None
    difficulty_signals: list[str] = Field(default_factory=list[str])
    trace_id: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    created_at: datetime = Field(default_factory=_now)


class Fact(BaseModel):
    fact_id: NonEmptyStr
    layer_id: LayerId
    stage_id: NonEmptyStr
    source_turn: int = Field(ge=0)
    text: NonEmptyStr
    source_excerpt: NonEmptyStr
    scores: InterpretationScores
    kind: FactKind
    origin: FactOrigin
    finding_area: FindingArea
    active: bool = True


class Gap(BaseModel):
    gap_id: NonEmptyStr
    layer_id: LayerId
    source_stage: NonEmptyStr
    description: NonEmptyStr
    origin: FactOrigin
    reason: NonEmptyStr
    status: GapStatus = "open"
    resolved_by_fact: str | None = None

    @model_validator(mode="after")
    def _resolved_needs_fact(self) -> Self:
        if self.status == "resolved" and not self.resolved_by_fact:
            raise ValueError("a gap is only resolved by a new fact (resolved_by_fact)")
        return self


class StoredSynthesis(BaseModel):
    layer_id: LayerId
    version: int = Field(ge=1)
    content: dict[str, str]
    fact_refs: list[str]
    gaps: list[str] = Field(default_factory=list[str])
    hypotheses: list[str] = Field(default_factory=list[str])
    status: SynthesisStatus = "proposed"


class Review(BaseModel):
    target: ReviewTarget
    intent: ReviewIntent
    notes: str = ""
    created_at: datetime = Field(default_factory=_now)


class PreCore(BaseModel):
    contradictions: list[str] = Field(default_factory=list[str])
    gaps: list[str] = Field(default_factory=list[str])
    corrections: list[str] = Field(default_factory=list[str])
    content: dict[str, str] = Field(default_factory=dict[str, str])
    status: SynthesisStatus = "proposed"


class EssentialCore(EssentialCoreOutput):
    created_at: datetime = Field(default_factory=_now)


class Evaluation(BaseModel):
    turn_seq: int = Field(ge=0)
    metric: NonEmptyStr
    score: float
    judge: NonEmptyStr
    prompt_version: str | None = None


class SessionState(BaseModel):
    """Everything the Conductor needs at the start of a turn (one Query by PK)."""

    session: Session
    baseline: Baseline | None = None
    public_context: PublicContextRecord | None = None
    progress: list[StageProgress] = Field(default_factory=list[StageProgress])
    open_gaps: list[Gap] = Field(default_factory=list[Gap])
    last_turn_seq: int = Field(default=0, ge=0)
    asked_questions: list[str] = Field(default_factory=list[str])
