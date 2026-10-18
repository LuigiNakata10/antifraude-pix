# Testes e validação — v2

**Política verificada:** `pix-v1.3` · **Data:** 18/10/2026

Como a suíte prova que o motor faz o que a [política](politica-antifraude-v2.md) e a [arquitetura](arquitetura-e-dados-v2.md) descrevem, o que ela cobre e o que ela não prova. Substitui, como referência, a [revisão dos testes da v3](historico/revisao-dos-testes-v3.md), que registra o detalhe das remoções e consolidações.

## Como rodar

Com a stack no ar, sem Python no host:

```bash
docker compose up --build -d --wait
docker compose --profile test run --build --rm tests          # a suíte inteira
docker compose --profile test run --rm --no-deps tests \
  pytest tests/integration/pix_transaction/test_policy.py      # um arquivo
docker compose --profile test run --rm --no-deps tests python -m flake8 .
```

Com Python 3.11+ no host, `pip install -r requirements-dev.txt` e `pytest` também funcionam, contra a API já de pé.

## Estratégia

- **Black box por HTTP.** Os testes falam com a API real (FastAPI e PostgreSQL) e não importam nada de `src/`. Uma regra que não muda o que o cliente recebe não é considerada testada só porque um rótulo interno está certo.
- **Cada teste monta o próprio mundo.** Contas, documentos e aparelhos são novos a cada teste, e todo o histórico financeiro é criado pelo `POST`, pelas mesmas regras da API, sem inserir aprovações impossíveis no banco.
- **O DICT é roteirizado por teste.** O Mockserver responde por conta, com prioridade crescente, e por padrão não marca ninguém. Timeout, 429 e corpo inesperado são simulados pelo próprio mock.
- **Cada teste confere status e motivo.** Nos tetos, também os valores observados e o limiar; nas regras do módulo, o estado, as evidências e o ato que aparecem no motivo.
- **Fronteiras exatas.** R$ 1.000, R$ 20.000 e R$ 5.000 exatos e um centavo acima; 2 minutos, 24 horas, 7 dias e 30 dias exatos e um segundo antes; igualdade dos limiares de R5 e do repasse.
- **Para cada regra, o caso que passa e o caso barrado.**

### Exceções conscientes ao black box

O que nunca volta na resposta só pode ser conferido no banco. Essas leituras são pontuais e só usam `SELECT`:

| Exceção | Por quê |
| --- | --- |
| Ler `analysis_details` e as colunas do DICT de uma análise | Conferir o registro de auditoria (estado, evidências, situação do DICT) |
| Controlar o `fetched_at` de uma resposta do DICT em `dict_lookup` | Testar a expiração de 5 minutos do cache sem esperar 5 minutos; só respostas externas fictícias, nunca aprovações financeiras |
| Instalar um gatilho que faz falhar a gravação em `account_link` | Provar que uma falha depois do INSERT da análise desfaz tudo, não responde sucesso e permite nova tentativa |

## O que cada arquivo cobre

Em `tests/integration/`:

| Arquivo | Cobre | Casos |
| --- | --- | ---: |
| `pix_transaction/test_contract.py` | 403, 404, campos faltando ou a mais, formatos, valor não inteiro, geolocalização, datas inexistentes, conta aberta depois do Pix, pedido retroativo | 67 |
| `pix_transaction/test_policy.py` | Cenários C01–C21 e as bordas de R1 a R4 | 33 |
| `pix_transaction/test_account_average.py` | R5: piso, igualdade, média fracionária, sem histórico, exclusões (Pix atual, rejeições, 2FA, recebimentos, reenvios), separação por conta, precedência | 23 |
| `pix_transaction/test_idempotency.py` | Reenvio equivalente (ordem de chaves, fuso, documento sem pontuação) dá 200; cada campo diferente dá 409; reenvio não conta nem consome limite | 20 |
| `pix_transaction/test_v11.py` | Texto inválido, P14–P19, aparelho compartilhado com aprovações das duas contas, arestas só de aprovações, identidade da conta, reputação em 30 dias | 21 |
| `pix_transaction/test_laranja_dict.py` | E1 por marcação e por duas instituições, E4, timeout, 429, corpo inesperado, cache de reserva do destino, DICT fora do ar | 19 |
| `pix_transaction/test_laranja.py` | Cenários P01–P13 | 15 |
| `pix_transaction/test_laranja_ato.py` | Gasto típico no limite de R$ 1.000, CNPJ de 90 dias, repasse em 50% e no mínimo de entradas, exceção do CNPJ antigo | 15 |
| `pix_transaction/test_v13.py` | Piso da R5, Pix para a mesma conta, contas do mesmo titular, datas extremas, expiração do cache do pagador | 15 |
| `pix_transaction/test_laranja_grafo.py` | Direção do dinheiro (P20), reputação de 9 e 10 contrapartes, proporção, expiração, um salto, aparelho compartilhado, E3 de PF e CNPJ, E2 + E4 (P15) | 14 |
| `pix_transaction/test_concurrency.py` | Dois Pix simultâneos não furam o teto; a terceira tentativa enxerga as anteriores; o mesmo id em paralelo grava uma vez | 5 |
| `pix_transaction/test_persistence.py` | Os três status ficam gravados e o GET devolve o mesmo envelope; falha de gravação não deixa nada | 4 |
| `pix_transaction/test_laranja_concorrencia.py` | Repasses simultâneos enxergam os anteriores; pagamentos simultâneos a conta marcada gravados uma vez cada | 2 |
| `test_healthcheck.py` | Disponibilidade do `/health_check` | 1 |
| **Total** | | **254** |

## Resultado

- **254 testes aprovados**, em cerca de 40 segundos, pelo comando do README.
- **flake8** limpo em `src`, `tests` e `scripts`.
- **Demo:** `scripts/seed_demo.py` confere 7 de 7 decisões esperadas; `scripts/graph_demo.py` desenha o grafo (`docs/img/grafo-demo-v2.png`).
- **Concorrência:** com a trava por conta removida, os testes de concorrência falham; com ela, passam. A verificação foi feita durante o desenvolvimento, para garantir que esses testes não passam por acaso.
- **Compatibilidade:** análises gravadas em `pix-v1.1` e `pix-v1.2` continuam sendo devolvidas com a versão e o motivo originais pelo GET e pelos reenvios.

## O que a suíte não prova

- **Eficácia contra fraude real.** Os testes provam aderência à política descrita, com dados fictícios. Taxa de detecção e de falso positivo só se medem com dados reais.
- **Ausência de espera entre contas diferentes.** A trava é por conta, mas não há medição de que contas diferentes nunca esperem umas pelas outras.
- **O DICT real.** O mock segue uma estrutura simplificada e a extensão `EvidenceSince` é fictícia.
- **Desenvolvimento inteiro em TDD.** Boa parte dos cenários foi escrita antes do código (com falhas registradas antes da implementação), mas a revisão da suíte não transforma retrospectivamente todo o desenvolvimento em TDD.
