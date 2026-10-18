# Revisão e justificativas — pix-v1.3

**Integrantes:** Renan Correia e Luigi Nakata. O grupo ainda não definiu um nome; o título do README identifica o projeto.

Esta revisão da branch `v3` corrige a fragilidade de R5, dois tipos de erro de entrada e o prazo do cache do pagador. Os documentos v1.1 e v1.2 ficam preservados como histórico. O teto geral permanece em R$ 20.000 em 24 horas, e a exceção de idade da conta de destino CNPJ permanece como estava.

## Regra e justificativa

| Decisão | Implementação | A favor | Custo ou limitação |
| --- | --- | --- | --- |
| R5 com piso da referência | 2FA acima de 10 × maior(média aprovada, R$ 500), com ao menos uma aprovação anterior | Um pagamento pequeno não desliga a regra; cálculo simples e explicável | Pagamentos excepcionais legítimos acima de R$ 5.000 podem pedir 2FA em contas de média baixa |
| R2 mantida | Rejeitar acumulado aprovado + atual acima de R$ 20.000 em 24h | Teto independente do perfil e resistente a fracionamento | Continua limitando clientes legítimos de maior volume |
| Origem e destino iguais | HTTP 422 `QIT003008` antes das consultas externas e da gravação | Evita erro de vínculo duplicado e impede contabilizar a mesma conta como entrada e saída | Chamada inválida precisa ser corrigida pelo sistema chamador |
| Datas e cálculos seguros | HTTP 422 `QIT003001` quando UTC ou as janelas não forem representáveis; idades calculadas por diferença | Evita erros 500 e preserva datas coerentes que o motor consegue processar | Existe um limite técnico mínimo de data para comportar as janelas |
| Cache do pagador | 5 minutos desde `fetched_at`, sem renovar em leituras | Reduz o atraso potencial de marcações de 24h para 5min, sem consultar em todo Pix | Pode atrasar uma marcação por até 5min; aumenta as consultas em relação a 24h |
| Idade do destino CNPJ mantida | CNPJ com conta de pelo menos 90 dias fica fora da definição de repasse aparente | Preserva rateios e pagamentos legítimos concentrados para estabelecimentos | Uma conta antiga pode participar de fraude; a exceção pode liberar um repasse suspeito |

R$ 500, multiplicador 10, teto de R$ 20.000 e prazo de cinco minutos são escolhas do protótipo, não parâmetros calibrados em dados reais. As correções não acrescentam modelo de IA, pontuação ou nova fonte externa.

## Definição da média

O histórico continua sendo por conta pagadora: todos os Pix enviados e aprovados observados até `transaction_date`, sem o atual, recebimentos, rejeições, solicitações de 2FA ou reenvios. Uma aprovação anterior basta; sem aprovação anterior, R5 não atua. As aprovações provam decisões do motor, não liquidação bancária.

Na v1.2, a média acima de R$ 500 era uma condição para ligar R5. Exemplo: uma aprovação de R$ 600 seguida de R$ 1 produz média de R$ 300,50. A condição deixava de valer, e R$ 15.000 podia ser aprovado em aparelho conhecido e sem outros sinais.

Na v1.3, **R$ 500 é o piso da referência de comparação**, e não uma condição de ativação nem um valor mínimo do Pix. Essa mudança de critério é intencional: com média de R$ 300,50, a referência fica em R$ 500 e o limiar de 2FA em R$ 5.000. O Pix de R$ 15.000 passa a exigir confirmação. A média ainda pode variar; o que foi removido é a possibilidade de desligar R5 ao cruzar o piso para baixo.

Para soma `S`, quantidade `N` e valor atual em centavos:

```text
N > 0
referencia_total = max(S, 50000 × N)
solicitar_2fa = amount × N > 10 × referencia_total
```

A multiplicação cruzada preserva médias fracionárias sem arredondar ou usar ponto flutuante para decidir. Soma e quantidade continuam sendo consultadas juntas depois da trava da conta. Não criamos média persistida, faixas adicionais ou mínimo de amostra além de uma aprovação.

## Ordem e explicação

**R1 → R2 → L1 → L2 → L3 → R4 → R3 → R5 → aprovação.**

Rejeições prevalecem sobre 2FA, e o resultado tem um motivo determinante. R5 mantém o código `AMOUNT_ABOVE_ACCOUNT_AVERAGE`; informa valor atual, soma histórica, quantidade, multiplicador e `reference_floor_amount` de 50000 centavos. Este campo substitui `minimum_average_amount` da v1.2, pois o piso deixou de ser uma condição sobre a média. A versão da política identifica essa mudança; GET e reenvios preservam as respostas antigas.

Os R$ 6.000 do exemplo de média de R$ 600 eram um **limiar para pedir 2FA**, não um teto fixo de rejeição. O teto de rejeição é o acumulado de R$ 20.000 em 24h. `two_factor_required` não aprova, não consome esse teto e não cria vínculos. A conclusão do 2FA continua fora da API.

### Entrada e datas

Origem e destino são comparados por instituição, agência e número da conta. Duas contas distintas de um mesmo CPF/CNPJ continuam permitidas. Pix para a mesma conta é uma entrada incoerente, não uma classificação de fraude, e não fica registrado como tentativa válida.

A conversão UTC passa a tratar também `OverflowError`. A data da transação precisa comportar a maior janela retrospectiva do motor, hoje 30 dias; o mínimo técnico é `datetime.min` UTC mais essa janela. Datas anteriores a esse mínimo retornam 422, mesmo se tiverem formato ISO válido. Aberturas ainda precisam ser anteriores ou iguais à transação.

Idade da conta e tempo desde a aprovação do aparelho são diferenças entre datas; não somamos sete dias ou 24 horas a uma data próxima ao ano 9999. Datas representáveis com janelas seguras permanecem aceitas. Esta revisão não cria restrição por horário do dia nem muda a premissa de que o sistema chamador informa `transaction_date`, inclusive datas futuras.

### Cache

O relógio de validade é o do servidor, separado da data de negócio do Pix. O pagador usa uma consulta bem-sucedida por até cinco minutos. Leituras não renovam o prazo; a primeira análise depois da expiração consulta novamente. Se a fonte falhar após expirar, o registro antigo não é reutilizado: E1/E4 ficam desconhecidas e as demais regras continuam.

O destino permanece consultado ao vivo, com reserva de cache de uma hora se houver falha. Preservamos essa assimetria para detectar uma nova marcação do recebedor no Pix seguinte e reduzir consultas repetidas do pagador. Falhas e validade da reserva ainda podem atrasar informações; não afirmamos atualização instantânea de ambos os lados.

## Exemplos e limites

Os exemplos de R5 pressupõem conta fora de R1, aparelho conhecido, limite disponível, sem rajada e sem rejeição do módulo de laranjas.

| Histórico ou referência | Pix atual | Resultado |
| --- | --- | --- |
| Sem aprovação anterior | R$ 4.000 | R5 não atua |
| Média de R$ 50; referência de R$ 500 | R$ 5.000 | Não aciona R5: igualdade |
| Média de R$ 50; referência de R$ 500 | R$ 5.000,01 | 2FA por R5 |
| Média de R$ 600 | R$ 6.000 | Não aciona R5: igualdade |
| Média de R$ 600 | R$ 6.000,01 | 2FA por R5 |
| Aprovações de R$ 600 e R$ 1; média de R$ 300,50 | R$ 15.000 | 2FA por R5 |
| Média de R$ 2.000 | R$ 20.000,01 | Rejeição por R2 |

A R5 deixa de diferenciar valores dentro do teto quando a média é de R$ 2.000 ou mais; nesse caso, R2 prevalece antes do seu limiar. A média histórica pode ser distorcida por valores extremos e não acompanha necessariamente uma mudança recente de renda. Esses limites não foram resolvidos acrescentando novas regras sem dados que as sustentem.

**CNPJ com conta antiga: exceção preservada.** Um rateio de cinco amigos para pagar um restaurante pode produzir E3 e uma saída concentrada legítima. Remover a exceção de idade recusaria esse caso. Mantemos o comportamento atual e aceitamos o risco de uma conta apenas suspeita repassar para um CNPJ antigo sem acionar L3. Idade da conta não comprova legitimidade. L1 ainda pode bloquear destino com suspeita elevada, L2 ainda restringe pagador com suspeita elevada, e as regras base continuam valendo.

O gasto típico de até R$ 1.000 permanece limitado. Não prometemos liberar todo aluguel ou toda despesa essencial de um pagador marcado. Autenticação adicional confirma identidade, sem provar que um pagamento é voluntário ou que o recebedor é legítimo.

## Atualização e validação

Não há novas colunas nem novo motivo de análise: bancos que já usam v1.2 não precisam de outra migração. Para bancos anteriores à v1.2, continua necessária `database/migrations/001_account_average_reason.sql`, conforme o README. A revisão muda somente decisões de novos pedidos; análises antigas permanecem consultáveis com seus parâmetros e versão.

Os novos cenários foram escritos antes das correções. Os 17 casos aplicáveis à revisão tinham 13 falhas e quatro comportamentos já corretos; após a implementação, os 17 passaram. Eles verificam o piso de R5, o pagamento pequeno, igualdade do limiar, mesma conta versus mesmo titular, limites de datas, espera do aparelho e renovação/expiração do cache.

Para testar expiração sem esperar minutos, os cenários de cache inserem exclusivamente respostas externas fictícias com `fetched_at` controlado. Não fabricam aprovações financeiras: o histórico de Pix continua sendo produzido pela API. Cenários das outras regras usam uma aprovação inicial de valor compatível com R5 para evitar que a nova regra oculte o comportamento que estão verificando.

Resultado final: **271 testes aprovados em 41,13 s**, verificação de estilo aprovada e sete de sete decisões esperadas na demonstração. Os testes existentes de rateio e classificação de ato para CNPJ antigo continuam aprovados. A validação foi feita em serviços isolados, sem alterar os serviços usados pela outra implementação. Esses resultados verificam o código e suas regras, não uma taxa de detecção medida em clientes reais.

Também foram consultadas e reenviadas análises já gravadas em v1.1 e v1.2; ambas mantiveram a resposta original, incluindo versão e campos antigos do motivo.
