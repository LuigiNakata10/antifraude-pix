# [Nome do grupo] — Motor antifraude Pix

**Integrantes:** [nomes]

Hackathon QI Tech 2026. Uma API que recebe um pedido de Pix e responde `approved`, `two_factor_required` ou `rejected`, sempre com **um motivo explicado**. Construída a partir do Base Service, com banco próprio que guarda tudo o que chegou.

**Estado desta versão:** as regras base R1 a R4, a idempotência e a trava por conta estão implementadas e testadas (136 testes). O módulo de conta laranja (DICT simulado, grafo e L1 a L3) ainda não está implementado: veja [Módulo de conta laranja](#módulo-de-conta-laranja-em-andamento).

## Como o motor de decisão funciona

O problema impõe três restrições, e cada escolha abaixo sai delas:

- **Tempo.** A decisão sai antes do dinheiro. Nada de consulta externa pesada nem de analista no caminho: as regras são determinísticas e leem só o banco.
- **Histórico.** Um Pix sozinho diz pouco. As regras comparam com o que a **conta pagadora** já fez (acumulado, frequência, aparelho).
- **Fricção.** Bloquear cliente bom também é prejuízo. O 2FA só aparece onde há dúvida real; quem paga o aluguel todo mês passa direto.

Princípios: poucas regras, sem pontuação nem probabilidade de fraude; **um único motivo** na resposta; informação ausente não é evidência (a primeira transação de uma conta não sofre intervenção só por falta de histórico); aprovar não é garantia de segurança e rejeitar por teto não é fraude confirmada; **falha técnica nunca vira decisão** (vira erro 5xx).

**O caminho de um POST**, na ordem em que o controller executa (`src/controllers/pix_transaction_controller.py`):

1. valida o corpo (schema) e a coerência dos dados (data que não existe, conta aberta depois do Pix → 422), sem tocar no banco: entrada inválida não consome limite nem conta em frequência;
2. procura o `id`: um Pix já analisado não é analisado de novo;
3. **trava a conta pagadora** (`SELECT ... FOR NO KEY UPDATE`) e procura o `id` de novo, porque um reenvio pode ter concluído enquanto este pedido esperava;
4. recusa o pedido retroativo e lê o histórico da conta, **só depois da trava**;
5. a política pura decide (`src/rules/policy.py`: sem banco, sem relógio, sem I/O);
6. grava a análise e dá `commit`. Qualquer falha antes disso desfaz tudo.

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
| — | L1, L2, L3 | `rejected` | lugar reservado (módulo de laranja, ainda não implementado) |
| 3 | R4 | `two_factor_required` | `NEW_DEVICE_HIGH_AMOUNT` |
| 4 | R3 | `two_factor_required` | `HIGH_FREQUENCY` |
| 5 | nenhuma | `approved` | `POLICY_PASSED` |

- **Rejeição vem antes de 2FA.** R1 vem antes de R2 por ser a restrição específica da conta nova. Entre R4 e R3 a ordem é uma convenção de explicação, não uma alegação de que uma detecta mais fraude que a outra.
- **Quando pede 2FA:** quando há dúvida sobre quem faz o pedido (aparelho sem 24 h de aprovação com valor alto) ou insistência em intervalo curto, e nenhum teto foi violado. Nesses casos o cliente confirma que é ele, em vez de ser bloqueado.
- **Um único motivo.** Se R1 e R2 são excedidas ao mesmo tempo, sai só R1; se R4 e R3 se aplicam, sai só R4. A resposta traz os valores observados e o limiar da regra que decidiu, em centavos (R3, que explica uma contagem, traz `observed_count` e `limit_count`).
- **`two_factor_required` não cria aprovação nem familiaridade.** O contrato não traz a confirmação do 2FA e não há rota para ela: o mesmo aparelho pode continuar pedindo 2FA em Pix altos até uma aprovação comum completar as 24 h.

Exemplo de `metadata` (R4, real, gerado pela API):

```json
{
  "policy_version": "pix-v1",
  "reason": {
    "code": "NEW_DEVICE_HIGH_AMOUNT",
    "description": "Confirmação adicional: valor elevado em um aparelho ainda não conhecido para esta conta.",
    "observed_amount": 600000,
    "limit_amount": 500000
  }
}
```

## Módulo de conta laranja (em andamento)

Contra conta tomada, o 2FA funciona: o invasor não tem o segundo fator. Contra **conta laranja**, não: quem confirma é o próprio operador da conta. O módulo planejado classifica a conta (DICT simulado e grafo local de contas) e depois decide o ato: a laranja paga a conta de luz, mas não repassa o dinheiro do golpe.

| Regra | Lógica planejada | Status |
|---|---|---|
| **L1** destino laranja | destino `confirmada` e primeira relação do pagador com ele → `rejected` | não implementado |
| **L2** pagador laranja | pagador `confirmada` e ato que não é gasto típico → `rejected` | não implementado |
| **L3** repasse suspeito | pagador `suspeita` e ato de repasse → `rejected` | não implementado |

O desenho completo, com evidências, parâmetros e cenários P01 a P13, está em [`docs/Proposta classificação possivel_laranja e regras por ato-v1.md`](docs/Proposta%20classificação%20possivel_laranja%20e%20regras%20por%20ato-v1.md). Esta seção será completada com a tabela Regra, Lógica, Parâmetros e Por quê quando o módulo existir. As tabelas `account_link` e `dict_lookup` já existem no banco, e o lugar de L1 a L3 está marcado na política.

## Contrato da API

Rotas exigem o cabeçalho `INTERNAL-TOKEN` (sem ele: 403). `/` e `/health_check` são públicas.

- `POST /pix/transaction`: analisa e grava. O corpo é o do desafio (`id`, `amount` em centavos, `transaction_date` com fuso, `source_account`, `destination_account`, `source`); `geolocation` é opcional e todo campo a mais é recusado.
- `GET /pix/transaction/{id}`: devolve a análise **gravada**, sem rodar as regras de novo. O `{id}` é o `id` do cliente.
- Resposta: `{"key": "<uuid>", "status": "...", "metadata": {"policy_version": "pix-v1", "reason": {...}}}`. O id interno do banco nunca sai.

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

## Modelo de dados

Duas tabelas em uso, sem cadastro de clientes, saldo nem ledger (esquema em [`database/database.sql`](database/database.sql)):

- `payer_account`: a conta pagadora (agência e conta), âncora da trava. Nasce na primeira análise.
- `pix_analysis`: **uma linha por Pix**, com o pedido e a análise juntos, gravada uma vez já com a decisão. Tem colunas só para o que as regras consultam (valor, datas, aparelho, documentos, destino) e preserva o corpo completo em `request_payload` (JSONB). Índices nas janelas da conta e no parcial `WHERE status = 'approved'` da primeira aprovação do aparelho.
- `account_link` e `dict_lookup` já existem para o módulo de laranja e ainda não são gravadas.

**Histórico append-only:** nada que entrou é atualizado ou apagado. Rejeições e pedidos de 2FA também ficam gravados, e o `GET` devolve o resultado original mesmo que a política mude depois. Dinheiro é `BIGINT` em centavos.

## Como rodar e testar

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
pytest                   # ~10 s
```

Os testes rodam **na sua máquina, por HTTP, contra a API de pé** no Docker (black box: nenhum importa o código de `src/`). Cada teste monta o próprio histórico pela API, com contas novas, então não dependem uns dos outros.

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

**O que os testes cobrem** (`tests/integration/pix_transaction/`):

| Arquivo | Cobre |
|---|---|
| `test_policy.py` | os 21 cenários da política (C01 a C21) e as bordas exatas: R$ 1.000, R$ 10.000, R$ 5.000, 24 h, 2 min, 7 dias; o que `rejected` e `two_factor_required` não consomem |
| `test_idempotency.py` | reenvio equivalente (outra ordem de chaves, outro fuso, documento sem pontuação) → 200; qualquer outra diferença → 409; reenvio não conta como tentativa |
| `test_concurrency.py` | dois Pix simultâneos não atravessam o teto juntos; a terceira tentativa enxerga as anteriores; o mesmo `id` em paralelo grava uma vez |
| `test_persistence.py` | os três status ficam gravados e o `GET` devolve o mesmo envelope; falha de gravação não responde sucesso e não deixa nada |
| `test_contract.py` | 403, 404, campos faltando ou a mais, formatos, valor, geolocalização, datas incoerentes, pedido retroativo |

## Limitações e decisões

- **Data futura não é validada.** O sistema chamador é a fonte da `transaction_date`; assim os cenários históricos são reproduzíveis. Em produção seria preciso um relógio de referência e uma tolerância.
- **Pedido retroativo é recusado** (422): uma `transaction_date` anterior à última já analisada da conta obrigaria a reavaliar decisões já tomadas. Eventos que chegam atrasados exigiriam outro desenho.
- **Uma instituição de origem por instância.** O payload só informa o ISPB do destino; a conta pagadora é identificada por agência e conta, e CPF/CNPJ nunca a substitui.
- **2FA sem retorno.** O contrato não traz a conclusão do 2FA e o motor não simula a confirmação, então um aparelho pode continuar pedindo 2FA em Pix altos até uma aprovação comum completar as 24 h.
- **Risco residual assumido:** uma única solicitação fraudulenta abaixo dos tetos, no aparelho conhecido e com autenticação válida, é aprovada; um pagamento sob ameaça também. Uma rajada espaçada além de 2 minutos não dispara R3. Uma aprovação pequena pode tornar o aparelho conhecido para um Pix alto depois de 24 h. As regras não comprovam fraude: aprovar significa só que nenhuma intervenção foi exigida.
- **Escolhas retiradas:** pontuação e IA (a explicação tem de ser nomeada e reproduzível), limite por média do cliente, ajuste por saldo (não é fornecido), limites progressivos após 7 dias, limite somado por CPF/CNPJ, regra por deslocamento geográfico. Detalhes e justificativas em [`docs/regras-de-negocio-v1.md`](docs/regras-de-negocio-v1.md).
- **Divergências do desenho original:** a trava é `FOR NO KEY UPDATE`, e não `FOR UPDATE`, porque o `INSERT` de `pix_analysis` pega `FOR KEY SHARE` na mesma linha e daria deadlock; entrada incoerente é 422, e não 400; `SQLAlchemy` está em 2.0.51 (a 2.0.23 do projeto base não importa em Python 3.14).

## Documentação

| Documento | O que contém |
|---|---|
| [`docs/regras-de-negocio-v1.md`](docs/regras-de-negocio-v1.md) | política acordada: definições, R1 a R4, ordem, 21 cenários, riscos residuais |
| [`docs/dados-e-fluxo-v1.md`](docs/dados-e-fluxo-v1.md) | modelo de dados, janelas, fluxo do POST, trava por conta, idempotência |
| [`docs/Proposta classificação possivel_laranja e regras por ato-v1.md`](docs/Proposta%20classificação%20possivel_laranja%20e%20regras%20por%20ato-v1.md) | módulo de conta laranja: DICT, grafo, L1 a L3, cenários P01 a P13 |
| [`docs/Motor Antifraude Pix — Guia de desenvolvimento - v1.md`](docs/Motor%20Antifraude%20Pix%20—%20Guia%20de%20desenvolvimento%20-%20v1.md) | desenho consolidado e plano de implementação |

O código segue as camadas do Base Service: `resource → controller → repository → model`, com `schemas/` na entrada, `dtos/` na saída, `connectors/` para serviços de fora e `errors/` com um código por recusa. A política pura fica em `src/rules/`.
