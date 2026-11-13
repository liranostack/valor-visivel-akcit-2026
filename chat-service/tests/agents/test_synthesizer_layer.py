"""Layer Synthesizer: every claim traceable to a fact, gaps never hidden, partial refine."""

import json
from typing import Any, TypeVar

from pydantic import BaseModel
from vv_chat.agents.synthesizer import (
    BLIND_GAP,
    SynthesisError,
    SynthesizeContext,
    refine_section,
    synthesize_layer,
    validate_synthesis,
)
from vv_chat.gateway.fake import FakeToolGateway
from vv_contracts.agents import ExtractedFact, InterpretationScores, LayerSynthesis
from vv_contracts.common import FactKind, FactOrigin, FindingArea
from vv_contracts.state import StoredSynthesis
from vv_contracts.tools import SaveFactIn, SaveGapIn

T = TypeVar("T", bound=BaseModel)
TEMPLATE = "# Mapa de Clareza\n\n## O que você faz\n\n## Para quem\n\n## Lacunas e hipóteses\n"
SCORES = InterpretationScores(concreteness=4, relevance=4, defensibility=3, domain_fit=5)


class ScriptLLM:
    def __init__(self, *script: dict[str, Any] | Exception, ids: dict[str, str] | None = None):
        self.script = list(script)
        self.ids = ids or {}
        self.prompts: list[str] = []
        self.system = ""

    async def generate(self, system: str, prompt: str, output: type[T]) -> T:
        self.system = system
        self.prompts.append(prompt)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        text = json.dumps(step, ensure_ascii=False)
        for key, value in self.ids.items():
            text = text.replace(key, value)
        return output.model_validate_json(text)


async def add_fact(
    gw: FakeToolGateway,
    text: str,
    quadrant: FindingArea,
    kind: FactKind = "characteristic",
    origin: FactOrigin | None = None,
) -> str:
    out = await gw.save_fact(
        SaveFactIn(
            session_id="s1",
            turn_seq=1,
            layer_id="clarity",
            stage_id="clarity.routine",
            fact=ExtractedFact(
                text=text,
                source_excerpt=text,
                kind=kind,
                origin=origin
                or ("external_perception" if quadrant == "blind" else "client_statement"),
                finding_area=quadrant,
            ),
            scores=SCORES,
        )
    )
    return out.fact_id


async def setup(
    with_blind: bool = True, open_gap: bool = False
) -> tuple[FakeToolGateway, dict[str, str]]:
    gw = FakeToolGateway(templates={"clarity": TEMPLATE})
    gw.start_session("s1")
    ids = {"{F1}": await add_fact(gw, "Confirma por escrito o pedido.", "hidden")}
    if with_blind:
        ids["{F2}"] = await add_fact(gw, "Clientes dizem que ela explica tudo antes.", "blind")
    if open_gap:
        await gw.save_gap(
            SaveGapIn(
                session_id="s1",
                layer_id="clarity",
                stage_id="clarity.routine",
                description="Não disse como confere o resultado.",
                origin="client_statement",
                reason="duas respostas vagas",
            )
        )
    return gw, ids


def sections(content: dict[str, str]) -> list[dict[str, str]]:
    return [{"title": k, "markdown": v} for k, v in content.items()]


GOOD: dict[str, Any] = {
    "sections": sections(
        {
            "O que você faz": "Você confirma por escrito o pedido antes de começar [fact:{F1}].",
            "Para quem": "Quem compra percebe que você explica tudo antes [fact:{F2}].",
            "Lacunas e hipóteses": "Nada em aberto.",
        }
    ),
    "gaps": [],
    "hypotheses": [],
}
CTX = SynthesizeContext(session_id="s1", layer_id="clarity")


class TestValidation:
    def test_unknown_fact_reference_fails(self) -> None:
        bad = LayerSynthesis.model_validate(
            {
                "layer_id": "clarity",
                "content": {"A": "Algo [fact:inventado]."},
                "fact_refs": ["inventado"],
            }
        )
        try:
            validate_synthesis(bad, known_fact_ids={"f1"}, open_gaps=[])
        except SynthesisError as exc:
            assert "inventado" in str(exc)
        else:
            raise AssertionError("expected SynthesisError")

    def test_open_gaps_must_be_listed(self) -> None:
        ok = LayerSynthesis.model_validate(
            {"layer_id": "clarity", "content": {"A": "x [fact:f1]."}, "fact_refs": ["f1"]}
        )
        try:
            validate_synthesis(ok, known_fact_ids={"f1"}, open_gaps=["Sem prova."])
        except SynthesisError as exc:
            assert "gap" in str(exc)
        else:
            raise AssertionError("expected SynthesisError")


async def test_every_reference_exists_and_fact_refs_are_recomputed() -> None:
    gw, ids = await setup()
    llm = ScriptLLM(GOOD, ids=ids)
    out = await synthesize_layer(CTX, gw, llm)
    assert not out.used_fallback
    assert sorted(out.synthesis.fact_refs) == sorted(ids.values())


async def test_invented_reference_is_retried_then_falls_back() -> None:
    gw, ids = await setup()
    bad = {**GOOD, "sections": sections({"O que você faz": "Atende bem [fact:nope]."})}
    llm = ScriptLLM(bad, bad, ids=ids)
    out = await synthesize_layer(CTX, gw, llm)
    assert out.used_fallback
    assert "unknown fact" in llm.prompts[1]
    assert "nope" not in json.dumps(out.synthesis.content)
    assert set(out.synthesis.fact_refs) <= set(ids.values())


async def test_open_gap_is_never_hidden() -> None:
    gw, ids = await setup(open_gap=True)
    out = await synthesize_layer(CTX, gw, ScriptLLM(GOOD, GOOD, ids=ids))
    assert "Não disse como confere o resultado." in out.synthesis.gaps


async def test_layer_without_blind_fact_records_the_blind_gap() -> None:
    gw, ids = await setup(with_blind=False)
    only_hidden = {
        **GOOD,
        "sections": sections({"O que você faz": "Confirma por escrito [fact:{F1}]."}),
    }
    out = await synthesize_layer(CTX, gw, ScriptLLM(only_hidden, ids=ids))
    assert BLIND_GAP in out.synthesis.gaps


async def test_her_guess_about_clients_does_not_close_the_blind_gap() -> None:
    # Lead's method guide (13/11): what she supposes clients think is not a verified external
    # perception; without someone else's words the blind area stays a gap.
    gw, ids = await setup(with_blind=False)
    ids["{F2}"] = await add_fact(
        gw,
        "Acho que voltam porque explico tudo antes.",
        "blind",
        kind="hypothesis",
        origin="client_statement",
    )
    only_hidden = {
        **GOOD,
        "sections": sections({"O que você faz": "Confirma por escrito [fact:{F1}]."}),
    }
    out = await synthesize_layer(CTX, gw, ScriptLLM(only_hidden, ids=ids))
    assert BLIND_GAP in out.synthesis.gaps


async def test_model_failure_gives_a_traceable_fallback() -> None:
    gw, ids = await setup()
    out = await synthesize_layer(CTX, gw, ScriptLLM(TimeoutError()))
    assert out.used_fallback
    text = json.dumps(out.synthesis.content, ensure_ascii=False)
    for fid in ids.values():
        assert f"[fact:{fid}]" in text
    assert BLIND_GAP not in out.synthesis.gaps


async def test_prompt_has_template_facts_and_gaps() -> None:
    gw, ids = await setup(open_gap=True)
    llm = ScriptLLM(GOOD, ids=ids)
    await synthesize_layer(CTX, gw, llm)
    assert "Synthesizer" in llm.system and "Valor Visível" in llm.system
    prompt = llm.prompts[0]
    assert "## Para quem" in prompt
    assert f"[{ids['{F1}']}] (hidden, characteristic) Confirma por escrito o pedido." in prompt
    assert "Não disse como confere o resultado." in prompt


class TestRefine:
    async def test_only_the_requested_section_changes(self) -> None:
        gw, ids = await setup()
        current = StoredSynthesis(
            layer_id="clarity",
            version=1,
            content={
                "O que você faz": f"Confirma por escrito [fact:{ids['{F1}']}].",
                "Para quem": f"Explica antes [fact:{ids['{F2}']}].",
            },
            fact_refs=list(ids.values()),
        )
        llm = ScriptLLM(
            {"markdown": "Antes de começar, você confirma o pedido por escrito [fact:{F1}]."},
            ids=ids,
        )
        out = await refine_section(CTX, current, "O que você faz", "mais direto", gw, llm)
        assert out.content["Para quem"] == current.content["Para quem"]
        assert out.content["O que você faz"].startswith("Antes de começar")
        assert "mais direto" in llm.prompts[0]

    async def test_refine_with_invented_reference_keeps_the_old_section(self) -> None:
        gw, ids = await setup()
        current = StoredSynthesis(
            layer_id="clarity",
            version=1,
            content={"O que você faz": f"Confirma por escrito [fact:{ids['{F1}']}]."},
            fact_refs=[ids["{F1}"]],
        )
        llm = ScriptLLM({"markdown": "Inventado [fact:zzz]."}, ids=ids)
        out = await refine_section(CTX, current, "O que você faz", "x", gw, llm)
        assert out.content == current.content


async def test_missing_template_does_not_stop_the_synthesis() -> None:
    gw, ids = await setup()

    async def no_template(*_: object) -> None:
        raise RuntimeError("missing knowledge-base file 'templates/clarity_map.md'")

    gw.get_synthesis_template = no_template  # type: ignore[method-assign]
    llm = ScriptLLM(GOOD, ids=ids)
    out = await synthesize_layer(CTX, gw, llm)
    assert not out.used_fallback
    assert "no template" in llm.prompts[0]


def test_llm_draft_uses_a_list_of_sections_not_a_dict() -> None:
    from vv_chat.agents.synthesizer import SynthesisDraft

    schema = SynthesisDraft.model_json_schema()
    assert schema["properties"]["sections"]["type"] == "array"
    draft = SynthesisDraft.model_validate(
        {"sections": [{"title": "O que você faz", "markdown": "x [fact:f1]"}], "gaps": []}
    )
    syn = draft.to_synthesis("clarity")
    assert syn.content == {"O que você faz": "x [fact:f1]"} and syn.layer_id == "clarity"


class TestUncitedParagraphs:
    def test_paragraphs_without_fact_are_removed(self) -> None:
        from vv_chat.agents.synthesizer import drop_uncited

        content = {
            "O que você faz": "Você faz bolos [fact:f1].\n\nVocê trabalha sozinha em tudo.",
            "Lacunas e hipóteses": "Não sabemos o que as noivas dizem.",
            "O que quem compra percebe, segundo você": "Ainda não sabemos.",
        }
        cleaned, removed = drop_uncited(content)
        assert cleaned["O que você faz"] == "Você faz bolos [fact:f1]."
        assert cleaned["Lacunas e hipóteses"] == content["Lacunas e hipóteses"]
        assert cleaned["O que quem compra percebe, segundo você"] == "Ainda não sabemos."
        assert removed == ["Você trabalha sozinha em tudo."]

    def test_section_left_empty_says_we_do_not_know(self) -> None:
        from vv_chat.agents.synthesizer import drop_uncited

        cleaned, _ = drop_uncited({"Para quem": "Atende noivas exigentes de alto padrão."})
        assert cleaned["Para quem"] == "Ainda não sabemos."

    async def test_synthesis_never_shows_an_uncited_paragraph(self) -> None:
        gw, ids = await setup()
        draft = {
            **GOOD,
            "sections": sections(
                {
                    "O que você faz": (
                        "Confirma por escrito [fact:{F1}].\n\nAtende eventos de grande porte."
                    ),
                    "Lacunas e hipóteses": "Nada em aberto.",
                }
            ),
        }
        out = await synthesize_layer(CTX, gw, ScriptLLM(draft, ids=ids))
        assert "grande porte" not in json.dumps(out.synthesis.content, ensure_ascii=False)


class TestBusinessProfile:
    """What she said in the onboarding can be cited, so the synthesis never says 'não sabemos'
    about it (A.06.10)."""

    PROFILE = {
        "ob-audience": "who buys: cafés, bares e restaurantes",
        "baseline": "how she presents herself today: Temos muitos sabores.",
    }

    async def test_profile_lines_are_in_the_prompt(self) -> None:
        gw, ids = await setup()
        llm = ScriptLLM(GOOD, ids=ids)
        await synthesize_layer(CTX.model_copy(update={"profile": self.PROFILE}), gw, llm)
        assert "<business>" in llm.prompts[0]
        assert "[ob-audience] who buys: cafés, bares e restaurantes" in llm.prompts[0]

    async def test_citing_a_profile_line_is_valid(self) -> None:
        gw, ids = await setup()
        cites_profile = {
            **GOOD,
            "sections": sections(
                {
                    "O que você faz": "Confirma por escrito [fact:{F1}].",
                    "Para quem": "Cafés, bares e restaurantes [fact:ob-audience].",
                }
            ),
        }
        out = await synthesize_layer(
            CTX.model_copy(update={"profile": self.PROFILE}), gw, ScriptLLM(cites_profile, ids=ids)
        )
        assert not out.used_fallback
        assert "[fact:ob-audience]" in out.synthesis.content["Para quem"]


def test_an_uncited_sentence_after_the_last_citation_is_removed() -> None:
    from vv_chat.agents.synthesizer import drop_uncited

    content = {
        "Como você faz": "Você pesa massa e recheio [fact:f1]. Esse controle acontece em cada lote."
    }
    cleaned, removed = drop_uncited(content)
    assert cleaned["Como você faz"] == "Você pesa massa e recheio [fact:f1]."
    assert removed == ["Esse controle acontece em cada lote."]


def test_a_sentence_covered_by_a_later_citation_stays() -> None:
    from vv_chat.agents.synthesizer import drop_uncited

    text = "Você pesa massa e recheio. Faz isso antes de fechar [fact:f1]."
    cleaned, removed = drop_uncited({"Como você faz": text})
    assert cleaned["Como você faz"] == text and removed == []


class TestModelFailure:
    """Round 3 of the simulation: one model failure turned the map into a flat list (A.06.12)."""

    async def test_one_failure_is_retried(self) -> None:
        gw, ids = await setup()
        out = await synthesize_layer(CTX, gw, ScriptLLM(RuntimeError("throttled"), GOOD, ids=ids))
        assert not out.used_fallback

    async def test_the_fallback_keeps_the_reason(self) -> None:
        gw, ids = await setup()
        llm = ScriptLLM(RuntimeError("one"), ValueError("two"), ids=ids)
        out = await synthesize_layer(CTX, gw, llm)
        assert out.used_fallback
        assert out.fallback_reason == "ValueError: two"


async def test_long_dashes_are_removed_from_the_map() -> None:
    gw, ids = await setup()
    dashed = {
        **GOOD,
        "sections": sections({"O que você faz": "Confirma por escrito — sempre [fact:{F1}]."}),
    }
    out = await synthesize_layer(CTX, gw, ScriptLLM(dashed, ids=ids))
    assert "—" not in out.synthesis.content["O que você faz"]
