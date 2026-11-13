"""Turn loop for one answer of the client (ERD, 'Fluxo de um turno').

guardrail in → Interpreter → Conductor → Investigator → Moderator (or Synthesizer)
→ output checks → guardrail out → persist → stream.

Every agent falls back on its own; anything else that fails becomes a safe pt-BR ErrorEvent.
Nothing the client typed is stored before the input guardrail (blocked text is never stored;
masked text is what moves on).
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol

from vv_contracts.agents import AbcOption, InterpretationResult, LayerSynthesis
from vv_contracts.common import LAYERS_ORDER, LayerId
from vv_contracts.kb import LayerSpec, fill_placeholders
from vv_contracts.ports import ToolGateway
from vv_contracts.state import Gap, SessionState, StageProgress, Turn
from vv_contracts.tools import (
    GetLayerSpecIn,
    GetQuestionFromPoolIn,
    GetSessionStateIn,
    ListFactsIn,
    ListGapsIn,
    SaveFactIn,
    SaveGapIn,
    SaveSynthesisIn,
    SaveTurnIn,
    UpdateGapIn,
    UpdateSessionIn,
    UpdateStageProgressIn,
)
from vv_contracts.ws import (
    DeliverableEvent,
    ErrorEvent,
    MessageDoneEvent,
    ProgressEvent,
    ProgressStep,
    ServerEvent,
    StateEvent,
    TokenEvent,
)

from vv_chat.agents.interpreter import InterpretContext, interpret
from vv_chat.agents.investigator import InvestigateContext, NoNewQuestionError, investigate
from vv_chat.agents.llm import StructuredLLM
from vv_chat.agents.moderator import ModerateContext, iter_text, moderate
from vv_chat.agents.modes import Mode, mode_for
from vv_chat.agents.synthesizer import SynthesizeContext, synthesize_layer
from vv_chat.business import LAYER_DONE, business_profile, closing_message, entry_focus
from vv_chat.conductor.config import ConductorConfig
from vv_chat.conductor.rules import StageState, decide, decide_resume
from vv_chat.conductor.state_machine import Position, next_position
from vv_chat.guardrails import InputCheck, OutputCheck
from vv_chat.progress import PROGRESS_MESSAGES

log = logging.getLogger(__name__)

Role = Literal["interpreter", "investigator", "moderator", "synthesizer"]
TURN_FAILED = "Tive um problema agora. Pode repetir sua última resposta?"
NOT_IN_LAYER = "Ainda não chegamos na conversa sobre o seu negócio. Vamos terminar o início?"
OFF_TOPIC_RELEVANCE = 1


class Guardrails(Protocol):
    async def check_input(self, text: str, current_question: str = "") -> InputCheck: ...
    async def check_output(self, text: str) -> OutputCheck: ...


@dataclass
class TurnDeps:
    gateway: ToolGateway
    llms: dict[Role, StructuredLLM]
    guardrails: Guardrails
    config: ConductorConfig = field(default_factory=ConductorConfig)
    # Optional diagnostics: called with (step, data) after each step (scripts, telemetry).
    on_step: Callable[[str, dict[str, Any]], None] | None = None
    # Set by the turn itself: forwards progress steps to the client stream.
    progress: Callable[[ProgressStep], None] | None = None


def _emit(deps: TurnDeps, step: str, **data: Any) -> None:
    if deps.on_step is None:
        return
    try:
        deps.on_step(step, data)
    except Exception:  # diagnostics must never break a turn
        log.warning("on_step failed for %s", step)


def _notify(deps: TurnDeps, step: ProgressStep) -> None:
    if deps.progress is not None:
        deps.progress(step)


def _ms(since: float) -> int:
    return int((time.monotonic() - since) * 1000)


@dataclass
class _Reply:
    text: str
    question: str | None = None
    abc: list[AbcOption] | None = None
    mode: str | None = None
    deliverable: LayerSynthesis | None = None


async def run_turn(session_id: str, message: str, deps: TurnDeps) -> AsyncIterator[ServerEvent]:
    """Run one turn; never raises to the caller."""
    try:
        async for event in _turn(session_id, message, deps):
            yield event
    except Exception:
        log.exception("turn failed")
        yield ErrorEvent(session_id=session_id, code="turn_failed", message=TURN_FAILED)


async def _turn(session_id: str, message: str, deps: TurnDeps) -> AsyncIterator[ServerEvent]:
    started = time.monotonic()
    gw = deps.gateway
    state = await gw.get_session_state(GetSessionStateIn(session_id=session_id))
    session = state.session
    seq = state.last_turn_seq + 1
    last_question = state.asked_questions[-1] if state.asked_questions else ""

    if session.status != "in_layer" or not session.active_layer or not session.active_stage:
        for event in _stream(session_id, _Reply(NOT_IN_LAYER), seq):
            yield event
        return

    t0 = time.monotonic()
    checked = await deps.guardrails.check_input(message, current_question=last_question)
    _emit(deps, "guardrail_input", allowed=checked.allowed, masked=checked.masked, ms=_ms(t0))
    if not checked.allowed:
        reply = _Reply(checked.message_if_blocked or last_question, mode="blocked_input")
        await _save_turn(gw, session_id, seq, "", reply, None, None, started)
        for event in _stream(session_id, reply, seq):
            yield event
        return
    text = checked.text

    layer_id: LayerId = session.active_layer
    layer = await gw.get_layer_spec(GetLayerSpecIn(layer_id=layer_id))
    vocabulary = _vocabulary(state)

    # The agents run as a task; their progress steps stream out while it works.
    steps: asyncio.Queue[ProgressStep | None] = asyncio.Queue()
    work_deps = replace(deps, progress=steps.put_nowait)
    answer = _resume_answer if session.pending_gap_id else _stage_answer

    async def work() -> tuple[InterpretationResult, str, _Reply]:
        try:
            return await answer(text, state, layer, vocabulary, seq, work_deps)
        finally:
            steps.put_nowait(None)

    task = asyncio.create_task(work())
    yield _progress_event(session_id, "reading")
    try:
        while (step := await steps.get()) is not None:
            yield _progress_event(session_id, step)
    finally:
        if not task.done():
            task.cancel()
    interp, decision_action, reply = await task

    if reply.question is not None:
        t0 = time.monotonic()
        guarded = await _guard_output(reply, layer, vocabulary, deps, state)
        _emit(deps, "guardrail_output", allowed=guarded is reply, ms=_ms(t0))
        reply = guarded

    await _save_turn(gw, session_id, seq, text, reply, decision_action, interp, started)
    _emit(deps, "turn", seq=seq, decision=decision_action, mode=reply.mode, ms=_ms(started))
    if reply.deliverable is not None:
        yield DeliverableEvent(
            session_id=session_id,
            kind="layer_synthesis",
            layer_id=reply.deliverable.layer_id,
            content=reply.deliverable.model_dump(mode="json"),
        )
    for event in _stream(session_id, reply, seq):
        yield event
    final = (await gw.get_session_state(GetSessionStateIn(session_id=session_id))).session
    position = Position(
        status=final.status,
        active_layer=final.active_layer if final.status in ("in_layer", "layer_review") else None,
    )
    yield StateEvent(
        session_id=session_id,
        status=final.status,
        active_layer=position.active_layer,
        layer_index=position.layer_index,
    )


def _progress_event(session_id: str, step: ProgressStep) -> ProgressEvent:
    return ProgressEvent(session_id=session_id, step=step, message=PROGRESS_MESSAGES[step])


async def _stage_answer(
    text: str,
    state: SessionState,
    layer: LayerSpec,
    vocabulary: dict[str, str],
    seq: int,
    deps: TurnDeps,
) -> tuple[InterpretationResult, str, _Reply]:
    gw, sid = deps.gateway, state.session.session_id
    stage_id = state.session.active_stage or layer.stages[0].stage_id
    progress = _progress(state, layer)
    t0 = time.monotonic()
    interpretation = await interpret(
        text,
        InterpretContext(
            layer_id=layer.layer_id,
            stage_id=stage_id,
            question=state.asked_questions[-1] if state.asked_questions else "",
        ),
        gw,
        deps.llms["interpreter"],
    )
    interp = interpretation.result
    _emit(
        deps,
        "interpreter",
        result=interp.model_dump(mode="json"),
        used_fallback=interpretation.used_fallback,
        dropped_facts=interpretation.dropped_facts,
        ms=_ms(t0),
    )
    layer_facts = (await gw.list_facts(ListFactsIn(session_id=sid, layer_id=layer.layer_id))).facts
    layer_gaps = (await gw.list_gaps(ListGapsIn(session_id=sid, layer_id=layer.layer_id))).gaps
    for fact in interp.facts:
        await gw.save_fact(
            SaveFactIn(
                session_id=sid,
                turn_seq=seq,
                layer_id=layer.layer_id,
                stage_id=stage_id,
                fact=fact,
                scores=interp,
            )
        )

    outcome = decide(
        StageState(
            layer_id=layer.layer_id,
            stage_id=stage_id,
            stage_ids=[s.stage_id for s in layer.stages],
            progress=progress,
            layer_has_hidden_or_blind=any(
                f.finding_area in ("hidden", "blind") for f in layer_facts
            ),
            open_gaps=[g for g in layer_gaps if g.status == "open"],
            resumed_gap_in_layer=any(g.status != "open" for g in layer_gaps),
        ),
        interp,
        deps.config,
    )
    _emit(
        deps,
        "conductor",
        stage_id=stage_id,
        decision=outcome.decision.model_dump(mode="json"),
        stage_status=outcome.stage_status,
        attempts=outcome.attempts,
        create_gap=outcome.create_gap,
        gap_reason=outcome.gap_reason,
        flag_for_review=outcome.flag_for_review,
    )
    current = progress[stage_id]
    await gw.update_stage_progress(
        UpdateStageProgressIn(
            session_id=sid,
            progress=current.model_copy(
                update={
                    "attempts": outcome.attempts,
                    "status": outcome.stage_status,
                    "flagged_for_review": current.flagged_for_review or outcome.flag_for_review,
                    "difficulty_signals": current.difficulty_signals + interp.difficulty_signals,
                }
            ),
        )
    )
    if outcome.create_gap:
        description = interp.gaps[0] if interp.gaps else outcome.gap_reason or "sem evidência"
        await gw.save_gap(
            SaveGapIn(
                session_id=sid,
                layer_id=layer.layer_id,
                stage_id=stage_id,
                description=description,
                origin="client_statement",
                reason=outcome.gap_reason or "sem evidência",
            )
        )

    decision = outcome.decision
    if decision.action == "synthesize":
        return interp, decision.action, await _synthesize(state, layer, deps)
    if decision.action == "resume_gap" and decision.gap_id:
        gap = next(g for g in layer_gaps if g.gap_id == decision.gap_id)
        _notify(deps, "planning")
        await gw.update_gap(UpdateGapIn(session_id=sid, gap_id=gap.gap_id, status="resumed"))
        reply = await _ask(
            state,
            layer,
            gap.source_stage,
            1,
            False,
            vocabulary,
            interp,
            deps,
            text,
            gap,
            mode="rescue_prompt",
        )
        await gw.update_session(UpdateSessionIn(session_id=sid, pending_gap_id=gap.gap_id))
        return interp, decision.action, reply

    next_stage = decision.next_stage_id or stage_id
    _notify(deps, "planning")
    try:
        reply = await _ask(
            state,
            layer,
            next_stage,
            decision.attempt,
            decision.offer_abc_options,
            vocabulary,
            interp,
            deps,
            text,
            mode=mode_for(
                decision.action,
                concreteness=interp.concreteness,
                relevance=interp.relevance,
            ),
        )
    except NoNewQuestionError:
        return interp, "synthesize", await _synthesize(state, layer, deps)
    await gw.update_session(UpdateSessionIn(session_id=sid, active_stage=next_stage))
    return interp, decision.action, reply


async def _resume_answer(
    text: str,
    state: SessionState,
    layer: LayerSpec,
    vocabulary: dict[str, str],
    seq: int,
    deps: TurnDeps,
) -> tuple[InterpretationResult, str, _Reply]:
    gw, sid = deps.gateway, state.session.session_id
    gap_id = state.session.pending_gap_id or ""
    gaps = (await gw.list_gaps(ListGapsIn(session_id=sid, layer_id=layer.layer_id))).gaps
    gap = next((g for g in gaps if g.gap_id == gap_id), None)
    stage_id = gap.source_stage if gap else (state.session.active_stage or "")
    t0 = time.monotonic()
    interpretation = await interpret(
        text,
        InterpretContext(
            layer_id=layer.layer_id,
            stage_id=stage_id,
            question=state.asked_questions[-1] if state.asked_questions else "",
        ),
        gw,
        deps.llms["interpreter"],
    )
    interp = interpretation.result
    _emit(
        deps,
        "interpreter",
        result=interp.model_dump(mode="json"),
        used_fallback=interpretation.used_fallback,
        dropped_facts=interpretation.dropped_facts,
        ms=_ms(t0),
    )
    fact_ids: list[str] = []
    for fact in interp.facts:
        saved = await gw.save_fact(
            SaveFactIn(
                session_id=sid,
                turn_seq=seq,
                layer_id=layer.layer_id,
                stage_id=stage_id,
                fact=fact,
                scores=interp,
            )
        )
        fact_ids.append(saved.fact_id)
    resume = decide_resume(interp, gap_id, deps.config)
    _emit(
        deps,
        "conductor",
        stage_id=stage_id,
        decision=resume.decision.model_dump(mode="json"),
        resumed_gap=gap_id,
        gap_status=resume.gap_status,
    )
    if gap is not None:
        resolved = resume.gap_status == "resolved" and fact_ids
        await gw.update_gap(
            UpdateGapIn(
                session_id=sid,
                gap_id=gap_id,
                status="resolved" if resolved else "kept_as_hypothesis",
                fact_id=fact_ids[0] if resolved else None,
            )
        )
    await gw.update_session(UpdateSessionIn(session_id=sid, clear=["pending_gap_id"]))
    return interp, resume.decision.action, await _synthesize(state, layer, deps)


async def _ask(
    state: SessionState,
    layer: LayerSpec,
    stage_id: str,
    attempt: int,
    offer_abc: bool,
    vocabulary: dict[str, str],
    interp: InterpretationResult,
    deps: TurnDeps,
    answer: str = "",
    gap: Gap | None = None,
    mode: Mode = "advance",
) -> _Reply:
    sid = state.session.session_id
    profile = business_profile(state.session, state.baseline)
    focus = entry_focus(
        deps.config.focus_on_stage_entry, stage_id, attempt, gap.description if gap else None
    )
    if focus is not None:  # an open question: options would narrow what she is about to tell
        offer_abc = False
    t0 = time.monotonic()
    investigation = await investigate(
        InvestigateContext(
            session_id=sid,
            layer_id=layer.layer_id,
            stage_id=stage_id,
            attempt=attempt,
            asked_questions=state.asked_questions,
            vocabulary=vocabulary,
            gap=gap.description if gap else None,
            profile=profile,
            focus=focus,
        ),
        deps.gateway,
        deps.llms["investigator"],
    )
    _emit(
        deps,
        "investigator",
        stage_id=stage_id,
        draft=investigation.draft.model_dump(mode="json"),
        used_fallback=investigation.used_fallback,
        retried=investigation.retried,
        ms=_ms(t0),
    )
    stage = next(s for s in layer.stages if s.stage_id == stage_id)
    position = LAYERS_ORDER.index(layer.layer_id) + 1
    _notify(deps, "writing")
    if offer_abc:  # PRD MOD-02: A and B must rest on facts she already gave
        facts = await deps.gateway.list_facts(ListFactsIn(session_id=sid, layer_id=layer.layer_id))
        offer_abc = bool(facts.facts)
    t0 = time.monotonic()
    moderation = await moderate(
        ModerateContext(
            session_id=sid,
            layer_id=layer.layer_id,
            stage_title=stage.title,
            draft=investigation.draft,
            attempt=attempt,
            offer_abc_options=offer_abc,
            last_answer=answer,
            sector=_sector(state),
            off_topic=interp.relevance <= OFF_TOPIC_RELEVANCE,
            difficulty_signals=interp.difficulty_signals,
            progress=f"camada {position} de 4, {stage.title}",
            mode=mode,
        ),
        deps.gateway,
        deps.llms["moderator"],
    )
    framed = moderation.message
    _emit(
        deps,
        "moderator",
        mode=mode,
        abc_offered=offer_abc,
        message=framed.model_dump(mode="json"),
        used_fallback=moderation.used_fallback,
        abc_dropped=moderation.abc_dropped,
        removed=list(moderation.removed),
        fallback_reason=moderation.fallback_reason,
        ms=_ms(t0),
    )
    used = "fallback" if investigation.used_fallback or moderation.used_fallback else None
    return _Reply(
        text="".join(iter_text(framed)),
        question=framed.question,
        abc=framed.abc_options,
        mode=used,
    )


async def _synthesize(state: SessionState, layer: LayerSpec, deps: TurnDeps) -> _Reply:
    gw, session = deps.gateway, state.session
    _notify(deps, "synthesizing")
    t0 = time.monotonic()
    result = await synthesize_layer(
        SynthesizeContext(
            session_id=session.session_id,
            layer_id=layer.layer_id,
            profile=business_profile(session, state.baseline),
        ),
        gw,
        deps.llms["synthesizer"],
    )
    _emit(
        deps,
        "synthesizer",
        synthesis=result.synthesis.model_dump(mode="json"),
        used_fallback=result.used_fallback,
        fallback_reason=result.fallback_reason,
        ms=_ms(t0),
    )
    await gw.save_synthesis(
        SaveSynthesisIn(session_id=session.session_id, synthesis=result.synthesis)
    )
    pos = next_position(
        Position(status="in_layer", active_layer=layer.layer_id),
        "layer_synthesized",
        layer_review_enabled=deps.config.layer_review_enabled,
    )
    first_stage: str | None = None
    if pos.status == "in_layer" and pos.active_layer is not None:
        next_layer = await gw.get_layer_spec(GetLayerSpecIn(layer_id=pos.active_layer))
        first_stage = next_layer.stages[0].stage_id
    await gw.update_session(
        UpdateSessionIn(
            session_id=session.session_id,
            status=pos.status,
            active_layer=pos.active_layer,
            active_stage=first_stage,
            clear=[] if pos.active_layer else ["active_layer", "active_stage"],
        )
    )
    message = closing_message(result.synthesis.content) if not result.used_fallback else LAYER_DONE
    return _Reply(message, mode="synthesis", deliverable=result.synthesis)


async def _guard_output(
    reply: _Reply,
    layer: LayerSpec,
    vocabulary: dict[str, str],
    deps: TurnDeps,
    state: SessionState,
) -> _Reply:
    checked = await deps.guardrails.check_output(reply.text)
    if checked.allowed:
        return reply
    refreshed = await deps.gateway.get_session_state(
        GetSessionStateIn(session_id=state.session.session_id)
    )
    stage_id = refreshed.session.active_stage or layer.stages[0].stage_id
    pool = await deps.gateway.get_question_from_pool(GetQuestionFromPoolIn(stage_id=stage_id))
    safe = fill_placeholders(pool.anchors[0].question, vocabulary)
    return _Reply(safe, question=safe, mode="safe_anchor")


async def _save_turn(
    gw: ToolGateway,
    session_id: str,
    seq: int,
    user_message: str,
    reply: _Reply,
    decision: str | None,
    interp: InterpretationResult | None,
    started: float,
) -> None:
    turn = Turn.model_validate(
        {
            "seq": seq,
            "user_message": user_message,
            "question_asked": reply.question,
            "decision": decision,
            "mode": reply.mode,
            "abc_options": reply.abc,
            "scores": (
                {
                    "concreteness": interp.concreteness,
                    "relevance": interp.relevance,
                    "defensibility": interp.defensibility,
                    "domain_fit": interp.domain_fit,
                }
                if interp
                else None
            ),
            "difficulty_signals": interp.difficulty_signals if interp else [],
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
    )
    await gw.save_turn(SaveTurnIn(session_id=session_id, turn=turn))


def _stream(session_id: str, reply: _Reply, seq: int) -> list[ServerEvent]:
    words = reply.text.split(" ")
    events: list[ServerEvent] = [
        TokenEvent(session_id=session_id, text=w if i == len(words) - 1 else w + " ")
        for i, w in enumerate(words)
    ]
    events.append(
        MessageDoneEvent(
            session_id=session_id, message=reply.text, turn_seq=seq, abc_options=reply.abc
        )
    )
    return events


def _progress(state: SessionState, layer: LayerSpec) -> dict[str, StageProgress]:
    known = {p.stage_id: p for p in state.progress}
    return {
        s.stage_id: known.get(s.stage_id)
        or StageProgress(stage_id=s.stage_id, layer_id=layer.layer_id)
        for s in layer.stages
    }


def _vocabulary(state: SessionState) -> dict[str, str]:
    answers = state.session.onboarding
    if answers is None:
        return {}
    pairs = {
        "seu_trabalho": answers.offer,
        "sua_oferta": answers.offer,
        "a_cliente": answers.audience,
        "as_clientes": answers.audience,
        "setor": answers.business_type,
    }
    return {k: v for k, v in pairs.items() if v}


def _sector(state: SessionState) -> str:
    answers = state.session.onboarding
    return (answers.business_type if answers else None) or ""
