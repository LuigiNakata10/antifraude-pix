# Revisão dos testes da v3

Esta revisão altera apenas testes e documentação. As regras e seus parâmetros continuam na política **pix-v1.3**. Não há alteração de endpoint, schema, migração, classificação ou decisão da aplicação.

## Critério de permanência

Um teste deve comprovar um efeito para quem paga ou integra a API: permitir um pagamento legítimo no cenário definido, restringir um risco previsto, explicar a decisão, manter o resultado consultável ou recuperar uma falha sem consumir histórico indevidamente.

Não basta chamar um teste de integração. Conferir apenas um rótulo interno, como `gasto_tipico` ou `suspeita`, pode deixar passar uma decisão final errada. Quando a situação importa para o cliente, preservamos o cenário e conferimos `status` e motivo pela API.

Não há importação de funções da aplicação para testá-las isoladamente. Os pedidos e o histórico financeiro são produzidos pelo HTTP, contra FastAPI e PostgreSQL reais. O DICT continua simulado. Há exceções pontuais de acesso ao banco para verificar persistência, controlar o relógio de um cache externo e provocar uma falha de gravação.

## Remoções e consolidações

| Alteração | Justificativa | Garantia preservada |
| --- | --- | --- |
| Healthcheck reduzido de seis casos para um | Rotas de exemplo, raiz e erros genéricos do Base Service não demonstravam o comportamento do antifraude | Disponibilidade no healthcheck; autenticação e texto com acentos continuam no endpoint Pix |
| Removida a falsa prova de independência entre contas | Todos terminarem aprovados não demonstra que não esperaram numa fila global | Permanecem concorrência de teto, frequência, ID e repasse; não alegamos ter medido ausência de espera entre contas |
| Envelope integrado aos testes parametrizados de POST/GET | Não requer outro Pix só para conferir os mesmos campos ou o comprimento de um identificador | Os três resultados têm envelope público e análise original consultável |
| Coordenadas fracionárias integradas a um Pix válido | Obter um segundo erro de entrada não era a forma mais clara de provar a aceitação do pedido | Um Pix coerente, com coordenadas fracionárias, recebe aprovação |
| Regra da média mantém apenas R$ 600 seguido de R$ 1 na regressão específica | Esse caso atravessa para baixo o antigo critério de ativação; as variantes de média já baixa repetiam a matriz do piso | O Pix posterior de R$ 15.000 pede 2FA; a matriz mantém piso, igualdade, um centavo acima e média fracionária |
| Teto isolado e acumulado reunidos em R2 | A cobertura do teto estava dividida entre regra base e média | Mantidos pagamento isolado e fracionado, no teto e um centavo acima |
| Removidas contagens isoladas de consultas ao cache | Já havia cenários de cache com efeito na decisão | Cache válido, expiração, marcação nova e reserva na falha continuam cobertos |
| Valores explicativos de E1 incorporados à matriz de sinais externos | Dois novos pedidos apenas para os mesmos tipos de marcação eram redundantes | Decisão, janela, quantidade de instituições e ausência de documento no motivo |
| E2+E4 e proteção de quem pagou a conta marcada consolidados | Os cenários gerais repetiam situações agora verificadas com contrastes de aprovação/rejeição | O segundo relato aberto muda a decisão quando há E2; o pagador anterior e quem recebeu dinheiro marcado têm desfechos diferentes |
| Retiradas verificações isoladas de rótulos E5 e do formato exato de quatro arestas | A representação interna não era uma nova prova de experiência do cliente | E5 passou a ser verificada também por aprovações de conta com recebimentos modestos e de conta com sete dias; vínculos de usos aprovados e decisões dependentes do grafo continuam cobertos |

As fronteiras monetárias, janelas, tipos de entrada e modos distintos de falha externa foram mantidos. Eles não são descartáveis apenas porque podem terminar com o mesmo status. Também foram mantidas as regressões conhecidas de datas extremas: não foi criada uma restrição nova de data para reduzir a suíte.

## Cenários fortalecidos

**Ato e contexto do pagamento.** Os testes de gasto típico agora usam uma conta marcada: R$ 1.000 para titular conhecido passa e R$ 1.000,01 é recusado. Os testes de repasse usam uma conta com suspeita, de modo que atingir a proporção ou o mínimo de entradas realmente muda aprovação para rejeição. Recebimentos rejeitados e que pediram 2FA não podem fazer o recebedor parecer um repassador. A precedência de repasse sobre titular conhecido permanece no cenário P16.

**Grafo e boa-fé.** Nos testes de E2, E4 é uma condição controlada. O pagamento observado é de R$ 1.500 para CNPJ com conta antiga: fica fora de gasto típico e da definição de repasse. Assim, a presença de E2 muda o resultado por L2, sem confundir esse efeito com L3. Isso permite observar os efeitos da proporção, de nove versus dez contrapartes, da direção do dinheiro e da expiração dos vínculos. Os casos de aparelho incluem usos aprovados das duas contas e aparelho exclusivo do cenário.

**Concentração de recebimentos.** Para PF e CNPJ, o valor de saída e o volume recebido permitem que a concentração, quando presente, produza uma recusa por repasse. E5 isolada e E3+E5 permitem uma saída de R$ 900 que cabe no teto de conta nova e não constitui repasse. Se essas evidências elevassem automaticamente a suspeita, a decisão passaria a ser incorreta. Os testes verificam esse efeito, além da auditoria auxiliar.

Dois contrastes de aprovação foram preservados na conferência final: conta de três dias que recebeu R$ 1.800 de três titulares e envia R$ 900, e conta com exatamente sete dias que recebeu R$ 6.000 de três titulares e envia R$ 3.000. Sem outros sinais, ambas devem ser aprovadas. Uma aplicação indevida de E5 nesses casos transformaria a saída de metade do recebido em rejeição por L3. Assim, os critérios de idade e de volume também protegem clientes legítimos por meio do resultado público.

**Reenvio.** O cenário de reordenação envia um novo dicionário com as chaves realmente reordenadas. O `update` anterior não mudava a ordem das chaves existentes. A expectativa continua sendo receber a análise original, sem novo consumo de limite ou tentativa.

**Recuperação de erro.** A falha provocada ocorre em `account_link`, depois de inserir `pix_analysis`, antes do commit. O teste exige erro técnico, GET sem análise parcial e sucesso na nova tentativa. A falha anterior acontecia antes do INSERT da análise e não comprovava esse desfazimento posterior.

**Prazo do cache.** O cache válido produz uma decisão observável, e a leitura adicional do `fetched_at` confirma que a consulta não prolongou o prazo na mesma linha. Os cenários de expiração verificam que uma resposta nova pode tanto restringir quanto liberar a conta. Não há espera real de cinco minutos.

**Pagamentos simultâneos para conta marcada.** Além das recusas, cada pedido é consultado e reenviado para verificar o mesmo resultado e a mesma análise. Quatro identificadores de resposta diferentes, sozinhos, não comprovavam persistência e reenvio estável.

## Inventário antes e depois

| Arquivo | Antes | Depois |
| --- | ---: | ---: |
| `test_account_average.py` | 25 | 23 |
| `test_concurrency.py` | 6 | 5 |
| `test_contract.py` | 68 | 67 |
| `test_idempotency.py` | 20 | 20 |
| `test_laranja.py` | 13 | 15 |
| `test_laranja_ato.py` | 15 | 15 |
| `test_laranja_concorrencia.py` | 2 | 2 |
| `test_laranja_dict.py` | 21 | 19 |
| `test_laranja_grafo.py` | 17 | 14 |
| `test_persistence.py` | 5 | 4 |
| `test_policy.py` | 31 | 33 |
| `test_v11.py` | 25 | 21 |
| `test_v13.py` | 17 | 15 |
| `test_healthcheck.py` | 6 | 1 |
| **Casos parametrizados** | **271** | **254** |
| **Funções de teste** | **165** | **138** |

A queda líquida é de 17 casos. Algumas matrizes receberam contrastes que antes estavam agrupados numa função; a quantidade não foi usada como meta. Não foi reduzida a cobertura apenas para chegar a um número menor.

## Validação

- **254 testes aprovados em 40,34 s**, com API, PostgreSQL e Mockserver num projeto Compose isolado, sem portas publicadas no host. A rodada intermediária de 252 casos também passou; a rodada final inclui os dois contrastes de aprovação descritos acima.
- **Flake8 aprovado**, com os mesmos arquivos de teste usados na rodada final.
- Nenhum arquivo de `src`, `database` ou `scripts` foi alterado.
- Serviços de outra implementação não foram modificados.

O comando de pytest é o mesmo do README. Nesta validação foi usado um nome próprio de projeto e um override local de portas para não interferir nos serviços existentes. Os resultados comprovam aderência à política implementada, não eficácia de detecção com dados reais. A revisão da suíte também não transforma retrospectivamente todo o desenvolvimento em TDD.
