"""Layer Synthesizer: writes the synthesis of one layer from the KB template and the facts.

Large model (ADR-011). Deterministic guards: every [fact:<id>] must exist (one retry, then a
traceable fallback); fact_refs are recomputed from the content; open gaps are always listed; a
layer without any 'blind' fact records the gap BLIND_GAP instead of supposing external
perception. refine_section rewrites one section and keeps the others byte for byte.
Source: reference/ts-engine layer-reading.ts, outputs.ts, refine.ts.
"""

import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field
from vv_contracts.agents import LayerSynthesis
from vv_contracts.common import LayerId, NonEmptyStr
from vv_contracts.ports import ToolGateway
from vv_contracts.state import Fact, StoredSynthesis
from vv_contracts.tools import GetSynthesisTemplateIn, ListFactsIn, ListGapsIn

from vv_chat.agents.llm import StructuredLLM
from vv_chat.business import render_profile
from vv_chat.prompts import load_prompt
from vv_chat.style import no_em_dash

log = logging.getLogger(__name__)

BLIND_GAP = "Percepção de quem compra não mapeada: ainda não sabemos o que essas pessoas dizem."
FACT_REF = re.compile(r"\[fact:([^\]\s]+)\]")
FALLBACK_SECTION = "O que você contou"
GAPS_SECTION = "Lacunas e hipóteses"
UNKNOWN = "Ainda não sabemos."


class SynthesisError(ValueError):
    """The synthesis cites unknown facts or hides open gaps."""


class SynthesizeContext(BaseModel):
    session_id: NonEmptyStr
    layer_id: LayerId
    profile: dict[str, str] = Field(
        default_factory=dict[str, str],
        description="What she said before the layers (onboarding, baseline), citable by id.",
    )


class DraftSection(BaseModel):
    """One section of the synthesis."""

    title: NonEmptyStr = Field(description="Section title, exactly as in the template (pt-BR).")
    markdown: str = Field(
        description="Section content in pt-BR Markdown; every claim ends with [fact:<id>]."
    )


class SynthesisDraft(BaseModel):
    """What the model writes: sections as a list (structured output cannot express a dict)."""

    sections: list[DraftSection] = Field(description="Sections in the template order.")
    gaps: list[str] = Field(
        default_factory=list[str], description="What remains unsupported, pt-BR."
    )
    hypotheses: list[str] = Field(
        default_factory=list[str],
        description="Plausible readings not yet supported by evidence, labelled as such.",
    )

    def to_synthesis(self, layer_id: LayerId) -> LayerSynthesis:
        content = {s.title: s.markdown for s in self.sections}
        return LayerSynthesis(
            layer_id=layer_id,
            content=content,
            fact_refs=cited(content),
            gaps=list(self.gaps),
            hypotheses=list(self.hypotheses),
        )


class RefinedSection(BaseModel):
    """One rewritten section of a synthesis."""

    markdown: NonEmptyStr = Field(
        description="New Markdown of the section in pt-BR; every claim ends with [fact:<id>]."
    )


@dataclass(frozen=True)
class Synthesis:
    synthesis: LayerSynthesis
    used_fallback: bool
    prompt_version: str
    fallback_reason: str | None = None


def cited(content: dict[str, str]) -> list[str]:
    seen: dict[str, None] = {}
    for text in content.values():
        for fid in FACT_REF.findall(text):
            seen.setdefault(fid, None)
    return list(seen)


def validate_synthesis(
    synthesis: LayerSynthesis, known_fact_ids: set[str], open_gaps: list[str]
) -> None:
    unknown = [f for f in cited(synthesis.content) if f not in known_fact_ids]
    if unknown:
        raise SynthesisError(f"unknown fact ids: {', '.join(unknown)}")
    missing = [g for g in open_gaps if g not in synthesis.gaps]
    if missing:
        raise SynthesisError(f"open gap not listed: {missing[0]}")


async def synthesize_layer(
    context: SynthesizeContext, gateway: ToolGateway, llm: StructuredLLM
) -> Synthesis:
    try:
        template = (
            await gateway.get_synthesis_template(GetSynthesisTemplateIn(kind=context.layer_id))
        ).markdown
    except Exception as exc:  # a missing template must not stop the layer from closing
        log.warning("synthesis template unavailable: %s", type(exc).__name__)
        template = ""
    facts = await _facts(context, gateway)
    open_gaps = [
        g.description
        for g in (
            await gateway.list_gaps(
                ListGapsIn(session_id=context.session_id, layer_id=context.layer_id, status="open")
            )
        ).gaps
    ]
    required_gaps = open_gaps + (
        # Only someone else's words close it; her guess about clients stays a hypothesis
        # (lead's method guide, 13/11).
        []
        if any(f.finding_area == "blind" and f.origin == "external_perception" for f in facts)
        else [BLIND_GAP]
    )
    known = {f.fact_id for f in facts} | set(context.profile)
    prompt = load_prompt("synthesizer_layer")
    user = _user_prompt(template, facts, open_gaps, context.profile)

    reason: str | None = None
    for attempt in range(2):  # one retry: a model failure or a rejected draft
        try:
            draft = await llm.generate(prompt.text, user, SynthesisDraft)
            raw = draft.to_synthesis(context.layer_id)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {str(exc)[:300]}"
            log.warning("synthesizer attempt %d failed: %s", attempt + 1, reason)
            continue
        result = _complete(raw, context.layer_id, required_gaps)
        try:
            validate_synthesis(result, known, required_gaps)
        except SynthesisError as exc:
            reason = f"SynthesisError: {exc}"
            if attempt == 0:
                user += f"\n\nYour previous synthesis was rejected: {exc}. Fix it."
            continue
        return Synthesis(result, False, prompt.version)
    return Synthesis(fallback(context.layer_id, facts, required_gaps), True, prompt.version, reason)


async def refine_section(
    context: SynthesizeContext,
    current: StoredSynthesis,
    section: str,
    notes: str,
    gateway: ToolGateway,
    llm: StructuredLLM,
) -> LayerSynthesis:
    """Rewrite one section; on any failure the synthesis stays as it was."""
    facts = await _facts(context, gateway)
    known = {f.fact_id for f in facts} | set(context.profile)
    prompt = load_prompt("synthesizer_refine")
    user = "\n\n".join(
        [
            f"<section>\n## {section}\n{current.content.get(section, '')}\n</section>",
            f"<request>\n{notes}\n</request>",
            f"<facts>\n{_fact_lines(facts)}\n</facts>",
            f"<business>\n{render_profile(context.profile)}\n</business>",
        ]
    )
    base = LayerSynthesis(
        layer_id=current.layer_id,
        content=dict(current.content),
        fact_refs=list(current.fact_refs),
        gaps=list(current.gaps),
        hypotheses=list(current.hypotheses),
    )
    try:
        new = await llm.generate(prompt.text, user, RefinedSection)
    except Exception as exc:
        log.warning("refine fallback: %s", type(exc).__name__)
        return base
    if any(f not in known for f in FACT_REF.findall(new.markdown)):
        return base
    content = dict(current.content) | {section: new.markdown.strip()}
    return base.model_copy(update={"content": content, "fact_refs": cited(content)})


def fallback(layer_id: LayerId, facts: list[Fact], gaps: list[str]) -> LayerSynthesis:
    """No model: list what she said, each line cited; hypotheses stay hypotheses."""
    stated = [f for f in facts if f.kind != "hypothesis" and f.origin != "public_source"]
    lines = "\n".join(f"- {f.text} [fact:{f.fact_id}]" for f in stated) or "- (nada ainda)"
    content = {FALLBACK_SECTION: lines}
    return LayerSynthesis(
        layer_id=layer_id,
        content=content,
        fact_refs=cited(content),
        gaps=list(gaps),
        hypotheses=[f.text for f in facts if f not in stated],
    )


SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _trim_uncited_tail(line: str, removed: list[str]) -> str:
    """Drop sentences after the last citation of a line: a claim must end with its source, and
    an uncited sentence after it is the model adding something (A.06.11)."""
    if not FACT_REF.search(line):
        return line
    sentences = SENTENCE_END.split(line)
    last = max(i for i, s in enumerate(sentences) if FACT_REF.search(s))
    removed.extend(s for s in sentences[last + 1 :] if s.strip())
    return " ".join(sentences[: last + 1])


def drop_uncited(content: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Remove paragraphs with no [fact:<id>] (outside the gaps section); she never reads a claim
    that is not traceable to something she said. Returns the content and what was removed."""
    cleaned: dict[str, str] = {}
    removed: list[str] = []
    for title, text in content.items():
        if title == GAPS_SECTION or text.strip().startswith("Ainda não"):
            cleaned[title] = text
            continue
        kept: list[str] = []
        for paragraph in (p.strip() for p in text.split("\n\n")):
            if not paragraph:
                continue
            if not FACT_REF.search(paragraph):
                removed.append(paragraph)
                continue
            lines = [_trim_uncited_tail(line, removed) for line in paragraph.split("\n")]
            kept.append("\n".join(lines))
        cleaned[title] = "\n\n".join(kept) if kept else UNKNOWN
    return cleaned, removed


def _complete(raw: LayerSynthesis, layer_id: LayerId, required_gaps: list[str]) -> LayerSynthesis:
    gaps = list(raw.gaps) + [g for g in required_gaps if g not in raw.gaps]
    content, removed = drop_uncited({k: no_em_dash(v) for k, v in raw.content.items()})
    if removed:
        log.warning("synthesis: %d uncited paragraph(s) removed", len(removed))
    return raw.model_copy(
        update={
            "layer_id": layer_id,
            "content": content,
            "fact_refs": cited(content),
            "gaps": gaps,
        }
    )


async def _facts(context: SynthesizeContext, gateway: ToolGateway) -> list[Fact]:
    out = await gateway.list_facts(
        ListFactsIn(session_id=context.session_id, layer_id=context.layer_id)
    )
    return [f for f in out.facts if f.active]


def _fact_lines(facts: list[Fact]) -> str:
    return (
        "\n".join(f"- [{f.fact_id}] ({f.finding_area}, {f.kind}) {f.text}" for f in facts)
        or "(none)"
    )


def _user_prompt(
    template: str, facts: list[Fact], open_gaps: list[str], profile: dict[str, str] | None = None
) -> str:
    gaps = "\n".join(f"- {g}" for g in open_gaps) or "(none)"
    body = template.strip() or "(no template: use clear section titles)"
    return "\n\n".join(
        [
            f"<template>\n{body}\n</template>",
            f"<business>\n{render_profile(profile or {})}\n</business>",
            f"<facts>\n{_fact_lines(facts)}\n</facts>",
            f"<open_gaps>\n{gaps}\n</open_gaps>",
        ]
    )
