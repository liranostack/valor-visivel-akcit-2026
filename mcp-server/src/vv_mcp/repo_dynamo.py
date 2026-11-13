"""DynamoDB single-table StateRepository (ERD, 'Modelo de dados e padrões de acesso').

PK = SESSION#<session_id>; SKs from vv_contracts.keys. Each item stores the model as JSON in
`data` (avoids float/Decimal conversions) plus `ttl` (epoch seconds of the session's
retention_until, 30 days by default). No secondary indexes: every read is a Query by PK.
"""

from datetime import datetime
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from pydantic import BaseModel
from vv_contracts import keys
from vv_contracts.common import FactKind, FindingArea, LayerId
from vv_contracts.state import (
    Baseline,
    EssentialCore,
    Evaluation,
    Fact,
    Gap,
    GapStatus,
    PreCore,
    PublicContextRecord,
    Review,
    Session,
    SessionState,
    StageProgress,
    StoredSynthesis,
    Turn,
    retention_until,
)


def create_table(dynamodb: Any, table_name: str) -> Any:
    """Create the table as the CDK DataStack does (used by tests and local runs)."""
    table = dynamodb.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


class DynamoStateRepository:
    """Implements vv_contracts.ports.StateRepository."""

    def __init__(self, table_name: str, dynamodb: Any | None = None) -> None:
        resource: Any = dynamodb if dynamodb is not None else boto3.resource("dynamodb")
        self._table = resource.Table(table_name)
        self._ttl_cache: dict[str, int] = {}

    # --- low level -------------------------------------------------------------------------
    def _ttl(self, session_id: str) -> int:
        if session_id not in self._ttl_cache:
            meta = self._table.get_item(Key={"PK": keys.pk(session_id), "SK": keys.SK_META})
            if "Item" not in meta:
                raise KeyError(f"unknown session {session_id!r}")
            self._ttl_cache[session_id] = int(meta["Item"]["ttl"])
        return self._ttl_cache[session_id]

    def _put(self, session_id: str, sk: str, model: BaseModel) -> None:
        self._table.put_item(
            Item={
                "PK": keys.pk(session_id),
                "SK": sk,
                "ttl": self._ttl(session_id),
                "data": model.model_dump_json(),
            }
        )

    def _get_item(self, session_id: str, sk: str) -> str | None:
        res = self._table.get_item(Key={"PK": keys.pk(session_id), "SK": sk})
        return res["Item"]["data"] if "Item" in res else None

    def _query(self, session_id: str, prefix: str | None = None) -> list[dict[str, Any]]:
        condition = Key("PK").eq(keys.pk(session_id))
        if prefix:
            condition = condition & Key("SK").begins_with(prefix)
        kwargs: dict[str, Any] = {"KeyConditionExpression": condition}
        found: list[dict[str, Any]] = []
        while True:
            page = self._table.query(**kwargs)
            found.extend(page["Items"])
            if "LastEvaluatedKey" not in page:
                return found
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    # --- session ---------------------------------------------------------------------------
    def put_session(self, session: Session) -> None:
        until: datetime = session.retention_until or retention_until()
        ttl = int(until.timestamp())
        self._ttl_cache[session.session_id] = ttl
        self._put(session.session_id, keys.SK_META, session)

    def get_state(self, session_id: str) -> SessionState | None:
        rows = self._query(session_id)
        by_sk = {r["SK"]: r["data"] for r in rows}
        if keys.SK_META not in by_sk:
            return None
        turns = [
            Turn.model_validate_json(d)
            for sk, d in sorted(by_sk.items())
            if sk.startswith(keys.TURN_PREFIX)
        ]
        gaps = [
            Gap.model_validate_json(d) for sk, d in by_sk.items() if sk.startswith(keys.GAP_PREFIX)
        ]
        baseline = by_sk.get(keys.SK_BASELINE)
        context = by_sk.get(keys.SK_CONTEXT)
        return SessionState(
            session=Session.model_validate_json(by_sk[keys.SK_META]),
            baseline=Baseline.model_validate_json(baseline) if baseline else None,
            public_context=PublicContextRecord.model_validate_json(context) if context else None,
            progress=[
                StageProgress.model_validate_json(d)
                for sk, d in sorted(by_sk.items())
                if sk.startswith(keys.PROGRESS_PREFIX)
            ],
            open_gaps=[g for g in gaps if g.status == "open"],
            last_turn_seq=turns[-1].seq if turns else 0,
            asked_questions=[t.question_asked for t in turns if t.question_asked],
        )

    def save_baseline(self, session_id: str, baseline: Baseline) -> None:
        self._put(session_id, keys.SK_BASELINE, baseline)

    def save_public_context(self, session_id: str, context: PublicContextRecord) -> None:
        self._put(session_id, keys.SK_CONTEXT, context)

    def save_turn(self, session_id: str, turn: Turn) -> int:
        self._put(session_id, keys.sk_turn(turn.seq), turn)
        return turn.seq

    def list_turns(self, session_id: str) -> list[Turn]:
        return [
            Turn.model_validate_json(r["data"]) for r in self._query(session_id, keys.TURN_PREFIX)
        ]

    def update_stage_progress(self, session_id: str, progress: StageProgress) -> None:
        self._put(session_id, keys.sk_progress(progress.stage_id), progress)

    def flagged_stages(self, session_id: str) -> list[StageProgress]:
        rows = self._query(session_id, keys.PROGRESS_PREFIX)
        progress = [StageProgress.model_validate_json(r["data"]) for r in rows]
        return [p for p in progress if p.flagged_for_review]

    # --- facts and gaps --------------------------------------------------------------------
    def save_fact(self, session_id: str, fact: Fact) -> str:
        self._put(session_id, keys.sk_fact(fact.layer_id, fact.fact_id), fact)
        return fact.fact_id

    def list_facts(
        self,
        session_id: str,
        layer_id: LayerId | None = None,
        finding_area: FindingArea | None = None,
        kind: FactKind | None = None,
    ) -> list[Fact]:
        rows = self._query(session_id, keys.fact_prefix(layer_id))
        facts = [Fact.model_validate_json(r["data"]) for r in rows]
        return [
            f
            for f in facts
            if (finding_area is None or f.finding_area == finding_area)
            and (kind is None or f.kind == kind)
        ]

    def save_gap(self, session_id: str, gap: Gap) -> str:
        self._put(session_id, keys.sk_gap(gap.layer_id, gap.gap_id), gap)
        return gap.gap_id

    def list_gaps(
        self, session_id: str, layer_id: LayerId | None = None, status: GapStatus | None = None
    ) -> list[Gap]:
        rows = self._query(session_id, keys.gap_prefix(layer_id))
        gaps = [Gap.model_validate_json(r["data"]) for r in rows]
        return [g for g in gaps if status is None or g.status == status]

    def update_gap(
        self, session_id: str, gap_id: str, status: GapStatus, fact_id: str | None = None
    ) -> None:
        current = next((g for g in self.list_gaps(session_id) if g.gap_id == gap_id), None)
        if current is None:
            raise KeyError(f"unknown gap {gap_id!r}")
        updated = Gap.model_validate(
            current.model_dump() | {"status": status, "resolved_by_fact": fact_id}
        )
        self.save_gap(session_id, updated)

    # --- deliverables ----------------------------------------------------------------------
    def latest_synthesis(self, session_id: str, layer_id: LayerId) -> StoredSynthesis | None:
        res = self._table.query(
            KeyConditionExpression=Key("PK").eq(keys.pk(session_id))
            & Key("SK").begins_with(keys.synthesis_prefix(layer_id)),
            ScanIndexForward=False,
            Limit=1,
        )
        rows = res["Items"]
        return StoredSynthesis.model_validate_json(rows[0]["data"]) if rows else None

    def save_synthesis(self, session_id: str, synthesis: StoredSynthesis) -> int:
        latest = self.latest_synthesis(session_id, synthesis.layer_id)
        version = 1 if latest is None else latest.version + 1
        stored = synthesis.model_copy(update={"version": version})
        self._put(session_id, keys.sk_synthesis(synthesis.layer_id, version), stored)
        return version

    def save_review(self, session_id: str, review: Review) -> None:
        seq = len(self._query(session_id, keys.REVIEW_PREFIX)) + 1
        self._put(session_id, keys.sk_review(seq), review)

    def reviews(self, session_id: str) -> list[Review]:
        return [
            Review.model_validate_json(r["data"])
            for r in self._query(session_id, keys.REVIEW_PREFIX)
        ]

    def save_pre_core(self, session_id: str, pre_core: PreCore) -> None:
        self._put(session_id, keys.SK_PRECORE, pre_core)

    def save_core(self, session_id: str, core: EssentialCore) -> None:
        self._put(session_id, keys.SK_CORE, core)

    def core(self, session_id: str) -> EssentialCore | None:
        data = self._get_item(session_id, keys.SK_CORE)
        return EssentialCore.model_validate_json(data) if data else None

    def save_evaluation(self, session_id: str, evaluation: Evaluation) -> None:
        self._put(session_id, keys.sk_eval(evaluation.turn_seq, evaluation.metric), evaluation)
