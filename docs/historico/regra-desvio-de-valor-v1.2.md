# Desvio de valor e teto geral — pix-v1.2

Esta revisão, publicada na branch `v3`, acrescenta R5 e muda R2 para R$ 20.000 em 24 horas. Os documentos v1 e v1.1 ficam preservados; para estes dois pontos, vale esta revisão. O contrato de entrada e os três status do desafio permanecem os mesmos.

## Regra e justificativa

| Regra | Lógica | Parâmetros | Por quê |
| --- | --- | --- | --- |
| R2 | Rejeitar quando os valores aprovados em 24h, mais o atual, ultrapassarem o teto | R$ 20.000; igualdade permitida | Manter um teto fixo de exposição e abrir espaço para R5 atuar antes dele |
| R5 | Solicitar `two_factor_required` quando a média superar o piso e o Pix superar dez vezes a média | Média > R$ 500; Pix > 10 × média | Detectar desvio de valor individual mesmo em aparelho conhecido; confirmar em vez de rejeitar só por desvio |

O mínimo de R$ 500 é aplicado à **média**, não ao valor da transação atual. As duas comparações são estritas. Uma média de R$ 500 não aciona R5, por maior que seja o Pix. As outras regras continuam atuando.

## Definição da média

- Unidade: conta pagadora, sem somar contas de um mesmo CPF/CNPJ.
- Base: todos os Pix enviados pela conta com análise `approved` já registrada e `transaction_date` menor ou igual à data do pedido atual.
- Cálculo: soma dos valores dividida pela quantidade dessas aprovações; não é média de volume por dia nem média em 24 horas.
- Exclusões: Pix atual, recebimentos, rejeições, solicitações de 2FA, entradas inválidas e reenvios do mesmo ID.
- Sem nenhuma aprovação anterior, a regra não atua. Não foi acrescentado outro mínimo de amostra.
- Uma aprovação anterior com data igual à do pedido atual conta, seguindo a convenção temporal existente.

Só conhecemos o histórico observado pelo motor, não todas as operações bancárias desde a abertura nem sua liquidação. Dados de outros bancos ou anteriores à integração não são presumidos.

Para manter exatidão em centavos, com `S` igual à soma e `N` igual à quantidade, avaliamos:

```text
N > 0
S > 50000 × N
amount × N > 10 × S
```

Isso equivale às duas comparações com `S / N`, sem arredondar médias com frações de centavo nem usar ponto flutuante para decidir. Soma e quantidade são consultadas juntas, depois da trava da conta pagadora. Não criamos uma tabela de agregados nem atualizamos médias armazenadas.

## Ordem e explicação

**R1 → R2 → L1 → L2 → L3 → R4 → R3 → R5 → aprovação.**

Rejeições continuam prevalecendo sobre 2FA. Os pedidos existentes de 2FA mantêm prioridade para preservar o motivo determinante. R5 tem efeito próprio em aparelho conhecido e fora da rajada de R3.

Quando R5 decide, o motivo é `AMOUNT_ABOVE_ACCOUNT_AVERAGE`. Além da descrição e do valor atual (`observed_amount`), o motivo informa:

| Campo | Significado |
| --- | --- |
| `historical_total_amount` | Soma aprovada em centavos |
| `historical_transaction_count` | Quantidade de aprovações usadas |
| `average_multiplier` | Multiplicador 10 |
| `minimum_average_amount` | Piso da média, 50000 centavos |

Soma e quantidade representam a média exata, inclusive quando fracionária. A versão é `pix-v1.2`. GET e reenvios equivalentes preservam a versão e a decisão originais. R5 não aprova, não consome o teto e não cria vínculos; a confirmação do 2FA continua fora desta API.

## Exemplos e limites

Pressupõem conta com pelo menos 7 dias, aparelho conhecido, limite disponível, sem rajada e sem rejeição pelo módulo de laranjas.

| Média histórica | Pix | Resultado |
| --- | --- | --- |
| Sem aprovações | R$ 4.000 | R5 não atua |
| R$ 500 | R$ 9.000 | R5 não atua: média igual ao piso |
| R$ 600 | R$ 6.000 | R5 não atua: valor igual a dez vezes a média |
| R$ 600 | R$ 6.000,01 | 2FA por R5 |
| R$ 1.500 | R$ 15.000,01 | 2FA por R5 |
| R$ 1.000 | R$ 20.000,01 | Rejeição por R2 |

O aumento de R2 de R$ 10.000 para R$ 20.000 permite aprovar mais volume e aumenta a exposição máxima aceita. Para médias de R$ 2.000 ou mais, qualquer Pix que exceda dez vezes a média já ultrapassa o teto: R2 prevalece. A regra continua útil para médias entre R$ 500 e R$ 2.000.

A favor de R5: decisão simples, explicável e específica da conta. Contra: uma única aprovação já pode definir a média; valores extremos ou muitos pagamentos pequenos podem distorcê-la; pagamentos legítimos excepcionais podem pedir 2FA. Médias de até R$ 500 ficam sem esta proteção por decisão explícita. Esses parâmetros não foram calibrados em dados reais.

A antiga proposta de teto diário de cinco vezes a média continua retirada. R5 é outra decisão: comparação do valor individual com dez vezes a média, com saída de 2FA e um teto diário separado.

## Atualização e validação

Em bancos existentes, aplicar `database/migrations/001_account_average_reason.sql` conforme o README. A migração altera apenas os motivos permitidos, sem apagar histórico. Bancos novos já usam o schema atualizado. A aplicação passa a avaliar somente os novos pedidos com a versão v1.2.

O teste de referência anterior passou em 229 cenários. Antes da implementação, os 25 novos cenários tiveram 10 falhas esperadas e 15 resultados já corretos. Os testes cobrem pisos e multiplicadores exatos, média fracionária, ausência de histórico, exclusão do Pix atual e de resultados não aprovados, separação por conta, recebimentos, reenvios, persistência e prioridade das regras. Os cenários antigos do teto foram ajustados para R$ 20.000, inclusive o teste concorrente.

Após a implementação, os 25 novos cenários passaram, e a suíte completa passou em **254 testes, em 39,04 s**. Flake8 passou no container. A demo de laranjas manteve as sete decisões esperadas. A migração foi reaplicada duas vezes no banco isolado, preservando as 1.183 análises existentes; GET e reenvio de uma análise v1.1 mantiveram a resposta original. Esses resultados verificam o comportamento implementado, não a eficácia antifraude em clientes reais.
