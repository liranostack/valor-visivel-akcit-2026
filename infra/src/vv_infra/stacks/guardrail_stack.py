"""GuardrailStack: the Bedrock Guardrail applied with ApplyGuardrail on input and final output.

ERD 'Guardrails' (ADR-007): prompt-attack filter on input, denied topics (legal, medical,
investment advice, subjects unrelated to the business), PII masked before it reaches the state
(e-mail, phone, CPF by regex), contextual grounding for the Synthesizer output.
Blocked messages are pt-BR and bring the conversation back to the current question.
"""

from dataclasses import dataclass

import aws_cdk as cdk
from aws_cdk import aws_bedrock as bedrock
from constructs import Construct


@dataclass(frozen=True)
class GuardrailRef:
    """An already-deployed guardrail to reuse instead of creating one (guardrail names are unique
    per account, so a second environment shares the first one's guardrail)."""

    guardrail_id: str
    guardrail_version: str


BLOCKED_INPUT_MESSAGE = (
    "Vamos manter nossa conversa no seu negócio. Pode me contar mais sobre a pergunta anterior?"
)
BLOCKED_OUTPUT_MESSAGE = (
    "Prefiro reformular isso. Vamos voltar à sua última resposta sobre o seu negócio?"
)
CPF_REGEX = r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"

Topic = bedrock.CfnGuardrail.TopicConfigProperty

DENIED_TOPICS = [
    Topic(
        name="Aconselhamento juridico",
        type="DENY",
        definition=(
            "Pedidos de orientação jurídica, contratos, processos, direitos trabalhistas "
            "ou tributários que exigem um advogado ou contador."
        ),
        examples=["Posso processar minha cliente?", "Como faço um contrato de sociedade?"],
    ),
    Topic(
        name="Aconselhamento medico",
        type="DENY",
        definition=(
            "Pedidos de diagnóstico, tratamento, medicação ou indicação clínica para "
            "a pessoa ou suas clientes."
        ),
        examples=["Que remédio tomo para dor nas costas?", "Massagem cura hérnia de disco?"],
    ),
    Topic(
        name="Aconselhamento de investimento",
        type="DENY",
        definition=(
            "Pedidos de recomendação de investimentos, ações, criptomoedas ou aplicações "
            "financeiras."
        ),
        examples=["Devo investir em bitcoin?", "Qual ação compro com o lucro do mês?"],
    ),
    Topic(
        name="Assuntos sem relacao com o negocio",
        type="DENY",
        definition=(
            "Conversa sem relação com o negócio da pessoa, como política, esportes, "
            "fofoca, tarefas escolares ou pedidos de código."
        ),
        examples=["Quem vai ganhar a eleição?", "Escreve um poema sobre o mar", "Faz meu dever"],
    ),
]


class GuardrailStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]

        filter_ = bedrock.CfnGuardrail.ContentFilterConfigProperty
        self.guardrail = bedrock.CfnGuardrail(
            self,
            "Guardrail",
            name="valor-visivel",
            description="Valor Visível: input and final-output protection (ERD, ADR-007).",
            blocked_input_messaging=BLOCKED_INPUT_MESSAGE,
            blocked_outputs_messaging=BLOCKED_OUTPUT_MESSAGE,
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                filters_config=[
                    filter_(type="PROMPT_ATTACK", input_strength="HIGH", output_strength="NONE"),
                    filter_(type="HATE", input_strength="MEDIUM", output_strength="MEDIUM"),
                    filter_(type="INSULTS", input_strength="MEDIUM", output_strength="MEDIUM"),
                    filter_(type="SEXUAL", input_strength="MEDIUM", output_strength="MEDIUM"),
                    filter_(type="VIOLENCE", input_strength="MEDIUM", output_strength="MEDIUM"),
                    filter_(type="MISCONDUCT", input_strength="MEDIUM", output_strength="MEDIUM"),
                ]
            ),
            topic_policy_config=bedrock.CfnGuardrail.TopicPolicyConfigProperty(
                topics_config=DENIED_TOPICS
            ),
            sensitive_information_policy_config=bedrock.CfnGuardrail.SensitiveInformationPolicyConfigProperty(
                pii_entities_config=[
                    bedrock.CfnGuardrail.PiiEntityConfigProperty(type="EMAIL", action="ANONYMIZE"),
                    bedrock.CfnGuardrail.PiiEntityConfigProperty(type="PHONE", action="ANONYMIZE"),
                    bedrock.CfnGuardrail.PiiEntityConfigProperty(
                        type="CREDIT_DEBIT_CARD_NUMBER", action="ANONYMIZE"
                    ),
                ],
                regexes_config=[
                    bedrock.CfnGuardrail.RegexConfigProperty(
                        name="CPF",
                        description="Brazilian individual taxpayer id",
                        pattern=CPF_REGEX,
                        action="ANONYMIZE",
                    )
                ],
            ),
            contextual_grounding_policy_config=bedrock.CfnGuardrail.ContextualGroundingPolicyConfigProperty(
                filters_config=[
                    bedrock.CfnGuardrail.ContextualGroundingFilterConfigProperty(
                        type="GROUNDING", threshold=0.75
                    ),
                    bedrock.CfnGuardrail.ContextualGroundingFilterConfigProperty(
                        type="RELEVANCE", threshold=0.5
                    ),
                ]
            ),
        )
        self.published = bedrock.CfnGuardrailVersion(
            self,
            "PublishedVersion",
            guardrail_identifier=self.guardrail.attr_guardrail_id,
            description="Published version used by the chat-service.",
        )
        self.guardrail_id = self.guardrail.attr_guardrail_id
        self.guardrail_version = self.published.attr_version

        cdk.CfnOutput(self, "GuardrailId", value=self.guardrail_id)
        cdk.CfnOutput(self, "GuardrailVersion", value=self.guardrail_version)
