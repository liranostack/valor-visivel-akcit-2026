"""revisão do mapa (lead, 12/11): at the end of each layer the journey pauses until she
approves the factual map or asks for an adjustment (A.06.15).

- approve: the review is recorded; the next layer opens when its content exists in the KB.
  When the last layer (sustainment) is approved, the Essential Core is generated instead.
- adjust / doubt: her words become a correction the Synthesizer must apply; the map is rewritten
  from the same facts plus the correction, and the pause continues until she approves.
- Free text typed during the pause is an adjustment with that text as the notes.
"""

import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator

from vv_contracts.common import LAYERS_ORDER, LayerId
from vv_contracts.ports import ToolGateway
from vv_contracts.state import EssentialCore, Turn
from vv_contracts.tools import (
    GetLayerSpecIn,
    GetSessionStateIn,
    SaveCoreIn,
    SaveReviewIn,
    SaveSynthesisIn,
    SaveTurnIn,
    UpdateSessionIn,
)
from vv_contracts.ws import (
    DeliverableEvent,
    MessageDoneEvent,
    ReviewAction,
    ServerEvent,
    StateEvent,
    TokenEvent,
)

from vv_chat.agents.core_synthesizer import CoreContext, synthesize_core
from vv_chat.agents.llm import StructuredLLM
from vv_chat.agents.synthesizer import SynthesizeContext, synthesize_layer
from vv_chat.business import business_profile, map_reading
from vv_chat.turn import Guardrails

log = logging.getLogger(__name__)

APPROVED = (
    "Mapa aprovado. Ele fica guardado como a base das próximas partes, que aprofundam o que "
    "torna o seu trabalho único e como contar isso para quem compra."
)
APPROVED_LAST = (
    "Mapa aprovado. Estou gerando o seu Núcleo Essencial com tudo o que levantamos nas quatro "
    "partes. Um momento."
)
CORE_DONE = (
    "Pronto. O Núcleo Essencial está ao lado com a síntese completa da jornada, os materiais "
    "prontos para usar e o plano de sete dias."
)
ADJUST_ASK = (
    "O que não está fiel ao que você contou? Escreva com as suas palavras que eu ajusto o mapa."
)
ADJUSTED_TAIL = "Ajustei o mapa com o que você disse. Confira ao lado e aprove quando estiver fiel."
NOTHING_TO_REVIEW = "Ainda não há um mapa para revisar. Vamos seguir a conversa?"
REVIEW_ID = "review"


class ReviewFlow:
    def __init__(
        self,
        gateway: ToolGateway,
        synthesizer: StructuredLLM,
        guardrails: Guardrails,
        core_synthesizer: StructuredLLM | None = None,
    ) -> None:
        self.gateway = gateway
        self.synthesizer = synthesizer
        self.guardrails = guardrails
        self.core_synthesizer = core_synthesizer or synthesizer

    async def from_text(self, session_id: str, text: str) -> ReviewAction | None:
        """Free text typed while the map waits for approval is an adjustment."""
        state = await self.gateway.get_session_state(GetSessionStateIn(session_id=session_id))
        session = state.session
        if session.status != "layer_review" or session.active_layer is None:
            return None
        return ReviewAction(
            session_id=session_id, target=session.active_layer, intent="adjust", notes=text
        )

    async def handle(self, msg: ReviewAction) -> AsyncIterator[ServerEvent]:
        sid = msg.session_id
        state = await self.gateway.get_session_state(GetSessionStateIn(session_id=sid))
        session = state.session
        seq = state.last_turn_seq + 1
        layer = session.active_layer
        if session.status != "layer_review" or layer is None or layer != msg.target:
            for event in _say(sid, NOTHING_TO_REVIEW, seq):
                yield event
            return

        notes = msg.notes.strip()
        if notes:
            checked = await self.guardrails.check_input(notes)
            if not checked.allowed:
                for event in _say(sid, checked.message_if_blocked or ADJUST_ASK, seq):
                    yield event
                return
            notes = checked.text

        if msg.intent == "approve":
            await self.gateway.save_review(
                SaveReviewIn(session_id=sid, target=msg.target, intent="approve", notes=notes)
            )
            is_last = LAYERS_ORDER.index(layer) + 1 >= len(LAYERS_ORDER)
            approve_msg = APPROVED_LAST if is_last else APPROVED
            await self._save_turn(sid, seq, "[aprovou o mapa]", approve_msg)
            for event in _say(sid, approve_msg, seq):
                yield event
            if is_last:
                async for event in self._generate_core(sid, seq + 1):
                    yield event
            else:
                await self._open_next_layer(sid, layer)
            return

        if not notes:
            for event in _say(sid, ADJUST_ASK, seq):
                yield event
            return

        await self.gateway.save_review(
            SaveReviewIn(session_id=sid, target=msg.target, intent=msg.intent, notes=notes)
        )
        profile = business_profile(session, state.baseline) | {
            REVIEW_ID: (
                "her correction to the previous version of this map (apply it; it is her word "
                f"and can be cited): {notes}"
            )
        }
        t0 = time.monotonic()
        result = await synthesize_layer(
            SynthesizeContext(session_id=sid, layer_id=layer, profile=profile),
            self.gateway,
            self.synthesizer,
        )
        log.info("review: map rewritten in %d ms", int((time.monotonic() - t0) * 1000))
        await self.gateway.save_synthesis(
            SaveSynthesisIn(session_id=sid, synthesis=result.synthesis)
        )
        reading = map_reading(result.synthesis.content)
        message = f"{reading}\n\n{ADJUSTED_TAIL}" if reading else ADJUSTED_TAIL
        await self._save_turn(sid, seq, notes, message)
        yield DeliverableEvent(
            session_id=sid,
            kind="layer_synthesis",
            layer_id=layer,
            content=result.synthesis.model_dump(mode="json"),
        )
        for event in _say(sid, message, seq):
            yield event
        yield StateEvent(
            session_id=sid,
            status="layer_review",
            active_layer=layer,
            layer_index=LAYERS_ORDER.index(layer) + 1,
        )

    async def _open_next_layer(self, sid: str, layer: LayerId) -> None:
        """Opens the next layer when its KB spec exists."""
        position = LAYERS_ORDER.index(layer)
        if position + 1 >= len(LAYERS_ORDER):
            return
        nxt = LAYERS_ORDER[position + 1]
        try:
            spec = await self.gateway.get_layer_spec(GetLayerSpecIn(layer_id=nxt))
        except Exception:  # spec not in KB yet: stay on the approved map
            return
        await self.gateway.update_session(
            UpdateSessionIn(
                session_id=sid,
                status="in_layer",
                active_layer=nxt,
                active_stage=spec.stages[0].stage_id,
            )
        )

    async def _generate_core(self, sid: str, seq: int) -> AsyncGenerator[ServerEvent, None]:
        """Generate the Essential Core after the last layer (sustainment) is approved."""
        t0 = time.monotonic()
        state = await self.gateway.get_session_state(GetSessionStateIn(session_id=sid))
        profile = business_profile(state.session, state.baseline)
        try:
            result = await synthesize_core(
                CoreContext(session_id=sid, profile=profile),
                self.gateway,
                self.core_synthesizer,
            )
        except Exception as exc:
            log.error("core generation failed: %s", exc)
            for event in _say(sid, CORE_DONE, seq):
                yield event
            await self.gateway.update_session(UpdateSessionIn(session_id=sid, status="completed"))
            return
        log.info(
            "core: generated in %d ms (fallback=%s)",
            int((time.monotonic() - t0) * 1000),
            result.used_fallback,
        )
        core = EssentialCore(**result.core.model_dump())
        await self.gateway.save_core(SaveCoreIn(session_id=sid, core=core))
        await self.gateway.update_session(
            UpdateSessionIn(
                session_id=sid, status="completed", clear=["active_layer", "active_stage"]
            )
        )
        await self._save_turn(sid, seq, "[núcleo gerado]", CORE_DONE)
        yield DeliverableEvent(
            session_id=sid,
            kind="core",
            content=result.core.model_dump(mode="json"),
        )
        for event in _say(sid, CORE_DONE, seq):
            yield event
        yield StateEvent(session_id=sid, status="completed")

    async def _save_turn(self, sid: str, seq: int, said: str, reply: str) -> None:
        await self.gateway.save_turn(
            SaveTurnIn(
                session_id=sid,
                turn=Turn(seq=seq, user_message=said, question_asked=reply, mode="review"),
            )
        )


def _say(session_id: str, text: str, seq: int) -> list[ServerEvent]:
    events: list[ServerEvent] = [
        TokenEvent(session_id=session_id, text=word + " ") for word in text.split(" ")
    ]
    events.append(MessageDoneEvent(session_id=session_id, message=text, turn_seq=seq))
    return events
