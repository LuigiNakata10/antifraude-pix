# Política antifraude Pix — decisões de negócio

Status: política inicial acordada em discussão, sem implementação nem calibração com dados reais. As pendências estão explícitas na seção 9. Esta revisão substitui as hipóteses do primeiro rascunho; não define a arquitetura final.

## 1. Objetivo, escopo e premissas

Receber uma solicitação de Pix, avaliar seu risco e devolver `approved`, `two_factor_required` ou `rejected`, com uma explicação verificável.

Referências de escopo: PDFs `Hackathon Antifraude Pix.pdf` e `Desafio Antifraude Pix.pdf`, fornecidos pelo usuário. Entregas: POST `/pix/transaction`, GET `/pix/transaction/{id}`, histórico próprio, regras, testes, README e apresentação. O ZIP da biblioteca é referência geral de estrutura; não determina a solução nem impõe o reaproveitamento de componentes.

Premissas acordadas:

- O sistema chamador já realizou a autenticação básica. Nosso motor pode solicitar autenticação adicional; não executa o Pix nem o 2FA.
- O contrato não informa saldo, limite bancário real, liquidação, fraude confirmada ou conclusão do 2FA.
- O histórico representa solicitações e análises, não transferências comprovadamente realizadas.
- A primeira transação observada não sofre intervenção somente por ausência de histórico. Valor elevado ou frequência podem justificar 2FA.
- Preferir poucas regras determinísticas, combinações explícitas e justificativas claras. Não usar pontuação geral ou probabilidade de fraude nesta versão.
- Controlar fricção é parte do objetivo: tanto uma fraude permitida quanto uma intervenção indevida têm custo.
- Conta antiga não significa conta conhecida pelo motor. Idade da conta vem de `opening_date`; familiaridade depende de análises anteriores.
- Segundo esclarecimento do usuário, tempo real de execução não será critério de avaliação. Manter a solução simples, sem meta numérica de latência ou otimização antecipada. Isso é diferente das janelas temporais usadas pelas regras.
- Os valores e intervalos são escolhas do protótipo. Não são apresentados como padrão universal dos bancos ou como limiares validados para produção.

## 2. Definições comuns

### Unidade de avaliação

As regras se aplicam por conta pagadora, não pela soma das contas de um CPF/CNPJ. Outras contas do titular não consomem esse limite.

O `id` é o identificador da solicitação. Reenvios equivalentes com o mesmo ID não contam novamente nem produzem uma nova decisão. A definição exata de equivalência e do tratamento de conflito ainda será documentada.

Valores são inteiros em centavos. Nas tabelas abaixo, reais são usados somente para facilitar a leitura.

### Conta nova

Conta pagadora com menos de sete dias completos entre abertura e `transaction_date`. Ao completar exatamente sete dias, deixa de ser nova para esta política. Não haverá faixas progressivas de limite nesta versão.

### Acumulado de 24 horas

Soma dos valores de solicitações anteriores da mesma conta com análise `approved`, na janela móvel de 24 horas anterior à data da transação em análise, mais o valor do Pix atual para testar a regra.

`rejected` e `two_factor_required` não consomem esse limite. O Pix atual só entra no histórico aprovado se a decisão final for `approved`.

Só podem ser usados resultados já conhecidos pelo motor no momento da decisão. Não antecipar informações que chegaram posteriormente.

### Dispositivo conhecido

Existe análise anterior `approved` da mesma conta pagadora para o mesmo `device_id`, e já se passaram pelo menos 24 horas desde a primeira dessas aprovações, usando a data da transação como referência. O prazo é uma espera inicial: aprovações posteriores não reiniciam a contagem. A referência temporal segue a convenção acordada para o negócio; o tratamento de datas inconsistentes e de eventos atrasados continua pendente.

Sem aprovação anterior ou antes de completar essa espera, o aparelho é tratado como novo para R4. Apenas aparecer em tentativa rejeitada ou com pedido de 2FA não inicia o prazo.

Isso representa familiaridade observada, não comprova autorização do aparelho no banco ou legitimidade.

### Destinatário conhecido

Existe análise anterior `approved` da mesma conta pagadora para o CPF/CNPJ do destinatário. A comparação é pelo titular, não apenas pela conta destinatária.

Essa definição foi discutida, mas a familiaridade do destinatário não altera as quatro regras atuais. Não é necessário calcular esse indicador no MVP se não houver uso na decisão.

## 3. Regras acordadas

| Código | Condição | Resultado |
|---|---|---|
| R1 — Conta pagadora nova | Conta com menos de 7 dias e acumulado aprovado de 24 horas, incluindo o pedido atual, acima de R$ 1.000 | `rejected` |
| R2 — Teto geral | Acumulado aprovado de 24 horas da conta, incluindo o pedido atual, acima de R$ 10.000 | `rejected` |
| R3 — Frequência | Pedido atual é pelo menos a terceira tentativa distinta da conta em uma janela móvel de 2 minutos, para quaisquer destinatários | `two_factor_required` |
| R4 — Dispositivo novo e valor elevado | Dispositivo sem aprovação anterior na conta, ou com menos de 24h desde a primeira aprovação, e valor individual do Pix de R$ 5.000 ou mais | `two_factor_required` |

Na ausência de condições de rejeição ou 2FA, o resultado é `approved`.

### R1 — Conta pagadora nova

- Teto de R$ 1.000 para a soma aprovada nas últimas 24 horas, por conta.
- Exatamente R$ 1.000 é permitido por esta regra; ultrapassar esse valor gera rejeição.
- Uma transação individual superior a R$ 1.000 também é rejeitada, mesmo com acumulado anterior zero. Não é necessária outra regra para o teto individual.
- Idade da conta e janela de 24 horas usam a data da transação como referência.
- A restrição termina aos sete dias completos; as demais regras continuam valendo.

**Por que:** limitar a exposição inicial e impedir que dividir um pagamento em várias partes contorne o teto.

**Custo e limitação:** contas novas legítimas também ficam restritas. Sete dias e R$ 1.000 são parâmetros do protótipo, não evidência de fraude. Uma conta antiga pode ser fraudulenta.

### R2 — Teto geral

- Teto fixo e configurável de R$ 10.000 em uma janela móvel de 24 horas.
- Conta exatamente no teto passa por esta regra. O que exceder é rejeitado, sem substituir rejeição por 2FA.
- Para contas novas, prevalece o teto mais restritivo de R$ 1.000.

**Por que:** estabelecer uma exposição máxima simples, previsível e resistente à fragmentação do valor dentro da janela.

**Custo e limitação:** pode impedir compras ou pagamentos legítimos superiores ao teto. Estar abaixo dele não comprova segurança. Não reproduz limites bancários reais personalizados, ausentes do contrato.

### R3 — Frequência

- A partir do terceiro pedido distinto na janela de dois minutos, solicitar 2FA, salvo se houver motivo de rejeição.
- Contar solicitações válidas anteriores com qualquer um dos três resultados e incluir o pedido atual uma única vez.
- O destinatário pode ser o mesmo ou diferente.
- O valor pode ser baixo: o usuário aceitou a fricção para sequências concentradas.
- Não há dispensa automática por sequências habituais em dois dias anteriores. Essa hipótese foi retirada ao simplificar a política.

**Por que:** identificar uma rajada de solicitações e acrescentar confirmação de identidade sem rejeitar só por quantidade. Incluir recusas permite perceber insistência; reenvios do mesmo ID não são novas tentativas.

**Custo e limitação:** pagamentos legítimos em lote podem exigir 2FA. Tentativas recusadas também prolongam o gatilho. Uma janela de dois minutos deixa passar sequências mais lentas. Não afirmar que três Pix em dois minutos comprovam fraude ou que essa é uma regra divulgada pelos bancos.

**Referência temporal acordada:** usar `transaction_date` também na janela de dois minutos, mantendo uma referência única com as demais regras temporais e permitindo reprodução de cenários históricos. O sistema chamador é a fonte dessa data; eventos atrasados e datas inconsistentes ainda precisam de tratamento explícito.

### R4 — Dispositivo novo e valor elevado

- Valor individual de R$ 5.000 ou mais em aparelho que ainda não seja conhecido pela definição da seção 2: solicitar 2FA.
- Destinatário novo não é requisito. A hipótese anterior de exigir os três fatores foi substituída.
- Dispositivo novo com valor abaixo de R$ 5.000 não aciona esta regra.
- Uma primeira solicitação com decisão final `approved` inicia a espera de 24 horas para aquele dispositivo na mesma conta. Durante a espera, pedidos de R$ 5.000 ou mais continuam sujeitos a 2FA, sem rejeição apenas por esse motivo.
- Ao completar 24 horas desde a primeira aprovação, o aparelho passa a ser conhecido e R4 deixa de intervir. Novas aprovações não reiniciam o prazo. Limites e frequência continuam valendo.
- Uma conta antiga sem nenhuma aprovação anterior solicita 2FA para um primeiro Pix de R$ 5.000 ou mais, pois não há dispositivo conhecido.
- Para uma conta nova, o teto de R$ 1.000 impede alcançar essa faixa; prevalece a rejeição.

**Por que:** concentrar confirmação adicional na combinação de falta de familiaridade do acesso e exposição financeira relevante, preservando pagamentos menores após troca de aparelho. A espera inicial evita que uma aprovação pequena dispense imediatamente o 2FA em um pedido elevado. Usar a primeira aprovação, em vez da última, evita prolongar indefinidamente a espera para quem usa a conta diariamente.

**Custo e limitação:** a espera acrescenta fricção por 24 horas após uma troca legítima de aparelho. Uma aprovação pequena ainda pode criar familiaridade para uma operação elevada depois desse prazo; o tempo decorrido não comprova segurança. Dispositivo conhecido pode estar comprometido. 2FA não comprova que o pagamento é voluntário nem impede necessariamente golpe ou coação. A política aceita essas limitações nesta versão.

## 4. Composição da decisão

Entrada que não pode ser processada gera erro de entrada, não uma decisão de fraude. Pedidos inválidos não consomem os limites, não contam para frequência e não criam familiaridade do dispositivo ou destinatário.

Aplicar a seguinte ordem para determinar o status e um único motivo:

1. Se R1 for acionada, retornar `rejected`, com motivo de teto de conta nova.
2. Caso contrário, se R2 for acionada, retornar `rejected`, com motivo de teto geral.
3. Caso contrário, se R4 for acionada, retornar `two_factor_required`, com motivo de dispositivo novo e valor elevado.
4. Caso contrário, se R3 for acionada, retornar `two_factor_required`, com motivo de frequência elevada.
5. Caso contrário, retornar `approved`, explicando que nenhuma condição de intervenção da política foi acionada.

R1 tem precedência sobre R2 por ser a restrição específica da conta nova. Rejeições prevalecem sobre 2FA. Entre R4 e R3, a precedência é uma convenção explícita de explicação, não uma alegação de maior capacidade de detectar fraude. Os códigos R1–R4 identificam regras, não sua posição na ordem de avaliação.

Informar somente o motivo determinante, com seus valores observados e parâmetros aplicáveis; não listar os demais fatores simultâneos no resultado da análise.

Uma aprovação significa apenas que nenhuma intervenção da política foi exigida. Uma rejeição por teto significa descumprimento do limite, não fraude confirmada.

As análises nos três status devem ser persistidas. O GET recupera o resultado original; não o recalcula com o histórico ou a política atuais.

## 5. Matriz de cenários

Todos os casos abaixo pressupõem entrada válida e ausência de condições não mencionadas. “Primeiro/segundo/terceiro” refere-se à contagem de solicitações na janela curta. Os cenários não são resultados de testes executados.

| Caso | Situação | Resultado esperado | Motivo |
|---|---|---|---|
| C01 | Conta de 3 dias; nenhum aprovado em 24h; Pix de R$ 500; primeira tentativa | `approved` | Abaixo do teto inicial e sem outro gatilho |
| C02 | Conta de 3 dias; R$ 700 aprovados em 24h; Pix de R$ 300; sem rajada | `approved` | Exatamente R$ 1.000 |
| C03 | Mesmo caso, Pix de R$ 301 | `rejected` | R1: total de R$ 1.001 |
| C04 | Conta com exatamente 7 dias; sem acumulado; Pix de R$ 1.500; dispositivo conhecido; sem rajada | `approved` | R1 não se aplica e R2 não foi excedida |
| C05 | Conta antiga; dispositivo conhecido; R$ 7.000 aprovados em 24h; Pix de R$ 3.000; sem rajada | `approved` | Exatamente R$ 10.000 |
| C06 | Mesmo caso, Pix de R$ 3.001 | `rejected` | R2: total de R$ 10.001 |
| C07 | Conta antiga; aparelho conhecido; pedidos aprovados de R$ 200 e R$ 150, seguidos por R$ 300, todos em 80 segundos | `two_factor_required` | R3: terceira tentativa; baixo valor não dispensa |
| C08 | Conta antiga; uma tentativa aprovada e outra rejeitada dentro da janela; chega uma terceira de baixo valor, dentro do teto | `two_factor_required` | R3 inclui tentativas rejeitadas |
| C09 | Reenvio equivalente do mesmo ID já analisado | Mesma análise original | Sem nova contribuição nos indicadores |
| C10 | Conta antiga; nenhum aprovado anterior; primeiro Pix de R$ 6.000 | `two_factor_required` | R4: valor elevado e dispositivo sem aprovação anterior |
| C11 | Conta antiga; nenhum aprovado anterior; primeiro Pix de R$ 500 | `approved` | Ausência de histórico, isoladamente, não intervém |
| C12 | Conta antiga; dispositivo novo; Pix de R$ 4.999; sem acumulado ou rajada | `approved` | Abaixo do limiar de R4 |
| C13 | Mesmo caso, Pix de R$ 5.000 para destinatário conhecido | `two_factor_required` | R4: destinatário conhecido não dispensa |
| C14 | Conta antiga; dispositivo conhecido; Pix de R$ 6.000 para destinatário novo | `approved` | Valor e novidade do destino, sem novidade do dispositivo, não acionam R4 |
| C15 | Mesmo caso, conta destinatária aberta há 2 dias | `approved` | Idade do destino não acrescenta intervenção |
| C16 | Conta de 3 dias; Pix de R$ 5.000; dispositivo novo | `rejected` | R1 prevalece sobre R4 |
| C17 | Conta antiga; terceira tentativa em 2 minutos e acumulado aprovado mais pedido atual acima de R$ 10.000 | `rejected` | R2 prevalece sobre R3 |
| C18 | Conta antiga; primeira solicitação de R$ 100 aprovada no aparelho; dez minutos depois, Pix de R$ 6.000 no mesmo aparelho, dentro do teto | `two_factor_required` | R4: ainda não passaram 24h desde a primeira aprovação |
| C19 | Conta antiga; primeira aprovação no aparelho há 26h; nova aprovação de R$ 50 há 1h; agora Pix de R$ 6.000, dentro do teto e sem rajada | `approved` | Espera inicial concluída; aprovação recente não reinicia o prazo |
| C20 | Conta de 3 dias; sem acumulado; Pix de R$ 11.000 | `rejected` | Somente motivo R1, embora R2 também fosse excedida |
| C21 | Conta antiga; dispositivo sem as 24h iniciais; terceiro pedido na janela curta, de R$ 5.000, dentro do teto | `two_factor_required` | Somente motivo R4, embora R3 também fosse acionada |

## 6. Casos de risco residual que precisamos apresentar honestamente

- Uma única solicitação fraudulenta abaixo dos tetos, no dispositivo conhecido, pode ser aprovada.
- Um pagamento sob ameaça pode ocorrer com autenticação válida e dispositivo habitual.
- Uma rajada espaçada além da janela curta pode não disparar R3.
- Uma operação pequena aprovada pode criar familiaridade do aparelho para um pagamento elevado após a espera inicial de 24 horas.
- Sem confirmação do 2FA ou rótulos posteriores, recorrência e aprovação não comprovam legitimidade.

Esses casos não autorizam inserir regras implícitas. Servem para avaliar o recorte e justificar evoluções somente quando o benefício compensar custo e fricção.

## 7. Escolhas retiradas ou adiadas

| Alternativa | Situação e justificativa |
|---|---|
| Limite de 5 vezes a média por transação | Retirado: mistura referência por pagamento com exposição diária e acrescenta definição de amostra e tratamento de extremos |
| Ajuste por saldo | Fora desta versão: saldo não é fornecido e não pode ser reconstruído das análises |
| Dispensa de frequência por hábito em 2 dias | Retirada: repetição não confirma segurança e cria critérios adicionais de confiança |
| Limites progressivos após 7 dias | Não adotados: novas faixas sem benefício demonstrado; usar R2 após encerrar R1 |
| Somar limites entre contas do mesmo CPF/CNPJ | Não adotado: limite é por conta pagadora |
| Rejeitar valor elevado para destinatário novo | Não adotado como combinação suficiente: também descreve pagamentos legítimos excepcionais |
| Exigir destinatário novo em R4 | Substituído: dispositivo novo e valor elevado bastam para solicitar 2FA |
| Intervir por idade da conta destinatária | Não adotado isoladamente ou apenas junto de valor alto: pouca sustentação para distinguir fraude |
| IA ou consultas externas | Não necessárias para as quatro regras; avaliar somente se houver problema concreto não resolvido |
| Meta de latência e arquitetura final | Não definidas nesta fase; foco atual em negócio e testes de coerência |
| Regra por deslocamento geográfico | Adiada: acrescenta distância, janela e interpretação de imprecisões sem benefício suficiente demonstrado para o recorte simples |

## 8. Evidências da análise

Proposta de explicação para o `metadata`, ainda sem schema final:

- Versão da política aplicada.
- Um único código e uma descrição do motivo determinante, seguindo a ordem R1, R2, R4, R3.
- Somente os valores observados e limiares necessários para explicar esse motivo. Exemplo: teto de conta nova, acumulado incluindo o Pix atual de R$ 1.200 e limite de R$ 1.000.

Para uma aprovação, a explicação indica que nenhuma condição de intervenção da política foi acionada. Não inventar evidência positiva nem incluir uma lista de outros sinais.

Não é necessário expor CPF/CNPJ completo, IP ou coordenadas para explicar essas quatro regras. Não apresentar índice manual como probabilidade de fraude.

## 9. Pendências antes da implementação

1. Definir as bordas exatas das janelas de dois minutos e de 24 horas. Ambas usam `transaction_date` como referência acordada. Os cenários apresentados evitam as bordas temporais ainda não decididas.
2. Definir eventos atrasados, datas futuras e datas anteriores à abertura. Não misturar data informada e relógio do serviço silenciosamente.
3. Definir identidade técnica da conta pagadora: o payload não fornece ISPB de origem. Não substituir o limite por conta por um limite por CPF/CNPJ.
4. Definir normalização e equivalência de reenvios, conflito de ID e tratamento de entrada inválida.
5. Explicitar que o contrato não traz conclusão de 2FA. Um retorno `two_factor_required` não cria aprovação nem familiaridade; pedidos seguintes podem continuar solicitando 2FA. Não simular confirmação automática ou criar rota adicional sem necessidade acordada.
6. Explicitar que a leitura histórica usa resultados já conhecidos no instante da decisão. Não usar histórico futuro para melhorar artificialmente a avaliação.
7. Garantir persistência e contagens coerentes em concorrência; a estratégia técnica será escolhida depois da política.
8. Transformar a matriz em testes e adicionar cenários de contraste. A matriz é uma especificação, não comprovação de que testes passaram.

Em um cenário real, os parâmetros e pressupostos precisariam ser revistos com dados representativos, avaliação de perdas e fricção, informações adicionais de autenticação/liquidação e requisitos aplicáveis. Essa evolução não integra automaticamente o escopo do protótipo.
