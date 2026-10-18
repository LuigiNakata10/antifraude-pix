# Política antifraude Pix — v2

**Integrantes:** Renan Correia e Luigi Nakata · **Política em vigor:** `pix-v1.3` · **Data:** 18/10/2026

Versão final e consolidada da política do motor. Reúne, num documento só, o que estava distribuído entre a política acordada (v1), o módulo de conta laranja (v1.1) e as revisões v1.2 e v1.3. Descreve o comportamento implementado e conferido pela suíte de testes. Os documentos anteriores ficam preservados em [`historico/`](historico/), e o [histórico de versões](#11-histórico-de-versões) no fim diz o que mudou em cada um.

Os valores são **parâmetros do protótipo**, sem calibração em dados reais, e não representam limites usados pelos bancos. Cada um tem o porquê ao lado, também no código, em [`src/rules/parameters.py`](../src/rules/parameters.py).

## 1. Objetivo e premissas

Receber uma solicitação de Pix, avaliar seu risco e devolver `approved`, `two_factor_required` ou `rejected`, sempre com **um único motivo** verificável.

- O sistema chamador já autenticou o cliente. O motor pode pedir autenticação adicional (2FA), mas não executa o Pix nem o 2FA.
- O contrato não traz saldo, limite bancário real, liquidação, fraude confirmada nem a conclusão do 2FA.
- O histórico representa **solicitações e decisões observadas pelo motor**, não transferências liquidadas.
- Poucas regras determinísticas, combinações explícitas e justificativas claras. Sem pontuação nem probabilidade de fraude.
- Controlar a fricção é parte do objetivo: deixar passar uma fraude e intervir num cliente legítimo têm custo.
- Informação ausente nunca é evidência. Falha técnica nunca vira decisão.

## 2. Definições comuns

| Termo | Definição |
| --- | --- |
| Unidade de avaliação | A **conta pagadora** (agência e conta). Outras contas do mesmo CPF/CNPJ não somam nos limites |
| Referência temporal | A `transaction_date` do pedido, para janelas, idade da conta e espera do aparelho |
| Janela | Intervalo `(t − janela, t]`: um Pix exatamente em `t − janela` não conta; um já gravado com data igual a `t` conta. O Pix atual entra uma única vez, na regra |
| Acumulado de 24 h | Soma dos Pix da conta com análise `approved` na janela de 24 h, mais o Pix atual |
| Conta nova | Menos de 7 dias completos entre a abertura e o Pix. Com exatamente 7 dias, deixa de ser nova |
| Aparelho conhecido | A conta tem aprovação anterior com esse `device_id` e já passaram 24 h desde a **primeira** delas. Aprovações seguintes não reiniciam a espera |
| Destinatário conhecido | O pagador tem aprovação anterior para o mesmo **titular** de destino (CPF/CNPJ) |
| Média aprovada | Soma dos Pix enviados e aprovados pela conta até `t`, dividida pela quantidade. Sem o Pix atual, recebimentos, rejeições, 2FA ou reenvios |
| "Recebido" e "enviado" | Só Pix `approved` que passaram pelo motor. Rejeição e 2FA não contam |

`two_factor_required` não aprova, não consome limite, não inicia a espera do aparelho e não cria vínculo no grafo. Entrada inválida (400) ou incoerente (422) também não conta em nada.

## 3. Regras base

| Regra | Lógica | Parâmetros | Por quê |
| --- | --- | --- | --- |
| **R1** conta nova | Conta nova e acumulado de 24 h acima do teto → `rejected` | 7 dias; R$ 1.000 (exatamente R$ 1.000 passa) | Limita a exposição inicial; por ser acumulado, impede contornar o teto fracionando |
| **R2** teto geral | Acumulado de 24 h acima do teto → `rejected` | R$ 20.000, janela móvel (exatamente R$ 20.000 passa) | Exposição máxima fixa, resistente à fragmentação, sem depender de renda ou saldo ausentes do contrato |
| **R3** frequência | A partir da 3ª solicitação distinta da conta em 2 minutos, qualquer valor e destino → `two_factor_required` | 3 solicitações; 2 minutos | Rajada levanta dúvida sobre quem opera a conta; 2FA resolve sem barrar o legítimo. Conta qualquer resultado, não conta reenvios |
| **R4** aparelho novo | Aparelho não conhecido e Pix individual de R$ 5.000 ou mais → `two_factor_required` | R$ 5.000; espera de 24 h | Falta de familiaridade somada a exposição relevante; uma aprovação pequena não libera um Pix alto na hora |
| **R5** desvio da média | Pix acima de 10 vezes a referência da conta → `two_factor_required` | Referência = maior entre a média aprovada e R$ 500; exige ao menos uma aprovação anterior; comparação estrita | Pega o Pix fora do padrão da conta mesmo no aparelho conhecido; o piso impede que um Pix de R$ 1 derrube a média e desligue a regra |

**Por que R1 e R2 rejeitam e não pedem 2FA.** Teto mede o tamanho do prejuízo, não a identidade. Na conta aberta para o golpe, no golpe com a vítima no controle e na conta laranja, quem confirma o 2FA é justamente quem não devia passar. Um teto que o 2FA derruba deixa de ser teto.

**Por que R3, R4 e R5 pedem 2FA e não rejeitam.** Frequência, aparelho novo e desvio da média são sinais isolados e ambíguos: um rateio, uma troca de celular, uma compra excepcional. Rejeitar trataria dúvida como certeza; o 2FA custa segundos ao dono e para o invasor sem o segundo fator.

**R5 em números.** Com soma `S` e quantidade `N`, sem arredondar a média:

```text
N > 0
referência_total = max(S, 50000 × N)
pede 2FA quando  amount × N > 10 × referência_total
```

| Histórico da conta | Pix atual | Resultado |
| --- | --- | --- |
| Sem aprovação anterior | R$ 4.000 | R5 não atua |
| Média de R$ 50 (referência R$ 500) | R$ 5.000 / R$ 5.000,01 | Não atua / 2FA |
| Média de R$ 600 | R$ 6.000 / R$ 6.000,01 | Não atua / 2FA |
| R$ 600 e R$ 1 (média R$ 300,50, referência R$ 500) | R$ 15.000 | 2FA |
| Média de R$ 2.000 | R$ 20.000,01 | Rejeição por R2, que vem antes |

Com médias de R$ 2.000 ou mais, qualquer Pix acima de 10 vezes a média já passa do teto de R2. R5 é útil para médias entre R$ 500 e R$ 2.000.

## 4. Módulo de conta laranja

**A tese.** Contra conta tomada, o 2FA ajuda: o invasor não tem o segundo fator. Contra **conta laranja**, não: quem confirma é o próprio operador da conta, seja o recrutado, seja quem comprou o acesso. Por isso o motor **primeiro classifica a conta** e **depois decide o ato**: a laranja paga a conta de luz, mas não repassa o dinheiro do golpe. O módulo nunca pede 2FA.

**A premissa.** Nem todo Pix que toca uma laranja é fraude. O recrutado paga as próprias contas, a vítima que paga a laranja não é cúmplice, e a mãe que manda mesada ao filho recrutado também não. Bloquear tudo que toca a conta trava inocentes e não recupera dinheiro.

**As fontes.** O DICT simulado traz sinais de outras instituições (E1, E4). O grafo local segue o dinheiro e o aparelho a partir das contas marcadas (E2) e enxerga padrões antes de qualquer marcação (E3, E5).

### 4.1 Evidências

| Evidência | Lógica | Parâmetros | Por quê |
| --- | --- | --- | --- |
| **E1** marcação no DICT | Conta laranja ou golpista marcada, ou titular marcado por instituições distintas | Janela `d90`; 1 marcação ou 2 instituições | Semente mais forte: outra instituição já confirmou |
| **E2** dinheiro ou aparelho de conta E1 | Mais de 50% do recebido em 30 dias veio de contas com E1 naquele Pix, **ou** a conta usou, com aprovação, um aparelho usado com aprovação por conta com E1 | 30 dias; só vale para conta com menos de 90 dias **ou** menos de 10 contrapartes distintas em 30 dias | Segue o dinheiro a partir das sementes, com travas de boa-fé. Só E1 propaga, por um salto |
| **E3** muitos titulares novos | Titulares distintos enviando à conta na última hora, com estreantes (sem aprovação anterior para a conta) | PF: 5 titulares e 3 estreantes; CNPJ: 30 titulares e 3 estreantes; 1 hora | Formato de conta de passagem; empresa recebe de muita gente por natureza |
| **E4** notificações abertas | Notificações de infração abertas no DICT | 2 ou mais | Uma pode ser disputa; duas já são padrão, e pesam combinadas com E2 |
| **E5** conta nova com volume | Conta com menos de 7 dias recebendo de vários titulares | Mais de R$ 5.000 em 24 h, de 3 ou mais titulares | Novidade, volume e diversidade juntos; o valor equivale a cinco vezes o teto de saída de R1 |

DICT indisponível deixa E1 e E4 **desconhecidas**: o estado sai só das evidências locais, e desconhecido nunca conta como evidência.

### 4.2 Estado da conta

| Estado | Quando |
| --- | --- |
| `suspeita_elevada` | E1, ou a combinação explícita E2 + E4 |
| `suspeita` | Qualquer outra evidência ou combinação, inclusive E3 + E5 e três evidências sem E1 nem E2 + E4 |
| `nao` | Nenhuma evidência positiva disponível (desconhecido não significa conta limpa) |

E3 + E5 não eleva o estado porque as duas podem descrever a mesma arrecadação legítima. O estado descreve a **conta**, não a transação, e sozinho não decide nada. Quando a janela de uma evidência passa, ela some e o estado cai sozinho: não há marcação local permanente.

### 4.3 O ato do pagador

Avaliado nesta ordem; o primeiro que se aplica vale:

1. **Repasse aparente:** a conta recebeu pelo menos R$ 1.000 aprovados na última hora, e o que ela já enviou na hora mais o Pix atual chega a 50% ou mais disso, para pessoa física ou CNPJ com conta de menos de 90 dias. É o dinheiro que sai logo depois de entrar.
2. **Gasto típico:** fora do repasse, até R$ 1.000 para destinatário conhecido ou para CNPJ com conta de 90 dias ou mais. O teto e a idade do CNPJ impedem disfarçar repasse de "gasto" numa empresa de fachada.
3. **Outro:** o resto.

O repasse prevalece mesmo para destinatário conhecido: o padrão observado de entrada e saída pesa mais que a familiaridade. Um repasse para CNPJ com conta antiga escapa da definição: a exceção preserva rateios e pagamentos a estabelecimentos e aceita esse risco.

### 4.4 Relação anterior com o destino

Existe relação anterior quando o pagador tem aprovação para o mesmo titular de destino **com data anterior ao início da evidência** do destino. É a mãe que já mandava a mesada antes de o filho virar laranja.

- O início da evidência vem **só de data explícita da fonte** (a extensão `EvidenceSince` do mock: a data de E1 é usada; a de E4 é validada, mas não usada, porque E4 só eleva o estado junto de E2, cujo início não é datado). Nunca é deduzido da data da consulta nem do início de uma janela.
- Sem data conhecida, inclusive em E2 + E4, a exceção **não é presumida**: o destino elevado é tratado como primeira relação.
- Uma "relação" pode ter sido fabricada antes do golpe; exigir anterioridade à evidência reduz, mas não elimina esse risco, que é aceito.

### 4.5 Regras L1 a L3

Todas rejeitam e combinam o estado de uma conta com o ato.

| Regra | Lógica | Parâmetros | Por quê |
| --- | --- | --- | --- |
| **L1** destino laranja | Destino `suspeita_elevada` e sem relação anterior → `rejected` | Estado do destino; data explícita da evidência | Protege a vítima nova sem travar quem já se relacionava com a conta |
| **L2** pagador laranja | Pagador `suspeita_elevada` e ato que não é gasto típico (repasse ou outro) → `rejected` | Estado do pagador; ato | Prende o dinheiro do golpe e deixa a pessoa pagar as próprias contas, com teto |
| **L3** repasse suspeito | Pagador `suspeita` e repasse aparente → `rejected` | Estado do pagador; repasse | A evidência da conta mais o repasse formam os dois sinais exigidos para rejeitar |

| Pagador \\ ato | Gasto típico | Repasse aparente | Outro |
| --- | --- | --- | --- |
| `nao` | regras base | regras base | regras base |
| `suspeita` | regras base | **L3** | regras base |
| `suspeita_elevada` | regras base | **L2** | **L2** |

| Destino \\ relação | Relação anterior | Primeira relação |
| --- | --- | --- |
| `nao` ou `suspeita` | regras base | regras base |
| `suspeita_elevada` | regras base | **L1** |

**Custo de L2:** rejeitar também o ato "outro" barra, por exemplo, um Pix legítimo de R$ 1.500 a uma pessoa nova feito por uma conta marcada. A fricção é aceita para prender o dinheiro do golpe.

### 4.6 Travas que protegem quem recebeu de boa-fé

Receber Pix é passivo, e um golpista pode mandar R$ 1 de uma conta marcada para prejudicar alguém. Por isso:

1. **Direção:** quem pagou a conta marcada está *antes* dela e quase sempre é vítima; não ganha E2.
2. **Reputação:** E2 só vale para conta com menos de 90 dias ou menos de 10 contrapartes em 30 dias.
3. **Proporção:** só conta se mais de 50% do recebido em 30 dias veio de conta marcada.
4. **Expiração:** passados 30 dias, a evidência some.
5. **Um salto:** só E1 origina E2; a suspeita não se espalha a partir de outras suspeitas.
6. **Suspeita só pesa no repasse:** uma conta só `suspeita` continua pagando contas e fazendo Pix comuns.

Quem resolve o dinheiro da fraude é o MED, do Banco Central, não o motor: o motor só impede o próximo repasse.

## 5. Ordem de decisão e motivo único

**R1 → R2 → L1 → L2 → L3 → R4 → R3 → R5 → aprovação.** A primeira condição aplicável decide o status e o único motivo.

- R1 vem antes de R2 por ser a restrição específica da conta nova.
- As regras do módulo entram depois dos tetos e antes de qualquer 2FA: rejeição prevalece sobre 2FA.
- Entre os pedidos de 2FA, a ordem R4, R3, R5 é convenção de explicação, não alegação de que uma detecta mais fraude.

| Código | Regra | Status | Campos explicativos no `reason` |
| --- | --- | --- | --- |
| `NEW_ACCOUNT_LIMIT_EXCEEDED` | R1 | `rejected` | Acumulado projetado e teto, em centavos |
| `DAILY_LIMIT_EXCEEDED` | R2 | `rejected` | Acumulado projetado e teto |
| `MULE_DESTINATION` | L1 | `rejected` | Conta, estado, evidências e seus valores, ato |
| `MULE_PAYER` | L2 | `rejected` | Idem; no repasse, entradas e saídas da hora e o limiar |
| `SUSPECTED_MULE_FORWARDING` | L3 | `rejected` | Idem |
| `NEW_DEVICE_HIGH_AMOUNT` | R4 | `two_factor_required` | Valor do Pix e limiar |
| `HIGH_FREQUENCY` | R3 | `two_factor_required` | Contagem projetada e limiar |
| `AMOUNT_ABOVE_ACCOUNT_AVERAGE` | R5 | `two_factor_required` | Valor, soma e quantidade históricas, multiplicador e piso |
| `POLICY_PASSED` | nenhuma | `approved` | Só código e descrição |

O motivo nunca traz documento completo nem a identidade de contas marcadas. Aprovação significa só que nenhuma intervenção foi exigida, não garantia de segurança; rejeição por teto não é fraude confirmada. O retrato completo (estados, evidências, ato, situação do DICT) fica gravado para auditoria e não volta na resposta.

## 6. Cenários das regras base (C01 a C21)

Pressupõem entrada válida e ausência de condições não mencionadas. Valores em reais para facilitar a leitura.

| Caso | Situação | Resultado | Motivo |
| --- | --- | --- | --- |
| C01 | Conta de 3 dias; nada aprovado em 24 h; Pix de R$ 500 | `approved` | Abaixo do teto inicial |
| C02 | Conta de 3 dias; R$ 700 aprovados em 24 h; Pix de R$ 300 | `approved` | Exatamente R$ 1.000 |
| C03 | Mesmo caso, Pix de R$ 301 | `rejected` | R1: R$ 1.001 |
| C04 | Conta com exatamente 7 dias; aparelho conhecido; Pix de R$ 1.500 | `approved` | Deixou de ser nova |
| C05 | Conta antiga; R$ 17.000 aprovados em 24 h; Pix de R$ 3.000 | `approved` | Exatamente R$ 20.000 |
| C06 | Mesmo caso, Pix de R$ 3.000,01 | `rejected` | R2: acima de R$ 20.000 |
| C07 | Três Pix de baixo valor em 80 segundos, aparelho conhecido | `two_factor_required` | R3: terceira tentativa |
| C08 | Uma aprovada e uma rejeitada na janela; chega a terceira | `two_factor_required` | R3 conta rejeitadas |
| C09 | Reenvio equivalente do mesmo `id` | análise original | Não conta de novo |
| C10 | Conta antiga sem aprovações; primeiro Pix de R$ 6.000 | `two_factor_required` | R4 |
| C11 | Conta antiga sem aprovações; primeiro Pix de R$ 500 | `approved` | Falta de histórico, sozinha, não intervém |
| C12 | Aparelho novo; Pix de R$ 4.999 | `approved` | Abaixo do limiar de R4 |
| C13 | Aparelho novo; R$ 5.000 para destinatário conhecido | `two_factor_required` | R4; destinatário conhecido não dispensa |
| C14 | Aparelho conhecido; R$ 6.000 para destinatário novo | `approved` | Sem novidade do aparelho |
| C15 | Mesmo caso, conta de destino aberta há 2 dias | `approved` | Idade do destino não intervém |
| C16 | Conta de 3 dias; aparelho novo; Pix de R$ 5.000 | `rejected` | R1 prevalece sobre R4 |
| C17 | Terceira tentativa em 2 minutos que leva o acumulado acima de R$ 20.000 | `rejected` | R2 prevalece sobre R3 |
| C18 | Aprovação de R$ 100; 10 minutos depois, R$ 6.000 no mesmo aparelho | `two_factor_required` | R4: espera de 24 h incompleta |
| C19 | Primeira aprovação há 26 h, outra há 1 h; agora R$ 6.000 | `approved` | Espera cumprida e não reiniciada |
| C20 | Conta de 3 dias; Pix de R$ 21.000 | `rejected` | Só R1, embora R2 também se aplicasse |
| C21 | Aparelho sem as 24 h; terceiro pedido na janela, de R$ 5.000 | `two_factor_required` | Só R4, embora R3 também se aplicasse |

Para que a R5 não esconda o comportamento que cada cenário verifica, os testes começam o histórico com uma aprovação de valor compatível com a média.

## 7. Cenários do módulo de conta laranja (P01 a P20)

Pressupõem que R1 a R4 não se aplicam, salvo quando indicado.

| Caso | Situação | Estado | Ato ou relação | Resultado |
| --- | --- | --- | --- | --- |
| P01 | Mãe manda a mesada; aprovação anterior ao início informado da marcação do filho | destino `suspeita_elevada` (E1) | relação anterior | `approved` |
| P02 | Pagador novo envia à mesma conta | destino `suspeita_elevada` (E1) | primeira relação | `rejected` (L1) |
| P03 | Conta com E1 paga R$ 180 à concessionária (CNPJ antigo) | pagador `suspeita_elevada` | gasto típico | `approved` |
| P04 | Conta com E1 recebeu R$ 5.000 na hora e envia R$ 4.000 a pessoa física | pagador `suspeita_elevada` | repasse aparente | `rejected` (L2) |
| P05 | Conta com E1 envia R$ 1.500 a pessoa nova, sem entradas recentes | pagador `suspeita_elevada` | outro | `rejected` (L2) |
| P06 | Conta PF com E3: 6 titulares em 1 h, 4 estreantes; repassa a pessoa física | pagador `suspeita` | repasse aparente | `rejected` (L3) |
| P07 | Mesma conta paga R$ 90 a mercado (CNPJ antigo) | pagador `suspeita` | gasto típico | `approved` |
| P08 | Rateio: conta com E3 paga R$ 1.200 a restaurante (CNPJ antigo) | pagador `suspeita` | outro | `approved` |
| P09 | Padaria antiga, muitas contrapartes, R$ 50 de conta marcada | pagador `nao` | outro | `approved` |
| P10 | DICT fora do ar, sem cache nem indício local | pagador `nao` (E1/E4 desconhecidas) | conforme histórico | regras base |
| P11 | Oito dias depois de P06, sem evidências novas | pagador `nao` | outro | `approved` |
| P12 | Conta PF de 3 dias recebeu R$ 6.000 de 4 titulares; paga R$ 60 de telefone | pagador `suspeita` (E5) | gasto típico | `approved` |
| P13 | Mesma conta pede saída de R$ 5.000 | pagador `suspeita` | conforme histórico | `rejected` (R1 decide antes) |
| P14 | Conta PF nova recebe de 5 titulares em 1 h, 3 estreantes | `suspeita` (E3 + E5) | conforme pedido | não eleva o estado |
| P15 | E2 + E4, sem E1; saída de R$ 1.500 | pagador `suspeita_elevada` | outro | `rejected` (L2) |
| P16 | Conta suspeita recebeu R$ 1.000 na hora; envia R$ 600 a pessoa conhecida | pagador `suspeita` | repasse prevalece sobre gasto típico | `rejected` (L3) |
| P17 | Conta com E3, só R$ 600 de entradas na hora; envia R$ 400 | pagador `suspeita` | outro (mínimo não atingido) | `approved` |
| P18 | Destino elevado por E2 + E4, sem início determinável | destino `suspeita_elevada` | relação não estabelecida | `rejected` (L1) |
| P19 | CNPJ recebeu de 5 titulares em 1 h, sem outras evidências | `nao` (E3 de CNPJ exige 30) | conforme pedido | regras base |
| P20 | Único vínculo é ter enviado antes a uma conta marcada | pagador `nao` | conforme pedido | regras base, sem E2 contra quem pagou |

## 8. Riscos residuais assumidos

- Um Pix fraudulento abaixo dos tetos, no aparelho conhecido e sem laranja envolvida, pode ser aprovado.
- Um pagamento sob ameaça pode ocorrer com autenticação válida: o 2FA não prova que o pagamento é voluntário.
- Uma rajada mais lenta que 2 minutos não dispara R3; uma aprovação pequena torna o aparelho conhecido depois de 24 h.
- A média da R5 pode ser distorcida por valores extremos e não acompanha uma mudança recente de renda; pagamentos excepcionais legítimos podem pedir 2FA.
- Saídas de até R$ 1.000 podem passar como gasto típico quando não configuram repasse; repasse para CNPJ antigo escapa da definição. R2 e R3 continuam valendo.
- A laranja que só aparece em outros bancos, sem marcação no DICT, não é vista: o motor só enxerga os Pix que passam por ele.
- A marcação nova de um pagador pode levar até 5 minutos para valer (cache).
- A identidade de uma conta (titular e data de abertura) fica fixada pela primeira análise que a cita, de qualquer status. Se o sistema chamador mandar um dado errado uma vez, os Pix seguintes dessa conta recebem 422 `QIT003007`, e a API não oferece como corrigir o cadastro.
- O histórico prova decisões do motor, não liquidação; o repasse é "aparente".
- Todos os parâmetros são do protótipo e precisariam de dados reais, perdas e fricção medidas para calibrar.

## 9. Alternativas descartadas ou adiadas

| Alternativa | Situação e por quê |
| --- | --- |
| Score ponderado ou probabilidade de fraude | Descartado: pesos sem calibração e explicação pior que combinações nomeadas |
| Modelo de ML ou IA na decisão | Descartado: sem dados rotulados; a decisão deixaria de bater com as regras descritas |
| 2FA no lugar da rejeição em R1/R2 | Descartado: contra golpe, coação e conta aberta para fraude, quem confirma o 2FA é quem não devia passar |
| Teto diário de 5 vezes a média | Retirado: misturava referência por pagamento com exposição diária. A R5 é outra regra: compara o Pix isolado e pede 2FA |
| Ajuste por saldo, renda ou limite bancário real | Fora desta versão: o contrato não traz esses dados |
| Somar limites entre contas do mesmo CPF/CNPJ | Não adotado: o limite é por conta pagadora |
| Limites progressivos depois de 7 dias | Não adotado: faixas sem benefício demonstrado; R2 assume ao fim de R1 |
| Intervir por idade da conta destino ou destinatário novo isolado | Não adotado: descreve muito pagamento legítimo; no módulo, só entra combinado |
| Horário noturno e deslocamento geográfico | Adiados: o banco já aplica limite noturno; no motor, fuso e geolocalização imprecisos trariam falsos positivos |
| Bloquear tudo que toca uma laranja | Descartado: trava vítimas e familiares e não recupera dinheiro |
| IP como vínculo no grafo | Descartado: wi-fi público e operadoras ligariam pessoas sem relação |
| Banco de grafos dedicado | Descartado: infraestrutura nova sem ganho nesse volume; as arestas cabem no Postgres |
| Publicar suspeitas no DICT | Descartado: a classificação local alimentaria a própria fonte e criaria confirmação circular |
| Segurar o Pix suspeito para análise | Próximo passo: o desafio pede as três saídas imediatas |

## 10. Próximos passos

- **Novas evidências:** um aparelho operando várias contas de titulares diferentes (pega a rede antes da marcação), conta dormente que volta com volume, e fracionamento logo abaixo dos limites.
- **Menos fricção:** Pix entre contas do mesmo titular não contaria como repasse.
- **Dados externos:** situação cadastral de CPF/CNPJ e renda declarada, usada só como compatibilidade.
- **Separar o dinheiro suspeito da conta inteira,** na lógica do MED 2.0.
- **Calibrar os parâmetros** com dados reais de perdas e fricção.

## 11. Histórico de versões

| Versão | O que mudou | Documento preservado |
| --- | --- | --- |
| Política v1 | R1–R4, definições, ordem, cenários C01–C21 | [regras-de-negocio-v1.md](historico/regras-de-negocio-v1.md) |
| Módulo v1 | Proposta do módulo de laranja: DICT, grafo, E1–E5, L1–L3, P01–P13 | [Proposta ... -v1.md](historico/Proposta%20classificação%20possivel_laranja%20e%20regras%20por%20ato-v1.md) |
| Guia v1 e dados e fluxo v1 | Desenho consolidado inicial e proposta técnica | [guia v1](historico/Motor%20Antifraude%20Pix%20—%20Guia%20de%20desenvolvimento%20-%20v1.md), [dados-e-fluxo-v1.md](historico/dados-e-fluxo-v1.md) |
| `pix-v1.1` | Estado `suspeita_elevada` só por E1 ou E2+E4; repasse prevalece sobre gasto típico; E3 de CNPJ com 3 estreantes; arestas só de aprovações; início da evidência só por data explícita; P14–P20 | [guia v1.1](historico/guia-de-desenvolvimento-v1.1.md), [módulo v1.1](historico/modulo-contas-laranja-v1.1.md), [integração v1.1](historico/integracao-motor-v1.1.md) |
| `pix-v1.2` | R5 (desvio da média) e R2 de R$ 10.000 para R$ 20.000 | [regra-desvio-de-valor-v1.2.md](historico/regra-desvio-de-valor-v1.2.md) |
| `pix-v1.3` | R$ 500 vira piso da referência da R5; Pix para a mesma conta é 422; limites de data; cache do pagador de 24 h para 5 minutos | [revisao-e-justificativas-v1.3.md](historico/revisao-e-justificativas-v1.3.md), [revisão dos testes](historico/revisao-dos-testes-v3.md) |
| **Documentação v2** | Este documento: a política `pix-v1.3` consolidada num só lugar | — |

Análises gravadas em versões anteriores continuam consultáveis com a versão e o motivo originais: o GET e os reenvios nunca reavaliam.
