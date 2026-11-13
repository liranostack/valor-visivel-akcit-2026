"""Deterministic method checks over a recorded journey (A.02.21)."""

from typing import Any

from vv_it.fidelity import deterministic_checks
from vv_it.journey import JourneyRecord, TurnRecord


def fact(
    fid: str, quadrant: str, origin: str = "client_statement", kind: str = "characteristic"
) -> dict[str, str]:
    return {
        "fact_id": fid,
        "finding_area": quadrant,
        "origin": origin,
        "kind": kind,
        "text": fid,
        "source_excerpt": fid,
    }


def journey(**overrides: Any) -> JourneyRecord:
    base: dict[str, Any] = dict(
        persona="p",
        session_id="s",
        first_question="Q1?",
        turns=[
            TurnRecord(seq=2, question="Q1?", answer="a", reply="Como foi a última entrega?"),
            TurnRecord(seq=3, question="Como foi a última entrega?", answer="b", reply="ok"),
        ],
        facts=[fact("f1", "hidden"), fact("f2", "blind", origin="external_perception")],
        gaps=[],
        synthesis={"content": {"O que você faz": "Confere tudo [fact:f1]."}, "gaps": []},
        ended="layer_closed",
    )
    return JourneyRecord(**(base | overrides))


def by_metric(record: JourneyRecord) -> dict[str, float]:
    return {c.metric: c.value for c in deterministic_checks(record)}


def test_a_good_journey_passes_every_check() -> None:
    values = by_metric(journey())
    assert values["layer_closed"] == 1
    assert values["quadrant_coverage"] == 1
    assert values["hypothesis_as_fact"] == 0
    assert values["synthesis_traceability"] == 1.0
    assert values["non_repetition"] == 0


def test_missing_blind_without_a_registered_gap_fails_coverage() -> None:
    assert by_metric(journey(facts=[fact("f1", "hidden")]))["quadrant_coverage"] == 0


def test_a_registered_gap_covers_the_missing_blind() -> None:
    record = journey(
        facts=[fact("f1", "hidden")],
        synthesis={"content": {"x": "y [fact:f1]"}, "gaps": ["O que quem compra diz"]},
    )
    assert by_metric(record)["quadrant_coverage"] == 1


def test_a_hypothesis_cited_outside_the_hypotheses_section_counts() -> None:
    record = journey(
        facts=[fact("f1", "hidden"), fact("h1", "unknown", "inference", kind="hypothesis")],
        synthesis={
            "content": {
                "O que você faz": "Talvez use técnica [fact:h1].",
                "Lacunas e hipóteses": "Pode ser [fact:h1].",
            },
            "gaps": [],
        },
    )
    assert by_metric(record)["hypothesis_as_fact"] == 1


def test_uncited_paragraphs_lower_traceability() -> None:
    record = journey(synthesis={"content": {"a": "x [fact:f1]\n\nsem fonte"}, "gaps": []})
    assert by_metric(record)["synthesis_traceability"] == 0.5


def test_a_repeated_question_is_counted() -> None:
    turns = [
        TurnRecord(
            seq=2, question="Q1?", answer="a", reply="Como foi a última entrega para um café?"
        ),
        TurnRecord(
            seq=3,
            question="Como foi a última entrega para um café?",
            answer="b",
            reply="Como foi a última entrega para o café?",
        ),
    ]
    assert by_metric(journey(turns=turns))["non_repetition"] == 1


def test_no_synthesis_means_layer_not_closed() -> None:
    values = by_metric(journey(synthesis=None, ended="max_turns"))
    assert values["layer_closed"] == 0


def test_gaps_and_not_yet_known_paragraphs_are_not_counted_as_uncited() -> None:
    from vv_chat.agents.synthesizer import GAPS_SECTION, UNKNOWN

    record = journey(
        synthesis={
            "content": {
                "O que você faz": "Confere tudo [fact:f1].",
                "Para quem": UNKNOWN,
                GAPS_SECTION: "Lacunas:\n\n- quem compra",
            },
            "gaps": [],
        }
    )
    assert by_metric(record)["synthesis_traceability"] == 1.0


def test_long_dashes_in_what_she_reads_are_counted() -> None:
    turns = [TurnRecord(seq=2, question="Q1?", answer="a", reply="Como foi — de verdade?")]
    record = journey(turns=turns, synthesis={"content": {"x": "y — z [fact:f1]"}, "gaps": []})
    assert by_metric(record)["em_dash"] == 2


def test_a_reading_section_counts_as_hypotheses() -> None:
    record = journey(
        facts=[fact("f1", "hidden"), fact("h1", "unknown", "inference", kind="hypothesis")],
        synthesis={
            "content": {"Uma leitura para você conferir": "Será que é isso [fact:h1]?"},
            "gaps": ["x"],
        },
    )
    assert by_metric(record)["hypothesis_as_fact"] == 0


def test_question_coverage_counts_messages_that_end_in_one_question() -> None:
    turns = [
        TurnRecord(seq=2, question="Q1?", answer="a", reply="Tem um ponto bom.\n\nComo foi?"),
        TurnRecord(seq=3, question="Como foi?", answer="b", reply="Entendi."),
    ]
    record = journey(turns=turns, synthesis=None, ended="max_turns")
    assert by_metric(record)["question_coverage"] == 0.5
