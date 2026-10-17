# Motor Antifraude Pix — Guia de desenvolvimento — v1.1

Oct 17, 2026 · @renan · revisão v1.1 em 17/10/2026

Revisão documental: preserva a estrutura e os arquivos v1. Atualiza classificação, combinações de evidências, histórico observável, precedência dos atos e cenários. Não representa implementação nem testes executados.

## Contexto e objetivo

Vamos entregar uma API que analisa cada solicitação de Pix como `approved`, `two_factor_required` ou `rejected`, sempre com um motivo nomeado. O link do repositório vai no grupo da final no Slack até domingo, 18/10, às 12h.

O motor responde a três restrições do problema, e cada decisão deste guia sai delas:

- **Tempo.** A análise precede a operação; tempo de execução não é critério de avaliação. Consultas ao mock têm espera limitada, sem meta numérica de desempenho.
- **Histórico.** Um Pix sozinho diz pouco. Toda regra forte compara com o que esse pagador e esse destino já fizeram.
- **Fricção.** Bloquear cliente bom também é prejuízo. O 2FA só aparece onde há dúvida real; quem paga o aluguel todo mês passa direto.

Critérios de avaliação apresentados no desafio:

| Critério | O que eles olham | Onde este guia responde |
| --- | --- | --- |
| Profundidade antifraude | regras calibradas, sem parar no óbvio | Regras base; Módulo de conta laranja; Grafo de contas |
| Padrão de código | camadas do Base Service, testes bem elaborados | Fluxo do POST; Testes e demo |
| Modelagem de dados | estrutura do banco | Modelo de dados |
| Solução funcional | roda pelo README, todo Pix gravado e consultável, decisão bate com as regras | Contrato da API; Ordem de decisão |
| Documentação | README no modelo deles | Plano de implementação |
| Apresentação | 7 min + 3 de perguntas, raciocínio por trás das decisões | Testes e demo; Riscos e alternativas |

A correção começa pelo README: cada parâmetro precisa de um "por quê" escrito. Regra sem justificativa conta como regra que não existe.

## Fontes deste guia

Este guia junta três documentos do time num desenho único. Quando um deles decide algo, o guia segue; quando diverge, a seção Convenções e pendências registra.

| Documento | O que define | Status |
| --- | --- | --- |
| `regras-de-negocio-v1.md` (política acordada) | regras base R1 a R4, definições, ordem, motivo único, cenários C01 a C21 | acordada pelo time |
| `dados-e-fluxo-v1.md` | modelo de dados, indicadores, fluxo do POST, trava por conta, idempotência, GET | proposta técnica v0.1, a revisar |
| [Módulo de conta laranja v1.1](modulo-contas-laranja-v1.1.md) | DICT simulado, grafo, estado `possivel_laranja`, regras L1 a L3, cenários P01 a P20 | revisão v1.1 da proposta do time |

Princípios comuns aos três: poucas regras determinísticas; sem pontuação nem probabilidade de fraude; um único motivo na resposta; informação ausente não é evidência; o histórico prova solicitações e decisões, não liquidação nem fraude; falha técnica nunca vira decisão; valores são parâmetros do protótipo, não limiares validados; tempo de execução não é critério de avaliação.

Versões anteriores deste guia (catálogo de 27 regras, score, primeira política consolidada) ficam no histórico do documento.

## Regras base R1 a R4

Quatro regras determinísticas, implementadas exatamente como na política acordada.

**Definições.**

- **Unidade de avaliação:** a conta pagadora, não a soma das contas do mesmo CPF/CNPJ.
- **Referência temporal:** `transaction_date`, para janelas, idade da conta e espera do aparelho.
- **Conta nova:** menos de 7 dias completos entre a abertura e a `transaction_date`. Com exatamente 7 dias, deixa de ser nova.
- **Acumulado de 24 horas:** soma dos Pix anteriores da mesma conta com análise `approved` na janela, mais o Pix atual. `rejected` e `two_factor_required` não consomem o limite.
- **Dispositivo conhecido:** existe aprovação anterior da mesma conta com esse `device_id`, e a primeira dessas aprovações foi há 24 horas ou mais. Aprovações posteriores não reiniciam o prazo; tentativa rejeitada ou com 2FA não o inicia.
- **Destinatário conhecido:** aprovação anterior da mesma conta para o mesmo titular destino. Não é usado por R1 a R4; é usado pelo módulo de laranja.

| Regra | Condição | Resultado | Por quê |
| --- | --- | --- | --- |
| R1, conta pagadora nova | conta nova e acumulado de 24h acima de R$ 1.000 (exatamente R$ 1.000 passa) | `rejected` | Limita a exposição inicial e impede contornar o teto fracionando |
| R2, teto geral | acumulado de 24h acima de R$ 10.000 (exatamente R$ 10.000 passa) | `rejected` | Exposição máxima simples e resistente à fragmentação |
| R3, frequência | pelo menos a terceira tentativa distinta da conta em 2 minutos, qualquer destinatário, qualquer resultado, sem reenvios | `two_factor_required` | Rajada concentrada pede confirmação de identidade sem rejeitar só por quantidade |
| R4, dispositivo novo e valor elevado | dispositivo não conhecido e Pix individual de R$ 5.000 ou mais | `two_factor_required` | Falta de familiaridade do acesso com exposição relevante |

Entrada inválida é erro HTTP: não consome limites, não conta em R3 e não cria familiaridade. A primeira transação de uma conta não sofre intervenção só por falta de histórico.

Os cenários C01 a C21 da política acordada são a especificação de `test_policy.py`, um teste por cenário, com testes adicionais nas bordas temporais, após confirmar as convenções pendentes.

## Módulo de conta laranja

O motor primeiro classifica a conta (`possivel_laranja`), depois decide o ato: a laranja paga a conta de luz, mas não repassa o dinheiro do golpe.

**A tese.** Contra conta tomada, o 2FA pode ajudar se o invasor não tiver o segundo fator. Contra conta laranja, não: quem confirma é o próprio operador da conta. A política acordada reconhece esse risco residual (fraude abaixo dos tetos, no aparelho conhecido, com autenticação válida) e só admite fontes externas diante de um problema concreto não resolvido. O DICT dá marcações e relatos de outras instituições; o grafo local segue o dinheiro e o aparelho a partir delas. A QI é participante direto do Pix e se conecta ao DICT: o mock representa essa categoria de fonte, com simplificações explícitas.

**Premissa:** nem toda transação que envolve uma laranja é fraudulenta. O recrutado paga as próprias contas, a vítima que paga a laranja não é cúmplice, e a mãe que manda mesada ao filho recrutado também não.

### Estado da conta

Calculado na hora, para pagador e destino, a partir de cinco evidências.

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

Quando a janela de uma evidência passa, o estado cai sozinho; não há marcação local permanente. Com o DICT fora do ar, E1 e E4 ficam desconhecidas, e desconhecido nunca conta como evidência.

**Histórico observável.** “Recebeu” e “enviou” significam análises anteriores `approved` que passaram pelo motor, não liquidação nem saldo. Rejeições e 2FA não alimentam esses valores. O pedido atual entra uma única vez no total de saída projetado. Não inventar recebimentos de outras instituições: ausência de registros significa falta de observação e impede acionar o indicador dependente deles, sem apagar outras evidências. Usar `transaction_date`, histórico já persistido e nenhum evento futuro.

**Escopo das evidências.** O mock informa marcações por titular (CPF/CNPJ); idade, fluxo e reputação local são por conta. Em E2, o ramo de valor exige entradas positivas; o ramo de aparelho não exige proporção, mas exige a mesma condição de idade/reputação. Contrapartes são distintas e observadas em 30 dias. Aparelho compartilhado exige aprovações anteriores de contas pagadoras com o mesmo `device_id` em 30 dias; o aparelho do pagador nunca é atribuído ao destinatário. Só E1 origina E2, com snapshot válido da fonte; vínculo com outra conta suspeita não propaga a suspeita.

### Tipo de ato e relação

| Ato do pagador | Definição |
| --- | --- |
| Gasto típico | até R$ 1.000, para destinatário conhecido ou para CNPJ com conta de 90 dias ou mais |
| Repasse aparente | recebeu pelo menos R$ 1.000 em Pix aprovados na última hora, este Pix leva o enviado na mesma hora a 50% ou mais disso, e o destino é pessoa física ou CNPJ com menos de 90 dias |
| Outro | o resto |

**Prioridade do ato:** avaliar `repasse_aparente` primeiro, depois `gasto_tipico` e, por último, `outro`. Se recebeu R$ 1.000 observados e envia R$ 600 a uma pessoa conhecida, é repasse aparente, mesmo satisfazendo a descrição de gasto típico. O padrão observado de entrada/saída prevalece sobre a familiaridade; isso pode bloquear também um repasse legítimo. Sem entradas observadas suficientes, não inferir repasse. Um pagamento para CNPJ antigo pode escapar dessa definição mesmo sendo fraudulento; idade não comprova legitimidade.

Há **relação anterior** com o destino quando o mesmo pagador tem aprovação para o mesmo titular com data anterior à evidência mais antiga do estado atual do destino. Senão, é primeira relação.

**Datas e limite da exceção.** Cada evidência guarda início conhecido ou desconhecido. Em E1, o início vem do mock; em E2 + E4, usar o mais antigo entre o início do vínculo local e o início informado para E4. Se os dois caminhos sustentarem o estado, considerar todas as evidências que os sustentam. A data local é quando a condição passou a ser satisfeita no histórico observado; não substituir pelo instante da consulta. Sem data suficiente, não estabelecer a exceção de relação anterior. Identificação tardia não revela quando a fraude começou: o relacionamento anterior pode fazer parte do esquema. A exceção preserva a política v1 e aceita esse risco, sem comprovar legitimidade.

### Regras

| Regra | Condição | Resultado | Por quê |
| --- | --- | --- | --- |
| L1, destino laranja | destino `suspeita_elevada` e primeira relação | `rejected` | Protege a vítima nova sem travar quem já se relacionava com a conta |
| L2, pagador laranja | pagador `suspeita_elevada` e ato que não é gasto típico | `rejected` | Prende o dinheiro do golpe, mas deixa a pessoa pagar as próprias contas |
| L3, repasse suspeito | pagador `suspeita` e ato de repasse aparente | `rejected` | Evidência do estado mais repasse formam a combinação de dois sinais exigida para rejeitar |

**Custo de L2:** mantém-se a rejeição também do ato “outro”, como na matriz v1. Um pagamento legítimo de R$ 1.500 sem recebimentos recentes pode ser recusado. A política é mais restritiva que impedir somente repasses; gasto típico e relação anterior são exceções assumidas, não provas de legitimidade.

Destino em `suspeita` não muda a decisão: uma evidência isolada não intervém. O módulo nunca pede 2FA.

### Cenários de aceite

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

Todos pressupõem que R1 a R4 não se aplicam, salvo indicação. Viram `test_laranja.py`.

## Ordem de decisão e motivo único

A política de decisão é uma função pura: recebe o contexto já montado (indicadores das regras base e resultado do módulo de laranja) e devolve o primeiro resultado aplicável, sem novas consultas.

&#91;embedded content: ordem de decisão · 7 regras, 3 resultados\]

R1 vem antes de R2 por ser a restrição específica da conta nova. As regras do módulo entram depois dos tetos e antes dos pedidos de 2FA, porque rejeição prevalece sobre 2FA. Entre R4 e R3, a ordem é convenção de explicação, não de capacidade de detectar fraude.

**Motivo único.** A resposta traz só o motivo determinante, com os valores observados e o limiar dele, em centavos. Regras secundárias não aparecem como lista de alertas. Para `approved`, o motivo diz que nenhuma condição de intervenção foi acionada; aprovação não é garantia de segurança, e rejeição por teto não é fraude confirmada.

| Código do motivo | Regra |
| --- | --- |
| `NEW_ACCOUNT_LIMIT_EXCEEDED` | R1 |
| `DAILY_LIMIT_EXCEEDED` | R2 |
| `MULE_DESTINATION` | L1 |
| `MULE_PAYER` | L2 |
| `SUSPECTED_MULE_FORWARDING` | L3 |
| `NEW_DEVICE_HIGH_AMOUNT` | R4 |
| `HIGH_FREQUENCY` | R3 |
| `POLICY_PASSED` | nenhuma |

Os nomes seguem o padrão proposto em `dados-e-fluxo-v1.md`; são propostas a confirmar com quem implementa as regras base.

## Contrato da API

Duas rotas, nos nomes exatos do desafio: `POST /pix/transaction` analisa e grava; `GET /pix/transaction/{id}` devolve a análise gravada. A entrada é o payload do slide; a saída tem os três campos pedidos.

```json
{
  "key": "b3f1c2e0-7d4a-4c1e-9a52-1f0e6c9d2a77",
  "status": "rejected",
  "metadata": {
    "policy_version": "pix-v1.1",
    "reason": {
      "code": "NEW_ACCOUNT_LIMIT_EXCEEDED",
      "description": "Teto de conta nova excedido.",
      "observed_amount": 120000,
      "limit_amount": 100000
    }
  }
}
```

Valores do motivo em centavos; o observado é o acumulado projetado, incluindo o Pix atual. Quando decide uma regra do módulo, o motivo traz o estado da conta, as evidências e o ato, sem documentos completos nem a identidade das contas marcadas.

| Situação | Resposta |
| --- | --- |
| Pix novo analisado | 201 com `key`, `status` e `metadata` |
| mesmo `id` com conteúdo equivalente | 200 com a análise original, sem reavaliar e sem contar de novo |
| mesmo `id` com conteúdo diferente | 409, sem alterar histórico nem contadores |
| payload inválido ou incoerente (conta aberta depois do evento) | 400, sem consumir limites |
| sem `INTERNAL-TOKEN` | 403 |
| `GET` de `id` inexistente | 404 |
| falha técnica antes de gravar | erro 5xx; nunca uma decisão |

Os códigos HTTP e o envelope de erro seguem o Base Service; os códigos de erro próprios ficam em `src/errors/`.

**Idempotência.** O `id` vem do cliente e pode repetir. A comparação é entre estruturas normalizadas, não entre textos JSON: ordem das chaves não diferencia pedidos, datas são normalizadas para UTC, documentos de forma consistente, identificadores textuais e zeros iniciais preservados, valor sem arredondamento. A equivalência cobre todo o payload. `UNIQUE(transaction_id)` é a garantia final, inclusive para IDs reutilizados entre contas diferentes.

**GET.** Consulta pelo `transaction_id` e devolve o mesmo envelope gravado. Não executa as regras de novo, não atualiza a idade do aparelho e não depende da versão atual da política.

**Schema de entrada** (`src/schemas/post_pix_transaction.json`): `amount` inteiro maior que zero, em centavos; datas com `pattern` ISO 8601 com fuso (o `format` não valida nada no Base Service); `geolocation` opcional; `additionalProperties: false`.

## Modelo de dados

A base é a proposta de `dados-e-fluxo-v1.md`: duas tabelas, a solicitação e sua análise na mesma linha, colunas só para o que as regras consultam e o resto preservado em JSON. O módulo de laranja acrescenta colunas do destino e duas tabelas próprias. Sem cadastro de clientes, saldo ou ledger.

```mermaid
erDiagram
    PAYER_ACCOUNT ||--o{ PIX_ANALYSIS : possui
    PIX_ANALYSIS }o--o{ ACCOUNT_LINK : gera
    DICT_LOOKUP {
        text document PK
        jsonb response
        timestamptz fetched_at
        timestamptz as_of
    }
    PAYER_ACCOUNT {
        bigint id PK
        text branch
        text account_number
        timestamptz created_at
    }
    PIX_ANALYSIS {
        bigint id PK
        text transaction_id UK
        uuid key UK
        bigint payer_account_id FK
        bigint amount
        timestamptz transaction_date
        text device_id
        text destination_key
        text destination_document
        text status
        jsonb metadata
    }
    ACCOUNT_LINK {
        text from_key
        text to_key
        text link_type
        bigint total_amount
    }
```

### Base (dados-e-fluxo)

| Tabela | Campo | Finalidade |
| --- | --- | --- |
| `payer_account` | `id`, `branch`, `account_number`, `created_at` | Identidade da conta pagadora e âncora da trava. `UNIQUE(branch, account_number)`, criada automaticamente na análise; não é onboarding |
| `pix_analysis` | `transaction_id` (UNIQUE), `key` (UUID, UNIQUE) | `id` do POST, sem exigir UUID; identificador público da análise |
|  | `payer_account_id`, `amount` (CHECK > 0), `transaction_date`, `source_opening_date`, `device_id` | O que R1 a R4 consultam |
|  | `received_at`, `analyzed_at` | Auditoria; as regras usam `transaction_date` |
|  | `status` (CHECK nos três valores), `reason_code`, `policy_version`, `metadata` | A decisão e a explicação devolvidas no POST e no GET |
|  | `request_payload` (JSONB) | Corpo completo, sem cabeçalhos nem token |

Índices: `(payer_account_id, transaction_date)` para as janelas; parcial `(payer_account_id, device_id, transaction_date) WHERE status = 'approved'` para a primeira aprovação do aparelho.

### Extensões do módulo de laranja

| Onde | Campo ou tabela | Finalidade |
| --- | --- | --- |
| `pix_analysis` | `payer_document`, `destination_key`, `destination_document`, `destination_opening_date` | Identificar o destino e o titular para E2, E3, E5, relação anterior e destinatário conhecido. `destination_key` = "participante:agência:conta" |
| `pix_analysis` | `analysis_details` (JSONB, interno) | Estados, evidências, ato e `dict_status` no momento da decisão; auditoria, não volta na resposta |
| `account_link` | `from_key`, `to_key`, `link_type` (`pix` com direção, `device`, `document`), `first_seen`, `last_seen`, `total_amount` | As arestas do grafo, gravadas no mesmo commit do Pix |
| `dict_lookup` | `document` (único), `response`, `fetched_at`, `as_of` | Cache por titular, com validade única configurável |

Índices do módulo: `(destination_key, transaction_date)` para entradas e titulares distintos; `(payer_account_id, destination_document, transaction_date)` para relação anterior; `(to_key, link_type, last_seen)` e `(from_key, link_type, last_seen)` nas arestas.

**Cálculos temporais.** Entradas, saídas, primeiras aprovações e vínculos de aparelho são consultados no histórico de `pix_analysis` com suas janelas. `account_link.total_amount` é um agregado histórico; filtrar por `last_seen` não o transforma em soma de 30 dias. Arestas Pix e de aparelho derivam apenas de aprovações. `analysis_details` preserva os snapshots, datas e incertezas usados, sem expor tudo no GET.

**Premissa de identidade, a confirmar.** Uma instituição de origem por instância do protótipo: o payload só informa ISPB do destino. A chave de uma conta pagadora no grafo usa o ISPB do banco do motor como constante, para que a mesma conta seja reconhecida quando aparece como destino (entradas) e como pagadora (saídas). CPF/CNPJ nunca substitui a identidade da conta.

## Fluxo do POST e trava por conta

O retorno de negócio só sai depois que a análise está gravada. Rejeição antifraude é resultado persistido; erro de entrada, conflito e falha técnica são caminhos diferentes.

```mermaid
flowchart TD
    A[Validar e normalizar o pedido] --> B{ID já analisado?}
    B -->|mesmos dados| C[Devolver análise original]
    B -->|dados diferentes| D[Erro de conflito]
    B -->|não| X[Consultar DICT: cache ou chamada com timeout]
    X --> E[Obter e travar a conta pagadora]
    E --> F[Rever ID e montar contexto: regras base e módulo]
    F --> G[Aplicar ordem: R1, R2, L1, L2, L3, R4, R3]
    G --> H[Gravar análise e arestas juntas]
    H --> I[Commit e resposta: key, status, metadata]
```

**Responsabilidades em cada passo:**

- **Entrada:** validar campos e coerência antes de contar qualquer tentativa. Conta aberta depois do evento é erro de entrada.
- **Reenvio:** comparar o pedido normalizado; mesmo ID com dados diferentes nunca sobrescreve a análise original.
- **DICT antes da trava:** a chamada externa acontece fora da transação do banco, para a trava da conta nunca ficar presa esperando a rede. Indisponível vira "desconhecido", não decisão.
- **Contexto:** depois da trava, uma única camada de repositório lê tudo de que as regras base e o módulo precisam (acumulado de 24h, tentativas em 2 minutos, primeira aprovação do aparelho, entradas e saídas da última hora, titulares distintos, relação anterior, vínculos de aparelho). O motor recebe valores prontos e não executa SQL.
- **Decisão:** função pura, sem novas consultas por regra.
- **Gravação:** análise, corpo original e arestas do grafo na mesma unidade atômica. Se falhar, desfaz tudo e não responde sucesso.

**Trava por conta, sem trava global.** Transação em READ COMMITTED; a linha de `payer_account` é criada de forma segura diante de concorrência e travada com `SELECT ... FOR UPDATE` antes de ler o histórico que decide, até o commit.

```text
Conta antiga; aparelho conhecido; acumulado inicial zero
A solicita R$ 6.000 -> obtém a trava -> aprova -> commit
B solicita R$ 6.000 -> aguarda a mesma conta
B lê o histórico após A -> total R$ 12.000 -> rejeita por R2
```

Sem a trava, os dois leriam zero e aprovariam. A mesma proteção faz a terceira tentativa enxergar as duas anteriores (R3) e cada repasse enxergar os anteriores (L3). Contas diferentes seguem independentes. A verificação do ID é repetida depois da trava para capturar um reenvio concluído enquanto esta requisição esperava; `UNIQUE` continua sendo a garantia final.

**Limite conhecido:** vários pagadores diferentes enviando ao mesmo destino ao mesmo tempo não se enxergam, porque a trava é por pagador. Entradas concorrentes podem ficar fora do contexto, em quantidade não limitada a uma ou duas; aceito no protótipo, sem alegar visão global atômica do grafo.

**E2 e snapshots das contrapartes:** preparar consultas das contas candidatas fora da trava. Após travar, reler o histórico; novas contrapartes sem snapshot válido continuam desconhecidas nessa análise, sem HTTP dentro da transação. Guardar essa limitação na auditoria.

**Camadas no Base Service:** resource (`src/resources/pix_transaction.py`), controller (orquestração, trava e commit), repositórios (todas as consultas), `src/rules/` (regras base, `laranja.py` e a política de ordem, sem banco), `src/connectors/dict_connector.py`, DTO da resposta e erros em `src/errors/`. Nenhum contador nem estado de confiança em memória: o banco é a única fonte.

## DICT simulado

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

- **Mock:** Mockserver no `docker compose`, com respostas em `mocks/dict_expectations.json`, versionado; se der trabalho, um container mínimo com FastAPI lendo o mesmo JSON.
- **Connector** (`src/connectors/dict_connector.py`): URL em variável de ambiente, sessão HTTP reaproveitada, timeout de 200 ms no mock (em produção, por volta de 800 ms). Timeout, erro ou 429 deixam E1 e E4 desconhecidas e o `dict_status` como `indisponivel`.
- **Cache** em `dict_lookup`, por titular: validade única configurável, compartilhada entre os papéis de pagador e destinatário. Documentar o valor escolhido e testar expiração. Sem cache válido, consultar a fonte; se ela falhar, manter desconhecido.
- **Contribuição:** não publicar automaticamente suspeitas no mock; a classificação local não deve alimentar a própria fonte e criar confirmação circular.

**Números do DICT real:**

| Métrica | Valor oficial |
| --- | --- |
| Consulta de chave no DICT | 99% em até 1 segundo |
| Disponibilidade do DICT para consulta | 99,9% |
| Limite por pagador na consulta de chave | PF: balde de 100, reposição de 2 por minuto; PJ: balde de 1.000, reposição de 20 por minuto |
| Estatísticas antifraude de pessoa | 12.000 por minuto por instituição, balde de 36.000 |
| Tempo máximo de um Pix | 40 segundos |

Fontes: [Manual de Tempos do Pix](https://www.bcb.gov.br/content/estabilidadefinanceira/pix/Regulamento_Pix/IX_ManualdeTemposdoPix.pdf) e [especificação da API do DICT](https://www.bcb.gov.br/content/estabilidadefinanceira/pix/API-DICT.html).

**Em produção, sem chamada extra:** para fazer um Pix por chave, o banco já consulta o DICT; com `IncludeStatistics=true`, os contadores antifraude chegam na mesma resposta. A QI, participante direto, já faz essa consulta.

## Grafo de contas e proteção de boa-fé

O grafo alimenta E2, E3 e E5 e define o ato de repasse. Não há banco de grafos: as arestas ficam no Postgres, em `account_link`, e cada evidência é uma consulta indexada.

| Aresta | Direção | Para quê |
| --- | --- | --- |
| `pix` | do pagador para o destino | seguir o dinheiro e separar vítima de cúmplice |
| `device` | sem direção | a mesma quadrilha operando várias contas |
| `document` | sem direção | o mesmo titular em contas diferentes |

IP não vira aresta: wi-fi público e operadoras com IP compartilhado ligariam pessoas sem relação.

**A direção separa vítima de cúmplice.** Quem mandou dinheiro para uma conta marcada está antes dela e quase sempre é vítima: não ganha evidência. Quem recebeu dela pode ser o próximo elo: ganha E2, se passar pelas travas.

&#91;embedded content: como E1 vira E2 na rede laranja · 5 contas\]

L2 ganha E2 por estar depois de L1 no dinheiro. L3 divide o aparelho com L2, mas não ganha E2, porque L2 não está marcada no DICT: a suspeita não anda em cadeia. A vítima A, que está antes, continua pagando o mercado sem fricção.

**Travas que protegem quem recebeu de boa-fé.** Receber Pix é passivo, e um golpista pode mandar R$ 1 de uma conta marcada para quem quiser prejudicar.

1. **Reputação:** E2 só vale para contas com menos de 90 dias ou menos de 10 contrapartes.
2. **Proporção:** só conta se mais de 50% do que a conta recebeu em 30 dias veio da marcada.
3. **Expiração:** passada a janela de 30 dias, a evidência some.
4. **Um salto, só a partir de E1:** a suspeita não se espalha a partir de outras suspeitas.
5. **E2 isolada gera `suspeita`,** e `suspeita` só pesa no repasse (L3). Uma conta com E2 apenas pode continuar fazendo operações que não satisfaçam a definição de repasse aparente; isso não garante a legitimidade dessas operações.

|  | Padaria do Seu João | Conta L2 |
| --- | --- | --- |
| Recebeu da conta marcada | R$ 50, de um cliente golpista | R$ 2.000 |
| Idade e contrapartes | 10 anos, 400 contrapartes | 12 dias, 2 contrapartes |
| Peso do dinheiro marcado | 0,06% | 91% |
| Estado | `nao` | `suspeita` (E2), ou `suspeita_elevada` com E4 |

**Quem resolve o dinheiro da fraude é o MED, não o motor.** O Mecanismo Especial de Devolução atua sobre o valor (bloqueio cautelar e devolução à vítima), com direito de defesa para quem recebeu de boa-fé. O motor só impede o próximo repasse. "Recebido" no grafo significa aprovado pelo motor, não liquidado.

## Testes e demo

Além dos testes HTTP de integração, testar as funções puras de classificação e ato: uma classificação incorreta pode produzir o mesmo status final. Verificar E1, E2+E4, E3+E5, precedência de repasse aparente, evidências desconhecidas e datas. As matrizes são especificação, não execução de testes.

Testes de integração black box, só por HTTP; os testes adicionais das funções puras verificam os resultados intermediários. Cada teste monta o próprio histórico pelo `POST`, com contas e documentos novos, e confere `status` e `metadata.reason.code`. As matrizes são especificação: não comprovam que os testes passaram até serem executadas.

| Arquivo | Cobre | Origem |
| --- | --- | --- |
| `test_policy.py` | C01 a C21, um teste por cenário, com valores exatamente nos tetos e datas nas bordas de 2 min, 24h e 7 dias | política acordada |
| `test_contract.py` | 201, 400 por campo errado e campo a mais, 403 sem token, 404 no GET, conta aberta depois do evento é 400 | contrato |
| `test_idempotency.py` | reenvio idêntico devolve a análise original e não conta de novo; conflito de ID; ordem de chaves diferente é o mesmo pedido; GET após mudança de política | dados e fluxo |
| `test_concurrency.py` | dois Pix simultâneos da mesma conta não atravessam R2 juntos; terceira tentativa enxerga as anteriores; mesmo ID em paralelo grava uma vez | dados e fluxo |
| `test_persistence.py` | falha de gravação não responde sucesso; rejeições e 2FA ficam gravados | dados e fluxo |
| `test_laranja.py` | P01 a P20 | módulo |
| `test_laranja_dict.py` | E1 por marcação e por 2 instituições; E4 com 1 e 2 notificações; DICT com timeout e com 429; pagador lido do cache | módulo |
| `test_laranja_grafo.py` | direção; travas de reputação, proporção e expiração; L3 sem E2 por aparelho de conta não marcada; R$ 1 enviado de propósito não trava a conta | módulo |
| `test_laranja_ato.py` | gasto típico no limite de R$ 1.000; CNPJ com 89 e 90 dias; repasse em 49% e 50%; rateio pago a CNPJ antigo | módulo |

**Demo da apresentação:**

Usar uma conta pagadora antiga no caso principal para R1 não ocultar a contribuição de L2/L3. Se a marcação surge depois dos recebimentos, o mock deve mudar ao longo do cenário, com cache coerente. Preparar o histórico pelas mesmas regras da API, sem aprovações artificiais. Mostrar também P14: E3+E5 não eleva a classificação.

1. Regras base: conta nova barrada acima de R$ 1.000 (C03); aparelho novo com R$ 6.000 pede 2FA (C10); rajada de 3 em 2 minutos pede 2FA (C07).
2. L1 está marcada no DICT. Uma vítima nova tenta pagar: `rejected`. A mãe que sempre mandava mesada: `approved`.
3. L1 paga a conta de luz: `approved`. L1 tenta repassar o que recebeu: `rejected`. A mesma conta, dois atos diferentes.
4. A padaria que recebeu R$ 50 de L1 paga o fornecedor: `approved`.
5. O DICT cai: o motor continua respondendo, só com evidências locais, e registra a indisponibilidade.
6. Na tela, o grafo do cenário, gerado por um script com `networkx` fora da API.

A frase da apresentação: **"quatro regras simples para o comum; para a laranja, onde o 2FA não funciona, o motor classifica a conta e depois decide o ato"**.

## Convenções e pendências

**Convenções propostas em `dados-e-fluxo-v1.md`, a revisar antes de virar comportamento definitivo:**

| Tema | Proposta | Consequência |
| --- | --- | --- |
| Janelas | histórico já confirmado com datas em `(t − janela, t]`; o pedido atual entra uma única vez no total e na contagem | sem dupla contagem; datas iguais a `t` entram se o pedido anterior já foi concluído |
| Pedido fora de ordem | rejeitar como erro de entrada um pedido retroativo da mesma conta, sem reanalisar decisões anteriores | restrição adicional ao acordo; precisa ser validada pelo time |
| Data futura | validar contra um relógio de referência; testes usam relógio controlado | tolerância ainda em aberto |
| Abertura inconsistente | transação anterior à abertura é erro; mudança de abertura ou titular entre pedidos da mesma conta precisa de tratamento explícito | evita idade de conta manipulada |
| Falhas técnicas | indisponibilidade nunca vira `approved`, `rejected` ou `two_factor_required` | DICT indisponível é a única exceção controlada: deixa E1 e E4 desconhecidas, sem decidir |
| Origem | uma instituição por instância | confirmar antes de implementar |

**Pendências herdadas da política acordada:**

- [ ] Bordas exatas das janelas de 2 minutos e de 24 horas (a convenção acima é a proposta).
- [ ] Eventos atrasados, datas futuras e datas anteriores à abertura.
- [ ] Identidade técnica da conta pagadora, sem trocar o limite por conta por limite por CPF/CNPJ.
- [ ] Normalização e equivalência de reenvios, conflito de ID e entrada inválida.
- [ ] Deixar explícito que `two_factor_required` não cria aprovação nem familiaridade, e que não há rota de confirmação de 2FA.

**Pendências de integração entre regras base e módulo:**

- [ ] Uma única camada monta o contexto e consulta o banco para os dois.
- [ ] Formato único de motivo e nomes de código (tabela da seção Ordem de decisão).
- [ ] A trava por conta pagadora vale para os dois: R1, R2, R3 e o cálculo de repasse dependem dela.
- [ ] Implementar os limiares mantidos do módulo: gasto típico (R$ 1.000, CNPJ de 90 dias), repasse aparente (50% em 1h, mínimo de R$ 1.000). L2 mantém a rejeição de “outro”; documentar seu custo de fricção.
- [ ] Conferir o Base Service: códigos HTTP, envelope de erro e convenções.

## Plano de implementação

Duas frentes em paralelo, que se encontram no contexto e na política de ordem. A ordem garante que, se o tempo acabar, o que existe roda, está testado e documentado.

**Frente base (regras R1 a R4 e dados e fluxo), em quatro entregas:**

- [ ] 1\. Conferir o Base Service e fechar as convenções pendentes.
- [ ] 2\. Schema (`payer_account`, `pix_analysis`), POST e GET, persistência atômica e idempotência.
- [ ] 3\. Contexto histórico e motor puro; ligar C01 a C21 às regras.
- [ ] 4\. Testes de integração e concorrência; README com decisões e limitações.

**Frente laranja (módulo), por ordem de valor:**

- [ ] Colunas do destino em `pix_analysis`, `account_link` gravada no commit do Pix, `dict_lookup`.
- [ ] Mock do DICT no compose e connector com timeout, 429 e cache.
- [ ] `classify_account` (E1 a E5), `classify_act` e regras L1 a L3, com P01 a P20 como testes.
- [ ] Testes de DICT, grafo e ato, incluindo os inocentes.
- [ ] Seed da demo e script do grafo com `networkx`.

**Integração:**

- [ ] Uma camada de contexto única e a política de ordem R1, R2, L1, L2, L3, R4, R3.
- [ ] Rodar C01 a C21 com o módulo ligado e suas premissas preservadas: sem indícios adicionais, manter resultados e motivos. Cenários que deliberadamente acrescentam evidências L1–L3 podem mudar de decisão.

**Fechamento, até domingo às 12h:**

- [ ] Clonar do zero, `docker compose up` e `pytest` verdes, sem passo manual.
- [ ] README no modelo do desafio: tabela Regra, Lógica, Parâmetros e Por quê, cobrindo R1 a R4 e L1 a L3.
- [ ] Ensaio cronometrado de 7 minutos, com plano B em vídeo ou print da demo.
- [ ] Link do repositório público no grupo da final no Slack antes das 11h45.

## Riscos, limites e alternativas descartadas

**Riscos residuais, apresentados com honestidade:**

- Um Pix fraudulento abaixo dos tetos, no aparelho conhecido, sem conta laranja envolvida, pode ser aprovado.
- Um pagamento sob ameaça pode ocorrer com autenticação válida; o 2FA não prova que o pagamento é voluntário.
- Uma rajada mais lenta que 2 minutos não dispara R3; uma aprovação pequena cria familiaridade do aparelho depois de 24 horas.
- Saídas de até R$ 1.000 podem passar como gastos típicos quando não satisfizerem antes o repasse aparente, por exemplo por falta de entradas observadas ou destino CNPJ antigo. R2 e R3 continuam valendo.
- Laranja só em outros bancos, sem marcação no DICT, não é vista: o motor só enxerga os Pix que passam por ele.
- O histórico prova análises, não liquidação; aprovação não é segurança e rejeição por teto não é fraude confirmada.
- Todos os parâmetros são do protótipo e precisariam de dados reais, perdas e fricção medidas para calibrar.

**Alternativas descartadas ou adiadas:**

| Alternativa | Situação e por quê |
| --- | --- |
| Score ponderado ou probabilidade de fraude | Descartado: pesos sem calibração e explicação pior que combinações nomeadas |
| Limite de 5 vezes a média por transação | Retirado pela política: mistura referência por pagamento com exposição diária |
| Ajuste por saldo, renda ou limite bancário real | Fora desta versão: o contrato não traz esses dados; renda via mock de cadastro fica como próximo passo, só como compatibilidade |
| Somar limites entre contas do mesmo CPF/CNPJ | Não adotado: limite é por conta pagadora |
| Intervir por idade da conta destino ou por destinatário novo isolado | Não adotado: descreve pagamentos legítimos; no módulo, só entra combinado como evidência |
| Horário noturno e deslocamento geográfico | Adiados: interpretação e falsos positivos sem benefício demonstrado no recorte |
| Bloquear tudo que toca uma laranja | Descartado: trava vítimas e familiares e não recupera dinheiro; substituído por estado mais ato |
| Banco de grafos dedicado (Neo4j) | Descartado: infraestrutura nova sem ganho nesse volume; as arestas cabem no Postgres |
| Modelo de ML ou IA no caminho da decisão (Jev, Isolation Forest) | Descartado: sem dados rotulados, a decisão deixaria de bater com as regras descritas e criaria dependência externa |
| Segurar o Pix suspeito para análise | Próximo passo: o Manual de Tempos do Pix permite até 30 minutos em horário comercial, mas o desafio pede três saídas imediatas |

**Fora do escopo do desafio:** onboarding e cadastro de contas, front-end, conclusão do 2FA, liquidação, o DICT real (usamos um mock) e recalibração automática dos parâmetros. Entram na apresentação como próximos passos, em uma frase cada, junto com situação cadastral de CPF e CNPJ via mock da Receita e a separação do dinheiro suspeito em vez da conta inteira.
