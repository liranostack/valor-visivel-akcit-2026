"""Essential Core Synthesizer: final deliverable after all 4 layers are approved.

Operates across the full journey: loads all facts from all layers, all layer syntheses, and the
essential_core template, then generates EssentialCoreOutput (content + final_statement +
before_after + action_plan_7d + gaps + outputs). Mirrors synthesizer.py's guard pattern:
one retry, then a traceable fallback.
"""

import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field
from vv_contracts.agents import ApplicationOutputs, BeforeAfter, EssentialCoreOutput
from vv_contracts.common import LAYERS_ORDER, NonEmptyStr
from vv_contracts.ports import ToolGateway
from vv_contracts.state import Fact
from vv_contracts.tools import GetSynthesisTemplateIn, ListFactsIn, ListGapsIn

from vv_chat.agents.llm import StructuredLLM
from vv_chat.business import render_profile
from vv_chat.prompts import load_prompt
from vv_chat.style import no_em_dash

log = logging.getLogger(__name__)

FACT_REF = re.compile(r"\[fact:([^\]\s]+)\]")
GAPS_SECTION = "Lacunas e hipóteses"
UNKNOWN = "Ainda não sabemos."


class CoreError(ValueError):
    """The core output cites unknown facts."""


class CoreContext(BaseModel):
    session_id: NonEmptyStr
    profile: dict[str, str] = Field(
        default_factory=dict[str, str],
        description="Onboarding + baseline answers, citable by id.",
    )


@dataclass(frozen=True)
class CoreResult:
    core: EssentialCoreOutput
    used_fallback: bool
    prompt_version: str
    fallback_reason: str | None = None


# --- structured output the model writes --------------------------------------------------------


class _CoreDraftSection(BaseModel):
    title: NonEmptyStr
    markdown: str


class _ApplicationOutputsDraft(BaseModel):
    bio: str = Field(min_length=10, max_length=220)
    narrativa: str = Field(min_length=20, max_length=520)
    checklist: list[str] = Field(min_length=3, max_length=7)
    whatsapp_pitch_curto: str = Field(min_length=10, max_length=300)
    whatsapp_pitch_prova: str = Field(min_length=10, max_length=300)
    instagram_bio: str = Field(min_length=10, max_length=220)
    instagram_legenda_curta: str = Field(min_length=10, max_length=300)
    instagram_story_roteiro: list[str] = Field(min_length=3, max_length=5)


class _BeforeAfterDraft(BaseModel):
    said_before: NonEmptyStr
    sustained_discovery: NonEmptyStr
    now_able_to: NonEmptyStr
    fact_refs: list[str] = Field(default_factory=list[str])


class _CoreDraft(BaseModel):
    """What the model writes: flat lists so structured output can express it."""

    sections: list[_CoreDraftSection]
    final_statement: NonEmptyStr
    before_after: _BeforeAfterDraft
    action_plan_7d: list[NonEmptyStr] = Field(min_length=7, max_length=7)
    gaps: list[str] = Field(default_factory=list[str])
    outputs: _ApplicationOutputsDraft

    def to_output(self) -> EssentialCoreOutput:
        content = {s.title: no_em_dash(s.markdown) for s in self.sections}
        return EssentialCoreOutput(
            content=content,
            final_statement=self.final_statement,
            before_after=BeforeAfter(
                said_before=self.before_after.said_before,
                sustained_discovery=self.before_after.sustained_discovery,
                now_able_to=self.before_after.now_able_to,
                fact_refs=self.before_after.fact_refs,
            ),
            action_plan_7d=list(self.action_plan_7d),
            gaps=list(self.gaps),
            outputs=ApplicationOutputs(
                bio=self.outputs.bio,
                narrativa=self.outputs.narrativa,
                checklist=list(self.outputs.checklist),
                whatsapp_pitch_curto=self.outputs.whatsapp_pitch_curto,
                whatsapp_pitch_prova=self.outputs.whatsapp_pitch_prova,
                instagram_bio=self.outputs.instagram_bio,
                instagram_legenda_curta=self.outputs.instagram_legenda_curta,
                instagram_story_roteiro=list(self.outputs.instagram_story_roteiro),
            ),
        )


# --- validation ---------------------------------------------------------------------------------


def _cited(content: dict[str, str]) -> list[str]:
    seen: dict[str, None] = {}
    for text in content.values():
        for fid in FACT_REF.findall(text):
            seen.setdefault(fid, None)
    return list(seen)


def _strip_unknown_refs(output: EssentialCoreOutput, known: set[str]) -> EssentialCoreOutput:
    """Remove [fact:xyz] citations that don't exist in known rather than rejecting the output."""
    unknown = {f for f in _cited(output.content) if f not in known}
    if not unknown:
        return output
    log.warning("stripping %d unknown fact refs from core content: %s", len(unknown), unknown)
    pattern = re.compile(r"\s*\[fact:(" + "|".join(re.escape(u) for u in unknown) + r")\]")
    clean = {title: pattern.sub("", text) for title, text in output.content.items()}
    clean_refs = [r for r in output.before_after.fact_refs if r in known]
    return output.model_copy(
        update={
            "content": clean,
            "before_after": output.before_after.model_copy(update={"fact_refs": clean_refs}),
        }
    )


# --- helpers ------------------------------------------------------------------------------------


async def _all_facts(session_id: str, gateway: ToolGateway) -> list[Fact]:
    out = await gateway.list_facts(ListFactsIn(session_id=session_id))
    return [f for f in out.facts if f.active]


def _fact_lines(facts: list[Fact]) -> str:
    return (
        "\n".join(
            f"- [{f.fact_id}] (layer:{f.layer_id}, {f.finding_area}, {f.kind}) {f.text}"
            for f in facts
        )
        or "(none)"
    )


async def _open_gaps_across_layers(session_id: str, gateway: ToolGateway) -> list[str]:
    gaps: list[str] = []
    for layer_id in LAYERS_ORDER:
        result = await gateway.list_gaps(
            ListGapsIn(session_id=session_id, layer_id=layer_id, status="open")
        )
        gaps.extend(g.description for g in result.gaps)
    return gaps


def _user_prompt(
    template: str,
    facts: list[Fact],
    open_gaps: list[str],
    profile: dict[str, str],
    syntheses_text: str,
) -> str:
    gaps_text = "\n".join(f"- {g}" for g in open_gaps) or "(none)"
    body = template.strip() or "(no template: use clear section titles)"
    return "\n\n".join(
        [
            f"<template>\n{body}\n</template>",
            f"<business>\n{render_profile(profile)}\n</business>",
            f"<facts>\n{_fact_lines(facts)}\n</facts>",
            f"<syntheses>\n{syntheses_text}\n</syntheses>",
            f"<open_gaps>\n{gaps_text}\n</open_gaps>",
        ]
    )


def _fallback_output(
    facts: list[Fact], gaps: list[str], profile: dict[str, str]
) -> EssentialCoreOutput:
    stated = [f for f in facts if f.kind != "hypothesis" and f.origin != "public_source"]
    lines = "\n".join(f"- {f.text} [fact:{f.fact_id}]" for f in stated) or "- (nada ainda)"
    baseline = profile.get("baseline", "")
    return EssentialCoreOutput(
        content={"O que você contou": lines},
        final_statement=baseline[:220] if baseline else "Ainda não sabemos.",
        before_after=BeforeAfter(
            said_before=baseline or "Não registrado.",
            sustained_discovery=(
                "A conversa levantou fatos, mas a síntese final não pôde ser gerada."
            ),
            now_able_to="Verificar as lacunas listadas antes de comunicar o valor.",
            fact_refs=[],
        ),
        action_plan_7d=[
            "Dia 1: Revise o que ficou como lacuna nesta conversa.",
            "Dia 2: Escolha um fato levantado e use-o em uma apresentação.",
            "Dia 3: Peça a um cliente recente para descrever seu trabalho com as palavras dele.",
            "Dia 4: Identifique a prova mais concreta que você tem disponível.",
            "Dia 5: Teste a narrativa curta em conversa informal.",
            "Dia 6: Anote o que funcionou e o que gerou dúvida.",
            "Dia 7: Defina o próximo passo para fechar a lacuna principal.",
        ],
        gaps=gaps,
        outputs=ApplicationOutputs(
            bio="Ainda não gerado — verifique as lacunas.",
            narrativa="Ainda não gerado — verifique as lacunas.",
            checklist=[
                "Revisar lacunas da conversa",
                "Testar narrativa curta",
                "Coletar evidência da entrega",
            ],
            whatsapp_pitch_curto="Ainda não gerado — verifique as lacunas.",
            whatsapp_pitch_prova="Ainda não gerado — verifique as lacunas.",
            instagram_bio="Ainda não gerado.",
            instagram_legenda_curta="Ainda não gerado.",
            instagram_story_roteiro=["Card 1: (a gerar)", "Card 2: (a gerar)", "Card 3: (a gerar)"],
        ),
    )


# --- main entry point ---------------------------------------------------------------------------


async def synthesize_core(
    context: CoreContext, gateway: ToolGateway, llm: StructuredLLM
) -> CoreResult:
    try:
        template = (
            await gateway.get_synthesis_template(GetSynthesisTemplateIn(kind="core"))
        ).markdown
    except Exception as exc:
        log.warning("core template unavailable: %s", type(exc).__name__)
        template = ""

    facts = await _all_facts(context.session_id, gateway)
    open_gaps = await _open_gaps_across_layers(context.session_id, gateway)
    known = {f.fact_id for f in facts} | set(context.profile)

    # Summarise facts per layer as synthesis context (no list_syntheses tool available)
    syntheses_parts: list[str] = []
    for layer_id in LAYERS_ORDER:
        layer_facts = [f for f in facts if f.layer_id == layer_id]
        if layer_facts:
            lines = "\n".join(f"  - [{f.fact_id}] {f.text}" for f in layer_facts[:12])
            syntheses_parts.append(f"### {layer_id}\n{lines}")
    syntheses_text = "\n\n".join(syntheses_parts) or "(no layer facts available)"

    prompt = load_prompt("core_synthesizer")
    user = _user_prompt(template, facts, open_gaps, context.profile, syntheses_text)

    reason: str | None = None
    for attempt in range(2):
        try:
            draft = await llm.generate(prompt.text, user, _CoreDraft)
            raw = draft.to_output()
        except Exception as exc:
            reason = f"{type(exc).__name__}: {str(exc)[:300]}"
            log.warning("core_synthesizer attempt %d failed: %s", attempt + 1, reason)
            continue
        return CoreResult(_strip_unknown_refs(raw, known), False, prompt.version)

    return CoreResult(
        _fallback_output(facts, open_gaps, context.profile), True, prompt.version, reason
    )
