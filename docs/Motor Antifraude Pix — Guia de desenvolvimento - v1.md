# Motor Antifraude Pix — Guia de desenvolvimento

Oct 17, 2026 · @renan

## Contexto e objetivo

Vamos entregar uma API que decide cada Pix em milissegundos como `approved`, `two_factor_required` ou `rejected`, sempre com um motivo nomeado. O link do repositório vai no grupo da final no Slack até domingo, 18/10, às 12h.

O motor responde a três restrições do problema, e cada decisão deste guia sai delas:

- **Tempo.** A decisão sai antes do dinheiro, em poucos segundos. Nada de consulta externa pesada nem de analista no caminho.
- **Histórico.** Um Pix sozinho diz pouco. Toda regra forte compara com o que esse pagador e esse destino já fizeram.
- **Fricção.** Bloquear cliente bom também é prejuízo. O 2FA só aparece onde há dúvida real; quem paga o aluguel todo mês passa direto.

Como a banca corrige, em ordem de peso:

| Critério | O que eles olham | Onde este guia responde |
| --- | --- | --- |
| Profundidade antifraude | regras calibradas, sem parar no óbvio | Catálogo de regras; Como as regras viram decisão |
| Padrão de código | camadas do Base Service, testes bem elaborados | Arquitetura; Testes |
| Modelagem de dados | estrutura do banco | Modelagem de dados |
| Solução funcional | roda pelo README, todo Pix gravado e consultável, decisão bate com as regras | Contrato; Testes |
| Documentação | README no modelo deles | Plano de execução |
| Apresentação | 7 min + 3 de perguntas, raciocínio por trás das decisões | Decisões descartadas |

A correção começa pelo README: cada parâmetro precisa de um "por quê" escrito. Regra sem justificativa conta como regra que não existe.

## Alinhamento com a política proposta pela equipe

O documento `regras-de-negocio.md` traz princípios que este guia adota, ajustes que já foram incorporados nas seções abaixo e cinco divergências. Esta seção registra a primeira versão do documento; a versão acordada pelo time substituiu as decisões abaixo, como mostra a seção Política vigente.

### Princípios adotados

1. Poucas regras determinísticas, com parâmetros explícitos.
2. Uma novidade isolada não caracteriza fraude: aparelho novo, destinatário novo ou conta recente precisam de contexto.
3. Informação ausente não é evidência desfavorável: no primeiro Pix, "aparelho novo" e "destinatário novo" são desconhecidos, não sinais negativos.
4. 2FA só para dúvida de identidade. O serviço apenas pede o 2FA: não executa, não recebe a conclusão e nunca libera uma nova tentativa por ter pedido 2FA antes.
5. Rejeição não afirma fraude confirmada.
6. O histórico prova solicitações recebidas e decisões emitidas. Não prova saldo, liquidação, conclusão de 2FA nem fraude. "Aprovado" não é "dinheiro que saiu".
7. Falha técnica nunca vira aprovação, rejeição ou 2FA silenciosamente: ou é erro HTTP, ou fica registrada no `metadata`.
8. Toda escolha tem um teste e, quando couber, um caso legítimo de contraste.
9. Parâmetros são hipóteses calibradas em cenários sintéticos, não valores validados pelo mercado.

### O que foi incorporado ao guia

| Ponto da política | Onde entrou |
| --- | --- |
| Janelas pelo instante de recebimento (`received_at`), no formato `(t − janela, t]`, com o Pix atual somado uma única vez | Semântica temporal, em Como as regras viram decisão; coluna nova na modelagem |
| Destinatário agregado pelo documento do titular, não pela conta, para que contas diferentes da mesma pessoa não fragmentem a soma | O que conta como histórico, no catálogo |
| IP compartilhado, sozinho, não liga pessoas (wi-fi público, operadora com IP compartilhado) | Grafo: arestas só por aparelho e titular |
| Primeiro Pix do pagador: `CTP_PRIMEIRA_VEZ` e `DSP_NOVO` em silêncio | Catálogo |
| Origem sem ISPB no payload: premissa de um único participante de origem, escrita no README | Modelagem |
| Medir latência total (fila, pool, espera de trava, consultas e commit) em p50, p95 e p99 | Metadata e explicabilidade |
| Cenários de borda: janela, fusos, chegada atrasada, falha na gravação, mudança de política, carga | Testes |

### Divergências e como foram resolvidas

| Tema | Este guia | Política da equipe | Decisão na política consolidada |
| --- | --- | --- | --- |
| Como os sinais fracos viram 2FA | score com pontos e limiar 50 | combinações nomeadas | Combinações nomeadas e precedência; o score sai |
| Horário noturno | `LIM_NOTURNO` | sem regra de horário | Mantido como 2FA, por âncora regulatória, em `America/Sao_Paulo` a partir de `received_at` |
| Montante | só aprovados | todas as tentativas | Todas as tentativas, sem reenvios. Aprovados só no perfil (A) e no repasse aparente (R) |
| Fontes externas e reputação | DICT simulado e grafo | nada de reputação ou consulta externa como dependência | DICT mantido, nunca como dependência: indisponível vira "desconhecido". Grafo limitado a 1 salto, com direção e travas de boa-fé, falando em "repasse aparente" |
| Quando rejeitar | regras fortes bloqueiam sozinhas | impedimento explícito ou combinação forte | Rejeita só por teto, por marcação no DICT ou por combinações de 2 evidências independentes; fan-in e proximidade sozinhos não rejeitam |

A rejeição contextual proposta pelo colega (aparelho novo, destinatário novo, valor atípico e conta destino recente juntos) entra como hipótese, com o contraste legítimo que ele mesmo propõe: troca de celular seguida de pagamento excepcional para fornecedor novo.

## Política vigente: R1 a R4 e camada de laranja

A equipe acordou uma política de quatro regras (`regras-de-negocio_1.md`), que substitui as versões anteriores e é implementada exatamente como está escrita. A camada de laranja, com DICT simulado e grafo, foi aprovada pelo time na forma do estado possivel\_laranja: ataca um risco residual que o próprio documento reconhece e segue os mesmos princípios.

### Base acordada

**Definições.**

- **Unidade de avaliação:** a conta pagadora, não a soma das contas do mesmo CPF/CNPJ.
- **Referência temporal:** `transaction_date`, para todas as janelas e para a idade da conta. Eventos atrasados, datas futuras e datas anteriores à abertura ainda estão pendentes.
- **Conta nova:** menos de 7 dias completos entre a abertura e a `transaction_date`. Com exatamente 7 dias, deixa de ser nova.
- **Acumulado de 24 horas:** soma dos Pix anteriores da mesma conta com análise `approved` na janela móvel de 24 horas, mais o Pix atual. `rejected` e `two_factor_required` não consomem o limite.
- **Dispositivo conhecido:** existe aprovação anterior da mesma conta com esse `device_id`, e a primeira dessas aprovações foi há 24 horas ou mais. Aprovações posteriores não reiniciam o prazo; tentativa rejeitada ou com 2FA não o inicia.

| Regra | Condição | Resultado |
| --- | --- | --- |
| R1, conta pagadora nova | conta nova e acumulado de 24h acima de R$ 1.000 (exatamente R$ 1.000 passa) | `rejected` |
| R2, teto geral | acumulado de 24h acima de R$ 10.000 (exatamente R$ 10.000 passa) | `rejected` |
| R3, frequência | pelo menos a terceira tentativa distinta da conta em 2 minutos, para quaisquer destinatários, contando tentativas com qualquer resultado e sem reenvios | `two_factor_required` |
| R4, dispositivo novo e valor elevado | dispositivo não conhecido e Pix individual de R$ 5.000 ou mais | `two_factor_required` |

**Ordem:** R1, R2, R4, R3; sem nenhuma, `approved`. Rejeição prevalece sobre 2FA. A resposta traz um único motivo, o determinante, com os valores observados e o limiar dele. Entrada inválida é erro HTTP: não consome limites, não conta na frequência e não cria familiaridade.

Os 21 cenários C01 a C21 do documento acordado são a especificação dos testes, um teste por cenário, nas bordas exatas que o documento define.

### Camada de laranja: possivel\_laranja (aprovada pelo time)

O motor primeiro classifica a conta, depois decide o ato. Nem toda transação que envolve uma laranja é fraudulenta: o recrutado paga as próprias contas, a vítima que paga a laranja não é cúmplice, e a mãe que manda mesada ao filho recrutado também não. A camada ataca o risco residual que o documento acordado reconhece (fraude abaixo dos tetos, no aparelho conhecido, com autenticação válida), sem pontuação, com um único motivo na resposta e sem pedir 2FA, porque contra laranja quem confirma o 2FA é o próprio operador.

**1. Estado da conta.** Calculado na hora, para pagador e destino, a partir de cinco evidências.

| Código | Evidência | Fonte | Parâmetro |
| --- | --- | --- | --- |
| E1 | marcação de conta laranja ou golpista no DICT, ou titular marcado por 2 ou mais instituições | DICT simulado | 90 dias |
| E2 | mais de 50% do que a conta recebeu veio de conta com E1, ou ela usa o aparelho de uma. Só E1 propaga, para o cálculo não andar em círculo | histórico local e grafo | 30 dias; só contas com menos de 90 dias ou menos de 10 contrapartes |
| E3 | muitos titulares distintos enviando, a maioria pela primeira vez | histórico local | 5 ou mais em 1h, sendo 3 de primeira vez; 30 para CNPJ |
| E4 | notificações de infração abertas contra a conta | DICT simulado | 2 ou mais |
| E5 | conta com menos de 7 dias recebendo volume alto de vários titulares | payload e histórico local | mais de R$ 5.000 em 24h, de 3 ou mais titulares |

| Estado | Quando |
| --- | --- |
| `confirmada` | E1, ou 2 ou mais evidências entre E2 e E5 |
| `suspeita` | exatamente 1 evidência entre E2 e E5 |
| `nao` | nenhuma evidência |

As evidências usam janelas; quando a janela passa, o estado cai sozinho, sem marcação local permanente. Com o DICT fora do ar, E1 e E4 ficam desconhecidas e o estado sai só das evidências locais; desconhecido nunca conta como evidência.

**2. Tipo de ato, do lado do pagador.**

| Ato | Definição |
| --- | --- |
| Gasto típico | até R$ 1.000, para destinatário conhecido (aprovação anterior para o mesmo titular) ou para CNPJ com conta de 90 dias ou mais |
| Repasse | o pagador recebeu pelo menos R$ 1.000 em Pix aprovados na última hora, este Pix leva o enviado na mesma hora a 50% ou mais disso, e o destino é pessoa física ou CNPJ com menos de 90 dias |
| Outro | o resto |

**3. Relação, do lado do destino.** Há relação anterior quando o mesmo pagador tem aprovação para o mesmo titular destino com data anterior à evidência mais antiga do estado atual do destino. Senão, é primeira relação.

**4. Regras.**

| Regra | Condição | Resultado | Por quê |
| --- | --- | --- | --- |
| L1, destino laranja | destino `confirmada` e primeira relação | `rejected` | Protege a vítima nova sem travar quem já se relacionava com a conta |
| L2, pagador laranja | pagador `confirmada` e ato que não é gasto típico | `rejected` | Prende o dinheiro do golpe, mas deixa a pessoa pagar as próprias contas |
| L3, repasse suspeito | pagador `suspeita` e ato de repasse | `rejected` | A evidência do estado mais o repasse formam a combinação de dois sinais exigida para rejeitar |

Destino em `suspeita` não muda a decisão: uma evidência isolada não intervém. O estado fica registrado na análise.

**Ordem completa:** R1, R2, L1, L2, L3, R4, R3; sem nenhuma, `approved`. Todas as rejeições vêm antes dos pedidos de 2FA.

**5. Cenários de aceite** (viram `test_laranja.py`; pressupõem que R1 a R4 não se aplicam, salvo indicação):

| Caso | Situação | Estado | Ato ou relação | Resultado |
| --- | --- | --- | --- | --- |
| P01 | Mãe manda a mesada de sempre ao filho, marcado no DICT na semana passada | destino `confirmada` | relação anterior | `approved` |
| P02 | Vítima nova paga a mesma conta | destino `confirmada` | primeira relação | `rejected` (L1) |
| P03 | A conta marcada paga R$ 180 de luz para a concessionária | pagador `confirmada` | gasto típico | `approved` |
| P04 | A conta marcada repassa R$ 4.000 do que acabou de receber | pagador `confirmada` | repasse | `rejected` (L2) |
| P05 | A conta marcada manda R$ 1.500 para uma pessoa nova, sem entradas recentes | pagador `confirmada` | outro | `rejected` (L2) |
| P06 | Conta que recebeu de 6 titulares em 1h, 4 de primeira vez, repassa 80% para pessoa física | pagador `suspeita` (E3) | repasse | `rejected` (L3) |
| P07 | A mesma conta paga R$ 90 no mercado | pagador `suspeita` | gasto típico | `approved` |
| P08 | Rateio: Ana recebe de 5 amigos, de primeira vez, e paga R$ 1.200 ao restaurante (CNPJ antigo) | pagador `suspeita` (E3) | outro | `approved` |
| P09 | Padaria antiga que recebeu R$ 50 de conta marcada paga o fornecedor | pagador `nao` | outro | `approved` |
| P10 | DICT fora do ar; a conta só era marcada no DICT | pagador `nao` (E1 desconhecida) | repasse | regras base, com `"dict": "indisponivel"` |
| P11 | Oito dias depois de P06, sem novas evidências, a conta repassa | pagador `nao` | repasse | regras base |
| P12 | Conta de 3 dias que recebeu R$ 6.000 de 4 titulares paga R$ 60 de telefone | pagador `confirmada` (E3 e E5) | gasto típico | `approved` |
| P13 | A mesma conta repassa R$ 5.000 | pagador `confirmada` | repasse | `rejected` (R1 decide antes) |

**6. Explicação e implementação.** Quando L1, L2 ou L3 decide, o motivo único traz o estado, as evidências e o ato, sem expor documentos nem a identidade das contas marcadas. O estado é calculado na hora (`classify_account` e `classify_act` em `src/rules/laranja.py`, sem acesso ao banco), e o retrato do momento fica gravado com a análise para o `GET` devolver a decisão original. As tabelas `account_link` e `dict_lookup` e o lock por conta pagadora já previstos bastam.

**7. Riscos aceitos.** A laranja pode disfarçar o repasse em vários gastos típicos de até R$ 1.000, limitados por R2 e R3. Laranja só em outros bancos, sem marcação no DICT, não é vista. A relação anterior só vale se for anterior à primeira evidência, para não ser fabricada com Pix pequenos. "Recebido" significa aprovado pelo motor, não liquidado.

**Próximos passos:** renda declarada e gastos como evidência E6 de compatibilidade, situação cadastral de CPF e CNPJ via mock da Receita, e separar o dinheiro suspeito em vez da conta inteira.

### O que o acordo mudou neste guia

| Tema | Antes | Agora |
| --- | --- | --- |
| Referência de tempo | `received_at` | `transaction_date` (o chamador é um sistema autenticado; o risco de data manipulada fica declarado) |
| Acumulado | todas as tentativas | só aprovados, por conta pagadora |
| Frequência | 5 em 10 minutos | 3 em 2 minutos |
| Regras retiradas | horário noturno, valor atípico (5x a média), idade da conta destino, geolocalização, IP | fora da versão acordada |
| Explicação | todos os indicadores no `metadata` | um único motivo determinante |
| Latência | medir p50, p95, p99 | não é critério; manter simples |

O catálogo de regras e as seções de decisão mais abaixo são histórico e backlog.

## Contrato da API

Duas rotas, nos nomes exatos do desafio: `POST /pix/transaction` analisa e grava; `GET /pix/transaction/{id}` devolve a análise gravada. A entrada é o payload do slide, sem campo a mais nem a menos.

Saída, nos três campos pedidos:

```json
{
  "key": "b3f1c2e0-7d4a-4c1e-9a52-1f0e6c9d2a77",
  "status": "two_factor_required",
  "metadata": {
    "policy_version": "2026-10-17.2",
    "reason_code": "R4",
    "reason": "dispositivo sem aprovação anterior há 24h e valor elevado",
    "observed": {"amount": 600000, "device_known": false},
    "threshold": {"amount_min": 500000, "device_wait_hours": 24},
    "dict": "consultado"
  }
}
```

| Situação | Status HTTP | Corpo |
| --- | --- | --- |
| Pix novo analisado | 201 | análise |
| mesmo `id` com o mesmo payload | 200 | a análise gravada, sem reavaliar |
| mesmo `id` com payload diferente | 409 | erro `PixIdConflict` |
| payload fora do schema | 400 | `QIT000001` |
| sem `INTERNAL-TOKEN` | 403 | `QIT000002` |
| `GET` de `id` inexistente | 404 | erro `PixAnalysisNotFound` |

**Idempotência pelo `id` do Pix.** O `id` vem do cliente e pode repetir por timeout ou clique duplo. Reavaliar um repetido muda a decisão (o histórico mudou) e infla a velocity com o próprio Pix. Por isso: `UNIQUE(pix_id)`, um `payload_hash` SHA-256 do JSON canônico (`sort_keys=True`) e a comparação acontece antes de qualquer regra. Dois envios simultâneos: o UNIQUE deixa um gravar; o outro relê e devolve a mesma análise.

**`key`** é nossa: `uuid4()` gerado no repository, `UNIQUE` no banco. O `id` interno do banco nunca sai.

**Schema de entrada** (`src/schemas/post_pix_transaction.json`): `amount` inteiro maior que zero, em centavos; datas com `pattern` ISO 8601 com fuso, porque `format` não valida nada no Base Service; `geolocation` opcional; `additionalProperties: false` em todos os objetos.

## Arquitetura do motor

O motor é uma função pura dentro das camadas do Base Service: os repositories trazem o histórico, as regras só calculam, o controller decide e grava tudo num único commit.

&#91;embedded content: caminho de um Pix no motor · 8 passos, 1 decisão\]

O único caminho que não chega às regras é o do Pix repetido, que devolve a análise já gravada.

| Peça | Onde mora | Responsabilidade |
| --- | --- | --- |
| Rotas | `src/resources/pix_transaction.py` + `src/app.py` | recebe, valida o schema, chama o controller, escolhe 201 ou 200 |
| Orquestração | `src/controllers/pix_transaction_controller.py` | idempotência, monta o contexto, chama o motor, grava e faz o commit |
| Contexto | `src/rules/context.py` | objeto com o payload e os números do histórico já calculados |
| Regras | `src/rules/<familia>.py` | uma classe por regra, com `code` e `evaluate(context)`, sem acesso ao banco |
| Política | `src/rules/policy.py` | transforma a lista de resultados em status, score e `decided_by` |
| Configuração | `src/rules/config.py` | limiares, pontos, liga/desliga e a versão das regras |
| Consultas | `src/repositories/pix_transaction_repository.py`, `account_repository.py` | as janelas de tempo, sempre pelos índices |
| Resposta | `src/dtos/pix_analysis_dto.py` | `key`, `status`, `metadata` |
| Erros | `src/errors/custom_errors.py` | `PixIdConflict` (409) e `PixAnalysisNotFound` (404), com código próprio |

**Por que as regras não tocam no banco.** O controller pede ao repository todos os números de que as regras precisam (contagens, somas, médias, último Pix com geolocalização) e entrega um contexto pronto. Isso deixa o número de consultas fixo por Pix, por volta de oito, e mantém o banco atrás do repository, como o Base Service exige.

**DICT no caminho do Pix.** Ao montar o contexto, o controller também chama o `DictConnector` (`src/connectors/dict_connector.py`) para a conta destino (e para a de origem, quando o cache diário dela não existir), com timeout de 200 ms e cache em `dict_lookup`. É a única chamada externa do motor, e ela nunca é obrigatória: sem resposta, as regras `DICT_*` ficam em silêncio e o `metadata` registra a indisponibilidade.

## Catálogo de regras

*Este catálogo é referência e backlog. A política que se implementa está na seção Política vigente.*

São 19 regras em seis famílias: as cinco do slide e mais Dispositivo, que o payload permite e quase ninguém vai usar. Outras oito, de DICT e grafo, estão na seção DICT simulado e grafo de contas: 27 no total. Cada regra tem um de três efeitos: **bloqueia** (`rejected`), **pede 2FA** (`two_factor_required`) ou **soma pontos** num score de sinais fracos. Valores em reais; no código, em centavos.

| Regra | Lógica | Parâmetros | Efeito | Por quê |
| --- | --- | --- | --- | --- |
| `LIM_NOTURNO` | valor acima do teto entre 20h e 6h em America/Sao\_Paulo, pelo received\_at; não pelo fuso de `transaction_date` | R$ 1.000 | 2FA | O Banco Central adota limite padrão menor à noite; golpe de sequestro relâmpago e conta tomada se concentram nesse horário |
| `LIM_TETO` | valor acima do teto por transação | R$ 50.000 | 2FA | Valor alto sozinho não prova fraude, mas o prejuízo potencial justifica um toque de confirmação |
| `LIM_COLD_START` | pagador com menos de 5 Pix aprovados, valor acima do teto | 5 Pix; R$ 2.000 | 2FA | Sem histórico não há perfil para comparar; teto menor protege o cliente novo sem bloqueá-lo |
| `VEL_RAJADA` | tentativas do pagador nos últimos 10 min, qualquer status | ≥ 5 → 2FA; ≥ 10 → bloqueia | 2FA / bloqueia | Pessoa raramente faz 5 Pix em 10 min; conta tomada esvazia o saldo em rajada |
| `VEL_REPETIDO` | mesmo pagador, destino e valor, `id` diferente, em menos de 2 min | 2 min | 2FA | Duplicidade acidental ou vítima pressionada a "tentar de novo"; o cliente confirma em um toque |
| `VEL_INSISTENCIA` | Pix bloqueados do pagador na última hora | ≥ 3 | bloqueia | Quem insiste depois de ser barrado está testando o limite do motor |
| `VEL_DESTINO_NOVO` | Pix do pagador, qualquer status, para o mesmo destino sem Pix aprovado há mais de 30 dias, na última hora, contando este | ≥ 3 | 2FA | Pagamento legítimo para alguém novo costuma ser um Pix só; vários em sequência é o valor sendo picotado, típico de conta tomada |
| `MNT_24H` | soma aprovada do pagador em 24h, mais este Pix | R$ 20.000 | 2FA | Pega o fracionamento: vários Pix abaixo dos tetos que juntos esvaziam a conta |
| `PRF_VALOR_ATIPICO` | valor comparado à média dos Pix aprovados em 90 dias, com pelo menos 5 | > 5x → +30; > 10x → 2FA | score / 2FA | Compara o cliente com ele mesmo; o mínimo de 5 evita punir quem tem pouco histórico |
| `PRF_HORARIO_ATIPICO` | pagador com 10 ou mais Pix e nenhum entre 0h e 5h, e este é nesse intervalo | 10 Pix; 0h–5h | +15 | Fora do padrão do cliente, mas sozinho não é fraude: só soma |
| `PRF_CONTA_PAGADORA_NOVA` | conta de origem aberta há menos de 30 dias, valor acima do teto | 30 dias; R$ 5.000 | +20 | Conta nova movimentando alto é padrão de conta aberta para fraude |
| `DSP_NOVO` | `device_id` nunca usado por esse pagador, que já tem histórico | +20; acima de R$ 200 → 2FA | score / 2FA | O Banco Central passou a limitar Pix de dispositivo nunca usado; aparelho novo é o sinal típico de conta tomada |
| `DSP_COMPARTILHADO` | pagadores distintos no mesmo `device_id` em 24h | ≥ 3 → 2FA; ≥ 5 → bloqueia | 2FA / bloqueia | Um aparelho operando várias contas é fazenda de contas ou golpista usando dados de várias vítimas |
| `DSP_VIAGEM_IMPOSSIVEL` | distância até o Pix anterior com geolocalização, dividida pelo tempo | > 900 km/h | 2FA | Mais rápido que um avião: o mesmo cliente não pode estar nos dois lugares |
| `CTP_DESTINO_NOVO` | conta destino aberta há pouco tempo | < 3 dias → +40; < 30 dias → +25 | score | Conta laranja é aberta para receber o golpe e usada logo em seguida |
| `CTP_PRIMEIRA_VEZ` | nenhum Pix aprovado antes entre esse pagador e esse titular destino; silenciosa se o pagador ainda não tem histórico, porque relação desconhecida não é sinal | — | +15 | Golpe quase sempre vai para destino novo; sozinho é o normal de qualquer pagamento novo |
| `CTP_FAN_IN` | pagadores distintos enviando ao mesmo destino na última hora | ≥ 5 → 2FA; ≥ 10 → bloqueia | 2FA / bloqueia | Conta laranja concentra várias vítimas em pouco tempo |
| `CTP_CONCENTRACAO_NOVO` | soma aprovada do pagador em 24h para destinos sem Pix aprovado há mais de 30 dias, mais este Pix | R$ 3.000 | 2FA | Invasão manda dinheiro para destino novo. Fecha o caso mais difícil: invasor no aparelho da vítima, picotando em valores que não parecem atípicos |
| `CTP_DESTINO_SUSPEITO` | destino recebeu Pix bloqueado nos últimos 7 dias | 7 dias | +30 | Quem já foi alvo de um bloqueio herda a suspeita, sem bloquear o próximo sozinho |

**Atenuantes**, contra a fricção. Eles só tiram pontos do score; nunca anulam um 2FA ou um bloqueio. E nenhum vale quando dispara `DSP_NOVO` ou quando a conta destino tem menos de 30 dias: é o que impede o invasor de abrir uma conta em nome da vítima para ganhar o `MIT_MESMO_TITULAR`.

| Atenuante | Lógica | Parâmetros | Efeito | Por quê |
| --- | --- | --- | --- | --- |
| `MIT_MESMO_TITULAR` | mesmo `document_number` nos dois lados | — | −30 e ignora `CTP_PRIMEIRA_VEZ` | Transferir para si mesmo, entre bancos, é o Pix de menor risco que existe |
| `MIT_DESTINO_RECORRENTE` | 3 ou mais Pix aprovados para esse destino em 90 dias, o primeiro há mais de 30 dias | 3 Pix; 90 dias | −25 | É o aluguel, a escola, o fornecedor: o cliente já confirmou esse destino várias vezes |

**O que conta como histórico.** Velocity e dispositivo contam todas as tentativas, inclusive bloqueadas: insistência é sinal. Montante, perfil e recorrência contam só `approved`, porque dinheiro bloqueado não saiu e 2FA não sabemos se foi confirmado. (O montante é divergência aberta com a política da equipe, que conta todas as tentativas.) Reenvios idempotentes nunca entram de novo nas contagens. Agregados por destinatário usam o documento do titular, não a conta: duas contas da mesma pessoa somam como um destino só.

**Fontes dos parâmetros.** Os dois valores do Banco Central (R$ 1.000 à noite e R$ 200 para dispositivo novo) precisam ser conferidos no texto vigente antes de entrarem no README. Os demais são julgamento nosso, justificados na coluna Por quê, e ficam em configuração para recalibrar.

## Como as regras viram decisão

*O score de pontos descrito nesta seção foi substituído pelas regras R1 a R4 da Política vigente. Valem daqui a semântica temporal atualizada e a ideia de regras como configuração.*

A decisão é a de maior severidade entre as regras que dispararam; o score só decide quando nenhuma regra forte disparou. O motor avalia sempre as 27 regras, sem parar na primeira, para que o `metadata` e a tabela `rule_evaluation` contem a história inteira.

1. Alguma regra **bloqueia** → `rejected`.
2. Senão, alguma regra **pede 2FA** → `two_factor_required`.
3. Senão, soma os pontos dos sinais fracos e subtrai os atenuantes, com piso em zero. Score ≥ 50 → `two_factor_required`.
4. Senão → `approved`.

**Por que o limiar é 50.** Nenhum sinal fraco passa de 40 sozinho, então o 2FA por score exige pelo menos dois sinais combinados. Conta destino aberta há 7 dias (+25) e primeiro Pix para ela (+15) somam 40: um pagamento novo para uma empresa nova, aprovado. Com o destino aberto há 2 dias (+40), a soma chega a 55 e pede confirmação.

**Por que a severidade máxima, e não tudo em pontos.** Uma rajada de 10 Pix ou um destino com 10 vítimas na última hora não devem depender de outros sinais para bloquear. E uma regra forte sozinha dá um motivo que o atendimento consegue explicar ao cliente.

Os sete casos que guiam a calibração, que também são os testes de ponta a ponta e a demo:

| Cenário | O que acontece | Regras disparadas | Score | Decisão |
| --- | --- | --- | --- | --- |
| Aluguel | R$ 2.500 às 10h, quinto mês para o mesmo destino, aparelho de sempre | `MIT_DESTINO_RECORRENTE` | 0 | `approved` |
| Autotransferência | R$ 8.000 para conta própria em outro banco, aberta há 2 anos | `CTP_PRIMEIRA_VEZ` ignorado, `MIT_MESMO_TITULAR` −30 | 0 | `approved` |
| Exemplo do slide | R$ 1.500 às 22h15 para conta aberta há 7 dias, primeira vez | `LIM_NOTURNO`, `CTP_DESTINO_NOVO` +25, `CTP_PRIMEIRA_VEZ` +15 | 40 | `two_factor_required` |
| Conta tomada, aparelho do invasor | R$ 9.000 de um aparelho nunca usado, 30x a média do cliente | `DSP_NOVO`, `PRF_VALOR_ATIPICO` | — | `two_factor_required` desde o primeiro Pix |
| Conta tomada, aparelho da vítima | 10 Pix de R$ 1.400 em paralelo para a conta do invasor, aberta há 20 dias | do 3º em diante: `CTP_CONCENTRACAO_NOVO` e `VEL_DESTINO_NOVO`; do 5º: `VEL_RAJADA` | 40 no 1º, 25 no 2º | 2 aprovados (R$ 2.800), depois `two_factor_required`, o 10º `rejected` |
| Rajada | sexto Pix do mesmo pagador em 10 minutos | `VEL_RAJADA` | — | `two_factor_required` |
| Conta laranja | destino que recebeu de 10 pagadores distintos na última hora | `CTP_FAN_IN` | — | `rejected` |

**Cold start.** Pagador sem histórico não é julgado por perfil: as regras `PRF_*` exigem o histórico mínimo e ficam em silêncio. No lugar delas entra o `LIM_COLD_START`, com teto de R$ 2.000 até o quinto Pix aprovado. As regras que só leem o payload (`LIM_NOTURNO`, `LIM_TETO`, `CTP_DESTINO_NOVO`, `PRF_CONTA_PAGADORA_NOVA`, `MIT_MESMO_TITULAR`) valem desde o primeiro Pix.

**Semântica temporal (atualizada pelo acordo).** Todas as janelas e a idade da conta usam `transaction_date`, a referência acordada pelo time, o que permite reproduzir cenários históricos. O serviço também grava `received_at`, só para auditoria. Só entram resultados já conhecidos no momento da decisão. Eventos atrasados, datas futuras e datas anteriores à abertura da conta são pendências do documento acordado: até serem decididas, o serviço não mistura data informada e relógio do serviço silenciosamente.

**Regras como configuração.** Limiares, pontos e liga/desliga ficam num único arquivo versionado (`src/rules/config.py`), e a versão vai em cada análise. É o equivalente, no protótipo, ao motor no code da QI, em que cada cliente define os próprios critérios, e permite responder "por que negou ontem?" mesmo depois de recalibrar.

## DICT simulado e grafo de contas

*Na Política vigente, esta seção vira a camada de laranja, com o estado possivel\_laranja e as regras L1 a L3. Valem daqui o desenho do mock, a direção das arestas, as travas de boa-fé e a demo; os pontos e as regras desta seção são histórico.*

O DICT simulado dá ao motor o que ele não tinha: contas confirmadas como fraudulentas por outras instituições. O grafo usa essas contas como sementes e segue o dinheiro a partir delas, sempre para frente, para não tratar a vítima como cúmplice.

### O mock do DICT

O DICT real guarda marcações de fraude feitas pelos participantes do Pix, associadas a chaves, contas e documentos. O mock é uma simplificação, mas segue a estrutura da seção Antifraude da API pública do DICT: contadores por tipo de marcação (MuleAccounts é conta laranja) em janelas de 90 dias, 12 meses e 60 meses. O README deve dizer isso e linkar a especificação.

```json
GET /dict/v1/statistics?participant=60701190&branch=3675&account=10442&document=98765432100
{
  "OwnerStatistics": {
    "FraudMarkers": {
      "Watermark": "2026-10-17T10:00:00Z",
      "ApplicationFrauds":           {"d90": 0, "m12": 0, "m60": 0},
      "MuleAccounts":                {"d90": 2, "m12": 2, "m60": 2},
      "ScammerAccounts":             {"d90": 0, "m12": 0, "m60": 0},
      "OtherFrauds":                 {"d90": 0, "m12": 1, "m60": 1},
      "TotalFraudTransactionAmount": {"d90": 520000, "m12": 610000, "m60": 610000},
      "DistinctFraudReporters":      {"d90": 2, "m12": 3, "m60": 3}
    },
    "InfractionReports": {"OpenReports": 3, "OpenReportsDistinctReporters": 2,
                          "RejectedReports": {"d90": 0, "m12": 0, "m60": 0}},
    "Entries": {"RegisteredAccounts": 4}
  }
}
```

- **Mockserver no compose**, com as respostas carregadas de `mocks/dict_expectations.json`, versionado. Sobe junto no `docker compose up`.
- **Connector** em `src/connectors/dict_connector.py`: URL em variável de ambiente, sessão HTTP reaproveitada (estabelecer conexão mTLS é caro), timeout de 200 ms no mock local e por volta de 800 ms em produção, porque o compromisso do Banco Central é de 1 segundo no percentil 99. Resposta 429 (limite de requisições) tem o mesmo tratamento do timeout. Estourou ou deu erro, o motor decide sem o DICT e o `metadata` registra `"dict": "indisponivel"`. O Pix nunca espera o DICT além disso.
- **Cache** em `dict_lookup`, com validade de 1 hora: a mesma conta consultada de novo não gera nova chamada.
- **Contribuição**: o mock aceita `POST /dict/v1/fraud-marks`. Quando o motor bloqueia por `GRF_LARANJA` ou `DICT_CONTA_MARCADA`, registra uma *suspeita*. Na vida real, a marcação definitiva passaria por análise humana.

**Origem e destino são consultados de formas diferentes.** A situação do pagador, que é cliente do banco, muda pouco; consultá-la a cada Pix gastaria tempo e o limite de consultas que o DICT impõe contra varredura.

|  | Destino | Origem |
| --- | --- | --- |
| Quando consultar | no momento do Pix | uma vez por dia, em lote, para os clientes ativos; e no primeiro Pix de um cliente novo |
| Cache em `dict_lookup` | 1 hora | 24 horas |
| No caminho do Pix | chamada com timeout de 200 ms | leitura local, quase sempre sem chamada |

Quando as duas consultas forem necessárias no mesmo Pix, elas rodam em paralelo, com um único limite de 200 ms. O mock aceita as duas contas numa chamada só; o README diz que é uma simplificação do DICT real.

**Os números do DICT real**, para calibrar o mock e responder à banca:

| Métrica | Valor oficial |
| --- | --- |
| Consulta de chave no DICT | 99% em até 1 segundo |
| Experiência do pagador na consulta ao DICT | 99% em até 2 segundos |
| Disponibilidade do DICT para consulta | 99,9% |
| Tempo máximo de um Pix | 40 segundos |
| Experiência do pagador no Pix inteiro | 50% em 6 segundos, 99% em 10 segundos |
| Limite por pagador na consulta de chave | PF: balde de 100, reposição de 2 por minuto; PJ: balde de 1.000, reposição de 20 por minuto; consulta com 404 custa 20 fichas |
| Estatísticas antifraude de pessoa | 12.000 por minuto por instituição, balde de 36.000 |

Fontes: [Manual de Tempos do Pix](https://www.bcb.gov.br/content/estabilidadefinanceira/pix/Regulamento_Pix/IX_ManualdeTemposdoPix.pdf) e [especificação da API do DICT](https://www.bcb.gov.br/content/estabilidadefinanceira/pix/API-DICT.html).

**Em produção, os contadores viriam de graça.** Para fazer um Pix por chave, o banco do pagador já consulta o DICT. Com o parâmetro `IncludeStatistics=true`, os contadores antifraude chegam na mesma resposta, sem chamada extra. O motor só precisaria recebê-los junto com o Pix.

### Regras do DICT e do grafo

| Regra | Lógica | Parâmetros | Efeito | Por quê |
| --- | --- | --- | --- | --- |
| `DICT_CONTA_MARCADA` | conta destino com marcação de conta laranja ou de golpista no DICT (MuleAccounts ou ScammerAccounts ≥ 1 em d90) | 90 dias | bloqueia | Evidência confirmada por outra instituição: é o caso em que dá para recusar com segurança |
| `DICT_DOCUMENTO_MARCADO` | titular do destino com marcações em 2 ou mais contas | 2 contas | +40 | Laranja que teve uma conta marcada abre outra em outro banco |
| `DICT_MED_RECENTE` | notificações de infração abertas contra o destino (OpenReports) | ≥ 2 em 30 dias | +30 | Vítimas já reclamaram, mesmo sem marcação concluída |
| `GRF_PROXIMIDADE_FRAUDE` | destino com cara de laranja (menos de 90 dias ou menos de 10 contrapartes) que recebeu dinheiro de conta marcada, ou que divide aparelho com ela | peso do dinheiro marcado em 30 dias: < 10% → 0; 10–50% → +15; > 50% → +35; aparelho → +35; 2 saltos, metade; marca vale 7 dias | score | A suspeita segue o dinheiro e a identidade da quadrilha; quem só enviou dinheiro para a conta marcada é vítima e não pontua |
| `GRF_LARANJA` | pagador repassando ≥ 50% do que recebeu na última hora, e mais 2 de: conta com menos de 30 dias; 3 ou mais pagadores de primeira vez; vínculo ativo (aparelho ou titular) com conta marcada; destino do repasse PF e novo | 1h; 50%; 2 sinais | bloqueia | Pega a laranja no momento do repasse, quando o 2FA não adianta porque quem confirma é o próprio operador da conta. Exigir sinais independentes evita bloquear o rateio da conta do restaurante |

Duas regras olham o **pagador** no DICT. Elas pegam a laranja que abriu conta neste banco limpa e foi marcada depois em outro, no momento em que tenta repassar por aqui:

| Regra | Lógica | Parâmetros | Efeito | Por quê |
| --- | --- | --- | --- | --- |
| `DICT_PAGADOR_MARCADO` | conta ou titular do pagador marcado como conta laranja no DICT | 90 dias | bloqueia | O pagador é uma laranja conhecida; 2FA não adianta porque quem confirma é o próprio operador. Recusar o repasse prende o dinheiro no primeiro salto |
| `DICT_PAGADOR_DOC_MARCADO` | titular do pagador com marcações em outras contas, mas não nesta | 2 contas | +40 | Indício forte, mas a conta daqui pode ser a legítima dele |

Pagador marcado também vira semente do grafo na hora: os destinos para onde ele manda dinheiro já herdam a suspeita.

Uma regra olha o consenso entre instituições, que pesa mais do que muitas marcações de um banco só:

| Regra | Lógica | Parâmetros | Efeito | Por quê |
| --- | --- | --- | --- | --- |
| `DICT_MULTIPLAS_INSTITUICOES` | instituições diferentes marcaram o titular do destino (DistinctFraudReporters) | ≥ 2 em d90 | bloqueia | Duas instituições independentes chegando à mesma conclusão é a evidência mais forte que o DICT oferece |

### A direção da aresta separa vítima de cúmplice

Quem está antes da conta marcada, porque mandou dinheiro para ela, quase sempre é vítima. Quem está depois, porque recebeu dela, é o próximo elo. Propagar sem olhar a direção marcaria as vítimas como cúmplices.

&#91;embedded content: propagação da suspeita na rede laranja · 5 contas\]

L2 e L3 herdam a suspeita de L1 por estarem depois dela no dinheiro ou no aparelho; a vítima A, que está antes, continua pagando o mercado sem fricção.

| Ligação com uma conta marcada | O que provavelmente é | Pontos |
| --- | --- | --- |
| recebeu dinheiro dela nas últimas 24h | próximo elo da cadeia | +15 a +35, pelo peso do dinheiro marcado |
| mesmo aparelho | operada pela mesma quadrilha | +35 |
| mesmo titular | a mesma laranja em outro banco | coberto por `DICT_DOCUMENTO_MARCADO` |
| enviou dinheiro para ela | vítima | 0 |
| vizinho de um vizinho | possível cadeia | metade do primeiro salto |

### Proteção de quem recebeu de boa-fé

Receber Pix é passivo: qualquer um recebe de qualquer um. Sem freio, a propagação travaria o comerciante que vendeu para um golpista, e abriria um ataque: mandar R$ 1 de uma conta marcada para quem se quer prejudicar. Quatro travas impedem isso:

1. **Ligação passiva não pesa sobre os Pix que a pessoa envia.** Ter recebido de uma conta marcada nunca aumenta, sozinho, o risco dos Pix de saída. Na `GRF_LARANJA`, só contam vínculos ativos: aparelho ou titular. IP compartilhado, sozinho, não liga pessoas.
2. **A propagação para em contas com reputação.** A `GRF_PROXIMIDADE_FRAUDE` só pontua contas com menos de 90 dias ou menos de 10 contrapartes. As demais recebem o registro no `metadata`, com 0 pontos.
3. **Proporção, não presença.** Pesa a fatia do dinheiro recebido em 30 dias que veio da conta marcada: menos de 10% não pontua.
4. **A suspeita expira.** Marcas por propagação valem 7 dias e caem pela metade a cada salto.

|  | Padaria do Seu João | Conta L2 |
| --- | --- | --- |
| Recebeu da conta marcada | R$ 50, de um cliente golpista | R$ 2.000 |
| Idade da conta | 10 anos | 12 dias |
| Contrapartes no histórico | 400 | 2 |
| Peso do dinheiro marcado | 0,06% | 91% |
| Pix que clientes mandam para ela | `approved`, 0 pontos de proximidade | +35; com destino novo, 2FA |
| Pix que ela envia | fornecedor de sempre: `approved` | repasse rápido: `rejected` por `GRF_LARANJA` |

**Quem resolve o dinheiro da fraude é o MED, não o motor.** O Mecanismo Especial de Devolução atua sobre o valor: bloqueio cautelar daquele dinheiro e devolução à vítima, com direito de defesa para quem recebeu de boa-fé. O resto da conta segue normal. Prazos e procedimentos vêm da regulação do Banco Central e devem ser conferidos no texto vigente antes de citados.

**Rastreamento para frente.** Quando um destino aparece marcado, o motor procura para onde o dinheiro dele foi nas últimas horas e grava essas contas em `account_flag`, com origem `propagacao` e o caminho. O próximo Pix para qualquer uma delas já chega com suspeita. É a lógica do MED 2.0, que segue o dinheiro por vários níveis, aplicada antes do dinheiro sair.

**O motivo mostra o caminho:** `"observed": "destino recebeu R$ 2.000 há 3h de conta marcada no DICT (1 salto)"`.

### A demo da rede laranja

1. A conta L1 está marcada no DICT. Uma vítima tenta mandar Pix para ela: `rejected` por `DICT_CONTA_MARCADA`.
2. Antes da marcação, L1 repassou R$ 2.000 para L2, conta nova. Uma segunda vítima manda para L2: `GRF_PROXIMIDADE_FRAUDE` +35 e `CTP_DESTINO_NOVO` +25 somam 60, e sai `two_factor_required` com o caminho no motivo.
3. L3, operada do mesmo aparelho de L2, tenta repassar o que recebeu: `rejected` por `GRF_LARANJA`.
4. A primeira vítima, que mandou dinheiro para L1, faz um Pix comum para o mercado: `approved`. É a prova de que a direção importa.
5. L4, cliente do próprio banco há 2 meses e marcada no DICT como laranja por outra instituição na semana passada, tenta mandar R$ 3.000 para uma conta nova: `rejected` por `DICT_PAGADOR_MARCADO`. O motor protege nos dois sentidos: o dinheiro não entra numa laranja e não sai de uma.

**Limite a declarar.** O motor só vê os Pix enviados por clientes do banco. Se a laranja estiver em outro banco, o dinheiro chegando nela aparece, o saindo não. Em produção, o DICT real e o compartilhamento da Resolução Conjunta nº 6 cobrem esse ponto cego.

## Modelagem de dados

Quatro tabelas: as contas que aparecem nos Pix, a transação com sua decisão, o status como enumerador e uma linha por regra avaliada. O histórico que as regras consultam é a própria `pix_transaction`: tudo que chegou fica gravado, como o escopo pede.

| Tabela | Uma linha por | Para quê |
| --- | --- | --- |
| `account` | conta que já apareceu como origem ou destino | identificar o mesmo pagador e o mesmo destino entre Pix; guardar `opening_date` e documento |
| `pix_status` | status possível | enumerador no padrão do Base Service: o banco recusa status inexistente |
| `pix_transaction` | Pix recebido | o histórico consultado pelas regras e a análise devolvida no `GET` |
| `rule_evaluation` | regra avaliada em cada Pix | auditoria da decisão e medida de quanto cada regra dispara |

```sql
CREATE TABLE account (
    id              SERIAL PRIMARY KEY,
    participant     VARCHAR(8)  NOT NULL,   -- ISPB; origem sem participant = o nosso banco
    branch          VARCHAR(10) NOT NULL,
    account_number  VARCHAR(20) NOT NULL,
    document_number VARCHAR(18) NOT NULL,   -- CPF ou CNPJ, só dígitos
    opening_date    TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMP   NOT NULL DEFAULT NOW(),
    UNIQUE (participant, branch, account_number)
);

CREATE TABLE pix_status (
    id         SERIAL PRIMARY KEY,
    enumerator VARCHAR(30) NOT NULL UNIQUE    -- approved, two_factor_required, rejected
);

CREATE TABLE pix_transaction (
    id                     SERIAL PRIMARY KEY,
    pix_id                 VARCHAR(64) NOT NULL UNIQUE,   -- o "id" do payload
    analysis_key           CHAR(36)    NOT NULL UNIQUE,   -- a "key" da resposta
    payload_hash           CHAR(64)    NOT NULL,          -- idempotência
    payload                JSONB       NOT NULL,          -- auditoria
    amount                 BIGINT      NOT NULL CHECK (amount > 0),
    transaction_date       TIMESTAMPTZ NOT NULL,          -- do payload: interpreta o evento
    received_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(), -- relógio do serviço: só auditoria; janelas usam transaction_date
    source_account_id      INTEGER     NOT NULL REFERENCES account(id),
    destination_account_id INTEGER     NOT NULL REFERENCES account(id),
    device_id              VARCHAR(64) NOT NULL,
    channel                VARCHAR(20) NOT NULL,
    ip                     VARCHAR(45) NOT NULL,
    latitude               NUMERIC(9,6),
    longitude              NUMERIC(9,6),
    status_id              INTEGER     NOT NULL REFERENCES pix_status(id),
    score                  INTEGER     NOT NULL,
    metadata               JSONB       NOT NULL,
    rules_version          VARCHAR(20) NOT NULL,
    created_at             TIMESTAMP   NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_pix_source_date ON pix_transaction (source_account_id, transaction_date);
CREATE INDEX ix_pix_dest_date   ON pix_transaction (destination_account_id, transaction_date);
CREATE INDEX ix_pix_device_date ON pix_transaction (source_account_id, device_id, transaction_date);

CREATE TABLE rule_evaluation (
    id                 SERIAL PRIMARY KEY,
    pix_transaction_id INTEGER     NOT NULL REFERENCES pix_transaction(id),
    rule_code          VARCHAR(40) NOT NULL,
    triggered          BOOLEAN     NOT NULL,
    effect             VARCHAR(20) NOT NULL,   -- reject, two_factor, score, mitigator, none
    points             INTEGER     NOT NULL DEFAULT 0,
    observed           VARCHAR(255),
    UNIQUE (pix_transaction_id, rule_code)
);
```

**Decisões de modelagem que vale defender na banca:**

- **Os três índices são o desempenho do motor.** Toda regra de histórico é um `COUNT` ou `SUM` numa janela de tempo por pagador, por destino ou por aparelho; sem eles, cada Pix varre a tabela inteira.
- **Append-only.** Nenhuma linha de `pix_transaction` ou `rule_evaluation` é alterada ou apagada depois de gravada. A análise de ontem continua explicável amanhã.
- **`account` é um upsert**, não um cadastro: onboarding está fora do escopo. A conta de origem vem sem `participant` no payload; gravamos o ISPB do nosso banco como constante. Se a mesma conta chegar com outra `opening_date`, mantemos a primeira e registramos no log.
- **Pix, análise e regras numa transação só.** O controller grava as três coisas e faz um único `commit`; nunca existe Pix sem decisão ou decisão sem motivo.

**Tabelas do DICT e do grafo.** Três tabelas a mais, todas gravadas no mesmo commit do Pix:

```sql
CREATE TABLE dict_lookup (
    id          SERIAL PRIMARY KEY,
    account_id  INTEGER     NOT NULL UNIQUE REFERENCES account(id),
    response    JSONB       NOT NULL,          -- resposta do DICT simulado
    fetched_at  TIMESTAMPTZ NOT NULL           -- cache vale 1 hora
);

CREATE TABLE account_link (
    id          SERIAL PRIMARY KEY,
    from_id     INTEGER     NOT NULL REFERENCES account(id),
    to_id       INTEGER     NOT NULL REFERENCES account(id),
    link_type   VARCHAR(10) NOT NULL,          -- pix (com direção), device, document
    first_seen  TIMESTAMPTZ NOT NULL,
    last_seen   TIMESTAMPTZ NOT NULL,
    total_amount BIGINT     NOT NULL DEFAULT 0,  -- só para pix
    UNIQUE (from_id, to_id, link_type)
);
CREATE INDEX ix_link_to ON account_link (to_id, link_type, last_seen);

CREATE TABLE account_flag (
    id          SERIAL PRIMARY KEY,
    account_id  INTEGER     NOT NULL REFERENCES account(id),
    origin      VARCHAR(20) NOT NULL,          -- dict, regra_local, propagacao
    hops        INTEGER     NOT NULL DEFAULT 0, -- saltos até a semente
    path        JSONB,                          -- contas no caminho, para o metadata
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_flag_account ON account_flag (account_id, created_at);
```

As arestas de `device` e `document` não têm direção: são gravadas nos dois sentidos. A de `pix` tem, e é ela que separa vítima de cúmplice. IP não vira aresta: compartilhamento de IP, sozinho, não liga pessoas. Na decisão, a proximidade de uma conta marcada é uma consulta indexada em `account_link` unida a `account_flag`, sem percorrer o grafo inteiro.

**Premissa sobre a origem.** O payload não traz o ISPB da conta de origem. Assumimos um único participante de origem (o banco que usa o motor) e gravamos o ISPB dele como constante; agência e conta só identificam a origem dentro dessa premissa, que fica escrita no README.

## Metadata e explicabilidade

Toda decisão precisa ser reconstruível a partir do próprio `metadata`: quem ler a resposta tem que conseguir dizer qual regra decidiu, o que ela viu e qual era o limite.

*Pela política acordada, a resposta traz um único motivo: o código da regra determinante (R1 a R4 ou L1 a L3), uma descrição e só os valores observados e limiares que o explicam. Para `approved`, a explicação diz que nenhuma condição de intervenção foi acionada. A lista completa de avaliações fica só em `rule_evaluation`, para auditoria interna.*

| Campo do `metadata` | Conteúdo | Por que está lá |
| --- | --- | --- |
| `rules_version` | versão da configuração usada | a decisão de ontem continua explicável depois de recalibrar |
| `decided_by` | código da regra que definiu o status, ou `SCORE` ou `NONE` | responde "por que" em uma palavra, para o atendimento |
| `score` | soma final dos sinais fracos, depois dos atenuantes | mostra o quanto faltou para o 2FA |
| `triggered` | lista das regras que dispararam: `rule`, `effect`, `points`, `observed`, `threshold` | o motivo explicável que o slide exige |
| `mitigators` | atenuantes aplicados e seus pontos | mostra por que um caso parecido com fraude passou |
| `latency_ms` | tempo do motor | prova o critério de tempo na apresentação |

Regras que não dispararam ficam fora do `metadata`, para a resposta continuar legível, mas entram em `rule_evaluation` com `triggered = false`. Assim dá para medir, depois, quantas vezes cada regra dispara e quantas decisões ela mudou.

**Regras do texto de `observed`:**

- Valores observados em linguagem humana e com unidade: "conta aberta há 7 dias", "6 Pix em 10 min", "R$ 1.500,00 às 22h15".
- Nunca documento completo, IP ou `device_id` inteiros. O `metadata` volta para o cliente e vai para o log; dado pessoal ali é vazamento. Use "documento terminado em 09" quando precisar.

**Log.** Além das linhas `ENTROU` e `SAIU` do Base Service, o controller escreve uma linha por análise com `pix_id`, `analysis_key`, status, `decided_by`, score e latência. Com o `X-Request-ID` dá para achar qualquer decisão a partir de uma reclamação.

**Desempenho.** Pelo acordo do time, tempo de execução não é critério de avaliação: a solução fica simples, sem meta de latência nem otimização antecipada. O `latency_ms` pode continuar no log, só como informação.

## Testes e cenários de demonstração

Cada regra do catálogo tem pelo menos dois testes black box, um em que dispara e outro em que fica quieta, no limite do parâmetro. É o que prova o critério "as decisões batem com as regras descritas".

**Especificação principal:** a matriz C01 a C21 do documento acordado vira `test_policy.py`, um teste por cenário, e os cenários P01 a P13 da camada de laranja viram `test_laranja.py`. A matriz mínima abaixo é da versão anterior e serve como backlog.

**Como os testes são escritos**, no padrão do Base Service e da Aula 3:

- Só HTTP: nenhum teste importa nada de `src/`. O histórico é montado pela porta da frente, com `POST /pix/transaction`, nunca com `INSERT`.
- Cada teste cria o próprio mundo: contas, documentos e `device_id` novos, gerados por um `PixPayloadGenerator` em `tests/utils/`. Nenhum teste depende de outro.
- Confere o `status` e o `metadata.decided_by`. Só o status deixa passar uma decisão certa pelo motivo errado.
- Datas controladas pelo payload: os testes de janela de tempo mandam `transaction_date` no passado em sequência, sem dormir.

**Matriz mínima**, em `tests/integration/pix_transaction/`:

| Arquivo | Cobre |
| --- | --- |
| `test_pix_contract.py` | 201, 400 por campo errado e campo a mais, 403 sem token, `GET` 200 e 404 |
| `test_pix_idempotency.py` | mesmo `id` e payload → 200 com a mesma `key`; mesmo `id` com outro valor → 409; repetição não conta na velocity |
| `test_rules_limite.py` | `LIM_NOTURNO` às 19h59 e às 20h00, no fuso do payload; `LIM_TETO`; `LIM_COLD_START` no quarto e no sexto Pix |
| `test_rules_velocity.py` | quarto e quinto Pix em 10 min; décimo; `VEL_REPETIDO`; `VEL_INSISTENCIA`; VEL\_DESTINO\_NOVO no 2º e no 3º Pix para o mesmo destino novo |
| `test_rules_montante.py` | soma de 24h abaixo e acima do teto; Pix bloqueado não soma |
| `test_rules_perfil.py` | valor 5x e 10x a média; silêncio com menos de 5 Pix; horário atípico |
| `test_rules_dispositivo.py` | aparelho novo abaixo e acima de R$ 200; aparelho em 3 e 5 contas; viagem impossível; Pix sem geolocalização não dispara |
| `test_rules_contraparte.py` | destino com 2, 7 e 40 dias; fan-in de 5 e 10; destino com bloqueio recente; concentração em destinos novos de R$ 2.800 e R$ 4.200 |
| `test_mitigators.py` | atenuante reduz o score, mas não derruba um 2FA nem um bloqueio |
| `test_scenarios.py` | os sete cenários da seção de decisão, de ponta a ponta |

**DICT e grafo**, em `test_dict.py` e `test_graph.py`, com o Mockserver roteirizado por teste:

- conta destino marcada → `rejected`; titular marcado por 2 instituições → `rejected`; documento marcado em outras contas → +40;
- DICT demorando 1 segundo ou respondendo 429 → a decisão sai sem ele e o `metadata` registra;
- pagador marcado como laranja → `rejected`; consulta da origem lida do cache, sem chamada ao mock;
- destino que recebeu de conta marcada → +35; conta que só enviou para a marcada → 0 pontos;
- padaria antiga que recebeu R$ 1 de conta marcada continua pagando o fornecedor com `approved` (contaminação passiva);
- rateio do restaurante, feirante e vaquinha → `approved`, provando que a `GRF_LARANJA` não pega inocentes.

**Cenários de borda**, vindos da política da equipe, em `test_edges.py`:

- C01 a C21 do documento acordado, um teste por cenário, incluindo as bordas exatas: R$ 1.000 e R$ 10.000 passam, R$ 1.001 e R$ 10.001 não; conta com exatamente 7 dias deixa de ser nova;
- a ordem R1, R2, R4, R3 e o único motivo na resposta (C16, C17, C20, C21);
- dispositivo: primeira aprovação inicia a espera de 24h, e aprovações posteriores não a reiniciam (C18, C19);
- `rejected` e `two_factor_required` não consomem o acumulado, mas contam em R3 (C08);
- reenvio do mesmo `id` não conta de novo (C09); pedido inválido não consome limites;
- mudança de versão da política não altera o `GET` de uma análise antiga;
- falha na gravação não devolve sucesso sem análise persistida.

**Seed da demo.** Um script `scripts/seed_demo.py` chama o próprio `POST` para criar o passado dos sete cenários: cinco meses de aluguel, dez pagadores para a conta laranja, o histórico do cliente cuja conta é tomada. Na apresentação, um segundo script dispara o Pix de cada cenário e imprime status, `decided_by` e latência. A demo não depende de rede nem de serviço externo.

## Plano de execução até a entrega

A ordem garante que, se o tempo acabar, o que existe roda, está testado e documentado: primeiro o caminho completo com poucas regras, depois mais regras, por último o polimento. Três frentes em paralelo: **A** motor e regras, **B** API, banco e infraestrutura, **C** testes, seed e README.

**Sábado, até 19h: o caminho completo de ponta a ponta**

- [ ] B: `database.sql` com as quatro tabelas e os três índices; models; `docker compose down -v` e subir limpo
- [ ] B: schema JSON, resource, `POST` e `GET`, idempotência com `payload_hash`, DTO da resposta
- [ ] A: interface de regra, avaliador e política de decisão, com `LIM_NOTURNO`, `LIM_TETO` e `CTP_DESTINO_NOVO`
- [ ] C: `PixPayloadGenerator` e os testes de contrato e idempotência
- [ ] Todos: o exemplo do slide sai `two_factor_required` pelo motivo certo

**Sábado, 20h à 01h: o catálogo inteiro**

- [ ] A: as regras de histórico (velocity, montante, perfil, contraparte) e os atenuantes, com as travas contra conta em nome da vítima
- [ ] A: as regras de dispositivo, incluindo viagem impossível
- [ ] B: repositories com as consultas de janela; log por análise; `rule_evaluation` gravada no mesmo commit
- [ ] C: um arquivo de teste por família, dois testes por regra no limite do parâmetro

**Frente DICT e grafo, por ordem de valor**

- [ ] Mockserver no compose, `DictConnector` com timeout e fallback, `DICT_CONTA_MARCADA` (\~2h)
- [ ] `account_link` com direção e `GRF_PROXIMIDADE_FRAUDE` de 1 salto (\~2h)
- [ ] Testes do DICT e do grafo, incluindo vítima sem pontos e os três inocentes (\~1h)
- [ ] `GRF_LARANJA`, rastreamento para frente e `POST` de suspeita no mock (\~1h30)
- [ ] Dois saltos e o desenho da rede para a demo, se sobrar tempo

* [ ] `classify_account` (E1 a E5, estados `nao`, `suspeita`, `confirmada`), `classify_act` (gasto típico, repasse, outro) e as regras L1 a L3, com os cenários P01 a P13 como testes

**Madrugada: dormir pelo menos 5 horas.** Ninguém apresenta bem nem acha bug depois de 30 horas acordado.

**Domingo, até 10h: cenários, README e prova da máquina limpa**

- [ ] C: `test_scenarios.py` com os sete cenários e o `seed_demo.py`
- [ ] C e A: README no modelo do desafio, com a tabela Regra, Lógica, Parâmetros e Por quê copiada deste guia
- [ ] B: apagar a pasta, clonar de novo, `docker compose up` e `pytest` verdes, sem passo manual
- [ ] Conferir os parâmetros do Banco Central na fonte antes de citá-los

**Domingo, 10h às 12h: congelar e ensaiar**

- [ ] Código congelado às 11h: depois disso só correção de texto
- [ ] Ensaio cronometrado: 7 minutos, com a demo ao vivo e um plano B em vídeo ou print
- [ ] Link do repositório público no grupo da final no Slack antes das 11h45

**Roteiro dos 7 minutos:** 1 min o problema (tempo, histórico, fricção); 2 min como o motor decide; 2 min a demo com os sete cenários; 1 min modelagem e testes; 1 min o que descartamos e por quê. As perguntas mais prováveis da banca: "por que esse parâmetro?", "e se o cliente repetir o Pix?", "e o cliente sem histórico?". As três respostas já estão neste guia.

## Decisões descartadas, riscos e fora do escopo

Cada alternativa abaixo foi considerada e tem um cenário em que ganharia. É o material do último minuto da apresentação.

| Alternativa | Por que descartamos | Ganharia se |
| --- | --- | --- |
| Aprovar tudo, sem motor | a fraude passa inteira e o prejuízo fica com o banco e o cliente | o volume de fraude fosse menor que o custo de operar o motor |
| Modelo de ML treinado | sem dados rotulados de fraude; um modelo em dados sintéticos só reaprende as regras que geraram os dados, e não explica a decisão | houvesse histórico real rotulado e uma camada de explicação por feature |
| Jev como decisor | entrada toda estruturada, sem texto livre; acrescenta até 500 ms; a decisão deixaria de bater com as regras descritas; limite atual de 20 requisições por segundo. Custo não é o problema: cerca de R$ 0,000075 por Pix | o Pix trouxesse campo de mensagem, ou como segunda opinião na zona cinza, com timeout e fallback para as regras |
| Tudo em pontos, sem regras fortes | um destino com 10 vítimas na última hora dependeria de outros sinais para ser barrado, e o motivo ficaria difícil de explicar | houvesse dados para calibrar os pesos estatisticamente |
| Contadores pré-agregados em vez de consultas de janela | mais rápido, mas duplica estado e exige manter os contadores consistentes | o volume passasse do que índices em `pix_transaction` aguentam com folga |
| Reavaliar Pix repetido | a decisão mudaria com o histórico e a velocity contaria o mesmo Pix duas vezes | nunca: o mesmo `id` é o mesmo Pix |

**Riscos e como mitigamos:**

- **Parâmetros sem dados reais.** Sete dias, R$ 1.000, R$ 10.000, 3 em 2 minutos e R$ 5.000 são escolhas do protótipo, não padrão de mercado. Ficam em configuração versionada e `rule_evaluation` mede o quanto cada regra dispara.
- **Risco residual declarado no acordo.** Fraude abaixo dos tetos no dispositivo conhecido, pagamento sob ameaça com autenticação válida, rajada mais lenta que 2 minutos, aprovação pequena criando familiaridade do aparelho. A camada de laranja ataca os dois primeiros quando há conta laranja envolvida.
- **Data informada pelo chamador.** Como as janelas usam `transaction_date`, um chamador com datas erradas distorce as contagens. O chamador é um sistema autenticado; a validação de datas inconsistentes é pendência explícita.
- **Concorrência.** Pedidos simultâneos da mesma conta podem atravessar R1, R2 e R3 juntos. O lock por conta pagadora mantém as contagens coerentes.
- **Confundir decisão com fato.** Aprovação não prova liquidação, e rejeição por teto não é fraude confirmada. O README usa "tentativa", "aprovado pelo motor" e "repasse aparente".

**Fora do escopo** (do próprio desafio ou por tempo): onboarding e cadastro de contas; front-end; outras APIs; o retorno do 2FA (não sabemos se o cliente confirmou, por isso 2FA não conta como aprovado no histórico); o DICT real (usamos um mock inspirado nele); um banco de grafos dedicado, como Neo4j, que traria infraestrutura nova sem ganho nesse volume; recalibração automática dos parâmetros; e segurar o Pix suspeito para análise, que o Manual de Tempos do Pix permite por até 30 minutos das 8h às 20h em dias úteis e 60 minutos nos demais horários. Entram na apresentação como próximos passos, em uma frase cada.
