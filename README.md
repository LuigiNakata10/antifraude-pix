# [Nome do grupo] — Motor antifraude Pix

**Integrantes:** [nomes]

Hackathon QI Tech 2026. Uma API que recebe um pedido de Pix e responde `approved`, `two_factor_required` ou `rejected`, sempre com **um motivo explicado**. Construída a partir do Base Service, com banco próprio que guarda tudo o que chegou.

**Estado desta versão:** política revisada e integrada a partir de `feat/motor-antifraude` (resultados na [nota de integração](docs/integracao-motor-v1.1.md)): as regras base R1 a R4, a idempotência, a trava por conta e o **módulo de conta laranja** (DICT simulado, grafo de contas e as regras L1 a L3). Há uma [demo pronta](#demo-da-apresentação).

## Como o motor de decisão funciona

O problema impõe três restrições, e cada escolha abaixo sai delas:

- **Tempo.** A decisão sai antes do dinheiro. Nada de consulta externa pesada nem de analista no caminho: as regras são determinísticas e leem só o banco.
- **Histórico.** Um Pix sozinho diz pouco. As regras comparam com o que a **conta pagadora** já fez (acumulado, frequência, aparelho).
- **Fricção.** Bloquear cliente bom também é prejuízo. O 2FA só aparece onde há dúvida real; quem paga o aluguel todo mês passa direto.

Princípios: poucas regras, sem pontuação nem probabilidade de fraude; **um único motivo** na resposta; informação ausente não é evidência (a primeira transação de uma conta não sofre intervenção só por falta de histórico); aprovar não é garantia de segurança e rejeitar por teto não é fraude confirmada; **falha técnica nunca vira decisão** (vira erro 5xx).

**O caminho de um POST**, na ordem em que o controller executa (`src/controllers/pix_transaction_controller.py`):

1. valida o corpo (schema) e a coerência dos dados (data que não existe, conta aberta depois do Pix → 422), sem tocar no banco: entrada inválida não consome limite nem conta em frequência;
2. procura o `id`: um Pix já analisado não é analisado de novo;
3. **consulta o DICT**, fora da transação: o pagador vem do cache de 24 h, o destino é consultado ao vivo, as duas consultas em paralelo e com um único prazo de 200 ms. DICT lento ou fora do ar vira "desconhecido", nunca decisão;
4. **trava a conta pagadora** (`SELECT ... FOR NO KEY UPDATE`) e procura o `id` de novo, porque um reenvio pode ter concluído enquanto este pedido esperava;
5. recusa o pedido retroativo e lê o histórico da conta e do grafo, **só depois da trava**;
6. a política pura decide (`src/rules/policy.py`: sem banco, sem relógio, sem I/O);
7. grava a análise **e, se aprovada, as arestas do grafo** e dá `commit`. Qualquer falha antes disso desfaz tudo.

A trava por conta é o que impede dois Pix simultâneos de atravessar juntos o teto. Sem ela, os dois leriam acumulado zero e aprovariam R$ 12.000. Contas diferentes não esperam umas pelas outras. Nenhum contador fica em memória: o banco é a única fonte de estado, então qualquer réplica da API atende qualquer pedido.

## Regras

Todas as regras são **por conta pagadora**, não pela soma das contas do mesmo CPF/CNPJ. Valores em centavos inteiros; a referência de tempo é sempre a `transaction_date` do pedido. Os parâmetros são **deste protótipo**: não são limiares validados nem usados universalmente pelos bancos, e estão em [`src/rules/parameters.py`](src/rules/parameters.py).

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| **R1** conta nova | conta com menos de 7 dias completos entre a abertura e o Pix **e** acumulado de 24 h (aprovados + Pix atual) acima do teto → `rejected` | 7 dias; teto de R$ 1.000 (exatamente R$ 1.000 passa) | Limita a exposição inicial de uma conta sem histórico. Por ser acumulado, impede contornar o teto fracionando em vários Pix. Sete dias dão tempo de a conta mostrar um padrão |
| **R2** teto geral | acumulado de 24 h (aprovados + Pix atual) acima do teto → `rejected` | janela móvel de 24 h; teto de R$ 10.000 (exatamente R$ 10.000 passa) | Exposição máxima simples e resistente à fragmentação. Janela móvel, e não dia civil, para não zerar à meia-noite |
| **R3** frequência | pelo menos a **terceira** solicitação distinta da conta em 2 minutos, qualquer valor e destinatário → `two_factor_required` | janela de 2 minutos; limiar 3 | Uma rajada concentrada pede confirmação de identidade sem rejeitar só por quantidade. Conta **qualquer resultado** (insistir depois de recusa é sinal) e **não conta reenvios** do mesmo `id` |
| **R4** aparelho novo e valor alto | aparelho **não conhecido** e Pix individual de R$ 5.000 ou mais → `two_factor_required` | R$ 5.000; espera de 24 h | Falta de familiaridade do acesso somada a exposição relevante. Pagamentos menores seguem sem fricção depois de trocar de aparelho |

**Definições que as regras usam:**

- **Acumulado de 24 h:** soma dos Pix **`approved`** da conta na janela mais o Pix atual. `rejected` e `two_factor_required` **não consomem** o limite.
- **Aparelho conhecido:** a conta tem uma aprovação anterior com esse `device_id` e já passaram **24 h desde a primeira** dessas aprovações. Aprovações posteriores não reiniciam a espera (evita prolongá-la para quem usa a conta todo dia), e tentativa rejeitada ou com 2FA não a inicia. Isso mede familiaridade observada, não legitimidade.
- **Janelas `(t − janela, t]`**, com `t` a `transaction_date` do pedido: um Pix exatamente em `t − 24 h` ou `t − 2 min` **não** conta, e um já gravado com data igual a `t` conta. O pedido atual entra uma única vez.

## Como as regras viram decisão

A política devolve o **primeiro** resultado aplicável nesta ordem, e só o motivo determinante aparece na resposta:

| # | Regra | Resultado | `reason.code` |
|---|---|---|---|
| 1 | R1 | `rejected` | `NEW_ACCOUNT_LIMIT_EXCEEDED` |
| 2 | R2 | `rejected` | `DAILY_LIMIT_EXCEEDED` |
| 3 | L1 | `rejected` | `MULE_DESTINATION` |
| 4 | L2 | `rejected` | `MULE_PAYER` |
| 5 | L3 | `rejected` | `SUSPECTED_MULE_FORWARDING` |
| 6 | R4 | `two_factor_required` | `NEW_DEVICE_HIGH_AMOUNT` |
| 7 | R3 | `two_factor_required` | `HIGH_FREQUENCY` |
| 8 | nenhuma | `approved` | `POLICY_PASSED` |

- **Rejeição vem antes de 2FA.** R1 vem antes de R2 por ser a restrição específica da conta nova, e as regras do módulo de laranja entram depois dos tetos e antes de qualquer pedido de 2FA. **O módulo nunca pede 2FA:** contra conta laranja, quem confirma o segundo fator é o próprio operador da conta. Entre R4 e R3 a ordem é uma convenção de explicação, não uma alegação de que uma detecta mais fraude que a outra.
- **Quando pede 2FA:** quando há dúvida sobre quem faz o pedido (aparelho sem 24 h de aprovação com valor alto) ou insistência em intervalo curto, e nenhum teto foi violado. Nesses casos o cliente confirma que é ele, em vez de ser bloqueado.
- **Um único motivo.** Se R1 e R2 são excedidas ao mesmo tempo, sai só R1; se R4 e R3 se aplicam, sai só R4. Quando uma regra do módulo de laranja decide, o motivo traz o estado da conta, as evidências e o ato (`account`, `account_state`, `evidences`, `act`), nunca documento nem a identidade de contas marcadas. A resposta traz os valores observados e o limiar da regra que decidiu, em centavos (R3, que explica uma contagem, traz `observed_count` e `limit_count`).
- **`two_factor_required` não cria aprovação nem familiaridade.** O contrato não traz a confirmação do 2FA e não há rota para ela: o mesmo aparelho pode continuar pedindo 2FA em Pix altos até uma aprovação comum completar as 24 h.

Exemplo de `metadata` (R4, real, gerado pela API):

```json
{
  "policy_version": "pix-v1.1",
  "reason": {
    "code": "NEW_DEVICE_HIGH_AMOUNT",
    "description": "Confirmação adicional: valor elevado em um aparelho ainda não conhecido para esta conta.",
    "observed_amount": 600000,
    "limit_amount": 500000
  }
}
```

## Módulo de conta laranja

**A tese.** Contra conta tomada, o 2FA pode ajudar se o invasor não tiver o segundo fator. Contra **conta laranja**, não: quem confirma é o próprio operador da conta, seja o recrutado, seja quem comprou o acesso. A única saída é reconhecer a conta e recusar o ato certo. Por isso o motor **primeiro classifica a conta** (estado `nao`, `suspeita` ou `suspeita_elevada`) **e depois decide o ato**: a laranja paga a conta de luz, mas não repassa o dinheiro do golpe.

**Premissa: nem toda transação que envolve uma laranja é fraudulenta.** O recrutado paga as próprias contas, a vítima que paga a laranja não é cúmplice, e a mãe que manda mesada ao filho recrutado também não. Bloquear tudo que toca a conta trava inocentes e não recupera dinheiro.

Duas fontes se completam: o **DICT** dá marcações e relatos de outras instituições (o motor deixa de depender só do que viu), e o **grafo local** segue o dinheiro e o aparelho a partir delas e enxerga padrões antes de haver marcação.

### Estado da conta: cinco evidências

Calculado na hora, para o pagador e para o destino. Não há marcação local permanente: quando a janela de uma evidência passa, ela some e o estado cai sozinho. Só o DICT mantém uma conta `suspeita_elevada` por muito tempo.

| Evidência | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| **E1** marcação no DICT | conta laranja ou golpista marcada, ou titular marcado por 2 ou mais instituições | janela `d90` do DICT; 2 instituições | Marcação ou concordância entre relatos merece atenção, sem comprovar fraude. Duas instituições podem refletir o mesmo fato |
| **E2** dinheiro ou aparelho de conta E1 | mais de 50% do que a conta recebeu em 30 dias veio de contas com E1, ou ela usou o aparelho de uma. **Só E1 propaga**, um salto | 30 dias; mais de 50%; só se a conta tem menos de 90 dias **ou** menos de 10 contrapartes | Segue o dinheiro a partir das sementes. As travas protegem quem recebeu de boa-fé (veja abaixo) |
| **E3** muitos titulares enviando | titulares distintos que enviaram na última hora, pelo menos três estreantes | 5 ou mais, sendo 3 de primeira vez; para CNPJ, 30 e 3 | É o formato de uma conta de passagem. Empresa recebe de muita gente por natureza |
| **E4** notificações de infração | notificações abertas contra a conta, no DICT | 2 ou mais | Uma pode ser disputa; duas já são um padrão |
| **E5** conta nova com volume | conta com menos de 7 dias recebendo muito de vários titulares | mais de R$ 5.000 em 24 h, de 3 ou mais titulares | Conta recém-aberta com volume alto de desconhecidos é o perfil de conta aberta para o golpe |

| Estado | Quando |
|---|---|
| `suspeita_elevada` | E1 ou a combinação explícita E2+E4 |
| `suspeita` | outras combinações com evidência positiva, inclusive E3+E5 |
| `nao` | nenhuma evidência |

"Recebido" e "enviado" contam só Pix **`approved`**: aprovado pelo motor, não liquidado. **DICT indisponível:** E1 e E4 ficam desconhecidas e o estado sai só das evidências locais; desconhecido nunca conta como evidência.

**Travas que protegem quem recebeu de boa-fé.** Receber Pix é passivo, e um golpista pode mandar R$ 1 de uma conta marcada para quem quiser prejudicar:

1. **Reputação:** E2 só vale para conta com menos de 90 dias ou menos de 10 contrapartes. Uma padaria antiga, com muitos clientes, não ganha E2.
2. **Proporção:** só conta se mais de 50% do que a conta recebeu em 30 dias veio da marcada. R$ 1 de propósito não pesa.
3. **Expiração:** passados 30 dias, a evidência some.
4. **Um salto, só a partir de E1:** a suspeita não se espalha em cadeia a partir de outras suspeitas.
5. **Uma evidência é só `suspeita`,** e `suspeita` só pesa no repasse (L3): uma conta contaminada de propósito continua pagando contas e fazendo Pix comuns.

**A direção separa vítima de cúmplice.** Quem mandou dinheiro para uma conta marcada está *antes* dela e quase sempre é vítima: não ganha E2. Quem recebeu dela está *depois* e pode ser o próximo elo.

### O ato do pagador

| Ato | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| **Gasto típico** (somente se não houver repasse) | até o teto, para um titular que o pagador já conhecia (aprovação anterior) ou para CNPJ com conta de 90 dias ou mais | R$ 1.000; 90 dias | O padrão de quem usa a conta para a própria vida. O teto e a exigência de CNPJ antigo impedem o repasse de se disfarçar de "gasto" numa empresa de fachada |
| **Repasse aparente** (testado primeiro) | a conta recebeu pelo menos o mínimo na última hora, este Pix leva o enviado na hora à proporção ou mais, e o destino é pessoa física ou CNPJ com conta de menos de 90 dias | recebido de R$ 1.000 ou mais; 50% ou mais; 1 hora | O dinheiro sai logo depois de entrar, que é o que define uma conta de passagem |
| **Outro** | o resto | — | Fica com as regras base |

**Relação anterior:** exige uma aprovação para o mesmo titular antes do início explícito da evidência que sustenta a suspeita elevada. A extensão fictícia `EvidenceSince` do mock pode informar E1/E4; sem início, não presumimos relação anterior. E2+E4 tem início histórico desconhecido. A primeira consulta e o começo da janela não substituem esse dado.

### As regras L1 a L3

Todas rejeitam e só aparecem depois de R1 e R2 (a conta nova acima do teto é barrada primeiro).

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| **L1** destino laranja | destino `suspeita_elevada` e **primeira relação** do pagador com ele → `rejected` | estado `suspeita_elevada`; relação anterior | Protege a vítima nova sem travar quem já se relacionava com a conta |
| **L2** pagador laranja | pagador `suspeita_elevada` e ato que **não é gasto típico** (repasse ou outro) → `rejected` | estado `suspeita_elevada`; ato diferente de gasto típico | Prende o dinheiro do golpe, mas deixa a pessoa pagar as próprias contas |
| **L3** repasse suspeito | pagador `suspeita` e ato de **repasse** → `rejected` | estado `suspeita`; repasse | A evidência do estado mais o repasse formam a combinação de dois sinais exigida para rejeitar |

| Pagador \ ato | Gasto típico | Repasse | Outro |
|---|---|---|---|
| `nao` | regras base | regras base | regras base |
| `suspeita` | regras base | **L3** | regras base |
| `suspeita_elevada` | regras base | **L2** | **L2** |

Destino em `suspeita` não muda a decisão: uma evidência isolada não intervém. A matriz é pagadora × ato; L1 é destino × relação anterior.

### DICT simulado

O mock é um Mockserver no `docker compose` e **segue, de forma simplificada, a estrutura da seção Antifraude da [API pública do DICT](https://www.bcb.gov.br/content/estabilidadefinanceira/pix/API-DICT.html)** (`OwnerStatistics.FraudMarkers` e `InfractionReports`). Por padrão ele não marca ninguém (`mocks/dict_expectations.json`); os testes e a demo roteirizam as respostas por conta. A QI é participante direto do Pix e se conecta ao DICT: o mock é o desenho de produção.

- **E1** = `MuleAccounts.d90` ou `ScammerAccounts.d90` ≥ 1, ou `DistinctFraudReporters.d90` ≥ 2. **E4** = `OpenReports` ≥ 2.
- **Prazo de 200 ms** (`DICT_API_TIMEOUT`): a decisão sai em poucos segundos e esperar mais por uma consulta de apoio custa mais do que decidir sem ela. Timeout, erro, 429, status diferente de 200 e corpo fora do formato viram "desconhecido".
- **Cache** em `dict_lookup` (append-only): o pagador, cliente do banco e que muda pouco, vale 24 h; o destino é **sempre consultado ao vivo** (uma marcação nova vale no Pix seguinte) e o cache de 1 h só o socorre se o DICT falhar.
- **`INSTITUTION_ISPB`** (fictício, `99999999`): o payload só informa o ISPB do destino, então a conta pagadora é sempre desta instituição, e um destino com este ISPB é uma conta nossa. Entra na chave `ispb:agência:conta` do grafo.

### Grafo de contas

Não há banco de grafos: as arestas ficam no Postgres, em `account_link`, gravadas no mesmo `commit` da análise (nunca há Pix sem aresta nem aresta sem Pix), e cada evidência é uma consulta indexada. Três tipos: `pix` (do pagador para o destino, com valor), `device` (a conta e o aparelho) e `document` (a conta e o titular). **IP não vira aresta:** wi-fi público e operadoras com IP compartilhado ligariam pessoas sem relação. Quem resolve o dinheiro da fraude é o MED, do Banco Central, não o motor: o motor só impede o próximo repasse.

## Contrato da API

Rotas exigem o cabeçalho `INTERNAL-TOKEN` (sem ele: 403). `/` e `/health_check` são públicas.

- `POST /pix/transaction`: analisa e grava. O corpo é o do desafio (`id`, `amount` em centavos, `transaction_date` com fuso, `source_account`, `destination_account`, `source`); `geolocation` é opcional e todo campo a mais é recusado.
- `GET /pix/transaction/{id}`: devolve a análise **gravada**, sem rodar as regras de novo. O `{id}` é o `id` do cliente.
- Resposta: `{"key": "<uuid>", "status": "...", "metadata": {"policy_version": "pix-v1.1", "reason": {...}}}`. O id interno do banco nunca sai. O que o motor viu do DICT e o estado das contas ficam só em `analysis_details`, para auditoria, e não voltam na resposta.

| Situação | Resposta | Código |
|---|---|---|
| Pix novo analisado | `201` | — |
| mesmo `id`, conteúdo equivalente | `200` com a análise original, sem reavaliar | — |
| mesmo `id`, conteúdo diferente | `409` | `QIT003004` |
| corpo fora do formato, campo a mais ou faltando, `amount` não inteiro | `400` | `QIT000001` |
| sem `INTERNAL-TOKEN` | `403` | `QIT000002` |
| data que não existe no calendário | `422` | `QIT003001` |
| conta aberta depois do Pix | `422` | `QIT003002` |
| Pix anterior ao último da conta | `422` | `QIT003006` |
| `GET` de `id` inexistente | `404` | `QIT003003` |
| conta travada por outro pedido além de 5 s | `503` com `Retry-After` | `QIT003005` |
| erro inesperado | `500`, nunca uma decisão | `QIT000500` |

**Idempotência.** O `id` vem do cliente e pode repetir. A comparação é entre estruturas **normalizadas**, não entre textos JSON: ordem das chaves é ignorada, as três datas são comparadas como instantes (UTC) e os documentos só pelos dígitos. Todo o resto é exato (canal, IP, geolocalização, zeros à esquerda, valor). Um reenvio não conta como nova tentativa em R3 nem entra no acumulado. `UNIQUE(transaction_id)` é a garantia final: dois pedidos com o mesmo `id` em paralelo gravam uma análise só.

## Convenções da integração v1.1

As contas e o ato são classificados antes da aplicação de L1–L3. E3+E5 não eleva a suspeita, pois pode representar a mesma arrecadação legítima. E2+E4 também não prova independência entre fontes. O aparelho só liga contas depois de usos aprovados das duas em 30 dias. Reputação conta contas distintas nessa mesma janela; E3/E5 contam titulares.

O corte de 30 titulares para CNPJ dá tolerância maior a recebimentos comerciais, preservando três estreantes como requisito mínimo. O mínimo de R$ 1.000 e a saída de 50% em 1h procuram concentração relevante, mas podem atingir repasses legítimos. Noventa dias e dez contrapartes aproximam maturidade sem cadastro; continuam hipóteses de protótipo, sem eficácia comprovada. E1 não significa confirmação de fraude.

O motivo público mantém `evidences` e acrescenta `evidence_values`, com números e limiares, sem documentos de terceiros. Textos não persistíveis retornam 400; titular ou abertura divergente do histórico retorna 422 `QIT003007`.

Preservamos o cache por conta (24h pagador; destino ao vivo com reserva de 1h) e E2 com E1 observado nas aprovações históricas. Esses desvios da proposta de snapshots atuais por titular estão explicados na [nota de integração](docs/integracao-motor-v1.1.md).

## Modelo de dados

Sem cadastro de clientes, saldo nem ledger (esquema em [`database/database.sql`](database/database.sql)):

- `payer_account`: a conta pagadora (agência e conta), âncora da trava. Nasce na primeira análise.
- `pix_analysis`: **uma linha por Pix**, com o pedido e a análise juntos, gravada uma vez já com a decisão. Tem colunas só para o que as regras consultam (valor, datas, aparelho, documentos, destino, o que o DICT disse de cada conta) e preserva o corpo completo em `request_payload` e o retrato da decisão em `analysis_details` (JSONB). Índices nas janelas da conta e o parcial `WHERE status = 'approved'` da primeira aprovação do aparelho.
- `account_link`: as arestas do grafo, uma linha por evento aprovado; rejeições e 2FA continuam na análise.
- `dict_lookup`: o cache do DICT, uma linha por consulta que respondeu.

**Histórico append-only em todas as tabelas de histórico:** nada que entrou é atualizado ou apagado (o que seria um agregado, como "primeira vez" ou "total recebido", sai de `MIN` e `SUM` por consulta). Rejeições e pedidos de 2FA também ficam gravados, e o `GET` devolve o resultado original mesmo que a política mude depois. Dinheiro é `BIGINT` em centavos.

## Como rodar e testar

Também é possível executar tudo em containers, sem Python no host:

```bash
docker compose up --build -d --wait
docker compose --profile test run --build --rm tests
docker compose --profile test run --rm --no-deps tests python -m flake8 src tests scripts
docker compose --profile test run --rm --no-deps -v ./output/demo:/app/output/demo tests python scripts/seed_demo.py
docker compose --profile test run --rm --no-deps -v ./output/demo:/app/output/demo tests python scripts/graph_demo.py
```

O perfil de testes contém as dependências dos scripts; a imagem da API continua sem elas.


Precisa de **Docker** (com `docker compose`) e **Python 3.11+** só para rodar os testes.

```bash
# 1. sobe a API (porta 3000), o Postgres e o mockserver, com o banco criado
docker compose up -d

# 2. espere a API ficar saudável (leva alguns segundos)
docker compose ps        # a coluna STATUS da api deve mostrar (healthy)

# 3. instala o necessário para os testes, numa pasta isolada, e roda
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                   # ~30 s
```

Os testes rodam **na sua máquina, por HTTP, contra a API de pé** no Docker (black box: nenhum importa o código de `src/`). Cada teste monta o próprio histórico pela API, com contas novas, e roteiriza o DICT pelo mock, então não dependem uns dos outros. Três exceções conscientes, documentadas no código: conferir a auditoria (`analysis_details`, colunas do DICT, `dict_lookup`) por leitura direta ao Postgres, e provar a falha de gravação com um gatilho.

**Experimente na mão:**

```bash
curl -s -X POST localhost:3000/pix/transaction \
  -H "INTERNAL-TOKEN: default_token" -H "Content-Type: application/json" \
  -d '{
    "id": "pix-000123", "amount": 600000, "transaction_date": "2026-10-17T22:15:00-03:00",
    "source_account": {"branch": "0001", "account_number": "88213", "opening_date": "2025-03-02T10:00:00-03:00",
                       "owner": {"document_number": "123.456.789-09"}},
    "destination_account": {"participant": "60701190", "branch": "3675", "account_number": "10442",
                            "opening_date": "2026-10-10T09:00:00-03:00",
                            "owner": {"document_number": "987.654.321-00"}},
    "source": {"device_id": "dvc-9f2c71a8", "channel": "app", "ip": "198.51.100.23",
               "geolocation": {"latitude": -23.56, "longitude": -46.65}}
  }'
# 201 {"key":"...","status":"two_factor_required","metadata":{...NEW_DEVICE_HIGH_AMOUNT...}}

curl -s localhost:3000/pix/transaction/pix-000123 -H "INTERNAL-TOKEN: default_token"
# a mesma análise, sem rodar as regras de novo
```

O token padrão é `default_token` (a variável `INTERNAL_TOKEN` o troca). Em produção ele nunca teria valor padrão.

**Úteis:**

- Log de cada análise: `docker compose logs -f api` (uma linha `ANALISE <id> <status> <código>` por Pix, sem documento nem IP; toda resposta traz `X-Request-ID`).
- Mudou o `database/database.sql`: `docker compose down -v` e `up` de novo (ele só roda quando o banco nasce). Mudou o `requirements.txt`: `docker compose build --no-cache api`.
- **Porta ocupada** ("port is already allocated"): copie `.env.example` para `.env`, descomente e troque `API_PORT` ou `DB_PORT` e, se mudar a do banco, a mesma porta na `DATABASE_URL`.
- Um teste só: `pytest tests/integration/pix_transaction/test_policy.py::TestNewDeviceHighAmount`.

**O que os testes cobrem** (`tests/integration/pix_transaction/`, incluindo a integração v1.1):

| Arquivo | Cobre |
|---|---|
| `test_policy.py` | os 21 cenários da política (C01 a C21) e as bordas exatas: R$ 1.000, R$ 10.000, R$ 5.000, 24 h, 2 min, 7 dias; o que `rejected` e `two_factor_required` não consomem |
| `test_idempotency.py` | reenvio equivalente (outra ordem de chaves, outro fuso, documento sem pontuação) → 200; qualquer outra diferença → 409; reenvio não conta como tentativa |
| `test_concurrency.py` | dois Pix simultâneos não atravessam o teto juntos; a terceira tentativa enxerga as anteriores; o mesmo `id` em paralelo grava uma vez |
| `test_persistence.py` | os três status ficam gravados e o `GET` devolve o mesmo envelope; falha de gravação não responde sucesso e não deixa nada |
| `test_contract.py` | 403, 404, campos faltando ou a mais, formatos, valor, geolocalização, datas incoerentes, pedido retroativo |
| `test_laranja.py` | os cenários P01 a P13 do módulo de laranja, um teste por cenário |
| `test_laranja_dict.py` | E1 por marcação e por 2 instituições; E4 com 1 e 2 notificações; timeout, 429, corpo inesperado; pagador lido do cache; destino ao vivo e cache como reserva; o DICT fora do ar nunca impede a decisão |
| `test_laranja_grafo.py` | direção (quem pagou a marcada não ganha E2); reputação; proporção de 50%; expiração de 30 dias; um salto; aparelho de conta marcada e de conta limpa; E3 e E5 nos limites; arestas gravadas |
| `test_laranja_ato.py` | gasto típico no limite de R$ 1.000; CNPJ com 89 e 90 dias; repasse em 49% e 50%; só Pix aprovado conta como recebido |
| `test_laranja_concorrencia.py` | repasses simultâneos da mesma conta enxergam os anteriores; pagamentos simultâneos a uma conta marcada são gravados uma vez cada |

## Demo da apresentação

Dois scripts montam a demo e desenham o grafo. Ficam **fora da API** e têm dependências próprias (`scripts/requirements.txt`: `networkx` e `matplotlib`), que não entram na imagem. Com a API de pé:

```bash
pip install -r scripts/requirements.txt      # no mesmo .venv dos testes
python scripts/seed_demo.py                  # monta os passos pela API e pelo mock e imprime cada decisão
python scripts/graph_demo.py                 # desenha o grafo em output/demo/grafo-demo.png
```

Cada rodada usa contas novas, então pode repetir. O `seed_demo.py` sai com erro se alguma decisão diferir da esperada. Os passos: (1) a vítima nova é barrada pela conta marcada e a mãe de sempre passa; (2) a laranja paga a luz, mas não repassa o dinheiro do golpe; (3) uma segunda conta, no mesmo aparelho e recebendo de vários titulares novos, também é barrada; (4) a padaria antiga que recebeu de boa-fé continua pagando o fornecedor; (5) o DICT fica lento e o motor segue decidindo só com as regras locais.

## Limitações e decisões

- **Data futura não é validada.** O sistema chamador é a fonte da `transaction_date`; assim os cenários históricos são reproduzíveis. Em produção seria preciso um relógio de referência e uma tolerância.
- **Pedido retroativo é recusado** (422): uma `transaction_date` anterior à última já analisada da conta obrigaria a reavaliar decisões já tomadas. Eventos que chegam atrasados exigiriam outro desenho.
- **Uma instituição de origem por instância.** O payload só informa o ISPB do destino; a conta pagadora é identificada por agência e conta, e CPF/CNPJ nunca a substitui.
- **2FA sem retorno.** O contrato não traz a conclusão do 2FA e o motor não simula a confirmação, então um aparelho pode continuar pedindo 2FA em Pix altos até uma aprovação comum completar as 24 h.
- **Risco residual assumido:** uma única solicitação fraudulenta abaixo dos tetos, no aparelho conhecido e com autenticação válida, é aprovada; um pagamento sob ameaça também. Uma rajada espaçada além de 2 minutos não dispara R3. Uma aprovação pequena pode tornar o aparelho conhecido para um Pix alto depois de 24 h. As regras não comprovam fraude: aprovar significa só que nenhuma intervenção foi exigida.
- **O cache de 24 h do pagador atrasa uma marcação nova.** Uma conta marcada no DICT depois de ter sido consultada só é vista como pagadora quando o cache expira. É o preço de não consultar o DICT a cada Pix de um cliente do banco; o destino, ao contrário, é sempre ao vivo.
- **Relação anterior exige início explícito.** A extensão fictícia `EvidenceSince` do mock pode informar datas E1/E4. Campo ausente é desconhecido; primeira observação ou início da janela não substituem a data. Sem início reconstruível, inclusive em E2+E4, não se presume exceção de relacionamento.
- **O módulo só vê os Pix que passam por ele.** Uma laranja que só aparece em outros bancos, sem marcação no DICT, não é vista; a QI, como participante direto do Pix, veria mais. "Recebido" significa aprovado pelo motor, não liquidado.
- **Risco residual de gastos típicos.** Repasse aparente é avaliado primeiro; ainda assim, entradas não observadas e CNPJ antigo podem permitir operações fraudulentas. R2 e R3 continuam valendo.
- **Fora desta versão** (próximos passos): renda declarada e situação cadastral como novas evidências, e separar o dinheiro suspeito da conta (recusar só a parte da saída que excede o que entrou de fontes limpas, na lógica do MED 2.0).
- **Os parâmetros do módulo também são do protótipo** (R$ 1.000, 50%, 5 titulares, 90 dias...) e precisariam de dados reais para calibrar.
- **Escolhas retiradas:** pontuação e IA (a explicação tem de ser nomeada e reproduzível), limite por média do cliente, ajuste por saldo (não é fornecido), limites progressivos após 7 dias, limite somado por CPF/CNPJ, regra por deslocamento geográfico. Detalhes e justificativas em [`docs/regras-de-negocio-v1.md`](docs/regras-de-negocio-v1.md).
- **Divergências do desenho original:** a trava é `FOR NO KEY UPDATE`, e não `FOR UPDATE`, porque o `INSERT` de `pix_analysis` pega `FOR KEY SHARE` na mesma linha e daria deadlock; entrada incoerente é 422, e não 400; `SQLAlchemy` está em 2.0.51 (a 2.0.23 do projeto base não importa em Python 3.14).

## Documentação

A política atual está no [guia v1.1](docs/guia-de-desenvolvimento-v1.1.md), no [módulo v1.1](docs/modulo-contas-laranja-v1.1.md) e nas convenções da [integração](docs/integracao-motor-v1.1.md). Os documentos v1 abaixo são preservados como histórico.


| Documento | O que contém |
|---|---|
| [`docs/regras-de-negocio-v1.md`](docs/regras-de-negocio-v1.md) | política acordada: definições, R1 a R4, ordem, 21 cenários, riscos residuais |
| [`docs/dados-e-fluxo-v1.md`](docs/dados-e-fluxo-v1.md) | modelo de dados, janelas, fluxo do POST, trava por conta, idempotência |
| [`docs/Proposta classificação possivel_laranja e regras por ato-v1.md`](docs/Proposta%20classificação%20possivel_laranja%20e%20regras%20por%20ato-v1.md) | módulo de conta laranja: DICT, grafo, L1 a L3, cenários P01 a P13 |
| [`docs/Motor Antifraude Pix — Guia de desenvolvimento - v1.md`](docs/Motor%20Antifraude%20Pix%20—%20Guia%20de%20desenvolvimento%20-%20v1.md) | desenho consolidado e plano de implementação |

O código segue as camadas do Base Service: `resource → controller → repository → model`, com `schemas/` na entrada, `dtos/` na saída, `connectors/` para serviços de fora e `errors/` com um código por recusa. A política pura fica em `src/rules/`.
