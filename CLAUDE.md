# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Estado do repositório

Desafio do Bootcamp QI Tech 2026: motor antifraude Pix. Toda a documentação e os commits do time são em português; mantenha isso.

O código parte da `main` do Base Service (`bootcamp-base-api`, cópia sem histórico). **Implementado:** schema de entrada, banco e models, DTO, erros `QIT003001`–`QIT003006`, POST e GET completos, trava por conta pagadora, idempotência (200/409), contexto histórico e a política R1–R4 (C01–C21). **Ainda não existe:** consulta ao DICT (`DictConnector.get_statistics` levanta `NotImplementedError`; o controller nem o chama, e `analysis_details` grava `dict_status: "nao_consultado"`), grafo de contas (`account_link` existe no banco e não é gravada) e o módulo de laranja (o lugar de L1–L3 está marcado em `rules/policy.py`).

## Comandos

```bash
docker compose up -d                  # API (3000), Postgres e mockserver; espere o healthcheck (healthy)
docker compose down -v                # OBRIGATÓRIO ao mudar database/database.sql
docker compose build --no-cache api   # ao mudar requirements.txt
pytest                                # roda na máquina, por HTTP, contra a API já de pé (~12 s)
pytest tests/integration/pix_transaction/test_contract.py::TestPixTransactionContract::test_post_without_token_is_forbidden
```

Se 5432/5433 estiverem ocupadas no host, crie `.env` (fora do Git) com `DB_PORT=<livre>` e a mesma porta na `DATABASE_URL`.

## Decisões já fechadas e desvios do guia

- `status` é coluna com CHECK (não tabela enumeradora). `account_link` e `dict_lookup` são append-only: uma linha por evento, agregados por consulta. `pix_analysis` também: gravada uma vez, já com a decisão.
- Entrada incoerente (conta aberta depois do Pix, data inexistente) e pedido retroativo são **422**, não 400. Data futura não é validada no MVP: o sistema chamador é a fonte da data (limitação para o README).
- **Janelas** `(t − janela, t]`, `t` = `transaction_date` do pedido: uma linha exatamente em `t − janela` não conta; uma já gravada com data igual a `t` conta. O pedido atual entra uma vez, na regra.
- **Pedido retroativo** (data estritamente anterior à maior já gravada da conta, qualquer status): 422 `QIT003006`, depois da trava, sem gravar nem contar em R3. Data igual à última é aceita.
- **Reenvio:** mesmo `id` com payload equivalente → 200 com a original; diferente → 409 `QIT003004`. Equivalência em `utils/payload_normalizer.py`: ordem de chaves ignorada, datas em UTC, documentos só dígitos, o resto exato (canal, IP e geolocalização incluídos). O reenvio é conferido antes da ordem: reenviar um Pix antigo devolve a original. Mesmo `id` em contas diferentes: o `UNIQUE(transaction_id)` decide e o perdedor trata o vencedor como reenvio.
- Trava da conta pagadora é `FOR NO KEY UPDATE` (`with_for_update(key_share=True)`), não `FOR UPDATE` como diz o guia: o INSERT de `pix_analysis` pega `FOR KEY SHARE` e daria deadlock. Espera de trava acima de 5 s → 503 `QIT003005`.
- `amount` recusa float (inclusive `150000.0`) via `integer_fields` em `SchemaHandler.validate`; só ele, porque latitude/longitude são floats legítimos.
- Documentos: aceita formatado ou só dígitos, grava só dígitos. `channel` é texto livre. Padrões de agência (`\d{1,10}`) e conta (`\d{1,20}`) são suposição.
- `src/rules/` é pacote puro (sem banco nem I/O), chamado só pelo controller; os parâmetros e o porquê de cada um estão em `rules/parameters.py`. `reason` traz só os campos da regra que decidiu (R3 usa `observed_count`/`limit_count`).
- `test_persistence.py` tem uma exceção consciente ao black box: um gatilho instalado por conexão direta ao Postgres prova que falha de gravação não responde sucesso. "GET após mudança de política" não tem teste (exigiria alterar o código em execução).

## Documentos e hierarquia entre eles

- `docs/regras-de-negocio-v1.md`: política **acordada** pelo time. Regras base R1–R4, definições (conta nova, acumulado de 24h, dispositivo conhecido, destinatário conhecido), ordem de decisão e cenários C01–C21. Ela manda sobre qualquer outro documento.
- `docs/Proposta classificação possivel_laranja e regras por ato-v1.md`: módulo de conta laranja (**aprovado**): DICT simulado, grafo de contas, estado `possivel_laranja` (evidências E1–E5), regras L1–L3, cenários P01–P13.
- `docs/dados-e-fluxo-v1.md`: proposta **técnica a revisar**: modelo de dados (`payer_account`, `pix_analysis`), janelas, fluxo do POST, trava por conta, idempotência, GET.
- `docs/Motor Antifraude Pix — Guia de desenvolvimento - v1.md`: consolida os três num desenho único, com contrato da API, camadas, pendências e plano de implementação. Comece por ele; quando divergir de um documento fonte, a seção "Convenções e pendências" registra.

Os arquivos levam sufixo de versão (`-v1`). Ao revisar, o padrão do último commit foi criar/renomear com a versão no nome. Atenção: `README.md`, o guia e `scripts/gerar_pdf_dados_fluxo.py` ainda citam os nomes antigos sem versão (`docs/dados-e-fluxo.md`, `regras-de-negocio.md`); o script falha até `SOURCE` ser atualizado.

## Gerar o PDF

Requer Python 3.11+ e `reportlab`:

```bash
python scripts/gerar_pdf_dados_fluxo.py
```

Lê o Markdown de dados e fluxo e reescreve `output/pdf/dados-e-fluxo-antifraude-pix.pdf`. O renderer é específico desse documento (não é conversor Markdown genérico) e desenha os fluxos como vetores equivalentes aos blocos Mermaid; se mudar a estrutura do Markdown ou os diagramas, o script precisa acompanhar. PDFs são `binary` no `.gitattributes`.

## Arquitetura planejada (do guia de desenvolvimento)

- Stack: Python sobre o **Base Service** da organização (camadas e envelope de erro dele), Postgres, `docker compose`, `pytest`. Critério de pronto: clonar, `docker compose up` e `pytest` verdes sem passo manual.
- Rotas exatas do desafio: `POST /pix/transaction` (analisa e grava) e `GET /pix/transaction/{id}` (devolve a análise gravada, sem reexecutar regras). Header `INTERNAL-TOKEN` obrigatório (403 sem ele).
- Resposta: `key`, `status` ∈ {`approved`, `two_factor_required`, `rejected`}, `metadata` com `policy_version` e **um único** `reason` (código, descrição, valores observados e limiar em centavos). Sem lista de alertas, sem score ou probabilidade.
- Camadas: resource `src/resources/pix_transaction.py` → controller (orquestração, trava por conta pagadora, commit) → repositórios (todas as consultas) → `src/rules/` (regras base, `laranja.py` e a política de ordem, **puras, sem banco**). Conector DICT em `src/connectors/dict_connector.py`, schema de entrada em `src/schemas/post_pix_transaction.json`, erros em `src/errors/`.
- Uma única camada monta o contexto histórico para R1–R4 e o módulo de laranja; a política recebe esse contexto e devolve o primeiro resultado aplicável na ordem **R1, R2, L1, L2, L3, R4, R3** (rejeição antes de 2FA).
- Banco é a única fonte de estado (nenhum contador em memória). Grafo de contas fica no Postgres (`account_link`), não em banco de grafos. DICT é mock (Mockserver no compose, `mocks/dict_expectations.json`).
- Idempotência por `transaction_id` do cliente: mesmo conteúdo normalizado → 200 com análise original; conteúdo diferente → 409; `UNIQUE(transaction_id)` como garantia final.

## Invariantes da política que o código deve respeitar

- Unidade de avaliação é a conta pagadora, não o CPF/CNPJ. Referência temporal é `transaction_date`.
- Valores em centavos inteiros. Bordas exatas importam (R$ 1.000 e R$ 10.000 exatos passam; conta com exatamente 7 dias não é nova; R4 dispara em ≥ R$ 5.000).
- Só análises `approved` consomem limite de 24h e criam familiaridade de dispositivo; R3 conta tentativas distintas com qualquer resultado, excluindo reenvios.
- Entrada inválida é erro HTTP (400 de formato, 422 de incoerência): não consome limites, não conta em R3, não cria familiaridade.
- Falha técnica nunca vira decisão (5xx). Única exceção controlada: DICT indisponível deixa E1/E4 desconhecidas.
- Informação ausente não é evidência; os parâmetros são do protótipo, cada um precisa de "por quê" no README final (tabela Regra, Lógica, Parâmetros, Por quê).
- Testes: um teste por cenário C01–C21 (`test_policy.py`) e P01–P13; com o módulo de laranja ligado, nenhum cenário C pode mudar de resultado.
