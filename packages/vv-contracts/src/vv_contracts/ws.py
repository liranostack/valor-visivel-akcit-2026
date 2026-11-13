"""WebSocket protocol between frontend, backend and chat-service.

Mirrored in frontend/lib/ws.ts.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, TypeAdapter, model_validator

from vv_contracts.agents import AbcOption
from vv_contracts.common import LayerId, NonEmptyStr, ReviewIntent, ReviewTarget
from vv_contracts.state import SessionStatus

# --- client -> server --------------------------------------------------------------------------


class StartSession(BaseModel):
    type: Literal["start_session"] = "start_session"


class Consent(BaseModel):
    type: Literal["consent"] = "consent"
    session_id: NonEmptyStr
    accepted: bool


class OnboardingAnswer(BaseModel):
    type: Literal["onboarding_answer"] = "onboarding_answer"
    session_id: NonEmptyStr
    field: NonEmptyStr
    value: str | list[str]


class UserMessage(BaseModel):
    type: Literal["user_message"] = "user_message"
    session_id: NonEmptyStr
    text: NonEmptyStr


class ReviewAction(BaseModel):
    type: Literal["review_action"] = "review_action"
    session_id: NonEmptyStr
    target: ReviewTarget
    intent: ReviewIntent
    notes: str = ""


ClientMessage = Annotated[
    StartSession | Consent | OnboardingAnswer | UserMessage | ReviewAction,
    Field(discriminator="type"),
]
CLIENT_MESSAGE_ADAPTER: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


def parse_client_message(raw: str | bytes) -> ClientMessage:
    return CLIENT_MESSAGE_ADAPTER.validate_json(raw)


# --- server -> client --------------------------------------------------------------------------


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    session_id: NonEmptyStr
    text: str


class MessageDoneEvent(BaseModel):
    type: Literal["message_done"] = "message_done"
    session_id: NonEmptyStr
    message: str
    turn_seq: int = Field(ge=0)
    abc_options: list[AbcOption] | None = None


class StateEvent(BaseModel):
    type: Literal["state"] = "state"
    session_id: NonEmptyStr
    status: SessionStatus
    active_layer: LayerId | None = None
    layer_index: int | None = Field(default=None, ge=1, le=4)  # "camada n de 4"


class DeliverableEvent(BaseModel):
    type: Literal["deliverable"] = "deliverable"
    session_id: NonEmptyStr
    kind: Literal["layer_synthesis", "pre_core", "core"]
    layer_id: LayerId | None = None
    content: dict[str, object] = Field(default_factory=dict[str, object])


class OnboardingStepEvent(BaseModel):
    """One onboarding question; the UI shows options as buttons and, if allowed, a text field.

    The answer comes back as OnboardingAnswer(field, value); `consent` is answered with Consent.
    """

    type: Literal["onboarding_step"] = "onboarding_step"
    session_id: NonEmptyStr
    field: NonEmptyStr  # OnboardingAnswers field, or "consent" / "baseline"
    question: NonEmptyStr  # pt-BR
    options: list[str] = Field(default_factory=list[str])
    multiple: bool = False  # more than one option can be chosen
    free_text: bool = False  # a text field is offered (alone or with the options)
    step: int = Field(ge=1)
    total: int = Field(ge=1)

    @model_validator(mode="after")
    def _answerable(self) -> Self:
        if not self.options and not self.free_text:
            raise ValueError("an onboarding step needs options or free text")
        return self


ProgressStep = Literal["reading", "planning", "writing", "synthesizing"]


class ProgressEvent(BaseModel):
    """A step of the turn while the reply is not ready; the UI shows `message` as an indicator."""

    type: Literal["progress"] = "progress"
    session_id: NonEmptyStr
    step: ProgressStep
    message: NonEmptyStr  # pt-BR


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    session_id: str | None = None
    code: NonEmptyStr
    message: str  # pt-BR, safe to show; never a stack trace


ServerEvent = Annotated[
    TokenEvent
    | MessageDoneEvent
    | StateEvent
    | DeliverableEvent
    | OnboardingStepEvent
    | ProgressEvent
    | ErrorEvent,
    Field(discriminator="type"),
]
SERVER_EVENT_ADAPTER: TypeAdapter[ServerEvent] = TypeAdapter(ServerEvent)


def parse_server_event(raw: str | bytes) -> ServerEvent:
    return SERVER_EVENT_ADAPTER.validate_json(raw)


def dump_server_event(event: ServerEvent) -> str:
    return SERVER_EVENT_ADAPTER.dump_json(event).decode()
