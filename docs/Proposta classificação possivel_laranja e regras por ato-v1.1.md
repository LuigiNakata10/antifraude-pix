# Módulo de conta laranja: DICT, grafo e possivel\_laranja — v1.1

Oct 17, 2026 · @renan · revisão v1.1 em 17/10/2026

Revisão documental: preserva a estrutura e os arquivos v1. Atualiza classificação, combinações de evidências, histórico observável, precedência dos atos e cenários. Não representa implementação nem testes executados.

## Objetivo e premissa

Este módulo, aprovado pelo time, cuida da conta laranja com um conceito só: o motor primeiro classifica a conta (`possivel_laranja`) e depois decide o ato. Assim a mesma conta laranja consegue pagar a conta de luz, mas não consegue repassar o dinheiro do golpe.

**Premissa: nem toda transação que envolve uma laranja é fraudulenta.** O recrutado paga as próprias contas, a vítima que paga a laranja não é cúmplice, e a mãe que manda mesada ao filho recrutado também não. Bloquear tudo que toca a conta trava inocentes e não recupera dinheiro.

A proposta segue a política acordada (`regras-de-negocio-v1.md`): R1 a R4 ficam como estão; sem pontuação; combinações explícitas; um único motivo na resposta; rejeição só por evidência externa ou por combinação descrita; nenhum 2FA novo, porque contra laranja quem confirma o 2FA é o próprio operador. Os valores são parâmetros do protótipo, não limiares validados.

## Fronteira com as regras base

A integração e o modelo únicos estão no [guia v1.1](guia-de-desenvolvimento-v1.1.md).

As regras base (R1 a R4) estão com outra pessoa do time; este módulo se encaixa nelas por uma interface pequena, para os dois lados avançarem em paralelo e integrarem depois.

**O que o módulo recebe**, montado pelo controller:

- o payload do Pix já validado;
- as janelas do histórico local que ele precisa (entradas e saídas da conta pagadora na última hora, titulares distintos enviando ao destino, aprovações anteriores entre pagador e titular destino, vínculos de aparelho);
- a resposta do DICT para pagador e destino, ou a marca de indisponível.

**O que o módulo devolve**, sem tocar no banco:

```python
@dataclass
class LaranjaResult:
    rule_code: str | None        # "L1", "L2", "L3" ou None
    reason: dict | None          # motivo único estruturado: código, descrição e valores
    payer_state: str             # "nao" | "suspeita" | "suspeita_elevada"
    destination_state: str
    evidences: dict              # E1..E5 de cada conta, para analysis_details
    act: str                     # "gasto_tipico" | "repasse_aparente" | "outro"
    prior_relationship: bool
    dict_status: dict            # por titular: "consultado" | "cache" | "indisponivel"
```

**Onde entra na ordem:** R1, R2, L1, L2, L3, R4, R3; sem nenhuma, `approved`. A política de decisão chama as regras base e o módulo e aplica essa ordem; o módulo nunca decide sozinho o status final.

**O que precisa ser combinado com quem faz as regras base:**

- [ ] Mesma referência de tempo (`transaction_date`, como no acordo) e mesma definição de destinatário conhecido (aprovação anterior para o mesmo titular).
- [ ] Um único ponto que monta o contexto e consulta o banco, para não haver consultas duplicadas.
- [ ] Formato único de motivo no `metadata` (código, descrição, valores observados e limiares).
- [ ] O lock por conta pagadora vale para os dois: R1, R2, R3 e o cálculo de repasse dependem dele.

## Por que grafo e DICT

**A tese:** contra conta tomada, o 2FA pode ajudar se o invasor não tiver o segundo fator. Contra conta laranja, não: quem confirma é o próprio operador da conta, seja o recrutado, seja quem comprou o acesso. A única saída é reconhecer a conta e recusar o ato certo. O documento acordado reconhece esse risco residual (fraude abaixo dos tetos, no aparelho conhecido, com autenticação válida) e só admite fontes externas diante de um problema concreto não resolvido. Este é o problema.

As duas fontes se completam:

| Fonte | O que resolve | Limite |
| --- | --- | --- |
| DICT | dá marcações e relatos de outras instituições: o motor deixa de depender só do que viu | só conhece o que alguém já marcou |
| Grafo local | segue o dinheiro e o aparelho a partir dessas sementes, e enxerga padrões (muitos pagadores, repasse rápido) antes de haver marcação | só vê os Pix que passam pelo motor |

**A QI é participante direto do Pix** e se conecta ao DICT; também oferece acesso indireto a outras instituições. O mock representa essa categoria de fonte, com simplificações explícitas; o protótipo continua limitado ao histórico que efetivamente observa.

**O que o mercado faz:** plataformas antifraude Pix descrevem o uso de rede de conexões entre contas suspeitas e monitoramento do fluxo de entrada para detectar contas laranja, e o MED 2.0 do Banco Central passou a rastrear o dinheiro por várias camadas. O módulo aplica a mesma lógica antes do dinheiro sair, não depois.

## O estado possivel\_laranja

O estado descreve a conta, não a transação, e sozinho não decide nada. É calculado na hora, para a conta pagadora e para a conta destino, a partir de cinco evidências.

| Código | Evidência | Fonte | Parâmetro |
| --- | --- | --- | --- |
| E1 | Marcação ativa de laranja/golpista, ou relatos de pelo menos duas instituições distintas | Mock do titular | Início da marcação ou relatos nos últimos 90 dias; simplificação do protótipo, não cancelamento de restrições reais |
| E2 | Mais de 50% das entradas aprovadas observadas vieram de contas cujo titular tem E1, ou aparelho compartilhado com uma conta cujo titular tem E1 | Histórico local e snapshot do mock | 30 dias; conta com menos de 90 dias ou menos de 10 contrapartes distintas observadas em 30 dias |
| E3 | Muitos titulares distintos enviando, com pelo menos três estreantes; não necessariamente maioria | Histórico local aprovado | Pelo menos 5 titulares em 1h, sendo 3 sem aprovação anterior para a conta; para CNPJ, 30 titulares e pelo menos 3 estreantes |
| E4 | Notificações de infração ainda abertas contra o titular; não comprovam fraude | Mock | Pelo menos 2 |
| E5 | Conta nova recebendo volume alto de vários titulares | Histórico local aprovado | Menos de 7 dias, mais de R$ 5.000 em 24h e pelo menos 3 titulares pagadores distintos |

| Estado | Quando |
| --- | --- |
| `suspeita_elevada` | E1, ou a combinação explícita E2 + E4 |
| `suspeita` | Uma ou mais evidências presentes, sem satisfazer a condição acima |
| `nao` | Nenhuma evidência positiva disponível; desconhecido não significa conta limpa |

**Combinações explícitas.** E2 + E4 combina um vínculo local com conta marcada e notificações externas abertas. Isso não garante independência: as fontes podem refletir os mesmos fatos. E3 + E5 não eleva o estado, pois pode descrever a mesma arrecadação legítima. E2 + E3, E2 + E5, E3 + E4 e E4 + E5 também não elevam automaticamente. Mesmo três evidências sem E1 ou E2 + E4 permanecem `suspeita`. O estado é uma classificação de risco, não confirmação de fraude.

**Validade.** As evidências usam janelas (de 1 hora a 90 dias). Quando a janela passa, a evidência some e o estado cai sozinho: não existe marcação local permanente. Só o DICT mantém uma conta em `suspeita_elevada` por muito tempo.

**DICT indisponível.** E1 e E4 ficam desconhecidas, e o estado sai só das evidências locais. Desconhecido nunca conta como evidência.

**Histórico observável.** “Recebeu” e “enviou” significam análises anteriores `approved` que passaram pelo motor, não liquidação nem saldo. Rejeições e 2FA não alimentam esses valores. O pedido atual entra uma única vez no total de saída projetado. Não inventar recebimentos de outras instituições: ausência de registros significa falta de observação e impede acionar o indicador dependente deles, sem apagar outras evidências. Usar `transaction_date`, histórico já persistido e nenhum evento futuro.

**Escopo das evidências.** O mock informa marcações por titular (CPF/CNPJ); idade, fluxo e reputação local são por conta. Em E2, o ramo de valor exige entradas positivas; o ramo de aparelho não exige proporção, mas exige a mesma condição de idade/reputação. Contrapartes são distintas e observadas em 30 dias. Aparelho compartilhado exige aprovações anteriores de contas pagadoras com o mesmo `device_id` em 30 dias; o aparelho do pagador nunca é atribuído ao destinatário. Só E1 origina E2, com snapshot válido da fonte; vínculo com outra conta suspeita não propaga a suspeita.

## Tipo de ato e relação anterior

Com o estado das contas em mãos, o motor classifica a transação por duas perguntas.

**1. Do lado do pagador: que tipo de ato é?**

| Ato | Definição | Por quê |
| --- | --- | --- |
| Gasto típico | até R$ 1.000, para destinatário conhecido (aprovação anterior para o mesmo titular, como no acordo) ou para CNPJ com conta aberta há 90 dias ou mais | O padrão de quem usa a conta para a própria vida: mercado, contas, pessoas de sempre |
| Repasse aparente | o pagador recebeu pelo menos R$ 1.000 em Pix aprovados na última hora, este Pix leva o total enviado na mesma hora a 50% ou mais disso, e o destino é pessoa física ou CNPJ com conta de menos de 90 dias | O dinheiro sai logo depois de entrar, que é o que define uma conta de passagem |
| Outro | o resto | Depende do estado: L2 rejeita quando há suspeita elevada |

**Prioridade do ato:** avaliar `repasse_aparente` primeiro, depois `gasto_tipico` e, por último, `outro`. Se recebeu R$ 1.000 observados e envia R$ 600 a uma pessoa conhecida, é repasse aparente, mesmo satisfazendo a descrição de gasto típico. O padrão observado de entrada/saída prevalece sobre a familiaridade; isso pode bloquear também um repasse legítimo. Sem entradas observadas suficientes, não inferir repasse. Um pagamento para CNPJ antigo pode escapar dessa definição mesmo sendo fraudulento; idade não comprova legitimidade.

O limite de R$ 1.000 e a exigência de CNPJ antigo existem para que o repasse não se disfarce de "gasto" numa empresa de fachada recém-aberta.

**2. Do lado do destino: o pagador já tinha relação com ele antes da suspeita?**

- **Relação anterior:** existe aprovação do mesmo pagador para o mesmo titular destino, com data anterior à evidência mais antiga do estado atual do destino. É a mãe que já mandava a mesada antes de o filho virar laranja.
- **Primeira relação:** qualquer outro caso. É o perfil da vítima do golpe.

**Datas e limite da exceção.** Cada evidência guarda início conhecido ou desconhecido. Em E1, o início vem do mock; em E2 + E4, usar o mais antigo entre o início do vínculo local e o início informado para E4. Se os dois caminhos sustentarem o estado, considerar todas as evidências que os sustentam. A data local é quando a condição passou a ser satisfeita no histórico observado; não substituir pelo instante da consulta. Sem data suficiente, não estabelecer a exceção de relação anterior. Identificação tardia não revela quando a fraude começou: o relacionamento anterior pode fazer parte do esquema. A exceção preserva a política v1 e aceita esse risco, sem comprovar legitimidade.

## Regras e ordem junto de R1 a R4

Três regras compõem o módulo. Todas rejeitam, e cada uma combina o estado de uma conta com o tipo de ato.

| Regra | Condição | Resultado | Por quê |
| --- | --- | --- | --- |
| L1, destino laranja | destino `suspeita_elevada` e primeira relação | `rejected` | Protege a vítima nova sem travar quem já se relacionava com a conta |
| L2, pagador laranja | pagador `suspeita_elevada` e ato que não é gasto típico | `rejected` | Prende o dinheiro do golpe, mas deixa a pessoa pagar as próprias contas |
| L3, repasse suspeito | pagador `suspeita` e ato de repasse aparente | `rejected` | A evidência do estado mais o repasse formam a combinação de dois sinais exigida para rejeitar |

**Custo de L2:** mantém-se a rejeição também do ato “outro”, como na matriz v1. Um pagamento legítimo de R$ 1.500 sem recebimentos recentes pode ser recusado. A política é mais restritiva que impedir somente repasses; gasto típico e relação anterior são exceções assumidas, não provas de legitimidade.

Visto como matriz:

| Pagador \\ ato | Gasto típico | Repasse aparente | Outro |
| --- | --- | --- | --- |
| `nao` | regras base | regras base | regras base |
| `suspeita` | regras base | `rejected` (L3) | regras base |
| `suspeita_elevada` | regras base | `rejected` (L2) | `rejected` (L2) |

| Destino \\ relação | Relação anterior | Primeira relação |
| --- | --- | --- |
| `nao` ou `suspeita` | regras base | regras base |
| `suspeita_elevada` | regras base | `rejected` (L1) |

Destino em `suspeita` não muda a decisão: uma evidência isolada não intervém, como no acordo. O estado fica registrado na análise.

**Ordem completa:** R1, R2, L1, L2, L3, R4, R3; sem nenhuma, `approved`. Todas as rejeições vêm antes dos pedidos de 2FA, como no documento acordado.

## Cenários de aceite

Todos pressupõem que R1 a R4 não se aplicam, salvo quando indicado. Viram `test_laranja.py`, um teste por cenário; a classificação e o ato também precisam ser verificados.

| Caso | Situação | Estado | Ato ou relação | Resultado |
| --- | --- | --- | --- | --- |
| P01 | Mãe envia a mesada; aprovação anterior ao início informado da marcação do destino | destino `suspeita_elevada` por E1 | relação anterior | `approved`, com risco da exceção documentado |
| P02 | Novo pagador envia à mesma conta | destino `suspeita_elevada` por E1 | sem relação anterior | `rejected` (L1) |
| P03 | Conta com E1 paga R$ 180 à concessionária com conta CNPJ antiga | pagador `suspeita_elevada` | gasto típico | `approved` |
| P04 | Conta com E1, R$ 5.000 de entradas observadas em 1h, envia R$ 4.000 a pessoa física | pagador `suspeita_elevada` | repasse aparente | `rejected` (L2) |
| P05 | Conta com E1 envia R$ 1.500 a pessoa nova, sem entradas recentes | pagador `suspeita_elevada` | outro | `rejected` (L2) |
| P06 | Conta PF com E3 somente: R$ 2.000 de 6 titulares em 1h, 4 estreantes; envia R$ 1.600 a pessoa física | pagador `suspeita` | repasse aparente | `rejected` (L3) |
| P07 | Contexto de P06; paga R$ 90 a mercado com conta CNPJ antiga | pagador `suspeita` | gasto típico | `approved` |
| P08 | Rateio em conta PF antiga com E3 somente; paga R$ 1.200 a restaurante com conta CNPJ antiga | pagador `suspeita` | outro | `approved` |
| P09 | Padaria: conta de 10 anos, 400 contrapartes observadas; R$ 50 de marcada são 0,06% das entradas de 30 dias; sem outras evidências | pagador `nao` | outro | `approved` |
| P10 | Mock fora do ar, sem cache válido nem indício local | pagador `nao`, E1/E4 desconhecidas | conforme histórico disponível | regras base, indisponibilidade registrada |
| P11 | Oito dias após P06, sem novas entradas nem evidências; paga R$ 1.500 a pessoa física | pagador `nao` | outro, sem repasse observado | `approved` |
| P12 | Conta PF de 3 dias recebeu R$ 6.000 de 4 titulares; paga R$ 60 a telefonia com conta CNPJ antiga | pagador `suspeita`, E5 somente | gasto típico | `approved`, dentro do teto R1 |
| P13 | Contexto de P12, solicita saída de R$ 5.000 | pagador `suspeita` | conforme histórico | `rejected` (R1 decide antes) |
| P14 | Conta PF nova recebe R$ 6.000 de 5 titulares em 1h, ao menos 3 estreantes; sem outras evidências | `suspeita`, E3+E5 | a classificar no pedido | não elevar estado; decisão ainda depende do ato e das regras base |
| P15 | E2+E4, sem E1; saída de R$ 1.500 para pessoa nova | pagador `suspeita_elevada` | outro ou repasse aparente | `rejected` (L2) |
| P16 | Conta suspeita, R$ 1.000 de entradas observadas em 1h, envia R$ 600 a pessoa conhecida | pagador `suspeita` | repasse aparente prevalece sobre gasto típico | `rejected` (L3) |
| P17 | Conta PF com E3 somente, entradas de apenas R$ 600 em 1h; envia R$ 400 a pessoa nova | pagador `suspeita` | outro; não atinge mínimo de entrada | `approved` |
| P18 | Destino elevado por E2+E4, sem início local determinável | destino `suspeita_elevada` | relação anterior não estabelecida | `rejected` (L1), limitação registrada |
| P19 | Conta CNPJ recebeu de 5 titulares em 1h, sem E1/E2/E4/E5 | `nao`; E3 exige 30 para CNPJ | conforme pedido | regras base |
| P20 | Único vínculo é ter enviado antes a uma conta marcada; agora paga destino sem impedimento | pagador `nao` | conforme pedido | regras base; não propagar E2 contra quem enviou |

P14 verifica apenas o estado: R1 e L3 ainda podem atuar nas saídas. Usar CPFs nos casos de 5 ou 6 titulares; para CNPJ, E3 exige 30. Montar o histórico pelas regras reais da API, sem inserir aprovações impossíveis. Só chamar a demo de reconstrução de caso real se houver fonte identificada; os fixtures são fictícios.

P13 mostra a ordem: R1 já pega a conta nova, e o motivo informado é R1, como pede o acordo.

## Fonte 1: DICT simulado

O mock alimenta E1 e E4 com informações normalizadas por titular. Ele representa uma fonte antifraude controlada, não uma base pública de CNPJs nem uma reprodução integral do DICT. A organização liberou mocks de APIs externas. O contrato abaixo é próprio do protótipo; seus campos não são apresentados como campos oficiais do DICT.

```json
{
  "document": "DOCUMENTO_FICTICIO_DO_CENARIO",
  "as_of": "2026-10-17T12:00:00Z",
  "mule_or_scammer_marker": {
    "active": true,
    "started_at": "2026-10-16T12:00:00Z"
  },
  "distinct_fraud_reporters_90d": 1,
  "second_reporter_at": null,
  "open_reports": 0,
  "second_open_report_at": null
}
```

- **E1:** marcação ativa de laranja/golpista iniciada nos últimos 90 dias, ou pelo menos duas instituições distintas com relatos nos últimos 90 dias.
- **E4:** pelo menos duas notificações ainda abertas.
- `started_at`, `second_reporter_at` e `second_open_report_at` informam o início da condição que sustentam, não o início real da fraude. Exigir a data do caminho externo utilizado; campos incoerentes tornam a resposta indisponível.
- Fixtures devem representar o conhecimento disponível no instante do cenário, inclusive expiração e alterações. Nunca preencher início da evidência com a data da consulta. O corte de 90 dias é uma simplificação do protótipo, não regra de cancelamento de restrições reais.
- Cache válido pode ser usado; sem cache válido nem resposta utilizável, a evidência externa fica desconhecida. A decisão continua pelas evidências e regras disponíveis; falha não equivale a ausência de marcação.

**Como montar:**

- **Mock:** Mockserver no `docker compose`, com as respostas em `mocks/dict_expectations.json`, versionado. Se o Mockserver der trabalho, um container mínimo com FastAPI lendo o mesmo JSON serve.
- **Connector** em `src/connectors/dict_connector.py`: URL em variável de ambiente; sessão HTTP reaproveitada; timeout de 200 ms no mock local (em produção, por volta de 800 ms). Timeout, erro ou resposta 429 deixam E1 e E4 desconhecidas e o `dict_status` como `indisponivel`; nunca viram decisão.
- **Cache** em `dict_lookup`, por titular: validade única configurável, compartilhada entre os papéis de pagador e destinatário. Documentar o valor escolhido e testar expiração. Sem cache válido, consultar a fonte; se ela falhar, manter desconhecido.
- **Origem e destino:** o destino é consultado no momento do Pix. A origem é lida do cache e só consultada no primeiro Pix de um cliente ou quando o cache expira. Quando as duas consultas são necessárias, rodam em paralelo, com um único limite de tempo.
- **Contribuição:** não publicar automaticamente suspeitas no mock; a classificação local não deve alimentar a própria fonte e criar confirmação circular.

**Números do DICT real**, para calibrar o mock e responder à banca:

| Métrica | Valor oficial |
| --- | --- |
| Consulta de chave no DICT | 99% em até 1 segundo |
| Disponibilidade do DICT para consulta | 99,9% |
| Limite por pagador na consulta de chave | PF: balde de 100, reposição de 2 por minuto; PJ: balde de 1.000, reposição de 20 por minuto |
| Estatísticas antifraude de pessoa | 12.000 por minuto por instituição, balde de 36.000 |
| Tempo máximo de um Pix | 40 segundos |

Fontes: [Manual de Tempos do Pix](https://www.bcb.gov.br/content/estabilidadefinanceira/pix/Regulamento_Pix/IX_ManualdeTemposdoPix.pdf) e [especificação da API do DICT](https://www.bcb.gov.br/content/estabilidadefinanceira/pix/API-DICT.html).

**Em produção, sem chamada extra:** para fazer um Pix por chave, o banco já consulta o DICT; com `IncludeStatistics=true`, os contadores antifraude chegam na mesma resposta.

## Fonte 2: grafo de contas

O grafo alimenta E2, E3 e E5 e define o ato de repasse. Não há banco de grafos: as arestas ficam no Postgres, e cada evidência é uma consulta indexada.

**Arestas:**

| Tipo | Direção | Para quê |
| --- | --- | --- |
| `pix` | do pagador para o destino | seguir o dinheiro e separar vítima de cúmplice |
| `device` | sem direção | a mesma quadrilha operando várias contas |
| `document` | sem direção | o mesmo titular em contas diferentes |

IP não vira aresta: wi-fi público e operadoras com IP compartilhado ligariam pessoas sem relação nenhuma.

**A direção separa vítima de cúmplice.** Quem mandou dinheiro para uma conta marcada está antes dela e quase sempre é vítima: não ganha evidência. Quem recebeu dela está depois e pode ser o próximo elo: ganha E2, se passar pelas travas abaixo.

&#91;embedded content: como E1 vira E2 na rede laranja · 5 contas\]

L2 ganha E2 por estar depois de L1 no dinheiro. L3 divide o aparelho com L2, mas não ganha E2, porque L2 não está marcada no DICT: a suspeita não anda em cadeia. Se L3 repassar o que recebeu e tiver outra evidência (E3 ou E5), cai em L3 do mesmo jeito. A vítima A, que está antes, continua pagando o mercado sem fricção.

**Travas que protegem quem recebeu de boa-fé.** Receber Pix é passivo, e um golpista pode mandar R$ 1 de uma conta marcada para quem quiser prejudicar. Por isso:

1. **Reputação:** E2 só vale para contas com menos de 90 dias ou menos de 10 contrapartes. Uma padaria antiga não ganha E2.
2. **Proporção:** só conta se mais de 50% do que a conta recebeu em 30 dias veio da marcada.
3. **Expiração:** a janela de 30 dias passa, e a evidência some.
4. **Um salto, só a partir de E1:** a suspeita não se espalha em cadeia a partir de outras suspeitas.
5. **E2 isolada gera `suspeita`,** e `suspeita` só pesa no repasse (L3). Uma conta com E2 apenas pode continuar fazendo operações que não satisfaçam a definição de repasse aparente; isso não garante a legitimidade dessas operações.

|  | Padaria do Seu João | Conta L2 |
| --- | --- | --- |
| Recebeu da conta marcada | R$ 50, de um cliente golpista | R$ 2.000 |
| Idade e contrapartes | 10 anos, 400 contrapartes | 12 dias, 2 contrapartes |
| Peso do dinheiro marcado | 0,06% | 91% |
| Estado | `nao` | `suspeita` (E2), ou `suspeita_elevada` se houver E4 |

**Quem resolve o dinheiro da fraude é o MED, não o motor.** O Mecanismo Especial de Devolução atua sobre o valor (bloqueio cautelar e devolução à vítima), com direito de defesa para quem recebeu de boa-fé. O motor só impede que o próximo repasse saia.

## Modelagem de dados do módulo

O módulo não guarda estado de conta: tudo é calculado na hora a partir de `pix_analysis`, das arestas e do cache do DICT. O retrato do estado no momento da decisão vai para `pix_analysis.analysis_details`, para o `GET` devolver a análise original.

```sql
CREATE TABLE dict_lookup (
    document     TEXT PRIMARY KEY,  -- mock por titular, não por conta
    response     JSONB NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL,
    as_of        TIMESTAMPTZ NOT NULL
);

CREATE TABLE account_link (
    id           BIGSERIAL PRIMARY KEY,
    from_key     TEXT NOT NULL,  -- participante:agência:conta
    to_key       TEXT NOT NULL,
    link_type    VARCHAR(10) NOT NULL,
    first_seen   TIMESTAMPTZ NOT NULL,
    last_seen    TIMESTAMPTZ NOT NULL,
    total_amount BIGINT NOT NULL DEFAULT 0, -- agregado; não soma de janela
    UNIQUE (from_key, to_key, link_type)
);
CREATE INDEX ix_link_to ON account_link (to_key, link_type, last_seen);
CREATE INDEX ix_link_from ON account_link (from_key, link_type, last_seen);
```

**Cálculos temporais.** Entradas, saídas, primeiras aprovações e vínculos de aparelho são consultados no histórico de `pix_analysis` com suas janelas. `account_link.total_amount` é um agregado histórico; filtrar por `last_seen` não o transforma em soma de 30 dias. Arestas Pix e de aparelho derivam apenas de aprovações. `analysis_details` preserva os snapshots, datas e incertezas usados, sem expor tudo no GET.

O modelo único usa `payer_account`, `pix_analysis`, `account_link` e `dict_lookup`, conforme o guia v1.1. O SQL acima complementa as duas tabelas base; não criar as antigas `account` ou `rule_evaluation`. E2 precisa de snapshots válidos das contrapartes, preparados fora da trava; contraparte nova sem snapshot fica desconhecida nessa análise.

**Consultas que o módulo precisa**, todas com janela e índice:

| Para | Consulta |
| --- | --- |
| E2 | quanto a conta recebeu em 30 dias e quanto disso veio de contas com E1; aparelhos compartilhados com contas E1 |
| E3 | titulares distintos que enviaram à conta na última hora, e quantos nunca tinham enviado antes |
| E5 | quanto a conta recebeu em 24h, de quantos titulares |
| Repasse aparente | quanto o pagador recebeu e quanto enviou na última hora, em Pix aprovados |
| Relação anterior | primeira aprovação do pagador para o titular destino |
| Reputação | idade da conta e número de contrapartes distintas |

As arestas são gravadas no mesmo commit do Pix, para nunca haver Pix sem aresta ou aresta sem Pix. A identificação da conta de origem segue a premissa do guia: o payload não traz ISPB, então assumimos o banco do motor como participante único de origem.

## Testes e demo

Além dos testes HTTP de integração, testar as funções puras de classificação e ato: uma classificação incorreta pode produzir o mesmo status final. Verificar E1, E2+E4, E3+E5, precedência de repasse aparente, evidências desconhecidas e datas. As matrizes são especificação, não execução de testes.

Testes de integração black box por HTTP, com o mock roteirizado por teste; cada um monta o próprio histórico pelo `POST`.

| Arquivo | Cobre |
| --- | --- |
| `test_laranja.py` | P01 a P20, um teste por cenário |
| `test_laranja_dict.py` | E1 por marcação e por 2 instituições; E4 com 1 e 2 notificações; DICT com timeout e com 429 (decisão sai sem ele); pagador lido do cache, sem chamada ao mock |
| `test_laranja_grafo.py` | direção (quem enviou para a marcada não ganha E2); trava de reputação (padaria antiga); proporção de 50%; expiração de 30 dias; L3 sem E2 por aparelho de conta não marcada; R$ 1 enviado de propósito não trava a conta |
| `test_laranja_ato.py` | gasto típico no limite de R$ 1.000; CNPJ com 89 e 90 dias; repasse em 49% e 50%; rateio do restaurante pago a CNPJ antigo |
| `test_laranja_concorrencia.py` | vários repasses simultâneos da mesma conta: o lock faz cada um enxergar os anteriores |

**Demo, em cinco minutos de história:**

Usar conta pagadora antiga no caso principal, evitando que R1 esconda L2/L3. Se a marcação surge depois dos recebimentos, roteirizar a mudança no mock e no cache. Mostrar também P14 como contraste: E3+E5 permanece suspeita. Não montar histórico que as próprias regras teriam recusado.

1. L1 está marcada no DICT. Uma vítima nova tenta pagar: `rejected` (L1). A mãe que sempre mandava mesada paga: `approved`.
2. L1 paga a conta de luz: `approved`. L1 tenta repassar o que recebeu: `rejected` (L2). A mesma conta, dois destinos diferentes.
3. L2, conta nova que recebeu 91% do dinheiro de L1 e também de vários pagadores novos, tenta repassar: `rejected`.
4. A padaria que recebeu R$ 50 de L1 paga o fornecedor: `approved`. Receber de boa-fé não trava ninguém.
5. O DICT cai: o motor continua respondendo, só com as evidências locais, e registra a indisponibilidade.
6. Na tela, o grafo do cenário, gerado por um script com `networkx` fora da API.

A frase da apresentação: **"primeiro o motor classifica a conta, depois decide o ato: a laranja paga a luz, mas não repassa o dinheiro do golpe"**.

## Explicação, implementação e o que fica de fora

**Explicação.** A resposta continua com um único motivo. Quando L1, L2 ou L3 decide, o motivo traz o estado da conta, as evidências que o formaram e o tipo de ato, por exemplo: "pagador em `suspeita` (6 titulares em 1h, 4 de primeira vez) repassando 80% do recebido na última hora". Quando não decide, o estado não aparece na resposta; fica só em `pix_analysis.analysis_details`, para auditoria. Nunca se expõe documento completo nem a identidade das contas marcadas.

**Implementação.**

- O estado é calculado na hora, a partir do histórico e da resposta do DICT. Não há job em segundo plano nem tabela de estado para manter consistente; o retrato do estado no momento da decisão fica gravado junto da análise, para o `GET` devolver a decisão original.
- Uma função `classify_account(conta, contexto)` devolve estado e evidências; `classify_act(pix, contexto)` devolve o tipo de ato; as três regras são combinações desses dois resultados. Tudo em `src/rules/laranja.py`, sem acesso ao banco.
- As consultas novas usam janelas sobre `pix_analysis` (entradas, saídas, titulares distintos, primeira vez e aprovações do aparelho). `account_link` representa os vínculos agregados, sem substituir os eventos datados. As tabelas do guia bastam.
- O lock por conta pagadora, já previsto, mantém o cálculo de repasse coerente quando chegam vários Pix da mesma conta ao mesmo tempo.

**Fica de fora desta versão, como próximos passos:**

- **Renda declarada e gastos atuais:** compatibilidade entre movimentação e capacidade financeira viraria a evidência E6, via mock de cadastro. Precisa ser usada só como compatibilidade, nunca como perfil social, e o acordo retirou ajustes por saldo por falta de dado.
- **Situação cadastral do CPF e dados do CNPJ:** CPF cancelado ou de titular falecido, e empresa recém-aberta com capital mínimo, via mock da Receita.
- **Separar o dinheiro suspeito, não só a conta:** recusar apenas a parte da saída que excede o que entrou de fontes limpas, na lógica do MED 2.0. Exige registrar entradas e saídas com cuidado, porque o contrato não traz saldo.

## Riscos residuais e decisões para o time

**Riscos que a proposta aceita e deve apresentar:**

- Saídas de até R$ 1.000 podem passar como gastos típicos quando não satisfizerem antes o repasse aparente, por exemplo por falta de entradas observadas ou destino CNPJ antigo. R2 e R3 continuam valendo.
- Uma laranja que só aparece em outros bancos, sem marcação no DICT, não é vista: o motor só enxerga os Pix que passam por ele.
- A relação anterior pode já fazer parte do esquema: a data da identificação não revela o início da fraude. Exigir anterioridade à evidência não elimina esse risco; a exceção o aceita.
- "Recebido" significa aprovado pelo motor, não liquidado; o repasse é aparente.
- Os parâmetros são do protótipo e precisariam de dados reais para calibrar.

**Decisões que o time precisa tomar:**

- [ ] Combinar a integração com quem faz R1 a R4, pelos itens da seção Fronteira com as regras base.
- [ ] Implementar os limiares mantidos de gasto típico (R$ 1.000 e CNPJ com 90 dias) e de repasse (50% em 1h, mínimo de R$ 1.000 recebido).
- [ ] Documentar o custo mantido de L2: “outro” também é recusado (P05), mesmo sem recebimento recente.
- [ ] Definir como a demo mostra o DICT fora do ar (P10).
