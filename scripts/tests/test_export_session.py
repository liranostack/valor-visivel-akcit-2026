"""export_session: one stored session as a readable transcript plus raw records (A.06.10)."""

import importlib.util
import json
from pathlib import Path

from vv_contracts.agents import InterpretationScores
from vv_contracts.state import Baseline, Fact, OnboardingAnswers, Session, StoredSynthesis, Turn
from vv_mcp.repo_memory import InMemoryStateRepository

SPEC = importlib.util.spec_from_file_location(
    "export_session", Path(__file__).resolve().parents[1] / "export_session.py"
)
assert SPEC and SPEC.loader
export_session = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export_session)


def repo() -> InMemoryStateRepository:
    r = InMemoryStateRepository()
    r.put_session(
        Session(
            session_id="s1",
            status="layer_review",
            onboarding=OnboardingAnswers(offer="Empanadas", perceived_difficulty="preço"),
        )
    )
    r.save_baseline("s1", Baseline(statement="Temos muitos sabores."))
    r.save_turn("s1", Turn(seq=1, user_message="", question_asked="Como foi a última vez?"))
    r.save_turn("s1", Turn(seq=2, user_message="normal, a gente tem cozinha", decision="deepen"))
    r.save_fact(
        "s1",
        Fact(
            fact_id="f1",
            layer_id="clarity",
            stage_id="clarity.real_context",
            source_turn=2,
            text="Tem cozinha profissional.",
            source_excerpt="a gente tem cozinha",
            scores=InterpretationScores(concreteness=3, relevance=4, defensibility=2, domain_fit=5),
            kind="characteristic",
            origin="client_statement",
            finding_area="hidden",
        ),
    )
    r.save_synthesis(
        "s1",
        StoredSynthesis(
            layer_id="clarity",
            version=1,
            content={"O que você faz": "Cozinha [fact:f1]."},
            fact_refs=["f1"],
        ),
    )
    return r


def test_markdown_has_onboarding_baseline_turns_facts_and_synthesis() -> None:
    md, _ = export_session.render(repo(), "s1")
    for expected in (
        "Empanadas",
        "Temos muitos sabores.",
        "Como foi a última vez?",
        "normal, a gente tem cozinha",
        "a gente tem cozinha",
        "hidden",
        "## O que você faz",
        "Cozinha [fact:f1].",
    ):
        assert expected in md


def test_records_are_json_lines_with_a_kind() -> None:
    _, records = export_session.render(repo(), "s1")
    kinds = {r["kind"] for r in records}
    assert {"session", "baseline", "turn", "fact", "synthesis"} <= kinds
    json.dumps(records, default=str)


def test_unknown_session_is_reported() -> None:
    try:
        export_session.render(InMemoryStateRepository(), "nope")
    except export_session.SessionNotFoundError:
        return
    raise AssertionError("expected SessionNotFoundError")


class TestReplay:
    """A.04.07: a recorded session becomes the demo replay (the same events the front receives)."""

    @staticmethod
    def recorded() -> list[dict[str, object]]:
        r = repo()
        r.save_turn(
            "s1",
            Turn(
                seq=2,
                user_message="normal, a gente tem cozinha",
                question_asked="Uma cozinha própria. O que você confere antes de sair a fornada?",
                decision="deepen",
                latency_ms=7200,
            ),
        )
        r.save_turn(
            "s1",
            Turn(
                seq=3,
                user_message="provo uma de cada sabor",
                question_asked=(
                    "Uma leitura para você conferir: você prova cada sabor.\n\nEle está fiel?"
                ),
                decision="synthesize",
                latency_ms=21000,
            ),
        )
        r.save_turn(
            "s1",
            Turn(
                seq=4,
                user_message="[aprovou o mapa]",
                question_asked="Mapa aprovado.",
                mode="review",
            ),
        )
        _, records = export_session.render(r, "s1")
        return json.loads(json.dumps(records, default=str))

    def test_starts_with_the_first_question_and_keeps_her_answers(self) -> None:
        script = export_session.replay_script(self.recorded(), label="empanadas")
        assert script["first_question"] == "Como foi a última vez?"
        assert [t["answer"] for t in script["turns"]] == [
            "normal, a gente tem cozinha",
            "provo uma de cada sabor",
        ]
        assert script["turns"][0]["latency_ms"] == 7200

    def test_the_closing_turn_carries_the_map(self) -> None:
        script = export_session.replay_script(self.recorded(), label="empanadas")
        first, closing = script["turns"]
        assert first["synthesis"] is None
        assert closing["synthesis"]["content"] == {"O que você faz": "Cozinha [fact:f1]."}
        assert script["approved_message"] == "Mapa aprovado."

    def test_onboarding_answers_are_not_replayed_as_turns(self) -> None:
        script = export_session.replay_script(self.recorded(), label="empanadas")
        assert all(t["answer"] for t in script["turns"])
        assert script["business"] == "Empanadas"

    def test_carries_the_baseline_for_the_result_page(self) -> None:
        script = export_session.replay_script(self.recorded(), label="empanadas")
        assert script["baseline"] == "Temos muitos sabores."
