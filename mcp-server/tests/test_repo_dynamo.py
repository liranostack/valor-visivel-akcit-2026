"""DynamoDB single-table repository (ERD, "Modelo de dados"), tested with moto."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from moto import mock_aws
from vv_contracts import keys
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
from vv_mcp.repo_dynamo import DynamoStateRepository, create_table

TABLE = "vv-test"
RETENTION = datetime(2026, 12, 13, tzinfo=UTC)
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


def gap(gap_id: str, layer: str = "clarity") -> Gap:
    return Gap.model_validate(
        {
            "gap_id": gap_id,
            "layer_id": layer,
            "source_stage": f"{layer}.x",
            "description": "d",
            "origin": "client_statement",
            "reason": "r",
        }
    )


@pytest.fixture
def ddb() -> Iterator[Any]:
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        create_table(resource, TABLE)
        yield resource


@pytest.fixture
def repo(ddb: Any) -> DynamoStateRepository:
    r = DynamoStateRepository(TABLE, dynamodb=ddb)
    r.put_session(
        Session(
            session_id="s1",
            status="in_layer",
            active_layer="clarity",
            retention_until=RETENTION,
        )
    )
    return r


def items(ddb: Any) -> list[dict[str, Any]]:
    return ddb.Table(TABLE).scan()["Items"]


def test_every_item_has_pk_sk_and_ttl(repo: DynamoStateRepository, ddb: Any) -> None:
    repo.save_baseline("s1", Baseline(statement="x"))
    repo.save_turn("s1", Turn(seq=1, user_message="oi"))
    repo.save_fact("s1", fact("f1"))
    for item in items(ddb):
        assert item["PK"] == keys.pk("s1")
        assert int(item["ttl"]) == int(RETENTION.timestamp())
    sks = {i["SK"] for i in items(ddb)}
    assert {"META", "BASELINE", "TURN#000001", "FACT#clarity#f1"} <= sks


def test_session_without_retention_gets_30_days(ddb: Any) -> None:
    r = DynamoStateRepository(TABLE, dynamodb=ddb)
    r.put_session(Session(session_id="s2", status="onboarding"))
    ttl = int(items(ddb)[0]["ttl"])
    delta_days = (ttl - datetime.now(UTC).timestamp()) / 86400
    assert 29.9 < delta_days < 30.1


def test_unknown_session(ddb: Any) -> None:
    assert DynamoStateRepository(TABLE, dynamodb=ddb).get_state("nope") is None


def test_get_state_in_one_query(repo: DynamoStateRepository) -> None:
    repo.save_baseline("s1", Baseline(statement="atendimento humanizado "))
    repo.save_public_context("s1", PublicContextRecord(source="https://x.com", summary="s"))
    repo.update_stage_progress("s1", StageProgress(stage_id="clarity.a", layer_id="clarity"))
    repo.save_gap("s1", gap("g1"))
    repo.save_turn("s1", Turn(seq=1, user_message="a", question_asked="Q1?"))
    repo.save_turn("s1", Turn(seq=10, user_message="b", question_asked="Q2?"))
    state = repo.get_state("s1")
    assert state is not None
    assert state.session.active_layer == "clarity"
    assert state.baseline is not None and state.baseline.statement == "atendimento humanizado "
    assert state.public_context is not None
    assert [p.stage_id for p in state.progress] == ["clarity.a"]
    assert [g.gap_id for g in state.open_gaps] == ["g1"]
    assert state.last_turn_seq == 10
    assert state.asked_questions == ["Q1?", "Q2?"]


def test_facts_by_layer_and_filters(repo: DynamoStateRepository) -> None:
    repo.save_fact("s1", fact("f1"))
    repo.save_fact("s1", fact("f2", layer="singularity", quadrant="hidden", kind="benefit"))
    assert [f.fact_id for f in repo.list_facts("s1", layer_id="singularity")] == ["f2"]
    assert {f.fact_id for f in repo.list_facts("s1")} == {"f1", "f2"}
    assert [f.fact_id for f in repo.list_facts("s1", finding_area="hidden")] == ["f2"]
    assert [f.fact_id for f in repo.list_facts("s1", kind="evidence")] == ["f1"]


def test_gaps_and_update(repo: DynamoStateRepository) -> None:
    repo.save_gap("s1", gap("g1"))
    repo.save_gap("s1", gap("g2", layer="translation"))
    assert [g.gap_id for g in repo.list_gaps("s1", layer_id="translation")] == ["g2"]
    repo.update_gap("s1", "g1", "resolved", fact_id="f9")
    resolved = repo.list_gaps("s1", status="resolved")
    assert [(g.gap_id, g.resolved_by_fact) for g in resolved] == [("g1", "f9")]
    with pytest.raises(ValueError):
        repo.update_gap("s1", "g2", "resolved")
    with pytest.raises(KeyError):
        repo.update_gap("s1", "missing", "kept_as_hypothesis")


def test_latest_synthesis_uses_descending_query(repo: DynamoStateRepository) -> None:
    s = StoredSynthesis(layer_id="clarity", version=1, content={"a": "b"}, fact_refs=[])
    versions = [repo.save_synthesis("s1", s) for _ in range(11)]
    assert versions == list(range(1, 12))
    latest = repo.latest_synthesis("s1", "clarity")
    assert latest is not None and latest.version == 11
    assert repo.latest_synthesis("s1", "translation") is None


def test_flagged_stages_for_pre_core(repo: DynamoStateRepository) -> None:
    repo.update_stage_progress(
        "s1", StageProgress(stage_id="clarity.a", layer_id="clarity", flagged_for_review=True)
    )
    repo.update_stage_progress("s1", StageProgress(stage_id="clarity.b", layer_id="clarity"))
    assert [p.stage_id for p in repo.flagged_stages("s1")] == ["clarity.a"]


def test_turns_in_order(repo: DynamoStateRepository) -> None:
    for seq in (3, 1, 2):
        repo.save_turn("s1", Turn(seq=seq, user_message=str(seq)))
    assert [t.seq for t in repo.list_turns("s1")] == [1, 2, 3]


def test_reviews_pre_core_core_evaluations(repo: DynamoStateRepository, ddb: Any) -> None:
    repo.save_review("s1", Review(target="clarity", intent="adjust", notes="trocar termo"))
    repo.save_review("s1", Review(target="clarity", intent="approve"))
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
    repo.save_evaluation("s1", Evaluation(turn_seq=4, metric="conciseness", score=4.5, judge="h"))
    sks = {i["SK"] for i in items(ddb)}
    assert {"REVIEW#0001", "REVIEW#0002", "PRECORE", "CORE", "EVAL#000004#conciseness"} <= sks
    assert repo.core("s1") == core
    assert [r.intent for r in repo.reviews("s1")] == ["adjust", "approve"]


def test_writes_to_unknown_session_fail(ddb: Any) -> None:
    with pytest.raises(KeyError):
        DynamoStateRepository(TABLE, dynamodb=ddb).save_turn("nope", Turn(seq=1, user_message="x"))


def test_pagination(repo: DynamoStateRepository) -> None:
    big = "x" * 30_000
    for i in range(50):  # ~1.5 MB > 1 MB page
        repo.save_turn("s1", Turn(seq=i + 1, user_message=big))
    state = repo.get_state("s1")
    assert state is not None and state.last_turn_seq == 50
