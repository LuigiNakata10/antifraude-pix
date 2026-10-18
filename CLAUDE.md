# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Estado do repositório

Desafio do Bootcamp QI Tech 2026: motor antifraude Pix. Toda a documentação e os commits do time são em português; mantenha isso.

O código parte da `main` do Base Service (`bootcamp-base-api`, cópia sem histórico). A política em vigor é a **`pix-v1.3`** (`POLICY_VERSION` em `src/rules/parameters.py`), na branch `v3`: POST e GET, trava por conta pagadora, idempotência (200/409), regras base R1–R5 e o módulo de conta laranja (DICT simulado com cache, grafo de contas, E1–E5, ato, L1–L3), com 254 testes e os scripts da demo. Não há `NotImplementedError` em `src/`.

## Documentos

A referência é a **documentação v2**, que consolida tudo o que vale na `pix-v1.3`:

- `docs/politica-antifraude-v2.md`: definições, R1–R5, E1–E5, estado, ato, relação anterior, L1–L3, ordem, códigos de motivo, cenários C01–C21 e P01–P20, riscos, alternativas descartadas, histórico de versões.
- `docs/arquitetura-e-dados-v2.md`: contrato e respostas HTTP, modelo de dados, indicadores do contexto, DICT e cache, fluxos do POST e da decisão, trava e idempotência, camadas. É também a fonte do PDF.
- `docs/testes-e-validacao-v2.md`: estratégia, exceções ao black box, cobertura por arquivo, resultados e limites.

Tudo o que é anterior (política v1, guia e módulo v1.1, revisões v1.2 e v1.3, revisão dos testes) está intacto em `docs/historico/`. Não edite o histórico: documento novo ganha versão nova (o time combinou "documento novo vira v2", depois v3...).

Mudou regra, parâmetro ou código de erro? Atualize, na mesma mudança, `src/rules/parameters.py` (com o porquê), a política v2, a arquitetura v2 (e o PDF), a tabela do README e os testes.

## Comandos

Sem Python no host, tudo pelo compose:

```bash
docker compose up --build -d --wait                                    # API (3000), Postgres e mockserver
docker compose --profile test run --build --rm tests                   # a suíte inteira (~40 s)
docker compose --profile test run --rm --no-deps tests \
  pytest tests/integration/pix_transaction/test_policy.py::TestDailyLimit   # um teste
docker compose --profile test run --rm --no-deps tests python -m flake8 .   # lint
docker compose --profile test run --rm --no-deps -v ./output/demo:/app/output/demo tests python scripts/seed_demo.py
docker compose --profile test run --rm --no-deps -v ./output/demo:/app/output/demo tests python scripts/graph_demo.py
docker compose --profile test run --rm --no-deps -v ./docs:/app/docs:ro -v ./output/pdf:/app/output/pdf tests \
  python scripts/gerar_pdf_arquitetura.py                              # regera o PDF da arquitetura
docker compose down -v                                                 # obrigatório ao mudar database/database.sql
```

- A imagem `tests` copia `src/` para a raiz de `/app`: dentro dela não existe a pasta `src`, por isso o lint é `flake8 .`.
- **O compose não publica o Postgres nem o mock no host** (uma porta ocupada, como um Postgres local na 5432, derrubava o `up` inteiro). Para rodar o `pytest` do host (Python 3.11+, `pip install -r requirements-dev.txt`), suba com `docker compose -f docker-compose.yml -f docker-compose.host-ports.yml up --build -d --wait`; se 5432 ou 1080 estiverem ocupadas, ponha `DB_PORT`/`MOCKSERVER_PORT` num `.env` (fora do Git) e a mesma porta na `DATABASE_URL`.
- Banco criado antes da v1.2 não aceita o motivo da R5: aplique `database/migrations/001_account_average_reason.sql` (comando no README) ou recrie com `down -v`.
- Arquivos gerados pelo container (PDF, imagens em `output/`) ficam com dono `root`.

## Arquitetura

- **Camadas do Base Service:** `src/resources/pix_transaction.py` → `src/controllers/` (ordem dos passos, trava, releitura do id, commit; `DictController` decide cache × ao vivo) → `src/repositories/` (todas as consultas) → `src/models/`. A política é pura em `src/rules/` (`policy.py` com a ordem, `laranja.py` com estado, ato e L1–L3, `parameters.py` com os números), sem banco nem I/O, chamada só pelo controller.
- **Fluxo do POST:** normalizar e validar (400/422, sem banco) → procurar o id (reenvio) → consultar o DICT **antes da trava** (200 ms, paralelo) → travar a conta (`FOR NO KEY UPDATE`) → procurar o id de novo, recusar pedido retroativo e identidade divergente → montar o contexto numa única camada → decidir → gravar a análise e, se aprovada, as arestas → commit.
- **Ordem da política:** R1 → R2 → L1 → L2 → L3 → R4 → R3 → R5 → aprovação. Rejeição antes de 2FA; um único motivo; o módulo de laranja nunca pede 2FA.
- **Banco é a única fonte de estado.** Quatro tabelas, todas append-only: `payer_account`, `pix_analysis` (pedido e decisão numa linha, gravada uma vez), `account_link` (arestas do grafo, só de aprovações) e `dict_lookup` (cache do DICT, uma linha por consulta que respondeu).
- **DICT** é um Mockserver 5.15.0 que carrega `mocks/dict_expectations.json` (padrão: nenhuma marcação). Pagador: cache de 5 min sem renovar na leitura. Destino: sempre ao vivo, cache de 1 h só como reserva. Indisponível = desconhecido (`None`), nunca evidência.

## Decisões fechadas (não reabrir sem motivo)

- `status` é coluna com CHECK, não tabela enumeradora.
- **Janelas** `(t − janela, t]`, `t` = `transaction_date`; o Pix atual entra uma vez, na regra. Idades são diferença entre datas.
- **422** para entrada incoerente: data inexistente ou fora do intervalo (`QIT003001`), conta aberta depois do Pix (`QIT003002`), pedido retroativo (`QIT003006`), titular/abertura divergente (`QIT003007`), mesma conta na origem e no destino (`QIT003008`). Data futura não é validada.
- **Reenvio:** equivalência em `utils/payload_normalizer.py` (ordem de chaves, datas em UTC, documentos só dígitos, o resto exato) → 200 com a original; diferente → 409 `QIT003004`. Conferido antes da ordem. Mesmo id em contas diferentes: o `UNIQUE(transaction_id)` decide.
- **Trava** `FOR NO KEY UPDATE`, não `FOR UPDATE`: o INSERT de `pix_analysis` pega `FOR KEY SHARE` e daria deadlock. Espera acima de 5 s → 503 `QIT003005`.
- `amount` recusa float (inclusive `150000.0`) via `integer_fields`; latitude/longitude são floats legítimos.
- **R2** é R$ 20.000. **R5:** 2FA quando `amount × N > 10 × max(S, 50000 × N)`, com N aprovações enviadas e soma S, sem arredondar.
- **Estado:** `suspeita_elevada` só por E1 ou E2+E4; E3+E5 continua `suspeita`. **Repasse aparente prevalece sobre gasto típico.** E3 de CNPJ: 30 titulares e 3 estreantes. E2: contrapartes contadas por conta em 30 dias; aparelho exige aprovações das duas contas.
- **Início da evidência** só por data explícita (`EvidenceSince` do mock, para E1/E4); ausente é desconhecido, e então não há relação anterior presumida.
- **"Recebido" e "enviado"** são só Pix `approved`. E1 de quem enviou fica em `pix_analysis.payer_dict_e1`.
- O `reason` das regras L traz conta, estado, evidências, valores e ato; nunca documento nem identidade de conta marcada.

## Testes

- Black box por HTTP, sem importar `src/`; cada teste cria contas novas e monta o histórico pelo POST, com o DICT roteirizado por conta (`tests/utils/dict_mock.py`).
- Exceções conscientes (só onde a informação nunca volta na resposta): leitura de `analysis_details`/colunas do DICT e controle do `fetched_at` em `dict_lookup` (`tests/utils/db_utils.py`), e o gatilho de falha de gravação em `test_persistence.py`.
- **Não use o log do Mockserver** (`retrieve`/`clear` degradam com o volume).
- Os cenários de outras regras começam o histórico com uma aprovação de valor compatível com a R5, para ela não esconder o que o teste verifica.

## Invariantes da política

- Unidade de avaliação é a conta pagadora, não o CPF/CNPJ. Valores em centavos inteiros.
- Bordas exatas: R$ 1.000 e R$ 20.000 exatos passam; conta com exatamente 7 dias não é nova; R4 dispara em R$ 5.000 ou mais; R5 é estrita.
- Só `approved` consome limite, cria familiaridade de aparelho, entra na média da R5 e cria arestas. R3 conta qualquer resultado, sem reenvios.
- Entrada inválida (400) ou incoerente (422) não consome limite, não conta em R3 e não cria familiaridade.
- Falha técnica nunca vira decisão. Informação ausente nunca é evidência.

## PDF da arquitetura

`scripts/gerar_pdf_arquitetura.py` lê `docs/arquitetura-e-dados-v2.md` e grava `output/pdf/arquitetura-e-dados-v2.pdf` (a constante `VERSION` escolhe o arquivo). O renderer não é um conversor Markdown genérico: entende títulos, parágrafos, listas, tabelas, blocos de código e os marcadores `<!-- page -->` e `<!-- diagram:X -->`, e cada bloco Mermaid tem um desenho vetorial equivalente (`model`, `post`, `decision`). Mudou um diagrama, mude o desenho. Use só símbolos ASCII (`>=`, `->`, `x`) e links absolutos: a fonte embutida não tem `≥`/`→`, e links relativos não são renderizados. O PDF da proposta v1 fica em `output/pdf/historico/`.
