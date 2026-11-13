"""Onboarding (PRD steps 1–2, US01–US03): consent, quick choices, baseline, first question.

Nothing about her is stored before consent: the session record exists (status, retention date)
but onboarding answers and the baseline are rejected until `consent_at` is set. The baseline is
stored exactly as typed. After it, the session enters the first layer and the first question is
the first anchor of the first stage, filled with her own words.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from vv_contracts.common import LAYERS_ORDER
from vv_contracts.ports import ToolGateway
from vv_contracts.state import OnboardingAnswers, Session, Turn
from vv_contracts.tools import (
    CreateSessionIn,
    GetLayerSpecIn,
    GetSessionStateIn,
    SaveBaselineIn,
    SaveTurnIn,
    UpdateSessionIn,
)
from vv_contracts.ws import (
    ClientMessage,
    Consent,
    ErrorEvent,
    MessageDoneEvent,
    OnboardingAnswer,
    OnboardingStepEvent,
    ServerEvent,
    StartSession,
    StateEvent,
    TokenEvent,
    UserMessage,
)

from vv_chat.business import opening_question

CONFIG = Path(__file__).resolve().parents[3] / "config" / "onboarding.yaml"
NEEDS_CONSENT = 'Para seguir, preciso do seu consentimento. Toque em "Concordo" para começar.'
REFUSED = "Tudo bem. Nada do que você contou foi guardado. Se mudar de ideia, é só começar de novo."
UNKNOWN_FIELD = "Não reconheci essa resposta. Pode responder a pergunta da tela?"
LIST_FIELDS = {"channels", "declared_links"}
SKIP_VALUES = {"Pular", "Não tenho / pular"}


def load_onboarding(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class OnboardingFlow:
    def __init__(self, gateway: ToolGateway, config: dict[str, Any] | None = None) -> None:
        self.gw = gateway
        self.cfg = config or load_onboarding()
        self.steps: list[dict[str, Any]] = self.cfg["steps"]
        self.fields = [s["field"] for s in self.steps]

    async def handle(self, msg: ClientMessage) -> AsyncIterator[ServerEvent]:
        if isinstance(msg, StartSession):
            sid = (await self.gw.create_session(CreateSessionIn())).session_id
            yield StateEvent(session_id=sid, status="onboarding")
            yield self._consent_step(sid)
            return
        if isinstance(msg, Consent):
            async for e in self._consent(msg):
                yield e
            return
        if isinstance(msg, OnboardingAnswer):
            async for e in self._answer(msg.session_id, msg.field, msg.value):
                yield e
            return
        if isinstance(msg, UserMessage):  # baseline typed in the chat box
            async for e in self._answer(msg.session_id, "baseline", msg.text):
                yield e

    async def _session(self, sid: str) -> Session:
        return (await self.gw.get_session_state(GetSessionStateIn(session_id=sid))).session

    async def _consent(self, msg: Consent) -> AsyncIterator[ServerEvent]:
        sid = msg.session_id
        if not msg.accepted:
            for e in _say(sid, REFUSED, 0):
                yield e
            return
        await self.gw.update_session(UpdateSessionIn(session_id=sid, consent_at=datetime.now(UTC)))
        yield self._step(sid, 0)

    async def _answer(
        self, sid: str, field: str, value: str | list[str]
    ) -> AsyncIterator[ServerEvent]:
        session = await self._session(sid)
        if session.consent_at is None:
            yield ErrorEvent(session_id=sid, code="consent_required", message=NEEDS_CONSENT)
            return
        if field == "baseline":
            async for e in self._baseline(session, value):
                yield e
            return
        if field not in self.fields:
            yield ErrorEvent(session_id=sid, code="unknown_field", message=UNKNOWN_FIELD)
            return
        answers = (session.onboarding or OnboardingAnswers()).model_dump()
        answers[field] = _normalize(field, value)
        await self.gw.update_session(
            UpdateSessionIn(session_id=sid, onboarding=OnboardingAnswers.model_validate(answers))
        )
        index = self.fields.index(field) + 1
        if index < len(self.fields):
            yield self._step(sid, index)
            return
        await self.gw.update_session(UpdateSessionIn(session_id=sid, status="baseline"))
        yield StateEvent(session_id=sid, status="baseline")
        yield OnboardingStepEvent(
            session_id=sid,
            field="baseline",
            question=self.cfg["baseline"]["question"],
            free_text=True,
            step=len(self.fields) + 1,
            total=len(self.fields) + 1,
        )

    async def _baseline(
        self, session: Session, value: str | list[str]
    ) -> AsyncIterator[ServerEvent]:
        sid = session.session_id
        statement = value if isinstance(value, str) else " ".join(value)
        await self.gw.save_baseline(SaveBaselineIn(session_id=sid, statement=statement))
        layer_id = LAYERS_ORDER[0]
        layer = await self.gw.get_layer_spec(GetLayerSpecIn(layer_id=layer_id))
        stage = layer.stages[0]
        await self.gw.update_session(
            UpdateSessionIn(
                session_id=sid,
                status="in_layer",
                active_layer=layer_id,
                active_stage=stage.stage_id,
            )
        )
        question = opening_question(session.onboarding, stage.anchors[0].question)
        await self.gw.save_turn(
            SaveTurnIn(session_id=sid, turn=Turn(seq=1, user_message="", question_asked=question))
        )
        yield StateEvent(session_id=sid, status="in_layer", active_layer=layer_id, layer_index=1)
        for e in _say(sid, question, 1):
            yield e

    def _consent_step(self, sid: str) -> OnboardingStepEvent:
        c = self.cfg["consent"]
        return OnboardingStepEvent(
            session_id=sid,
            field="consent",
            question=c["question"].strip(),
            options=list(c["options"]),
            step=1,
            total=1,
        )

    def _step(self, sid: str, index: int) -> OnboardingStepEvent:
        s = self.steps[index]
        return OnboardingStepEvent(
            session_id=sid,
            field=s["field"],
            question=s["question"].strip(),
            options=list(s.get("options", [])),
            multiple=bool(s.get("multiple", False)),
            free_text=bool(s.get("free_text", False)),
            step=index + 1,
            total=len(self.steps) + 1,
        )


def _normalize(field: str, value: str | list[str]) -> str | list[str] | None:
    values = [value] if isinstance(value, str) else value
    values = [v.strip() for v in values if v.strip() and v.strip() not in SKIP_VALUES]
    if field in LIST_FIELDS:
        return values
    return " ".join(values) or None


def _say(sid: str, text: str, seq: int) -> list[ServerEvent]:
    words = text.split(" ")
    events: list[ServerEvent] = [
        TokenEvent(session_id=sid, text=w if i == len(words) - 1 else w + " ")
        for i, w in enumerate(words)
    ]
    events.append(MessageDoneEvent(session_id=sid, message=text, turn_seq=seq))
    return events
