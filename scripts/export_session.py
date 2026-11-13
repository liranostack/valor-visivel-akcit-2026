"""Export one stored session (DynamoDB) as a readable transcript (.md) and raw records (.jsonl).

Sessions expire after 30 days (TTL); export the ones worth keeping. Needs AWS credentials with
read access to the table (human-run; agents never touch real AWS).

Usage:
    uv run python scripts/export_session.py --table <TableName> --list
    uv run python scripts/export_session.py --table <TableName> --session <id> --label pastelaria

Files go to docs/e2e-runs/ (not committed), same place as try_turn --save.

Demo replay (A.04.07): --replay also writes frontend/public/replays/<label>.json, the recorded
layer-1 conversation the front plays back with ?replay=<label>. A file exported earlier can be
converted without AWS:
    uv run python scripts/export_session.py --from-jsonl docs/e2e-runs/<file>.jsonl --label demo
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from vv_contracts.common import LAYERS_ORDER

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "docs" / "e2e-runs"
REPLAYS = ROOT / "frontend" / "public" / "replays"
APPROVED_MARK = "[aprovou o mapa]"
Repo = Any  # InMemoryStateRepository or DynamoStateRepository (same methods)


class SessionNotFoundError(LookupError):
    pass


def render(repo: Repo, session_id: str) -> tuple[str, list[dict[str, Any]]]:
    state = repo.get_state(session_id)
    if state is None:
        raise SessionNotFoundError(session_id)
    records: list[dict[str, Any]] = [{"kind": "session", "data": state.session.model_dump()}]
    md = [f"# Sessão {session_id}", "", f"status: {state.session.status}", ""]

    answers = state.session.onboarding
    if answers is not None:
        md += ["## Onboarding", ""]
        for name, value in answers.model_dump().items():
            if value:
                md.append(f"- {name}: {', '.join(value) if isinstance(value, list) else value}")
        md.append("")
    if state.baseline is not None:
        records.append({"kind": "baseline", "data": state.baseline.model_dump()})
        md += ["## Como ela se apresenta (baseline)", "", f"> {state.baseline.statement}", ""]

    md += ["## Conversa", ""]
    for turn in repo.list_turns(session_id):
        records.append({"kind": "turn", "data": turn.model_dump()})
        if turn.user_message:
            md.append(f"**ela:** {turn.user_message}")
            md.append("")
        notes = [
            f"decisão {turn.decision}" if turn.decision else "",
            f"modo {turn.mode}" if turn.mode else "",
            f"{turn.latency_ms / 1000:.1f}s" if turn.latency_ms else "",
        ]
        if any(notes):
            md += [f"<sub>{' · '.join(n for n in notes if n)}</sub>", ""]
        if turn.question_asked:
            md += [f"> {turn.question_asked}", ""]
        for option in turn.abc_options or []:
            md += [f"> {option.label}) {option.text}"]

    facts = repo.list_facts(session_id)
    if facts:
        md += ["", "## Fatos", ""]
    for fact in facts:
        records.append({"kind": "fact", "data": fact.model_dump()})
        md.append(
            f"- [{fact.fact_id}] ({fact.finding_area}, {fact.kind}, {fact.origin}) "
            f'{fact.text} — "{fact.source_excerpt}"'
        )

    gaps = repo.list_gaps(session_id)
    if gaps:
        md += ["", "## Lacunas", ""]
    for gap in gaps:
        records.append({"kind": "gap", "data": gap.model_dump()})
        md.append(f"- ({gap.status}) {gap.description}")

    for layer_id in LAYERS_ORDER:
        synthesis = repo.latest_synthesis(session_id, layer_id)
        if synthesis is None:
            continue
        records.append({"kind": "synthesis", "data": synthesis.model_dump()})
        md += ["", f"# Síntese: {layer_id} (v{synthesis.version})", ""]
        for title, text in synthesis.content.items():
            md += [f"## {title}", "", text, ""]
        if synthesis.gaps:
            md += ["Lacunas: " + "; ".join(synthesis.gaps), ""]
        if synthesis.hypotheses:
            md += ["Hipóteses: " + "; ".join(synthesis.hypotheses), ""]
    return "\n".join(md) + "\n", records


def replay_script(records: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
    """The recorded conversation as the front replays it: the first question, then each of her
    answers with the reply she got, its latency and, on the closing turn, the map."""
    session = next(r["data"] for r in records if r["kind"] == "session")
    turns = sorted((r["data"] for r in records if r["kind"] == "turn"), key=lambda t: t["seq"])
    syntheses = [r["data"] for r in records if r["kind"] == "synthesis"]
    synthesis = syntheses[0] if syntheses else None
    onboarding = session.get("onboarding") or {}
    baseline = next((r["data"]["statement"] for r in records if r["kind"] == "baseline"), None)

    first_question = next((t["question_asked"] for t in turns if not t["user_message"]), "")
    replayed: list[dict[str, Any]] = []
    approved: str | None = None
    closed = False
    for turn in turns:
        said, reply = turn["user_message"], turn.get("question_asked") or ""
        if not said:
            continue
        if said == APPROVED_MARK:
            approved = reply
            continue
        closes = turn.get("decision") == "synthesize" or turn.get("mode") == "review"
        replayed.append(
            {
                "answer": said,
                "reply": reply,
                "abc_options": turn.get("abc_options"),
                "latency_ms": turn.get("latency_ms") or 0,
                "synthesis": synthesis if closes and synthesis else None,
            }
        )
        closed = closed or closes
    return {
        "label": label,
        "session_id": session["session_id"],
        "business": onboarding.get("offer"),
        "baseline": baseline,
        "first_question": first_question,
        "turns": replayed,
        "approved_message": approved,
        "layer_closed": closed,
    }


def write_replay(records: list[dict[str, Any]], label: str) -> Path:
    REPLAYS.mkdir(parents=True, exist_ok=True)
    out = REPLAYS / f"{label}.json"
    out.write_text(
        json.dumps(replay_script(records, label=label), ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    return out


def list_sessions(table_name: str) -> list[tuple[str, str, str]]:
    """(created_at, session_id, offer) of every session, newest first (one table Scan)."""
    import boto3
    from boto3.dynamodb.conditions import Attr
    from vv_contracts import keys
    from vv_contracts.state import Session

    table: Any = boto3.resource("dynamodb").Table(table_name)  # pyright: ignore[reportAttributeAccessIssue]
    kwargs: dict[str, Any] = {"FilterExpression": Attr("SK").eq(keys.SK_META)}
    rows: list[tuple[str, str, str]] = []
    while True:
        page = table.scan(**kwargs)
        for item in page["Items"]:
            s = Session.model_validate_json(str(item["data"]))
            offer = (s.onboarding.offer if s.onboarding else None) or "-"
            rows.append((s.created_at.isoformat(timespec="minutes"), s.session_id, offer))
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return sorted(rows, reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--table", help="DynamoDB table name (DataStack output)")
    parser.add_argument("--list", action="store_true", help="list sessions, newest first")
    parser.add_argument("--session", help="session id to export")
    parser.add_argument("--label", default="sessao", help="file name label")
    parser.add_argument("--replay", action="store_true", help="also write the demo replay")
    parser.add_argument("--from-jsonl", type=Path, help="convert an exported .jsonl to a replay")
    args = parser.parse_args()

    if args.from_jsonl:
        lines = args.from_jsonl.read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
        print(f"replay em {write_replay(records, args.label)}")
        return
    if not args.table:
        parser.error("--table is required unless --from-jsonl")

    if args.list:
        for created, sid, offer in list_sessions(args.table):
            print(f"{created}  {sid}  {offer}")
        return
    if not args.session:
        parser.error("--session is required unless --list")

    from vv_mcp.repo_dynamo import DynamoStateRepository

    md, records = render(DynamoStateRepository(args.table), args.session)
    RUNS.mkdir(parents=True, exist_ok=True)
    stem = RUNS / f"{datetime.now():%Y%m%d-%H%M}-{args.label}"
    stem.with_suffix(".md").write_text(md, encoding="utf-8")
    stem.with_suffix(".jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in records),
        encoding="utf-8",
    )
    print(f"salvo em {stem}.md e .jsonl")
    if args.replay:
        print(f"replay em {write_replay(json.loads(json.dumps(records, default=str)), args.label)}")


if __name__ == "__main__":
    main()
