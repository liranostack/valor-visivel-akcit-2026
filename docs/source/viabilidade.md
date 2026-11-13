# **Viabilidade econômica \| Valor Visível**

Nov 11, 2026 · @Ricardo · atualizado em 12/11/2026 com custos medidos

## **Resumo**

Atualizado em 12/11/2026 com o custo **medido** nas simulações da camada 1 (Nitidez), em vez de premissas.

Hoje, com todos os agentes no Sonnet 4.6 e sem cache, um turno de conversa custa **US\$ 0,085**, já incluída a parte da síntese da camada. A camada 1 fecha em 4 a 6 turnos e custa **US\$ 0,36 a 0,45 por sessão**. Projetada para a jornada completa (4 camadas, Pré-Núcleo e Núcleo), a configuração atual custa entre **US\$ 2,13 e US\$ 7,41**. O cenário realista fica em **US\$ 3,82 (≈ R\$ 21)**, 2,4 vezes a estimativa anterior (US\$ 1,61).

A diferença não vem do tamanho das chamadas. A premissa realista era de 5.000 tokens de entrada e 500 de saída por chamada, e o medido foi de 5.600 e 510. Ela vem de duas premissas que ainda não estão no código: Intérprete e Moderador no Haiku, e 40% da entrada servida por cache de prompt. Com essas duas alavancas, o realista volta para **US\$ 1,86 (≈ R\$ 10,20)**.

Leitura para o negócio: a R\$ 97 por diagnóstico, a margem bruta sobre a nuvem fica em 78% com a configuração atual e em 89% com as alavancas. Quase tudo continua sendo modelo de linguagem; infraestrutura, guardrails e avaliação somam centavos por jornada.

## **O que foi medido**

Simulações com o executor de jornada da suíte de integração (`make simulate`): agentes reais no Bedrock, cliente simulada no Haiku 4.5 e três personas (consultoria de RH, massoterapeuta, pastelaria). Os números contam só os agentes do produto: a cliente simulada e os juízes ficam de fora. Os preços estão em `chat-service/config/pricing.yaml`.

| Medição | Turnos | Chamadas | Entrada por chamada | Saída por chamada | US\$ por turno |
| :---- | :---- | :---- | :---- | :---- | :---- |
| Round 3 (87cae07d, 12/11) | 16 | 49 | 4.298 | 395 | 0,063 |
| Round 4 (9dcf0451, 12/11) | 14 | 44 | 5.598 | 510 | 0,085 |

O round 4 é a base da projeção: tem os prompts atuais, com o guia de voz e o ritmo de conversa, que são mais longos. Por sessão da camada 1, ele custou US\$ 0,45 na consultoria de RH, US\$ 0,36 na massoterapeuta e US\$ 0,38 na pastelaria. Em média, um turno faz 3 chamadas (Intérprete, Investigador e Moderador). As retentativas por repetição ou erro já estão no número medido.

## **Premissas da projeção**

Custo da jornada = turnos × (entrada por turno × crescimento do contexto + saída por turno) + outros custos. A conta está em `scripts/cost_model.py`.

| Premissa | Otimista | Realista | Pessimista |
| :---- | :---- | :---- | :---- |
| Turnos por jornada | 24 | 36 | 55 |
| Custo por turno na camada 1 (medido) | US\$ 0,085 | US\$ 0,085 | US\$ 0,085 |
| Entrada média ao longo da jornada, relativa à camada 1 \[HIPÓTESE\] | 1,0× | 1,3× | 1,8× |
| Guardrails, infraestrutura e avaliação online (1% dos turnos) por jornada \[estimativa anterior, não medido\] | US\$ 0,10 | US\$ 0,15 | US\$ 0,20 |
| Custos fixos mensais | US\$ 15 | US\$ 35 | US\$ 80 |

* **Turnos.** A camada 1 fechou em 4 a 6 turnos nas simulações. Cinco turnos por camada mais o Pré-Núcleo e o Núcleo dão os 24 do otimista. O auditor de raciocínio apontou que algumas camadas fecham cedo demais, então o realista mantém 36.
* **Crescimento do contexto.** Cada chamada recebe os fatos da sessão, e as camadas seguintes acumulam fatos das anteriores. Ainda não há medição das camadas 2 a 4.
* **Alavancas** \[HIPÓTESE até medir\]: Intérprete e Moderador no Haiku 4.5, cerca de 55% dos tokens, e 40% da entrada servida por cache de prompt (card A.06.07). A qualidade com o Haiku precisa passar no LLM-as-judge antes de virar padrão.

Outras premissas, mantidas da versão anterior: região us-east-1; câmbio de referência R\$ 5,50 por dólar; AgentCore Runtime sob consumo; DynamoDB, WebSocket e CloudWatch somando centavos por jornada.

## **Preços de referência**

| Item | Preço usado |
| :---- | :---- |
| Claude Haiku 4.5 no Bedrock (perfil us.\*) | US\$ 1,10 / 1M tokens de entrada · US\$ 5,50 / 1M de saída |
| Claude Sonnet 4.6 no Bedrock (perfil us.\*) | US\$ 3,30 / 1M de entrada · US\$ 16,50 / 1M de saída |
| Leitura de cache de prompt | 10% do preço de entrada |
| Bedrock Guardrails | US\$ 0,15 / 1.000 unidades de texto (filtros de conteúdo e tópicos negados) \+ US\$ 0,10 (PII); 1 unidade \= até 1.000 caracteres |
| AgentCore Runtime (microVM v2) | US\$ 0,1276 / vCPU-hora · US\$ 0,0169 / GB-hora; CPU zera durante espera de I/O |
| AgentCore Memory (curto prazo) | US\$ 0,25 / 1.000 eventos |
| AgentCore Evaluations (avaliador próprio) | US\$ 1,50 / 1.000 avaliações \+ tokens do modelo juiz |
| DynamoDB sob demanda | US\$ 0,625 / 1M escritas · US\$ 0,125 / 1M leituras |
| API Gateway WebSocket | US\$ 1 / 1M mensagens · US\$ 0,25 / 1M minutos de conexão |
| CloudWatch Logs | US\$ 0,50 / GB ingerido |

Preços públicos de lista, sem descontos nem créditos. Antes de qualquer número ir para o pitch, conferir no AWS Pricing Calculator: a AWS mudou a cobrança do AgentCore Memory em outubro de 2026 (de eventos para GB), o que muda pouco este cálculo.

## **Custo por jornada**

| Cenário | Turnos | Configuração atual | Com alavancas |
| :---- | :---- | :---- | :---- |
| Otimista | 24 | US\$ 2,13 (R\$ 11,71) | US\$ 1,07 (R\$ 5,87) |
| Realista | 36 | US\$ 3,82 (R\$ 21,02) | US\$ 1,86 (R\$ 10,20) |
| Pessimista | 55 | US\$ 7,41 (R\$ 40,73) | US\$ 3,45 (R\$ 18,99) |

Os modelos dos agentes são mais de 95% do custo em todos os cenários. Na camada 1 medida, a entrada responde por cerca de 70% do custo do turno: 17,6 mil tokens de entrada contra 1,6 mil de saída. Por isso o cache de prompt é a alavanca mais barata de implementar.

## **Custo mensal por volume**

Configuração atual: custo por jornada × jornadas no mês \+ custos fixos.

| Jornadas/mês | Otimista | Realista | Pessimista |
| :---- | :---- | :---- | :---- |
| 100 | US\$ 228 (R\$ 1.254) | US\$ 417 (R\$ 2.294) | US\$ 821 (R\$ 4.513) |
| 1.000 | US\$ 2.144 (R\$ 11.793) | US\$ 3.856 (R\$ 21.208) | US\$ 7.485 (R\$ 41.169) |
| 10.000 | US\$ 21.308 (R\$ 117.192) | US\$ 38.245 (R\$ 210.348) | US\$ 74.133 (R\$ 407.731) |

Com as alavancas, os valores variáveis caem para cerca de metade.

**Suíte de avaliação (medida).** Uma execução de `make simulate` com três personas na camada 1 custou US\$ 1,78: US\$ 1,18 de produto, US\$ 0,55 de juízes (Sonnet 4.6) e US\$ 0,04 de cliente simulada (Haiku 4.5). Rodando a cada merge, cerca de 30 por mês, dá ≈ US\$ 53 por mês. Com as quatro camadas, a suíte deve ficar perto de 4 vezes isso \[HIPÓTESE\]. Para o hackathon e a validação inicial, o gasto continua abaixo de US\$ 100 no mês.

## **Leitura para preço e BMC**

* **Preço mínimo por jornada.** Para margem bruta de 80% sobre o custo de nuvem, o preço precisa ser pelo menos 5 vezes o custo.

  | Cenário | Configuração atual | Com alavancas |
  | :---- | :---- | :---- |
  | Otimista | ≈ R\$ 59 | ≈ R\$ 29 |
  | Realista | ≈ R\$ 105 | ≈ R\$ 51 |
  | Pessimista | ≈ R\$ 204 | ≈ R\$ 95 |

  A R\$ 97 por diagnóstico, a margem bruta fica em 78% no realista e 58% no pessimista com a configuração atual. Com as alavancas, sobe para 89% e 80%.
* **Assinatura.** Se o modelo for mensal com jornadas ilimitadas, o risco é a cliente refazer a jornada muitas vezes. Limitar a 1 jornada completa por mês, com as revisões de camada (revisão do mapa) inclusas, mantém o custo previsível. Cada ajuste no mapa refaz uma síntese, então um teto de ajustes por camada também ajuda.
* **Linha de custos do BMC.** O custo variável é dominado por tokens de modelo de linguagem, e a entrada pesa mais que a saída. A infraestrutura é praticamente fixa e baixa. A avaliação de qualidade é um custo marginal: 1% dos turnos em produção, e a suíte completa só no merge.

## **Riscos de custo**

* **Cliente prolixa ou que não avança.** Mais turnos e mais texto por turno. Na medição, a persona mais prolixa (consultoria de RH) custou 18% a mais por sessão que a pastelaria. Mitigado pelo limite de 2 tentativas por etapa e pelas opções ABC do Moderador, que encurtam a conversa.  
* **Contexto crescente.** Se cada chamada carregar a conversa inteira, a entrada cresce a cada turno e o custo deixa de ser linear. Mitigado ao passar só fatos e progresso da etapa (via MCP), não o histórico bruto.  
* **Avaliação sem amostragem.** O teto é 1% dos turnos em produção e a suíte completa só no merge. Se esse teto escapar (avaliar todos os turnos com 8 métricas), a jornada realista fica cerca de US\$ 2 mais cara, mais que o próprio produto. Vale um alarme no dashboard.  
* **Mudança de preço ou de modelo.** Preços de lista mudam; trocar de modelo exige recalibrar os prompts e a suíte de LLM-as-judge.  
* **Câmbio.** Custo em dólar, receita em real: uma alta de 10% do dólar sobe o custo na mesma proporção.

## **Alavancas para reduzir custo**

1. **Cache de prompt** nos prompts de sistema e no material da KB, que se repetem em todo turno (card A.06.07). A entrada é cerca de 70% do custo medido do turno.  
2. **Modelo pequeno onde a tarefa é curta**: Intérprete e Moderador no Haiku; Sonnet só no Investigador e no Sintetizador. Hoje todos rodam no Sonnet 4.6. O Haiku custa um terço do Sonnet, e a troca só vale se a qualidade se mantiver no LLM-as-judge.  
3. **Amostragem da avaliação online** limitada a 1% dos turnos em produção, com juiz em Haiku e a suíte completa só no merge.  
4. **Orçamento de tokens por chamada**, já previsto no read\_public\_site (\~2k tokens) e aplicável às sínteses.  
5. **Batch** para avaliações fora do tempo real: o AgentCore Evaluations em lote custa 25% menos que o online.

## **Fontes**

* [Amazon Bedrock AgentCore — preços](https://aws.amazon.com/bedrock/agentcore/pricing/) (Runtime, Memory, Evaluations)  
* [Amazon Bedrock Guardrails reduz preços em até 85%](https://aws.amazon.com/about-aws/whats-new/2024/12/amazon-bedrock-guardrails-reduces-pricing-85-percent)  
* [Amazon Bedrock — preços](https://aws.amazon.com/bedrock/pricing/) (modelos Claude e Guardrails)  
* [Bifrost — Bedrock us.anthropic.claude-haiku-4-5](https://www.getmaxim.ai/bifrost/llm-cost-calculator/provider/bedrock/model/us.anthropic.claude-haiku-4-5-20251001-v1-0)  
* [Bifrost — Bedrock us.anthropic.claude-sonnet-4-6](https://www.getmaxim.ai/bifrost/llm-cost-calculator/provider/bedrock/model/us.anthropic.claude-sonnet-4-6)

Preços de DynamoDB, API Gateway e CloudWatch: tabelas públicas de cada serviço em us-east-1. Os tokens por turno foram medidos nas simulações da camada 1 (reports 87cae07d e 9dcf0451, rodados em 12/11/2026). Turnos por jornada, crescimento do contexto, alavancas, infraestrutura e avaliação online seguem estimados. Depois da demo, medir as camadas 2 a 4 e sessões reais e refazer a conta com `scripts/cost_model.py`.