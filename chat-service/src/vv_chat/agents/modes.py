"""Conversation modes: the Conductor's decision and the answer's quality pick the mode; the
Moderator gets its instruction, and when the model fails, the opener still acknowledges her answer.
"""

from typing import Literal

from vv_contracts.common import LayerId

Mode = Literal["retry_low", "retry_medium", "advance", "force_advance", "rescue_prompt"]

BASE_STYLE = (
    "Em todo turno: (1) reconhecer o que a resposta trouxe, com as palavras dela; (2) mostrar o "
    "que ainda falta; (3) fazer uma única pergunta curta."
)

INSTRUCTIONS: dict[Mode, str] = {
    "retry_low": f"{BASE_STYLE} A resposta veio abstrata: evite tom corretivo e peça um exemplo "
    "real e recente.",
    "retry_medium": f"{BASE_STYLE} Há algo concreto: peça o detalhe que mostra que se repete.",
    "force_advance": f"{BASE_STYLE} Siga adiante sem julgamento e diga que o ponto pode voltar "
    "depois.",
    "rescue_prompt": f"{BASE_STYLE} Mude o ângulo da pergunta para destravar, sem repetir a "
    "anterior.",
    "advance": f"{BASE_STYLE} Avanço normal, com linguagem simples e de rotina.",
}

# Opening sentence when the model fails, by mode and attempt.
OPENERS: dict[Mode, tuple[str, str]] = {
    "retry_low": (
        "Isso ajuda a entender o seu trabalho. Agora preciso de um exemplo de como acontece no "
        "dia a dia.",
        "Já temos um começo. Falta um caso real e recente para ficar concreto.",
    ),
    "retry_medium": (
        "Tem algo concreto aqui. Falta saber se isso se repete ou foi uma vez só.",
        "Você já trouxe algo concreto. Com mais um detalhe, fica fácil de explicar a quem compra.",
    ),
    "advance": (
        "Isso já dá uma boa base. Vamos para o próximo ponto.",
        "Isso já dá uma boa base. Vamos para o próximo ponto.",
    ),
    "rescue_prompt": (
        "Quero fechar esse ponto antes de seguir.",
        "Quero fechar esse ponto antes de seguir.",
    ),
    "force_advance": ("", ""),  # by layer, below
}
FORCE_ADVANCE_OPENER: dict[LayerId, str] = {
    "clarity": "Esse ponto ainda não ficou concreto.",
    "singularity": "Esse ponto ainda não ficou específico.",
    "translation": "Essa mensagem ainda não ficou clara.",
    "sustainment": "Essa prova ainda não ficou sólida.",
}
FORCE_ADVANCE_TAIL = "Vou organizar o que temos e seguimos; podemos voltar aqui depois."


def mode_for(action: str, *, concreteness: int, relevance: int) -> Mode:
    """Quality low -> retry_low, medium -> retry_medium, high -> advance; plus the
    Conductor's force_advance and gap resume (rescue)."""
    if action == "force_advance":
        return "force_advance"
    if action == "resume_gap":
        return "rescue_prompt"
    if action == "advance":
        return "advance"
    if concreteness <= 2 or relevance <= 2:
        return "retry_low"
    return "retry_medium"


def opener(mode: Mode, attempt: int, layer_id: LayerId) -> str:
    if mode == "force_advance":
        return f"{FORCE_ADVANCE_OPENER[layer_id]} {FORCE_ADVANCE_TAIL}"
    first, second = OPENERS[mode]
    return second if attempt >= 2 else first
