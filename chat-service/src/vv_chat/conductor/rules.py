"""Deterministic decision rules of the Conductor (ERD, 'Máquina de estados do Conductor').

Pure functions: no I/O, no model calls. Same input, same decision.

Attempt counting: `StageProgress.attempts` is the number of answers already received for the
current stage before this one. This answer is attempt `attempts + 1`. With the default
`max_attempts_per_stage = 2`, a first vague answer deepens (the next question is attempt 2 and
offers ABC options) and a second vague answer forces the advance.
"""

from pydantic import BaseModel, Field
from vv_contracts.agents import Decision, InterpretationResult
from vv_contracts.common import LayerId
from vv_contracts.state import Gap, GapStatus, StageProgress, StageStatus

from vv_chat.conductor.config import ConductorConfig

NO_EVIDENCE_REASON = "insufficient evidence after maximum attempts"
QUADRANT_REASON = "no hidden or blind fact found in this layer"


class StageState(BaseModel):
    """What the Conductor knows about the active layer when a turn arrives."""

    layer_id: LayerId
    stage_id: str
    stage_ids: list[str]  # ordered stages of the active layer (from the KB)
    progress: dict[str, StageProgress]
    layer_has_hidden_or_blind: bool = False
    open_gaps: list[Gap] = Field(default_factory=list[Gap])
    resumed_gap_in_layer: bool = False


class Outcome(BaseModel):
    decision: Decision
    stage_status: StageStatus  # new status of the current stage
    attempts: int  # new attempts value for the current stage
    flag_for_review: bool = False  # goes back to the Pre-Core
    create_gap: bool = False
    gap_reason: str | None = None
    layer_complete: bool = False
    quadrant_rule_pending: bool = False


class ResumeOutcome(BaseModel):
    decision: Decision
    gap_status: GapStatus


def _is_strong(interp: InterpretationResult, threshold: int) -> bool:
    return bool(interp.facts) and interp.concreteness >= threshold and interp.relevance >= threshold


def _next_open_stage(state: StageState, closing: str) -> str | None:
    for stage_id in state.stage_ids:
        if stage_id == closing:
            continue
        if state.progress[stage_id].status == "open":
            return stage_id
    return None


def _quadrant_ok(state: StageState, interp: InterpretationResult, cfg: ConductorConfig) -> bool:
    if state.layer_id not in cfg.require_hidden_or_blind_fact:
        return True
    found_now = any(f.finding_area in ("hidden", "blind") for f in interp.facts)
    return state.layer_has_hidden_or_blind or found_now


def _close_stage(
    state: StageState,
    cfg: ConductorConfig,
    *,
    action: str,
    status: StageStatus,
    gap_reason: str | None,
) -> Outcome:
    """Close the current stage and pick the next stage, a gap resume or the synthesis."""
    next_stage = _next_open_stage(state, state.stage_id)
    forced = status == "forced"
    common = {
        "stage_status": status,
        "attempts": state.progress[state.stage_id].attempts + 1,
        "flag_for_review": forced,
        "create_gap": forced,
        "gap_reason": gap_reason,
    }
    if next_stage is not None:
        decision = Decision.model_validate(
            {
                "action": action,
                "next_stage_id": next_stage,
                "attempt": 1,
                "offer_abc_options": False,
            }
        )
        return Outcome.model_validate({"decision": decision, **common})

    layer_gaps = [g for g in state.open_gaps if g.layer_id == state.layer_id]
    if cfg.resume_gaps_before_synthesis and layer_gaps and not state.resumed_gap_in_layer:
        decision = Decision(
            action="resume_gap",
            next_stage_id=None,
            attempt=1,
            offer_abc_options=False,
            gap_id=layer_gaps[0].gap_id,
        )
    else:
        decision = Decision(
            action="synthesize", next_stage_id=None, attempt=1, offer_abc_options=False
        )
    return Outcome.model_validate({"decision": decision, "layer_complete": True, **common})


def decide(state: StageState, interp: InterpretationResult, cfg: ConductorConfig) -> Outcome:
    """Decide what happens after the client's answer to the current stage question."""
    if state.stage_id not in state.stage_ids or state.stage_id not in state.progress:
        raise ValueError(f"unknown stage {state.stage_id!r} for layer {state.layer_id!r}")

    progress = state.progress[state.stage_id]
    attempt = progress.attempts + 1
    closing_layer = _next_open_stage(state, state.stage_id) is None
    strong = _is_strong(interp, cfg.advance_min_fact_score)
    quadrant_ok = not closing_layer or _quadrant_ok(state, interp, cfg)

    if strong and quadrant_ok:
        return _close_stage(state, cfg, action="advance", status="covered", gap_reason=None)

    if attempt >= cfg.max_attempts_per_stage:
        reason = (
            QUADRANT_REASON if strong else (interp.gaps[0] if interp.gaps else NO_EVIDENCE_REASON)
        )
        return _close_stage(state, cfg, action="force_advance", status="forced", gap_reason=reason)

    next_attempt = attempt + 1
    decision = Decision(
        action="deepen",
        next_stage_id=state.stage_id,
        attempt=next_attempt,
        offer_abc_options=next_attempt == cfg.abc_options_on_attempt,
    )
    return Outcome(
        decision=decision,
        stage_status="open",
        attempts=attempt,
        quadrant_rule_pending=strong and not quadrant_ok,
    )


def decide_resume(interp: InterpretationResult, gap_id: str, cfg: ConductorConfig) -> ResumeOutcome:
    """After a resume question, the gap becomes a fact only with new evidence >= threshold."""
    resolved = _is_strong(interp, cfg.advance_min_fact_score)
    return ResumeOutcome(
        decision=Decision(
            action="synthesize", next_stage_id=None, attempt=1, offer_abc_options=False
        ),
        gap_status="resolved" if resolved else "kept_as_hypothesis",
    )
