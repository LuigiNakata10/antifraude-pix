-- Schema do motor antifraude Pix.
--
-- Este arquivo é a fonte de verdade para bancos novos. Para atualizar bancos
-- existentes sem apagar histórico, aplicar os scripts de database/migrations.
--
-- Duas regras valem para todas as tabelas:
--   * HISTÓRICO É APPEND-ONLY. Nada que entrou é atualizado nem apagado: o que
--     muda no mundo vira uma linha nova. Agregados ("primeira vez", "total
--     recebido") se calculam por consulta, nunca por UPDATE.
--   * DINHEIRO É BIGINT EM CENTAVOS, e o id interno nunca sai na API.

-- A conta pagadora: a unidade de avaliação das regras e a âncora da trava
-- (SELECT ... FOR NO KEY UPDATE) que serializa os pedidos da mesma conta.
-- Nasce sozinha na primeira análise; não é cadastro de cliente.
--
-- Premissa a confirmar: UMA instituição de origem por instância do motor, já
-- que o payload só informa o ISPB do destino. Agência e conta bastam para
-- identificar a pagadora; CPF/CNPJ nunca substitui a identidade da conta.
CREATE TABLE payer_account(
    id                              BIGSERIAL PRIMARY KEY,
    branch                          VARCHAR(10) NOT NULL,
    account_number                  VARCHAR(20) NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(branch, account_number)
);

-- Uma linha por Pix: o pedido e a análise dele juntos, escrita uma única vez,
-- já com a decisão. Rejeição e pedido de 2FA também ficam gravados: o
-- histórico prova solicitações e decisões, não liquidação nem fraude.
--
-- Colunas só para o que as regras consultam; o resto (canal, IP, geolocalização
-- e o corpo inteiro) fica em `request_payload`.
CREATE TABLE pix_analysis(
    id                              BIGSERIAL PRIMARY KEY,
    -- `id` do Pix, como veio no POST (texto livre do cliente, não UUID).
    transaction_id                  TEXT NOT NULL,
    -- Identificador público da análise: é o `key` da resposta.
    analysis_key                    CHAR(36) NOT NULL,
    payer_account_id                BIGINT NOT NULL REFERENCES payer_account(id),
    amount                          BIGINT NOT NULL CHECK (amount > 0),
    -- Referência temporal de todas as regras (janelas, idade da conta, espera do aparelho).
    transaction_date                TIMESTAMPTZ NOT NULL,
    source_opening_date             TIMESTAMPTZ NOT NULL,
    -- Só dígitos: o CPF/CNPJ vem formatado ou não, e aqui é sempre igual.
    payer_document                  TEXT NOT NULL CHECK (payer_document ~ '^(\d{11}|\d{14})$'),
    device_id                       TEXT NOT NULL,
    -- "participante:agência:conta", a chave da conta de destino no grafo.
    destination_key                 TEXT NOT NULL,
    destination_document            TEXT NOT NULL CHECK (destination_document ~ '^(\d{11}|\d{14})$'),
    destination_opening_date        TIMESTAMPTZ NOT NULL,
    -- O que o DICT disse de cada conta NO MOMENTO da decisão (E1: marcação de conta
    -- laranja ou golpista; E4: notificações de infração abertas). NULL é
    -- desconhecido (DICT indisponível), e desconhecido nunca conta como evidência.
    -- Ficam em colunas porque o grafo as consulta: E2 soma o que a conta recebeu
    -- de quem tinha E1 naquele Pix, e a primeira vez que o motor viu uma conta marcada.
    payer_dict_e1                   BOOLEAN,
    payer_dict_e4                   BOOLEAN,
    destination_dict_e1             BOOLEAN,
    destination_dict_e4             BOOLEAN,
    -- Auditoria; as regras usam `transaction_date`.
    received_at                     TIMESTAMPTZ NOT NULL,
    analyzed_at                     TIMESTAMPTZ NOT NULL,
    status                          TEXT NOT NULL CHECK (status IN ('approved', 'two_factor_required', 'rejected')),
    reason_code                     TEXT NOT NULL CHECK (reason_code IN (
        'NEW_ACCOUNT_LIMIT_EXCEEDED',
        'DAILY_LIMIT_EXCEEDED',
        'MULE_DESTINATION',
        'MULE_PAYER',
        'SUSPECTED_MULE_FORWARDING',
        'NEW_DEVICE_HIGH_AMOUNT',
        'HIGH_FREQUENCY',
        'AMOUNT_ABOVE_ACCOUNT_AVERAGE',
        'POLICY_PASSED'
    )),
    policy_version                  TEXT NOT NULL,
    -- O que o POST e o GET devolvem: {"policy_version": ..., "reason": {...}}.
    metadata                        JSONB NOT NULL,
    -- Auditoria interna, nunca devolvida: estados, evidências, ato e dict_status
    -- no momento da decisão.
    analysis_details                JSONB NOT NULL DEFAULT('{}'),
    -- O corpo completo recebido, sem cabeçalhos nem token.
    request_payload                 JSONB NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(transaction_id),
    UNIQUE(analysis_key)
);

-- As janelas de 2 minutos e de 24 horas (R1 a R3) e o histórico da média (R5).
CREATE INDEX pix_analysis_payer_date_idx
    ON pix_analysis (payer_account_id, transaction_date);

-- Quando o aparelho foi aprovado pela primeira vez (R4): só aprovação conta.
CREATE INDEX pix_analysis_payer_device_approved_idx
    ON pix_analysis (payer_account_id, device_id, transaction_date)
    WHERE status = 'approved';

-- Entradas e titulares distintos de uma conta de destino (E3 e E5).
CREATE INDEX pix_analysis_destination_date_idx
    ON pix_analysis (destination_key, transaction_date);

-- Relação anterior e destinatário conhecido: o mesmo pagador para o mesmo titular.
CREATE INDEX pix_analysis_payer_destination_document_idx
    ON pix_analysis (payer_account_id, destination_document, transaction_date);

-- As arestas do grafo de contas, gravadas no mesmo commit da análise que as
-- gerou. UMA LINHA POR EVENTO, nunca um agregado atualizado: "primeira vez",
-- "última vez" e "total" saem de MIN, MAX e SUM por consulta indexada.
--
--   pix       do pagador para o destino (com direção): segue o dinheiro
--   device    sem direção: a mesma quadrilha operando várias contas
--   document  sem direção: o mesmo titular em contas diferentes
--
-- IP não vira aresta: wi-fi público e operadoras com IP compartilhado ligariam
-- pessoas sem relação. As chaves são "participante:agência:conta".
CREATE TABLE account_link(
    id                              BIGSERIAL PRIMARY KEY,
    pix_analysis_id                 BIGINT NOT NULL REFERENCES pix_analysis(id),
    from_key                        TEXT NOT NULL,
    to_key                          TEXT NOT NULL,
    link_type                       TEXT NOT NULL CHECK (link_type IN ('pix', 'device', 'document')),
    -- Em centavos, só nas arestas de dinheiro.
    amount                          BIGINT,
    -- A `transaction_date` do Pix que gerou a aresta.
    seen_at                         TIMESTAMPTZ NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    CHECK ((link_type = 'pix' AND amount > 0) OR (link_type <> 'pix' AND amount IS NULL)),
    UNIQUE(pix_analysis_id, link_type, from_key, to_key)
);

CREATE INDEX account_link_to_idx ON account_link (to_key, link_type, seen_at);
CREATE INDEX account_link_from_idx ON account_link (from_key, link_type, seen_at);

-- O cache do DICT, também append-only: cada consulta que respondeu é uma linha,
-- e quem lê usa a MAIS RECENTE dentro da validade (destino 1 hora, pagador 24
-- horas). Consulta que falhou não entra: indisponível vira "desconhecido".
CREATE TABLE dict_lookup(
    id                              BIGSERIAL PRIMARY KEY,
    account_key                     TEXT NOT NULL,
    response                        JSONB NOT NULL,
    fetched_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW())
);

CREATE INDEX dict_lookup_account_fetched_idx ON dict_lookup (account_key, fetched_at DESC);
