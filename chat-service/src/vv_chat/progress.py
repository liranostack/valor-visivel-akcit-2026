"""pt-BR texts of the progress indicator (A.06.05), kept in one place."""

from vv_contracts.ws import ProgressStep

PROGRESS_MESSAGES: dict[ProgressStep, str] = {
    "reading": "Lendo sua resposta…",
    "planning": "Pensando na próxima pergunta…",
    "writing": "Quase lá…",
    "synthesizing": "Montando a síntese desta parte…",
}
