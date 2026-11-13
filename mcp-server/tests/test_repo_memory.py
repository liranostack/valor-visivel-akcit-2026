import pytest
from vv_contracts.agents import InterpretationScores
from vv_contracts.state import (
    Baseline,
    EssentialCore,
    Evaluation,
    Fact,
    Gap,
    PreCore,
    PublicContextRecord,
    Review,
    Session,
    StageProgress,
    StoredSynthesis,
    Turn,
)
from vv_mcp.repo_memory import InMemoryStateRepository

SCORES = InterpretationScores(concreteness=4, relevance=4, defensibility=3, domain_fit=5)


def fact(
    fact_id: str, layer: str = "clarity", quadrant: str = "open", kind: str = "evidence"
) -> Fact:
    return Fact.model_validate(
        {
            "fact_id": fact_id,
            "layer_id": layer,
            "stage_id": f"{layer}.x",
            "source_turn": 1,
            "text": "t",
            "source_excerpt": "e",
            "scores": SCORES.model_dump(),
            "kind": kind,
            "origin": "client_statement",
            "finding_area": quadrant,
        }
    )


def gap(gap_id: str, layer: str = "clarity", status: str = "open") -> Gap:
    return Gap.model_validate(
        {
            "gap_id": gap_id,
            "layer_id": layer,
            "source_stage": f"{layer}.x",
            "description": "d",
            "origin": "client_statement",
            "reason": "r",
            "status": status,
            "resolved_by_fact": "f" if status == "resolved" else None,
        }
    )


@pytest.fixture
def repo() -> InMemoryStateRepository:
    r = InMemoryStateRepository()
    r.put_session(Session(session_id="s1", status="in_layer", active_layer="clarity"))
    return r


def test_unknown_session_has_no_state() -> None:
    assert InMemoryStateRepository().get_state("nope") is None


def test_state_aggregates_everything(repo: InMemoryStateRepository) -> None:
    repo.save_baseline("s1", Baseline(statement="atendimento humanizado "))
    repo.save_public_context("s1", PublicContextRecord(source="https://x.com", summary="s"))
    repo.update_stage_progress(
        "s1", StageProgress(stage_id="clarity.a", layer_id="clarity", attempts=1)
    )
    repo.save_gap("s1", gap("g1"))
    repo.save_gap("s1", gap("g2", status="resolved"))
    repo.save_turn("s1", Turn(seq=1, user_message="oi", question_asked="Como é seu dia?"))
    repo.save_turn("s1", Turn(seq=2, user_message="ok"))
    state = repo.get_state("s1")
    assert state is not None
    assert state.baseline is not None and state.baseline.statement == "atendimento humanizado "
    assert state.public_context is not None
    assert [p.stage_id for p in state.progress] == ["clarity.a"]
    assert [g.gap_id for g in state.open_gaps] == ["g1"]
    assert state.last_turn_seq == 2
    assert state.asked_questions == ["Como é seu dia?"]


def test_stage_progress_is_upserted(repo: InMemoryStateRepository) -> None:
    p = StageProgress(stage_id="clarity.a", layer_id="clarity")
    repo.update_stage_progress("s1", p)
    repo.update_stage_progress("s1", p.model_copy(update={"attempts": 2, "status": "forced"}))
    state = repo.get_state("s1")
    assert state is not None and state.progress[0].attempts == 2


def test_save_turn_returns_seq(repo: InMemoryStateRepository) -> None:
    assert repo.save_turn("s1", Turn(seq=7, user_message="x")) == 7


def test_facts_filters(repo: InMemoryStateRepository) -> None:
    assert repo.save_fact("s1", fact("f1")) == "f1"
    repo.save_fact("s1", fact("f2", layer="singularity", quadrant="hidden", kind="benefit"))
    assert [f.fact_id for f in repo.list_facts("s1")] == ["f1", "f2"]
    assert [f.fact_id for f in repo.list_facts("s1", layer_id="singularity")] == ["f2"]
    assert [f.fact_id for f in repo.list_facts("s1", finding_area="hidden")] == ["f2"]
    assert [f.fact_id for f in repo.list_facts("s1", kind="evidence")] == ["f1"]


def test_gaps_filters_and_update(repo: InMemoryStateRepository) -> None:
    repo.save_gap("s1", gap("g1"))
    repo.save_gap("s1", gap("g2", layer="translation"))
    assert [g.gap_id for g in repo.list_gaps("s1", layer_id="translation")] == ["g2"]
    repo.update_gap("s1", "g1", "resolved", fact_id="f9")
    assert repo.list_gaps("s1", status="resolved")[0].resolved_by_fact == "f9"
    repo.update_gap("s1", "g2", "kept_as_hypothesis")
    assert repo.list_gaps("s1", status="open") == []


def test_update_gap_rules(repo: InMemoryStateRepository) -> None:
    repo.save_gap("s1", gap("g1"))
    with pytest.raises(ValueError):
        repo.update_gap("s1", "g1", "resolved")
    with pytest.raises(KeyError):
        repo.update_gap("s1", "missing", "kept_as_hypothesis")


def test_synthesis_versions_increase(repo: InMemoryStateRepository) -> None:
    s = StoredSynthesis(layer_id="clarity", version=1, content={}, fact_refs=[])
    assert repo.save_synthesis("s1", s) == 1
    assert repo.save_synthesis("s1", s) == 2
    latest = repo.latest_synthesis("s1", "clarity")
    assert latest is not None and latest.version == 2
    assert repo.latest_synthesis("s1", "translation") is None


def test_reviews_pre_core_core_evaluations(repo: InMemoryStateRepository) -> None:
    repo.save_review("s1", Review(target="pre_core", intent="approve"))
    repo.save_pre_core("s1", PreCore(contradictions=["x"]))
    core = EssentialCore.model_validate(
        {
            "content": {},
            "final_statement": "f",
            "before_after": {
                "said_before": "a",
                "sustained_discovery": "b",
                "now_able_to": "c",
                "fact_refs": [],
            },
            "action_plan_7d": [str(i) for i in range(7)],
            "outputs": {
                "bio": "Ajudo clientes a resolver o problema porque faço X.",
                "narrativa": "Trabalho com Y. Faço Z. O cliente percebe W.",
                "checklist": [
                    "Prioridade alta: testar narrativa",
                    "Prioridade média: coletar prova",
                    "Prioridade baixa: documentar",
                ],
                "whatsapp_pitch_curto": "Oi! Trabalho com Y e entrego Z.",
                "whatsapp_pitch_prova": "Oi! Trabalho com Y e entrego Z. Prova: W.",
                "instagram_bio": "Como faço Z. Impacto: W.",
                "instagram_legenda_curta": "Bastidor real: X. Resultado: W.",
                "instagram_story_roteiro": ["Problema: ...", "Rotina: ...", "Prova: ..."],
            },
        }
    )
    repo.save_core("s1", core)
    repo.save_evaluation("s1", Evaluation(turn_seq=1, metric="conciseness", score=4, judge="h"))
    assert repo.reviews("s1")[0].intent == "approve"
    assert repo.pre_core("s1") is not None
    assert repo.core("s1") == core
    assert repo.evaluations("s1")[0].metric == "conciseness"


def test_writes_to_unknown_session_fail() -> None:
    with pytest.raises(KeyError):
        InMemoryStateRepository().save_turn("nope", Turn(seq=1, user_message="x"))
