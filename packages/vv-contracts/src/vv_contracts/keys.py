"""DynamoDB single-table keys. PK is always SESSION#<session_id>.

Numeric parts are zero-padded so that lexical order equals numeric order
(needed for "latest synthesis" = Query desc, limit 1).
"""

PK_PREFIX = "SESSION#"
SK_META = "META"
SK_BASELINE = "BASELINE"
SK_CONTEXT = "CONTEXT"
SK_PRECORE = "PRECORE"
SK_CORE = "CORE"
PROGRESS_PREFIX = "PROG#"
TURN_PREFIX = "TURN#"
FACT_PREFIX = "FACT#"
GAP_PREFIX = "GAP#"
SYNTHESIS_PREFIX = "SYN#"
EVAL_PREFIX = "EVAL#"
REVIEW_PREFIX = "REVIEW#"


def _pad(n: int, width: int) -> str:
    if n < 0:
        raise ValueError("key numbers must be non-negative")
    return str(n).zfill(width)


def pk(session_id: str) -> str:
    return f"{PK_PREFIX}{session_id}"


def sk_progress(stage_id: str) -> str:
    return f"{PROGRESS_PREFIX}{stage_id}"


def sk_turn(seq: int) -> str:
    return f"{TURN_PREFIX}{_pad(seq, 6)}"


def sk_fact(layer_id: str, fact_id: str) -> str:
    return f"{FACT_PREFIX}{layer_id}#{fact_id}"


def sk_gap(layer_id: str, gap_id: str) -> str:
    return f"{GAP_PREFIX}{layer_id}#{gap_id}"


def sk_synthesis(layer_id: str, version: int) -> str:
    return f"{SYNTHESIS_PREFIX}{layer_id}#v{_pad(version, 4)}"


def sk_eval(turn_seq: int, metric: str) -> str:
    return f"{EVAL_PREFIX}{_pad(turn_seq, 6)}#{metric}"


def sk_review(seq: int) -> str:
    return f"{REVIEW_PREFIX}{_pad(seq, 4)}"


def fact_prefix(layer_id: str | None = None) -> str:
    return FACT_PREFIX if layer_id is None else f"{FACT_PREFIX}{layer_id}#"


def gap_prefix(layer_id: str | None = None) -> str:
    return GAP_PREFIX if layer_id is None else f"{GAP_PREFIX}{layer_id}#"


def synthesis_prefix(layer_id: str) -> str:
    return f"{SYNTHESIS_PREFIX}{layer_id}#"
