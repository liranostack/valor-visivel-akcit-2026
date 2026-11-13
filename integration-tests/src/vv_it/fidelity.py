"""Deterministic method checks over a journey (A.02.21): no model, same answer every time.

- layer_closed: the layer reached its synthesis (1) or not (0).
- quadrant_coverage: the layer has a hidden fact and a blind one (a client's account), or the
  missing blind is registered as a gap in the synthesis (1/0).
- hypothesis_as_fact: synthesis paragraphs outside the hypotheses section that cite a hypothesis,
  an inference or a public source (count; ERD: 0).
- synthesis_traceability: share of synthesis paragraphs ending in a [fact:<id>] (ERD: 100%).
- non_repetition: questions that repeat an earlier one (token_set_ratio ≥ 85; ERD: 0).
- turns, median_latency_s: informative, no threshold by default.
"""

import re
from statistics import median
from typing import Any

from pydantic import BaseModel
from rapidfuzz import fuzz
from vv_chat.agents.synthesizer import GAPS_SECTION

from vv_it.journey import JourneyRecord

FACT_REF = re.compile(r"\[fact:([^\]\s]+)\]")
REPEAT_SIMILARITY = 85
CLOSING_PREFIXES = ("Fechamos esta parte", "Uma leitura para você conferir", "Mapa aprovado")
HYPOTHESES_SECTION = re.compile(r"lacunas|hip[oó]tes|leitura", re.IGNORECASE)


class Check(BaseModel):
    metric: str
    value: float
    detail: str = ""


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _content(record: JourneyRecord) -> dict[str, str]:
    content: dict[str, Any] = (record.synthesis or {}).get("content") or {}
    return {str(k): str(v) for k, v in content.items()}


def deterministic_checks(record: JourneyRecord) -> list[Check]:
    content = _content(record)
    facts = {f["fact_id"]: f for f in record.facts}
    checks = [Check(metric="layer_closed", value=1 if record.synthesis else 0, detail=record.ended)]

    has_hidden = any(f["finding_area"] == "hidden" for f in record.facts)
    has_blind = any(f["origin"] == "external_perception" for f in record.facts)
    gap_registered = bool((record.synthesis or {}).get("gaps"))
    covered = has_hidden and (has_blind or gap_registered)
    checks.append(
        Check(
            metric="quadrant_coverage",
            value=1 if covered else 0,
            detail=f"oculto={has_hidden}, relato externo={has_blind}, lacuna={gap_registered}",
        )
    )

    misused: list[str] = []
    cited = total = 0
    for title, text in content.items():
        in_hypotheses = bool(HYPOTHESES_SECTION.search(title))
        for paragraph in _paragraphs(text):
            refs = FACT_REF.findall(paragraph)
            # Same exemptions as the Synthesizer's drop_uncited: gaps and "Ainda não…" are
            # uncited on purpose.
            if title == GAPS_SECTION or paragraph.startswith("Ainda não"):
                continue
            total += 1
            cited += 1 if refs else 0
            if in_hypotheses:
                continue
            for ref in refs:
                fact = facts.get(ref)
                if fact and (
                    fact["kind"] == "hypothesis" or fact["origin"] in ("inference", "public_source")
                ):
                    misused.append(f"{title}: {ref}")
    checks.append(Check(metric="hypothesis_as_fact", value=len(misused), detail="; ".join(misused)))
    if total:
        checks.append(
            Check(
                metric="synthesis_traceability",
                value=round(cited / total, 3),
                detail=f"{cited}/{total} parágrafos com fonte",
            )
        )

    asked = [record.first_question] + [t.reply for t in record.turns]
    repeats = [
        f"turno {i + 1}"
        for i, question in enumerate(asked)
        if question
        and any(fuzz.token_set_ratio(question, before) >= REPEAT_SIMILARITY for before in asked[:i])
    ]
    checks.append(Check(metric="non_repetition", value=len(repeats), detail=", ".join(repeats)))

    # Voice guide: no long dash in anything she reads (questions and map).
    read = [t.reply for t in record.turns] + list(content.values())
    checks.append(Check(metric="em_dash", value=sum(text.count("—") for text in read)))

    # vv V2 criterion: messages that ask something end in exactly one question (closing excluded).
    asking = [
        t.reply.split("\n\nA) ")[0]  # options A/B/C come after the question
        for t in record.turns
        if not t.reply.startswith(CLOSING_PREFIXES)
    ]
    if asking:
        ok = sum(1 for r in asking if r.rstrip().endswith("?") and r.count("?") == 1)
        checks.append(Check(metric="question_coverage", value=round(ok / len(asking), 2)))

    checks.append(Check(metric="turns", value=len(record.turns)))
    latencies = [t.latency_ms for t in record.turns if t.latency_ms]
    if latencies:
        checks.append(Check(metric="median_latency_s", value=round(median(latencies) / 1000, 1)))
    return checks
