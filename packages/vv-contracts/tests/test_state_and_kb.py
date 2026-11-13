from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from vv_contracts import keys
from vv_contracts.kb import LayerSpec, StageSpec
from vv_contracts.state import RETENTION_DAYS, Gap, Session, StageProgress, retention_until


class TestKeys:
    def test_pk(self) -> None:
        assert keys.pk("abc") == "SESSION#abc"

    def test_fixed_sks(self) -> None:
        assert (keys.SK_META, keys.SK_BASELINE, keys.SK_CONTEXT) == ("META", "BASELINE", "CONTEXT")
        assert (keys.SK_PRECORE, keys.SK_CORE) == ("PRECORE", "CORE")

    def test_sortable_sks(self) -> None:
        assert keys.sk_turn(7) == "TURN#000007"
        assert keys.sk_turn(10) > keys.sk_turn(9)
        assert keys.sk_synthesis("clarity", 2) == "SYN#clarity#v0002"
        assert keys.sk_synthesis("clarity", 10) > keys.sk_synthesis("clarity", 9)
        assert keys.sk_eval(3, "conciseness") == "EVAL#000003#conciseness"

    def test_entity_sks_and_prefixes(self) -> None:
        assert keys.sk_progress("clarity.real_context") == "PROG#clarity.real_context"
        assert keys.sk_fact("singularity", "f1") == "FACT#singularity#f1"
        assert keys.sk_gap("clarity", "g1") == "GAP#clarity#g1"
        assert keys.fact_prefix() == "FACT#"
        assert keys.fact_prefix("clarity") == "FACT#clarity#"
        assert keys.gap_prefix("clarity") == "GAP#clarity#"
        assert keys.gap_prefix() == "GAP#"
        assert keys.synthesis_prefix("translation") == "SYN#translation#"
        assert keys.TURN_PREFIX == "TURN#"
        assert keys.PROGRESS_PREFIX == "PROG#"

    def test_negative_numbers_rejected(self) -> None:
        with pytest.raises(ValueError):
            keys.sk_turn(-1)


class TestState:
    def test_retention_is_30_days(self) -> None:
        now = datetime(2026, 11, 13, tzinfo=UTC)
        assert RETENTION_DAYS == 30
        assert retention_until(now) == now + timedelta(days=30)

    def test_session_defaults(self) -> None:
        s = Session(session_id="s1", status="onboarding")
        assert s.active_layer is None and s.onboarding is None

    def test_resolved_gap_needs_fact(self) -> None:
        base = {
            "gap_id": "g1",
            "layer_id": "clarity",
            "source_stage": "clarity.real_context",
            "description": "Sem rotina concreta",
            "origin": "client_statement",
            "reason": "Duas respostas vagas",
        }
        with pytest.raises(ValidationError):
            Gap.model_validate({**base, "status": "resolved"})
        assert Gap.model_validate({**base, "status": "resolved", "resolved_by_fact": "f9"})
        assert Gap.model_validate(base).status == "open"

    def test_stage_progress_attempts_not_negative(self) -> None:
        with pytest.raises(ValidationError):
            StageProgress(stage_id="clarity.real_context", layer_id="clarity", attempts=-1)


def stage(stage_id: str = "clarity.real_context") -> dict[str, object]:
    return {
        "stage_id": stage_id,
        "title": "Contexto Real",
        "objective": "Mapear o dia a dia",
        "extraction_focus": "ação concreta",
        "anchors": [
            {"angle": "routine", "question": "Como é um dia típico?"},
            {"angle": "limit", "question": "O que você não faz?"},
            {"angle": "blind_spot", "question": "O que dizem de você?"},
        ],
        "rescue_angles": ["routine", "limit"],
    }


def layer(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "layer_id": "clarity",
        "order": 1,
        "name": "Nitidez de Marca",
        "objective": "tirar a mensagem da névoa",
        "pain_to_solve": "cai no genérico",
        "success_signal": "fato observável",
        "closure_criteria": "síntese reflete rotina real",
        "synthesis_template": "templates/clarity_map.md",
        "stages": [stage()],
    }
    data.update(overrides)
    return data


class TestKb:
    def test_valid_layer(self) -> None:
        spec = LayerSpec.model_validate(layer())
        assert spec.stages[0].rescue_angles == ["routine", "limit"]

    def test_stage_must_belong_to_layer(self) -> None:
        with pytest.raises(ValidationError):
            LayerSpec.model_validate(layer(stages=[stage("singularity.x")]))

    def test_stage_ids_unique(self) -> None:
        with pytest.raises(ValidationError):
            LayerSpec.model_validate(layer(stages=[stage(), stage()]))

    def test_stage_id_format(self) -> None:
        with pytest.raises(ValidationError):
            StageSpec.model_validate(stage("Clarity Real"))

    def test_order_1_to_4(self) -> None:
        with pytest.raises(ValidationError):
            LayerSpec.model_validate(layer(order=5))


class TestFillPlaceholders:
    def test_her_words_lose_the_trailing_period_and_the_capital(self) -> None:
        from vv_contracts.kb import fill_placeholders

        out = fill_placeholders(
            "Como foi o último {seu_trabalho}?", {"seu_trabalho": "Empanadas argentinas."}
        )
        assert out == "Como foi o último empanadas argentinas?"

    def test_acronyms_keep_their_case(self) -> None:
        from vv_contracts.kb import fill_placeholders

        assert fill_placeholders("{setor}", {"setor": "TI para MEI"}) == "TI para MEI"

    def test_a_long_answer_falls_back_to_the_neutral_default(self) -> None:
        from vv_contracts.kb import ANCHOR_PLACEHOLDERS, fill_placeholders

        long = "A gente fornece principalmente para cafés, bares e restaurantes, 80/20"
        assert (
            fill_placeholders("{as_clientes}", {"as_clientes": long})
            == (ANCHOR_PLACEHOLDERS["as_clientes"])
        )
