"""AgentCore Runtime (HTTP) app: POST /invocations streams ServerEvents as SSE, GET /ping.

The backend worker posts one ClientMessage (vv_contracts.ws) per invocation. The turn handler
yields ServerEvents; any failure becomes an ErrorEvent with a safe pt-BR message, never a
stack trace. `turn_handler` sends onboarding messages (start, consent, answers, baseline) to the
onboarding flow and answers inside a layer to the turn loop; reviews arrive with A.04.03.
"""

import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic import ValidationError
from vv_contracts.ws import (
    CLIENT_MESSAGE_ADAPTER,
    ClientMessage,
    ErrorEvent,
    MessageDoneEvent,
    ReviewAction,
    ServerEvent,
    TokenEvent,
    UserMessage,
)

log = logging.getLogger(__name__)

TurnHandler = Callable[[ClientMessage], AsyncIterator[ServerEvent]]

INVALID_MESSAGE = "Não entendi essa mensagem. Pode tentar de novo?"
TURN_FAILED = "Tive um problema agora. Pode repetir sua última resposta?"


def _session_of(msg: ClientMessage) -> str | None:
    return getattr(msg, "session_id", None)


async def placeholder_handler(msg: ClientMessage) -> AsyncIterator[ServerEvent]:
    """Answers with a fixed pt-BR message so the deploy can be smoke-tested before A.04.01."""
    session_id = _session_of(msg) or "new"
    text = "Olá! O Valor Visível está no ar."
    for word in text.split(" "):
        yield TokenEvent(session_id=session_id, text=word + " ")
    yield MessageDoneEvent(session_id=session_id, message=text, turn_seq=0)


async def turn_handler(msg: ClientMessage) -> AsyncIterator[ServerEvent]:  # pragma: no cover
    """Production handler: onboarding messages go to the onboarding flow, answers in a layer to
    the turn loop. Gateway, Bedrock models and guardrails come from the environment."""
    from vv_contracts.tools import GetSessionStateIn

    from vv_chat.agents.llm import StrandsLLM
    from vv_chat.conductor.config import load_config
    from vv_chat.flows.onboarding import OnboardingFlow
    from vv_chat.flows.review import ReviewFlow
    from vv_chat.gateway.factory import open_gateway
    from vv_chat.guardrails import from_env
    from vv_chat.models import make_model
    from vv_chat.turn import TurnDeps, run_turn

    async with open_gateway() as gateway:
        onboarding = OnboardingFlow(gateway)
        review = ReviewFlow(gateway, StrandsLLM(make_model("synthesizer")), from_env())
        if isinstance(msg, UserMessage):
            state = await gateway.get_session_state(GetSessionStateIn(session_id=msg.session_id))
            if state.session.status == "layer_review":  # revisão do mapa: text adjusts the map
                action = await review.from_text(msg.session_id, msg.text)
                if action is not None:
                    async for event in review.handle(action):
                        yield event
                    return
            if state.session.status != "baseline":
                deps = TurnDeps(
                    gateway=gateway,
                    llms={
                        "interpreter": StrandsLLM(make_model("interpreter")),
                        "investigator": StrandsLLM(make_model("investigator")),
                        "moderator": StrandsLLM(make_model("moderator")),
                        "synthesizer": StrandsLLM(make_model("synthesizer")),
                    },
                    guardrails=from_env(),
                    config=load_config(),
                )
                async for event in run_turn(msg.session_id, msg.text, deps):
                    yield event
                return
        if isinstance(msg, ReviewAction):
            async for event in review.handle(msg):
                yield event
            return
        async for event in onboarding.handle(msg):
            yield event


def _dump(event: ServerEvent) -> dict[str, Any]:
    return event.model_dump(mode="json")


def build_app(handler: TurnHandler) -> BedrockAgentCoreApp:
    app = BedrockAgentCoreApp()

    @app.entrypoint
    async def invoke(payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        try:
            msg = CLIENT_MESSAGE_ADAPTER.validate_python(payload)
        except ValidationError:
            yield _dump(ErrorEvent(code="bad_request", message=INVALID_MESSAGE))
            return
        try:
            async for event in handler(msg):
                yield _dump(event)
        except Exception:  # never leak internals to the client
            log.exception("turn failed")
            yield _dump(
                ErrorEvent(session_id=_session_of(msg), code="turn_failed", message=TURN_FAILED)
            )

    return app


app = build_app(turn_handler)

if __name__ == "__main__":  # pragma: no cover
    app.run()
