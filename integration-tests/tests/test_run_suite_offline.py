"""Suite runner: offline end to end, thresholds and exit code (A.05.01)."""

from pathlib import Path

from vv_it.fidelity import Check
from vv_it.run_suite import Thresholds, failures, load_thresholds, main


def test_thresholds_file_has_the_erd_metrics() -> None:
    t = load_thresholds()
    for metric in (
        "layer_closed",
        "quadrant_coverage",
        "hypothesis_as_fact",
        "question_quality",
        "episode_anchoring",
        "leading_question",
        "praise_validation",
        "truth_recall",
    ):
        assert metric in t.rules


def test_values_below_the_limit_fail() -> None:
    t = Thresholds(rules={"a": {"min": 3.5}, "b": {"max": 0}})
    checks = [Check(metric="a", value=3.0), Check(metric="b", value=0), Check(metric="c", value=9)]
    assert [c.metric for c in failures(checks, t)] == ["a"]


def test_offline_run_writes_a_report_and_does_not_enforce(tmp_path: Path) -> None:
    code = main(
        ["--offline", "--persona", "pastelaria", "--max-turns", "2", "--out", str(tmp_path)]
    )
    assert code == 0
    reports = list(tmp_path.glob("*/report.md"))
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    assert "pastelaria" in text and "layer_closed" in text
    assert (reports[0].parent / "report.json").exists()


def test_real_mode_fails_below_threshold(tmp_path: Path, monkeypatch) -> None:
    import vv_it.run_suite as suite

    monkeypatch.setattr(suite, "enforce", lambda offline: True)
    code = main(
        ["--offline", "--persona", "pastelaria", "--max-turns", "1", "--out", str(tmp_path)]
    )
    assert code == 1


def test_a_not_applicable_value_is_not_a_failure() -> None:
    t = Thresholds(rules={"difficulty_handling": {"min": 3, "na": 0}})
    assert failures([Check(metric="difficulty_handling", value=0)], t) == []
    assert failures([Check(metric="difficulty_handling", value=2)], t)


def test_cost_table_separates_the_product_from_the_test_harness() -> None:
    from vv_chat.agents.llm import Usage
    from vv_it.report import cost_rows

    usages = [
        Usage(label="interpreter", model_id="m", input_tokens=1_000_000, output_tokens=0, calls=5),
        Usage(label="juiz", model_id="m", input_tokens=1_000_000, output_tokens=0, calls=2),
    ]
    prices = {"m": {"input": 3.0, "output": 15.0}}
    rows, product, total = cost_rows(usages, prices)
    assert [r["role"] for r in rows] == ["interpreter", "juiz"]
    assert product == 3.0 and total == 6.0


def test_offline_report_has_no_cost_section_but_still_renders(tmp_path: Path) -> None:
    code = main(
        ["--offline", "--persona", "pastelaria", "--max-turns", "1", "--out", str(tmp_path)]
    )
    assert code == 0
    report = next(tmp_path.glob("*/report.md")).read_text(encoding="utf-8")
    assert "Custo" not in report
