# Módulo de contas laranja — v1.1

17/10/2026. Revisão documental para o protótipo; não representa implementação, testes executados ou eficácia validada.

## Objetivo e relação com a v1

Integrar à API antifraude geral uma análise de possível uso de contas laranja. O motor combina informação de uma fonte simulada com o contexto que realmente conhece. Uma marcação não torna automaticamente fraudulenta toda operação envolvendo o titular.

Esta versão preserva o arquivo v1 como histórico e substitui sua especificação para a implementação do módulo. O [guia v1.1](guia-de-desenvolvimento-v1.1.md) define a integração. Os parâmetros continuam sendo escolhas do protótipo, sem calibração com dados reais.

Mudanças desta revisão:

- `confirmada` passa a `suspeita_elevada`; o nome descreve uma classificação de risco, não uma comprovação de fraude.
- A regra genérica de “quaisquer duas evidências” é substituída por uma lista explícita de combinações.
- Recebimentos e saídas são somente análises anteriores aprovadas, observadas pelo motor; não comprovam liquidação.
- `repasse_aparente` tem prioridade sobre `gasto_tipico` quando as duas definições coincidirem.
- A origem temporal das evidências e as limitações das exceções ficam explícitas.
- Os cenários e o modelo de integração são alinhados ao guia v1.1.

## 1. Dados disponíveis e fronteiras

O contexto recebe o payload validado, o histórico já conhecido pelo motor e a resposta do mock para os titulares do pagador e do destinatário. O mock não é uma base pública de CNPJs e não reproduz integralmente a API do DICT.

O recorte de apresentação pode usar CNPJ, mas o contrato recebido inclui CPF/CNPJ. Não transformar limite por conta em limite por documento. Para a fonte simulada, a marcação é por titular; para idade, recebimentos, saídas e reputação local, a avaliação é por conta.

Uma conta só tem uma entrada observada quando aparece como destinatária de uma análise anterior `approved`. Uma saída observada exige que apareça como pagadora de uma análise anterior `approved`. Rejeições e pedidos de 2FA não movimentam esses indicadores. O pedido atual entra apenas no total de saída projetado e uma única vez.

Não reconstruir saldo. Não supor recebimentos em outras instituições. Não inferir que não houve recebimento porque nada foi encontrado. Uma janela sem registros é uma janela sem observações; isso impede acionar a evidência dependente dessas entradas, mas não apaga outras evidências.

A identidade local usa participante, agência e conta. Como o payload não informa o participante de origem, vale a premissa de uma instituição de origem por instância, configurada no serviço. Uma conta externa que nunca aparece como pagadora não terá saídas ou aparelho conhecidos pelo motor.

As janelas usam `transaction_date`, com histórico já persistido e sem eventos posteriores à solicitação. A proposta de borda é `(t − janela, t]`, sujeita às convenções técnicas do guia. Não usar informações futuras para reproduzir uma análise passada.

## 2. Contrato simplificado do mock

Consultar um titular retorna informações normalizadas para esta demonstração. São campos próprios do protótipo, não nomes ou garantias da API real do DICT.

```json
{
  "document": "DOCUMENTO_FICTICIO_DO_CENARIO",
  "as_of": "2026-10-17T12:00:00Z",
  "mule_or_scammer_marker": {
    "active": true,
    "started_at": "2026-10-16T12:00:00Z"
  },
  "distinct_fraud_reporters_90d": 1,
  "second_reporter_at": null,
  "open_reports": 0,
  "second_open_report_at": null
}
```

- `started_at` é o início da marcação informada, não o início conhecido da fraude.
- `second_reporter_at` é quando o conjunto de relatos ainda válido atingiu duas instituições distintas; é obrigatório quando esse caminho sustenta E1.
- `second_open_report_at` é quando o conjunto de notificações ainda abertas atingiu duas; é obrigatório quando sustenta E4.
- Datas precisam ser coerentes com `as_of`. Os fixtures devem representar o conhecimento disponível no instante do cenário, inclusive alterações e expiração das evidências.
- Uma resposta malformada, timeout ou erro deixa a fonte indisponível; não inventar datas a partir do momento da consulta.
- Cache válido pode ser utilizado. Sem cache válido nem resposta utilizável, E1 e E4 ficam desconhecidas. Outras regras continuam sendo avaliadas. Uma eventual aprovação vem dessas regras, não de uma equivalência entre erro e ausência de marcação.

O snapshot usado na análise, sua data e a condição `consultado`, `cache` ou `indisponivel` ficam na auditoria interna. A consulta não altera a fonte e não publica automaticamente nossas suspeitas no mock.

## 3. Evidências

| Código | Definição operacional | Fonte e limite |
|---|---|---|
| E1 | Marcação ativa de laranja/golpista iniciada nos últimos 90 dias, ou relatos de pelo menos duas instituições distintas nos últimos 90 dias | Mock do titular. O corte de 90 dias é uma simplificação do protótipo, não uma regra de cancelamento de restrições reais |
| E2 | Mais de 50% das entradas aprovadas observadas em 30 dias vieram de contas cujo titular tem E1, ou há aparelho compartilhado com uma conta cujo titular tem E1 | Histórico local. Aplicável somente se a conta tiver menos de 90 dias ou menos de 10 contrapartes distintas observadas em 30 dias |
| E3 | Pelo menos 5 titulares distintos enviaram à conta em 1 hora, sendo pelo menos 3 sem aprovação anterior para essa conta; para conta de CNPJ, exigir 30 titulares distintos e pelo menos 3 estreantes | Histórico local aprovado. “3 estreantes” não significa maioria quando o total é maior |
| E4 | Pelo menos duas notificações de infração ainda abertas contra o titular | Mock. Notificação aberta não é confirmação de fraude |
| E5 | Conta com menos de 7 dias, mais de R$ 5.000 em entradas aprovadas observadas em 24 horas e pelo menos 3 titulares pagadores distintos | Histórico local aprovado |

Em E2, a proporção só existe com entradas observadas positivas. O ramo de aparelho não exige proporção de valores, mas exige a mesma condição de idade/reputação. O vínculo de aparelho só pode vir de aprovações anteriores de contas pagadoras com o mesmo `device_id`, nos últimos 30 dias. Não atribuir o aparelho do pagador ao destinatário.

Somente E1 pode originar E2: uma conta com E2 não contamina outra apenas por ter E2. A presença de E1 em uma contraparte precisa estar sustentada por snapshot válido do mock; sem essa informação, o vínculo não é evidência positiva. Consultas adicionais das contrapartes candidatas pertencem à camada de contexto, nunca às funções de regra.

Cada evidência registra `present` (verdadeiro, falso ou desconhecido), fonte, valores observados e `started_at`. Para evidência local, `started_at` representa quando a condição passou a ser satisfeita no histórico observado, não a data de criação da conta nem o instante da consulta. Se esse início não puder ser determinado, registrar desconhecido e não inventar uma data.

## 4. Classificação da conta

Aplicar a seguinte tabela na ordem:

| Condição | Estado |
|---|---|
| E1 presente | `suspeita_elevada` |
| E2 e E4 presentes | `suspeita_elevada` |
| Uma ou mais evidências presentes, sem condição acima | `suspeita` |
| Nenhuma evidência presente | `nao` |

`nao` significa ausência de indícios positivos disponíveis, não uma garantia de conta limpa. Evidências desconhecidas ficam registradas como desconhecidas e não satisfazem condições positivas.

**Por que E2 + E4:** combina um vínculo local com conta marcada e notificações externas ainda abertas. É uma escolha explícita, não uma alegação de independência estatística; as fontes ainda podem refletir os mesmos fatos. Esse risco residual precisa ser demonstrado e reconhecido.

**Por que E3 + E5 não eleva o estado:** os dois sinais podem vir de uma única arrecadação legítima. E2 + E3, E2 + E5, E3 + E4 e E4 + E5 também não elevam automaticamente o estado nesta versão. Mesmo três evidências sem E1 ou E2 + E4 permanecem `suspeita`. Contagem de sinais não substitui a combinação definida.

O estado é calculado em cada análise. A expiração ou retirada de evidências pode reduzi-lo. Persistir o snapshot da decisão permite consultar o resultado antigo sem recalcular o passado.

## 5. Tipo de ato: precedência explícita

Classificar o ato nesta ordem:

1. **`repasse_aparente`:** entradas aprovadas observadas na última hora de pelo menos R$ 1.000; saídas aprovadas na mesma hora mais o pedido atual equivalem a pelo menos 50% dessas entradas; destino é pessoa física ou conta de CNPJ com menos de 90 dias.
2. **`gasto_tipico`:** se não for repasse aparente, valor individual de até R$ 1.000 e destinatário conhecido ou conta destinatária de CNPJ com pelo menos 90 dias.
3. **`outro`:** demais situações.

Destinatário conhecido significa aprovação anterior da mesma conta pagadora para o mesmo titular destinatário. É uma familiaridade observada, não validação do propósito do pagamento.

**Exemplo de sobreposição:** uma conta recebeu R$ 1.000 observados e envia R$ 600 para uma pessoa conhecida. O ato é `repasse_aparente`, pois esta condição é avaliada primeiro. Um pagamento pequeno e familiar não apaga esse padrão.

**Custo aceito:** um repasse legítimo também pode ser recusado. A preferência foi dar prioridade ao padrão observado de entrada/saída, evitando que o resultado dependesse da ordem acidental do código. O nome não comprova que o dinheiro saiu das mesmas entradas, pois o motor não tem saldo nem liquidação.

Um rateio pago a uma conta antiga de CNPJ não satisfaz essa definição de repasse. Uma empresa de fachada antiga também pode escapar dela. Idade e personalidade jurídica são critérios simplificados da política, não prova de legitimidade.

## 6. Relação anterior com destinatário marcado

Mantém-se a exceção da proposta v1: há relação anterior quando existe aprovação da mesma conta pagadora para o titular destinatário com data anterior ao início mais antigo das evidências positivas que sustentam seu estado atual.

Se E1 sustenta a elevação, usar seu início informado. Se E2 + E4 sustenta a elevação, usar o início mais antigo entre essas duas evidências. Se ambos os caminhos estiverem presentes, considerar todas as evidências que os sustentam. Se faltar alguma dessas datas, não é possível estabelecer a exceção de relação anterior.

**Limitação essencial:** identificação tardia não revela quando a fraude começou; o relacionamento anterior pode já fazer parte do esquema. Esta exceção preserva a política v1 e aceita esse risco. Não apresentar a exceção como identificação de pagamento legítimo. O mesmo vale para chamar um ato de gasto típico.

## 7. Regras de decisão

| Regra | Condição | Resultado e código |
|---|---|---|
| L1 | Destinatário `suspeita_elevada` e sem relação anterior estabelecida | `rejected`, `MULE_DESTINATION` |
| L2 | Pagador `suspeita_elevada` e ato diferente de `gasto_tipico` | `rejected`, `MULE_PAYER` |
| L3 | Pagador `suspeita` e ato `repasse_aparente` | `rejected`, `SUSPECTED_MULE_FORWARDING` |
| Nenhuma | Nenhuma condição L1–L3 aplicável | Devolver controle às regras gerais; o módulo não aprova sozinho |

Mantém-se L2 também para `outro`, como na matriz v1. Isso é mais restritivo que bloquear somente repasses. Um pagamento legítimo de R$ 1.500 sem entradas recentes pode ser recusado se o pagador estiver em suspeita elevada. O custo fica explícito, não escondido na frase da apresentação.

Ordem completa: **R1, R2, L1, L2, L3, R4, R3**. Só o motivo determinante vai para a resposta. O módulo não pede 2FA para resolver a suspeita de laranja: autenticação adicional não elimina o risco de atuação do próprio operador.

## 8. Cenários de aceite v1.1

Salvo indicação, usar conta pagadora com mais de 7 dias, abaixo do teto geral, sem frequência elevada, destinatário sem outro impedimento e aparelho adequado ao valor. Cenários com E3 devem explicitar se o titular é CPF ou CNPJ. Preparações precisam resultar em aprovações reais do motor, sem ignorar R1–R4.

| Caso | Situação | Resultado esperado |
|---|---|---|
| P01 | Destino com E1; aprovação do pagador para seu titular anterior ao início informado da marcação | Seguir regras gerais; risco da exceção documentado |
| P02 | Mesmo destino, sem relação anterior | Rejeitar L1 |
| P03 | Pagador com E1 paga R$ 180 à conta antiga de CNPJ de concessionária, sem repasse aparente | Gasto típico; seguir regras gerais |
| P04 | Pagador com E1, R$ 5.000 de entradas observadas na hora, tenta enviar R$ 4.000 a pessoa física | Rejeitar L2 |
| P05 | Pagador com E1 envia R$ 1.500 a pessoa nova, sem entradas observadas recentes | Outro; rejeitar L2 |
| P06 | Pagador PF com E3 somente: 6 titulares em 1h, 4 estreantes, entradas de R$ 2.000; tenta repassar R$ 1.600 a pessoa física | Suspeita; rejeitar L3 |
| P07 | Contexto de P06, mas pagamento de R$ 90 a conta antiga de CNPJ de mercado | Gasto típico; seguir regras gerais |
| P08 | Rateio em conta PF antiga, E3 somente, R$ 1.200 ao restaurante com conta CNPJ antiga | Outro; seguir regras gerais |
| P09 | Padaria com conta de 10 anos, 400 contrapartes observadas, recebeu R$ 50 de marcada, 0,06% das entradas de 30 dias; sem outras evidências | Sem E2; seguir regras gerais |
| P10 | Sem cache válido, mock indisponível e nenhuma evidência local positiva | `nao`, com evidências externas desconhecidas; seguir regras gerais e registrar indisponibilidade |
| P11 | Oito dias após P06, sem novas entradas ou evidências, faz pagamento de R$ 1.500 para pessoa física | Sem E3 e sem repasse aparente; seguir regras gerais |
| P12 | Conta PF de 3 dias recebeu R$ 6.000 de 4 titulares; paga R$ 60 a conta antiga de CNPJ de telefonia | E5 somente, suspeita; gasto típico; aprovação se dentro do teto R1 |
| P13 | Contexto de P12; solicita saída de R$ 5.000 | Rejeitar R1, sem atribuir motivo L3 |
| P14 | Conta PF nova recebe R$ 6.000 de 5 titulares em 1h, ao menos 3 estreantes, sem outras evidências | E3 + E5 permanece suspeita; estado não eleva por contagem |
| P15 | Conta com E2 e E4, sem E1; tenta saída de R$ 1.500 para pessoa nova | Suspeita elevada; rejeitar L2 |
| P16 | Conta suspeita com R$ 1.000 de entradas observadas na hora envia R$ 600 para pessoa conhecida | Repasse aparente prevalece; rejeitar L3 |
| P17 | Conta PF suspeita por E3, mas entradas observadas na hora de apenas R$ 600, sem outras entradas; envia R$ 400 para pessoa nova | Não satisfaz mínimo do repasse; outro; seguir regras gerais |
| P18 | Destino com suspeita elevada, mas início de evidência local desconhecido | Não estabelecer relação anterior; rejeitar L1, registrando a limitação |
| P19 | Conta CNPJ recebeu de 5 titulares em 1h, sem E1/E2/E4/E5 | Não há E3: limiar de CNPJ é 30 |
| P20 | Pagamento para conta sem marcação, único vínculo sendo envio anterior para conta marcada | Não propagar E2 contra quem enviou; seguir regras gerais |

P14 testa a classificação, não implica que toda saída dessa conta passe: R1 e L3 ainda podem atuar. A redução de falsos positivos é específica à elevação indevida de estado, não uma promessa de liberar qualquer arrecadação.

Adicionar bordas: proporção E2 de 50% e acima; repasse em 49% e 50%; entradas de R$ 999,99 e R$ 1.000; gastos de R$ 1.000 e R$ 1.000,01; conta CNPJ de 89 e 90 dias; E4 com uma e duas notificações; expiração das janelas e mudança de marcação no mock.

## 9. Persistência, testes e demonstração

Usar o modelo do guia v1.1: `payer_account`, `pix_analysis`, `account_link` e `dict_lookup`. Não criar `account`, `pix_transaction` ou `rule_evaluation` adicionais com base no SQL histórico da v1.

`pix_analysis.analysis_details` guarda estados, evidências, datas, tipo de ato, relação e snapshots utilizados. O GET mantém o envelope original e não recalcula nada. O detalhe interno não vira lista pública de sinais nem expõe os documentos de contrapartes marcadas.

Testes HTTP verificam decisões, motivos, reenvios e persistência. Testes das funções puras verificam também estados, evidências e precedência do ato: apenas conferir `approved` em P12 não detecta uma classificação incorreta. As tabelas acima são especificação, não resultados de execução.

Para a demo, mostrar uma conta antiga com padrões que R1–R4 deixariam passar e uma decisão L2 ou L3 que acrescenta proteção. Mostrar em contraste um gasto típico permitido e P14, que não eleva a classificação por duas evidências sobrepostas. A fonte e os titulares são fictícios. Só chamar de reconstrução de caso real se houver uma fonte identificada e uma explicação das simplificações.

Se a marcação surgir depois dos recebimentos, o mock deve mudar de estado ao longo do cenário. Não iniciar a simulação com uma conta já impedida de realizar as operações necessárias para montar seu histórico.
