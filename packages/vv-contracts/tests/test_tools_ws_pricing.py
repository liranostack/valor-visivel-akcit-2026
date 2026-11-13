import pytest
from pydantic import ValidationError
from vv_contracts import ports, pricing, tools, ws


class TestTools:
    def test_update_gap_resolved_requires_fact(self) -> None:
        with pytest.raises(ValidationError):
            tools.UpdateGapIn(session_id="s", gap_id="g", status="resolved")
        assert tools.UpdateGapIn(session_id="s", gap_id="g", status="resolved", fact_id="f").fact_id

    def test_every_erd_tool_has_input_model(self) -> None:
        expected = {
            "create_session",
            "update_session",
            "save_baseline",
            "save_public_context",
            "get_session_state",
            "save_turn",
            "update_stage_progress",
            "save_fact",
            "list_facts",
            "save_gap",
            "list_gaps",
            "update_gap",
            "get_layer_spec",
            "get_question_from_pool",
            "get_synthesis_template",
            "get_method_guide",
            "save_synthesis",
            "save_review",
            "save_pre_core",
            "save_core",
            "check_output",
            "read_public_site",
        }
        assert set(tools.TOOL_INPUTS) == expected

    def test_read_public_site_out_round_trip(self) -> None:
        out = tools.ReadPublicSiteOut(
            outcome="ok",
            url="https://exemplo.com.br",
            title="Studio",
            text="Massoterapia",
            html_bytes=1000,
            extracted_tokens=10,
            budget_tokens=2000,
        )
        assert tools.ReadPublicSiteOut.model_validate_json(out.model_dump_json()) == out

    def test_check_output_violation_kinds(self) -> None:
        v = tools.Violation(kind="unsourced_number", excerpt="90%", message="sem fonte")
        assert tools.CheckOutputOut(violations=[v]).violations[0].kind == "unsourced_number"


class TestSessionTools:
    def test_update_session_is_a_patch(self) -> None:
        req = tools.UpdateSessionIn(session_id="s", status="in_layer", active_layer="clarity")
        assert req.patch() == {"status": "in_layer", "active_layer": "clarity"}

    def test_update_session_can_clear_a_field(self) -> None:
        req = tools.UpdateSessionIn(session_id="s", clear=["pending_gap_id"])
        assert req.patch() == {"pending_gap_id": None}

    def test_session_has_pending_gap(self) -> None:
        from vv_contracts.state import Session

        assert Session(session_id="s", status="in_layer").pending_gap_id is None


class TestPorts:
    def test_protocols_exist(self) -> None:
        for name in ("StateRepository", "KnowledgeBase", "ToolGateway"):
            assert hasattr(ports, name)

    def test_tool_gateway_covers_every_tool(self) -> None:
        missing = [t for t in tools.TOOL_INPUTS if not hasattr(ports.ToolGateway, t)]
        assert missing == []


class TestWebSocket:
    def test_parse_user_message(self) -> None:
        msg = ws.parse_client_message('{"type": "user_message", "session_id": "s1", "text": "oi"}')
        assert isinstance(msg, ws.UserMessage)
        assert msg.text == "oi"

    def test_parse_start_session(self) -> None:
        assert isinstance(ws.parse_client_message(b'{"type": "start_session"}'), ws.StartSession)

    def test_unknown_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ws.parse_client_message('{"type": "hack"}')

    def test_empty_user_message_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ws.parse_client_message('{"type": "user_message", "session_id": "s1", "text": ""}')

    def test_server_event_round_trip(self) -> None:
        events: list[ws.ServerEvent] = [
            ws.TokenEvent(session_id="s1", text="Olá"),
            ws.MessageDoneEvent(session_id="s1", message="Olá?", turn_seq=1),
            ws.StateEvent(
                session_id="s1", status="in_layer", active_layer="clarity", layer_index=1
            ),
            ws.DeliverableEvent(session_id="s1", kind="layer_synthesis", layer_id="clarity"),
            ws.ErrorEvent(session_id=None, code="bad_request", message="Mensagem inválida"),
            ws.OnboardingStepEvent(
                session_id="s1",
                field="business_structure",
                question="Como seu negócio está organizado hoje?",
                options=["Autônoma, sem CNPJ", "MEI"],
                multiple=False,
                free_text=True,
                step=2,
                total=9,
            ),
        ]
        for event in events:
            raw = ws.dump_server_event(event)
            assert ws.parse_server_event(raw) == event

    def test_onboarding_step_needs_options_or_free_text(self) -> None:
        with pytest.raises(ValidationError):
            ws.OnboardingStepEvent(
                session_id="s1",
                field="goal",
                question="?",
                options=[],
                free_text=False,
                step=1,
                total=1,
            )

    def test_progress_event_round_trip(self) -> None:
        event = ws.ProgressEvent(session_id="s1", step="reading", message="Lendo sua resposta…")
        assert ws.parse_server_event(ws.dump_server_event(event)) == event

    def test_progress_step_is_closed(self) -> None:
        with pytest.raises(ValidationError):
            ws.ProgressEvent(session_id="s1", step="anything", message="x")  # type: ignore[arg-type]

    def test_layer_index_1_to_4(self) -> None:
        with pytest.raises(ValidationError):
            ws.StateEvent(session_id="s1", status="in_layer", active_layer="clarity", layer_index=5)


class TestPricing:
    def test_haiku_and_sonnet(self) -> None:
        haiku = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        sonnet = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        assert pricing.cost_usd(haiku, 1_000_000, 0) == pytest.approx(1.0)
        assert pricing.cost_usd(haiku, 0, 1_000_000) == pytest.approx(5.0)
        assert pricing.cost_usd(sonnet, 1_000_000, 1_000_000) == pytest.approx(18.0)

    def test_cache_read_is_10_percent(self) -> None:
        sonnet = "anthropic.claude-sonnet-4-5-20250929-v1:0"
        cost = pricing.cost_usd(sonnet, 0, 0, cache_read_tokens=1_000_000)
        assert cost == pytest.approx(0.3)

    def test_unknown_model(self) -> None:
        with pytest.raises(pricing.UnknownModelError):
            pricing.cost_usd("acme.model", 1, 1)

    def test_negative_tokens(self) -> None:
        with pytest.raises(ValueError):
            pricing.cost_usd("anthropic.claude-haiku-4-5", -1, 0)


def test_framed_message_reads_empty_options_as_none() -> None:
    from vv_contracts.agents import FramedMessage

    assert FramedMessage(context_line=None, question="Q?", abc_options=[]).abc_options is None


def test_framed_message_without_context_line() -> None:
    # The Moderator is told to leave it out; the model then omits the field (round 3, A.06.12).
    from vv_contracts.agents import FramedMessage

    assert FramedMessage.model_validate({"question": "Q?"}).context_line is None


def test_question_draft_declares_what_it_goes_after() -> None:
    from vv_contracts.agents import QuestionDraft

    draft = QuestionDraft(question="Q?", angle="limit", target="commitments")
    assert draft.target == "commitments"
    assert QuestionDraft(question="Q?", angle="limit").target is None
