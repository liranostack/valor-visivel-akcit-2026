"""Conductor decision rules (ERD, 'Máquina de estados do Conductor').

TS tests ported from reference/ts-engine/engine/decision.test.ts are marked [TS].
"""

from pathlib import Path

import pytest
from vv_chat.conductor.config import ConductorConfig, load_config
from vv_chat.conductor.rules import StageState, decide, decide_resume
from vv_contracts.agents import ExtractedFact, InterpretationResult
from vv_contracts.state import Gap, StageProgress

CLARITY = ["clarity.real_context", "clarity.routine", "clarity.execution_evidence"]
SINGULARITY = ["singularity.backstage_gear", "singularity.uncopyable", "singularity.avoided_error"]
CONFIG = ConductorConfig()


def fact(quadrant: str = "open") -> ExtractedFact:
    return ExtractedFact.model_validate(
        {
            "text": "Ajusta a pressão pela respiração",
            "source_excerpt": "vou sentindo pela respiração",
            "kind": "characteristic",
            "origin": "client_statement",
            "finding_area": quadrant,
        }
    )


def interp(
    concreteness: int = 4, relevance: int = 4, facts: list[ExtractedFact] | None = None
) -> InterpretationResult:
    return InterpretationResult(
        concreteness=concreteness,
        relevance=relevance,
        defensibility=3,
        domain_fit=5,
        facts=[fact()] if facts is None else facts,
        gaps=["Não descreveu a rotina"] if concreteness < 3 else [],
    )


def gap(gap_id: str = "g1", layer: str = "clarity") -> Gap:
    return Gap.model_validate(
        {
            "gap_id": gap_id,
            "layer_id": layer,
            "source_stage": f"{layer}.x",
            "description": "Sem rotina concreta",
            "origin": "client_statement",
            "reason": "Duas respostas vagas",
        }
    )


def state(
    stage: str = CLARITY[0],
    attempts: int = 0,
    stages: list[str] | None = None,
    done: dict[str, str] | None = None,
    layer: str = "clarity",
    has_hidden_or_blind: bool = False,
    open_gaps: list[Gap] | None = None,
    resumed: bool = False,
) -> StageState:
    stage_ids = stages or (CLARITY if layer == "clarity" else SINGULARITY)
    progress = {
        s: StageProgress.model_validate(
            {"stage_id": s, "layer_id": layer, "status": (done or {}).get(s, "open")}
        )
        for s in stage_ids
    }
    progress[stage] = progress[stage].model_copy(update={"attempts": attempts})
    return StageState.model_validate(
        {
            "layer_id": layer,
            "stage_id": stage,
            "stage_ids": stage_ids,
            "progress": progress,
            "layer_has_hidden_or_blind": has_hidden_or_blind,
            "open_gaps": open_gaps or [],
            "resumed_gap_in_layer": resumed,
        }
    )


class TestPortedFromTs:
    def test_advances_when_quality_high(self) -> None:  # [TS] deve avancar quando quality for high
        out = decide(state(), interp(5, 5), CONFIG)
        assert out.decision.action == "advance"
        assert out.stage_status == "covered"
        assert out.decision.attempt == 1

    def test_deepens_before_max_attempts(self) -> None:  # [TS] deve pedir retry antes do limite
        out = decide(state(attempts=0), interp(1, 1), CONFIG)
        assert out.decision.action == "deepen"
        assert out.stage_status == "open"
        assert out.decision.attempt == 2

    def test_forces_advance_at_max_attempts(self) -> None:  # [TS] deve forcar avancar no limite
        out = decide(state(attempts=1), interp(1, 1), CONFIG)
        assert out.decision.action == "force_advance"
        assert out.stage_status == "forced"
        assert out.flag_for_review is True
        assert out.decision.attempt == 1


class TestErdTable:
    def test_advance_moves_to_next_stage(self) -> None:
        out = decide(state(), interp(), CONFIG)
        assert out.decision.next_stage_id == CLARITY[1]
        assert out.layer_complete is False

    def test_advance_needs_a_fact(self) -> None:
        out = decide(state(), interp(5, 5, facts=[]), CONFIG)
        assert out.decision.action == "deepen"

    @pytest.mark.parametrize(("c", "r"), [(2, 5), (5, 2)])
    def test_low_concreteness_or_relevance_deepens(self, c: int, r: int) -> None:
        assert decide(state(), interp(c, r), CONFIG).decision.action == "deepen"

    def test_deepen_offers_abc_on_configured_attempt(self) -> None:
        out = decide(state(attempts=0), interp(1, 1), CONFIG)
        assert out.decision.offer_abc_options is True
        assert out.decision.next_stage_id == CLARITY[0]

    def test_no_abc_when_not_configured_attempt(self) -> None:
        cfg = ConductorConfig(max_attempts_per_stage=4, abc_options_on_attempt=3)
        out = decide(state(attempts=0), interp(1, 1), cfg)
        assert out.decision.offer_abc_options is False

    def test_force_advance_creates_gap_with_reason(self) -> None:
        out = decide(state(attempts=1), interp(1, 1), CONFIG)
        assert out.create_gap is True
        assert out.gap_reason
        assert out.decision.next_stage_id == CLARITY[1]

    def test_force_advance_without_interpreter_gap_uses_default_reason(self) -> None:
        weak = InterpretationResult(concreteness=1, relevance=1, defensibility=1, domain_fit=1)
        out = decide(state(attempts=1), weak, CONFIG)
        assert out.gap_reason == "insufficient evidence after maximum attempts"

    def test_last_stage_advance_synthesizes(self) -> None:
        done = {CLARITY[0]: "covered", CLARITY[1]: "forced"}
        out = decide(state(stage=CLARITY[2], done=done), interp(), CONFIG)
        assert out.decision.action == "synthesize"
        assert out.stage_status == "covered"
        assert out.layer_complete is True
        assert out.decision.next_stage_id is None

    def test_last_stage_forced_synthesizes(self) -> None:
        done = {CLARITY[0]: "covered", CLARITY[1]: "covered"}
        out = decide(state(stage=CLARITY[2], attempts=1, done=done), interp(1, 1), CONFIG)
        assert out.decision.action == "synthesize"
        assert out.stage_status == "forced"

    def test_skips_stages_already_closed(self) -> None:
        done = {CLARITY[1]: "covered"}
        out = decide(state(stage=CLARITY[0], done=done), interp(), CONFIG)
        assert out.decision.next_stage_id == CLARITY[2]

    def test_resume_gap_before_synthesis(self) -> None:
        done = {CLARITY[0]: "covered", CLARITY[1]: "forced"}
        out = decide(state(stage=CLARITY[2], done=done, open_gaps=[gap("g7")]), interp(), CONFIG)
        assert out.decision.action == "resume_gap"
        assert out.decision.gap_id == "g7"
        assert out.layer_complete is True

    def test_only_one_resume_per_layer(self) -> None:
        done = {CLARITY[0]: "covered", CLARITY[1]: "forced"}
        st = state(stage=CLARITY[2], done=done, open_gaps=[gap()], resumed=True)
        assert decide(st, interp(), CONFIG).decision.action == "synthesize"

    def test_resume_disabled_by_config(self) -> None:
        done = {CLARITY[0]: "covered", CLARITY[1]: "forced"}
        cfg = ConductorConfig(resume_gaps_before_synthesis=False)
        st = state(stage=CLARITY[2], done=done, open_gaps=[gap()])
        assert decide(st, interp(), cfg).decision.action == "synthesize"

    def test_gaps_from_other_layers_are_ignored(self) -> None:
        done = {CLARITY[0]: "covered", CLARITY[1]: "forced"}
        st = state(stage=CLARITY[2], done=done, open_gaps=[gap(layer="singularity")])
        assert decide(st, interp(), CONFIG).decision.action == "synthesize"

    def test_unknown_stage_raises(self) -> None:
        st = state()
        bad = st.model_copy(update={"stage_id": "clarity.nope"})
        with pytest.raises(ValueError):
            decide(bad, interp(), CONFIG)


class TestQuadrantRule:
    def done_but_last(self) -> dict[str, str]:
        return {SINGULARITY[0]: "covered", SINGULARITY[1]: "covered"}

    def test_singularity_cannot_close_on_open_facts_only(self) -> None:
        st = state(stage=SINGULARITY[2], layer="singularity", done=self.done_but_last())
        out = decide(st, interp(5, 5), CONFIG)
        assert out.decision.action == "deepen"
        assert out.quadrant_rule_pending is True

    def test_singularity_closes_with_hidden_fact_now(self) -> None:
        st = state(stage=SINGULARITY[2], layer="singularity", done=self.done_but_last())
        out = decide(st, interp(5, 5, facts=[fact("hidden")]), CONFIG)
        assert out.decision.action == "synthesize"

    def test_singularity_closes_with_blind_fact_earlier(self) -> None:
        st = state(
            stage=SINGULARITY[2],
            layer="singularity",
            done=self.done_but_last(),
            has_hidden_or_blind=True,
        )
        assert decide(st, interp(5, 5), CONFIG).decision.action == "synthesize"

    def test_quadrant_rule_only_applies_when_closing_layer(self) -> None:
        st = state(stage=SINGULARITY[0], layer="singularity")
        assert decide(st, interp(5, 5), CONFIG).decision.action == "advance"

    def test_quadrant_rule_at_max_attempts_forces_and_records_gap(self) -> None:
        st = state(stage=SINGULARITY[2], layer="singularity", done=self.done_but_last(), attempts=1)
        out = decide(st, interp(5, 5), CONFIG)
        assert out.decision.action == "synthesize"
        assert out.stage_status == "forced"
        assert out.create_gap is True
        assert out.gap_reason == "no hidden or blind fact found in this layer"

    def test_clarity_has_no_quadrant_rule(self) -> None:
        done = {CLARITY[0]: "covered", CLARITY[1]: "covered"}
        out = decide(state(stage=CLARITY[2], done=done), interp(5, 5), CONFIG)
        assert out.decision.action == "synthesize"


class TestResume:
    def test_gap_resolved_only_with_new_fact_scored_3_or_more(self) -> None:
        out = decide_resume(interp(4, 4), "g1", CONFIG)
        assert out.gap_status == "resolved"
        assert out.decision.action == "synthesize"

    def test_gap_never_becomes_fact_without_evidence(self) -> None:
        assert decide_resume(interp(5, 5, facts=[]), "g1", CONFIG).gap_status == (
            "kept_as_hypothesis"
        )
        assert decide_resume(interp(2, 5), "g1", CONFIG).gap_status == "kept_as_hypothesis"


class TestConfig:
    def test_defaults_match_erd(self) -> None:
        cfg = ConductorConfig()
        assert cfg.max_attempts_per_stage == 2
        assert cfg.abc_options_on_attempt == 2
        assert cfg.deepen_below_score == 3
        assert cfg.advance_min_fact_score == 3
        assert cfg.resume_gaps_before_synthesis is True
        assert cfg.require_hidden_or_blind_fact == ["singularity"]
        assert cfg.layers_order == ["clarity", "singularity", "translation", "sustainment"]

    def test_yaml_file_matches_defaults(self) -> None:
        path = Path(__file__).resolve().parents[2] / "config" / "conductor.yaml"
        assert load_config(path) == ConductorConfig()

    def test_abc_attempt_cannot_exceed_max(self) -> None:
        with pytest.raises(ValueError):
            ConductorConfig(max_attempts_per_stage=2, abc_options_on_attempt=3)

    def test_custom_thresholds(self) -> None:
        cfg = ConductorConfig(deepen_below_score=4, advance_min_fact_score=4)
        assert decide(state(), interp(3, 5), cfg).decision.action == "deepen"
