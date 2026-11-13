# Guia de áreas

Guia de exemplo da versão aberta. Separa o que a pessoa já comunica (open), o que ela faz e não
conta (hidden), o que outras pessoas percebem e ela não reconhece (blind) e o que ninguém
identificou ainda (unknown). Classificamos fatos sobre o negócio, nunca a pessoa. Esses rótulos
nunca aparecem para ela.

### Regra de classificação

Primeiro decida a origem; a área vem depois.

- **Ela descreve o que faz, decide ou observa** → `client_statement`: hidden (se não comunica) ou
  open (se já comunica), nunca blind.
- **Ela conta o que outra pessoa disse ou fez em relação ao trabalho dela** →
  `external_perception`, que pode ser blind. Precisa ter alguém de fora como fonte.
- **Ela supõe o que clientes pensam** → `client_statement` com `kind: hypothesis`.
- **Está no site ou perfil público dela** → `public_source`: pista, não fato confirmado.
- **É leitura sua a partir do que ela disse** → `inference`, sempre `kind: hypothesis`.

Números só contam quando ela os diz.

### Armadilhas comuns

1. Elogiar ou dar veredito sobre a resposta, ou corrigir com tom duro.
2. Fazer pergunta ou opção que já sugere a resposta.
3. Apresentar hipótese como fato.
4. Supor o que os clientes pensam sem relato de alguém de fora.
5. Pedir opinião ou futuro em vez de um episódio real.
6. Chamar algo de diferencial cedo demais.

### Aplicação por camada

Na versão aberta as quatro camadas usam conteúdo de exemplo. Antes de sintetizar, buscar ao menos um fato hidden e
um relato externo; sem relato externo, registrar a lacuna.

## open

### No negócio

O que ela já diz a quem compra.

### Como reconhecer numa resposta

Ela conta o que costuma explicar a clientes, muitas vezes como frase pronta.

### Como chegar nele

Ângulo `proof`: o que ela mostra a quem está decidindo comprar.

### O que conta como evidência

`client_statement` sobre o que ela já comunica. Frase genérica não é evidência.

### Armadilhas

Aceitar a frase de apresentação como fato.

### Na síntese

O que ela já conta, ao lado do fato que sustenta ou contradiz a frase.

## hidden

### No negócio

Decisões, cuidados, limites e rotinas que ela conhece e não conta porque acha óbvios.

### Como reconhecer numa resposta

Ela descreve um passo ou uma regra e em seguida o minimiza ("é o normal").

### Como chegar nele

Ângulos `routine`, `limit`, `avoided_error` e `decision`, a partir de um episódio real.

### O que conta como evidência

`client_statement` com trecho literal.

### Armadilhas

Chamar de diferencial cedo demais.

### Na síntese

A regra ou o cuidado nas palavras dela, com o motivo que ela deu.

## blind

### No negócio

O que quem compra percebe no trabalho dela e ela não valoriza.

### Como reconhecer numa resposta

Ela relata algo dito por outra pessoa, com essa pessoa como fonte.

### Como chegar nele

Ângulo `blind_spot`: o que a última pessoa que comprou disse depois.

### O que conta como evidência

`external_perception` com trecho literal do relato dela.

### Armadilhas

Supor o que outras pessoas percebem sem relato.

### Na síntese

O que quem compra percebe, segundo ela. Sem relato externo, registrar como lacuna.

## unknown

### No negócio

Possibilidades que ninguém identificou ainda, plausíveis a partir do que foi dito.

### Como reconhecer numa resposta

Não aparece numa resposta: é leitura de quem investiga.

### Como chegar nele

Nenhum ângulo direto.

### O que conta como evidência

Nada ainda: sempre `kind: hypothesis` com `origin: inference`.

### Armadilhas

Converter hipótese em fato ou promessa.

### Na síntese

Somente em "Lacunas e hipóteses", como hipótese a confirmar.
