# Módulo de conta laranja: DICT, grafo e possivel\_laranja

Oct 17, 2026 · @renan

## Objetivo e premissa

Este módulo, aprovado pelo time, cuida da conta laranja com um conceito só: o motor primeiro classifica a conta (`possivel_laranja`) e depois decide o ato. Assim a mesma conta laranja consegue pagar a conta de luz, mas não consegue repassar o dinheiro do golpe.

**Premissa: nem toda transação que envolve uma laranja é fraudulenta.** O recrutado paga as próprias contas, a vítima que paga a laranja não é cúmplice, e a mãe que manda mesada ao filho recrutado também não. Bloquear tudo que toca a conta trava inocentes e não recupera dinheiro.

A proposta segue a política acordada (`regras-de-negocio_1.md`): R1 a R4 ficam como estão; sem pontuação; combinações explícitas; um único motivo na resposta; rejeição só por evidência externa ou por combinação descrita; nenhum 2FA novo, porque contra laranja quem confirma o 2FA é o próprio operador. Os valores são parâmetros do protótipo, não limiares validados.

## Fronteira com as regras base

As regras base (R1 a R4) estão com outra pessoa do time; este módulo se encaixa nelas por uma interface pequena, para os dois lados avançarem em paralelo e integrarem depois.

**O que o módulo recebe**, montado pelo controller:

- o payload do Pix já validado;
- as janelas do histórico local que ele precisa (entradas e saídas da conta pagadora na última hora, titulares distintos enviando ao destino, aprovações anteriores entre pagador e titular destino, vínculos de aparelho);
- a resposta do DICT para pagador e destino, ou a marca de indisponível.

**O que o módulo devolve**, sem tocar no banco:

```python
@dataclass
class LaranjaResult:
    rule_code: str | None        # "L1", "L2", "L3" ou None
    reason: str | None           # motivo único, pronto para o metadata
    payer_state: str             # "nao" | "suspeita" | "confirmada"
    destination_state: str
    evidences: dict              # E1..E5 de cada conta, para rule_evaluation
    act: str                     # "gasto_tipico" | "repasse" | "outro"
    prior_relationship: bool
    dict_status: str             # "consultado" | "cache" | "indisponivel"
```

**Onde entra na ordem:** R1, R2, L1, L2, L3, R4, R3; sem nenhuma, `approved`. A política de decisão chama as regras base e o módulo e aplica essa ordem; o módulo nunca decide sozinho o status final.

**O que precisa ser combinado com quem faz as regras base:**

- [ ] Mesma referência de tempo (`transaction_date`, como no acordo) e mesma definição de destinatário conhecido (aprovação anterior para o mesmo titular).
- [ ] Um único ponto que monta o contexto e consulta o banco, para não haver consultas duplicadas.
- [ ] Formato único de motivo no `metadata` (código, descrição, valores observados e limiares).
- [ ] O lock por conta pagadora vale para os dois: R1, R2, R3 e o cálculo de repasse dependem dele.

## Por que grafo e DICT

**A tese:** contra conta tomada, o 2FA funciona, porque o invasor não tem o segundo fator. Contra conta laranja, não: quem confirma é o próprio operador da conta, seja o recrutado, seja quem comprou o acesso. A única saída é reconhecer a conta e recusar o ato certo. O documento acordado reconhece esse risco residual (fraude abaixo dos tetos, no aparelho conhecido, com autenticação válida) e só admite fontes externas diante de um problema concreto não resolvido. Este é o problema.

As duas fontes se completam:

| Fonte | O que resolve | Limite |
| --- | --- | --- |
| DICT | dá sementes confirmadas por outras instituições: o motor deixa de depender só do que viu | só conhece o que alguém já marcou |
| Grafo local | segue o dinheiro e o aparelho a partir dessas sementes, e enxerga padrões (muitos pagadores, repasse rápido) antes de haver marcação | só vê os Pix que passam pelo motor |

**A QI é participante direto do Pix** e se conecta ao DICT; também oferece acesso indireto a outras instituições. O mock não é fantasia, é o desenho de produção, e o grafo da QI veria Pix de muitas instituições, não de um banco só.

**O que o mercado faz:** plataformas antifraude Pix descrevem o uso de rede de conexões entre contas suspeitas e monitoramento do fluxo de entrada para detectar contas laranja, e o MED 2.0 do Banco Central passou a rastrear o dinheiro por várias camadas. O módulo aplica a mesma lógica antes do dinheiro sair, não depois.

## O estado possivel\_laranja

O estado descreve a conta, não a transação, e sozinho não decide nada. É calculado na hora, para a conta pagadora e para a conta destino, a partir de cinco evidências.

| Código | Evidência | Fonte | Parâmetro |
| --- | --- | --- | --- |
| E1 | marcação de conta laranja ou golpista no DICT, ou titular marcado por 2 ou mais instituições | DICT simulado | 90 dias |
| E2 | mais de 50% do que a conta recebeu veio de conta marcada no DICT (E1), ou ela usa o mesmo aparelho de uma. Só E1 propaga, para o cálculo não andar em círculo | histórico local e grafo | 30 dias; só para contas com menos de 90 dias ou menos de 10 contrapartes |
| E3 | muitos titulares distintos enviando, a maioria pela primeira vez | histórico local | 5 ou mais em 1h, sendo 3 de primeira vez; 30 para CNPJ |
| E4 | notificações de infração abertas contra a conta | DICT simulado | 2 ou mais |
| E5 | conta aberta há menos de 7 dias recebendo volume alto de vários titulares | payload e histórico local | mais de R$ 5.000 em 24h, de 3 ou mais titulares |

| Estado | Quando |
| --- | --- |
| `confirmada` | E1, ou 2 ou mais evidências entre E2 e E5 |
| `suspeita` | exatamente 1 evidência entre E2 e E5 |
| `nao` | nenhuma evidência |

**Validade.** As evidências usam janelas (de 1 hora a 90 dias). Quando a janela passa, a evidência some e o estado cai sozinho: não existe marcação local permanente. Só o DICT mantém uma conta em `confirmada` por muito tempo.

**DICT indisponível.** E1 e E4 ficam desconhecidas, e o estado sai só das evidências locais. Desconhecido nunca conta como evidência.

## Tipo de ato e relação anterior

Com o estado das contas em mãos, o motor classifica a transação por duas perguntas.

**1. Do lado do pagador: que tipo de ato é?**

| Ato | Definição | Por quê |
| --- | --- | --- |
| Gasto típico | até R$ 1.000, para destinatário conhecido (aprovação anterior para o mesmo titular, como no acordo) ou para CNPJ com conta aberta há 90 dias ou mais | O padrão de quem usa a conta para a própria vida: mercado, contas, pessoas de sempre |
| Repasse | o pagador recebeu pelo menos R$ 1.000 em Pix aprovados na última hora, este Pix leva o total enviado na mesma hora a 50% ou mais disso, e o destino é pessoa física ou CNPJ com conta de menos de 90 dias | O dinheiro sai logo depois de entrar, que é o que define uma conta de passagem |
| Outro | o resto | Fica com as regras base |

O limite de R$ 1.000 e a exigência de CNPJ antigo existem para que o repasse não se disfarce de "gasto" numa empresa de fachada recém-aberta.

**2. Do lado do destino: o pagador já tinha relação com ele antes da suspeita?**

- **Relação anterior:** existe aprovação do mesmo pagador para o mesmo titular destino, com data anterior à evidência mais antiga do estado atual do destino. É a mãe que já mandava a mesada antes de o filho virar laranja.
- **Primeira relação:** qualquer outro caso. É o perfil da vítima do golpe.

## Regras e ordem junto de R1 a R4

Três regras substituem L1 a L4. Todas rejeitam, e cada uma combina o estado de uma conta com o tipo de ato.

| Regra | Condição | Resultado | Por quê |
| --- | --- | --- | --- |
| L1, destino laranja | destino `confirmada` e primeira relação | `rejected` | Protege a vítima nova sem travar quem já se relacionava com a conta |
| L2, pagador laranja | pagador `confirmada` e ato que não é gasto típico | `rejected` | Prende o dinheiro do golpe, mas deixa a pessoa pagar as próprias contas |
| L3, repasse suspeito | pagador `suspeita` e ato de repasse | `rejected` | A evidência do estado mais o repasse formam a combinação de dois sinais exigida para rejeitar |

Visto como matriz:

| Pagador \\ ato | Gasto típico | Repasse | Outro |
| --- | --- | --- | --- |
| `nao` | regras base | regras base | regras base |
| `suspeita` | regras base | `rejected` (L3) | regras base |
| `confirmada` | regras base | `rejected` (L2) | `rejected` (L2) |

| Destino \\ relação | Relação anterior | Primeira relação |
| --- | --- | --- |
| `nao` ou `suspeita` | regras base | regras base |
| `confirmada` | regras base | `rejected` (L1) |

Destino em `suspeita` não muda a decisão: uma evidência isolada não intervém, como no acordo. O estado fica registrado na análise.

**Ordem completa:** R1, R2, L1, L2, L3, R4, R3; sem nenhuma, `approved`. Todas as rejeições vêm antes dos pedidos de 2FA, como no documento acordado.

## Cenários de aceite

Todos pressupõem que R1 a R4 não se aplicam, salvo quando indicado. Viram `test_laranja.py`, um teste por cenário, e substituem C22 a C29 do guia.

| Caso | Situação | Estado | Ato ou relação | Resultado |
| --- | --- | --- | --- | --- |
| P01 | Mãe manda a mesada de sempre ao filho, marcado no DICT na semana passada | destino `confirmada` | relação anterior | `approved` |
| P02 | Vítima nova paga a mesma conta | destino `confirmada` | primeira relação | `rejected` (L1) |
| P03 | A conta marcada paga R$ 180 de luz para a concessionária | pagador `confirmada` | gasto típico | `approved` |
| P04 | A conta marcada repassa R$ 4.000 do que acabou de receber | pagador `confirmada` | repasse | `rejected` (L2) |
| P05 | A conta marcada manda R$ 1.500 para uma pessoa nova, sem entradas recentes | pagador `confirmada` | outro | `rejected` (L2) |
| P06 | Conta que recebeu de 6 titulares em 1h, 4 de primeira vez, repassa 80% para pessoa física | pagador `suspeita` (E3) | repasse | `rejected` (L3) |
| P07 | A mesma conta paga R$ 90 no mercado | pagador `suspeita` | gasto típico | `approved` |
| P08 | Rateio: Ana recebe de 5 amigos, de primeira vez, e paga R$ 1.200 ao restaurante (CNPJ antigo) | pagador `suspeita` (E3) | outro (destino é CNPJ antigo) | `approved` |
| P09 | Padaria antiga que recebeu R$ 50 de conta marcada paga o fornecedor | pagador `nao` (E2 não se aplica: conta antiga e 0,06% do recebido) | outro | `approved` |
| P10 | DICT fora do ar; a conta só era marcada no DICT | pagador `nao` (E1 desconhecida) | repasse | regras base, com `"dict": "indisponivel"` |
| P11 | Oito dias depois de P06, sem novas evidências, a conta repassa | pagador `nao` (janela de E3 passou) | repasse | regras base |
| P12 | Conta de 3 dias que recebeu R$ 6.000 de 4 titulares paga R$ 60 de telefone | pagador `confirmada` (E3 e E5) | gasto típico | `approved` |
| P13 | A mesma conta repassa R$ 5.000 | pagador `confirmada` | repasse | `rejected` (R1 decide antes: conta nova acima de R$ 1.000) |

P13 mostra a ordem: R1 já pega a conta nova, e o motivo informado é R1, como pede o acordo.

## Fonte 1: DICT simulado

O mock alimenta E1 e E4. Ele segue a estrutura da seção Antifraude da API pública do DICT, simplificada; o README deve dizer isso e linkar a especificação.

```json
GET /dict/v1/statistics?participant=60701190&branch=3675&account=10442&document=98765432100
{
  "OwnerStatistics": {
    "FraudMarkers": {
      "MuleAccounts":           {"d90": 2, "m12": 2, "m60": 2},
      "ScammerAccounts":        {"d90": 0, "m12": 0, "m60": 0},
      "DistinctFraudReporters": {"d90": 2, "m12": 3, "m60": 3}
    },
    "InfractionReports": {"OpenReports": 3, "OpenReportsDistinctReporters": 2}
  }
}
```

- **E1** = `MuleAccounts.d90` ou `ScammerAccounts.d90` ≥ 1, ou `DistinctFraudReporters.d90` ≥ 2.
- **E4** = `OpenReports` ≥ 2.

**Como montar:**

- **Mock:** Mockserver no `docker compose`, com as respostas em `mocks/dict_expectations.json`, versionado. Se o Mockserver der trabalho, um container mínimo com FastAPI lendo o mesmo JSON serve.
- **Connector** em `src/connectors/dict_connector.py`: URL em variável de ambiente; sessão HTTP reaproveitada; timeout de 200 ms no mock local (em produção, por volta de 800 ms). Timeout, erro ou resposta 429 deixam E1 e E4 desconhecidas e o `dict_status` como `indisponivel`; nunca viram decisão.
- **Cache** em `dict_lookup`: destino com validade de 1 hora; pagador, que é cliente do banco e muda pouco, com validade de 24 horas.
- **Origem e destino:** o destino é consultado no momento do Pix. A origem é lida do cache e só consultada no primeiro Pix de um cliente ou quando o cache expira. Quando as duas consultas são necessárias, rodam em paralelo, com um único limite de tempo.
- **Contribuição (opcional):** o mock aceita `POST` de suspeita quando L1, L2 ou L3 recusa. Na vida real, a marcação definitiva passaria por análise humana.

**Números do DICT real**, para calibrar o mock e responder à banca:

| Métrica | Valor oficial |
| --- | --- |
| Consulta de chave no DICT | 99% em até 1 segundo |
| Disponibilidade do DICT para consulta | 99,9% |
| Limite por pagador na consulta de chave | PF: balde de 100, reposição de 2 por minuto; PJ: balde de 1.000, reposição de 20 por minuto |
| Estatísticas antifraude de pessoa | 12.000 por minuto por instituição, balde de 36.000 |
| Tempo máximo de um Pix | 40 segundos |

Fontes: [Manual de Tempos do Pix](https://www.bcb.gov.br/content/estabilidadefinanceira/pix/Regulamento_Pix/IX_ManualdeTemposdoPix.pdf) e [especificação da API do DICT](https://www.bcb.gov.br/content/estabilidadefinanceira/pix/API-DICT.html).

**Em produção, sem chamada extra:** para fazer um Pix por chave, o banco já consulta o DICT; com `IncludeStatistics=true`, os contadores antifraude chegam na mesma resposta.

## Fonte 2: grafo de contas

O grafo alimenta E2, E3 e E5 e define o ato de repasse. Não há banco de grafos: as arestas ficam no Postgres, e cada evidência é uma consulta indexada.

**Arestas:**

| Tipo | Direção | Para quê |
| --- | --- | --- |
| `pix` | do pagador para o destino | seguir o dinheiro e separar vítima de cúmplice |
| `device` | sem direção | a mesma quadrilha operando várias contas |
| `document` | sem direção | o mesmo titular em contas diferentes |

IP não vira aresta: wi-fi público e operadoras com IP compartilhado ligariam pessoas sem relação nenhuma.

**A direção separa vítima de cúmplice.** Quem mandou dinheiro para uma conta marcada está antes dela e quase sempre é vítima: não ganha evidência. Quem recebeu dela está depois e pode ser o próximo elo: ganha E2, se passar pelas travas abaixo.

&#91;embedded content: como E1 vira E2 na rede laranja · 5 contas\]

L2 ganha E2 por estar depois de L1 no dinheiro. L3 divide o aparelho com L2, mas não ganha E2, porque L2 não está marcada no DICT: a suspeita não anda em cadeia. Se L3 repassar o que recebeu e tiver outra evidência (E3 ou E5), cai em L3 do mesmo jeito. A vítima A, que está antes, continua pagando o mercado sem fricção.

**Travas que protegem quem recebeu de boa-fé.** Receber Pix é passivo, e um golpista pode mandar R$ 1 de uma conta marcada para quem quiser prejudicar. Por isso:

1. **Reputação:** E2 só vale para contas com menos de 90 dias ou menos de 10 contrapartes. Uma padaria antiga não ganha E2.
2. **Proporção:** só conta se mais de 50% do que a conta recebeu em 30 dias veio da marcada.
3. **Expiração:** a janela de 30 dias passa, e a evidência some.
4. **Um salto, só a partir de E1:** a suspeita não se espalha em cadeia a partir de outras suspeitas.
5. **Uma evidência só é `suspeita`,** e `suspeita` só pesa no repasse (L3). Mesmo uma conta contaminada de propósito continua pagando contas e fazendo Pix comuns.

|  | Padaria do Seu João | Conta L2 |
| --- | --- | --- |
| Recebeu da conta marcada | R$ 50, de um cliente golpista | R$ 2.000 |
| Idade e contrapartes | 10 anos, 400 contrapartes | 12 dias, 2 contrapartes |
| Peso do dinheiro marcado | 0,06% | 91% |
| Estado | `nao` | `suspeita` (E2), ou `confirmada` se houver outra evidência |

**Quem resolve o dinheiro da fraude é o MED, não o motor.** O Mecanismo Especial de Devolução atua sobre o valor (bloqueio cautelar e devolução à vítima), com direito de defesa para quem recebeu de boa-fé. O motor só impede que o próximo repasse saia.

## Modelagem de dados do módulo

O módulo não guarda estado de conta: tudo é calculado na hora a partir de `pix_transaction`, das arestas e do cache do DICT. O retrato do estado no momento da decisão vai para `rule_evaluation`, para o `GET` devolver a análise original.

```sql
CREATE TABLE dict_lookup (
    id           SERIAL PRIMARY KEY,
    account_id   INTEGER     NOT NULL UNIQUE REFERENCES account(id),
    response     JSONB       NOT NULL,          -- resposta do DICT simulado
    fetched_at   TIMESTAMPTZ NOT NULL           -- destino: 1h; pagador: 24h
);

CREATE TABLE account_link (
    id           SERIAL PRIMARY KEY,
    from_id      INTEGER     NOT NULL REFERENCES account(id),
    to_id        INTEGER     NOT NULL REFERENCES account(id),
    link_type    VARCHAR(10) NOT NULL,          -- pix (com direção), device, document
    first_seen   TIMESTAMPTZ NOT NULL,
    last_seen    TIMESTAMPTZ NOT NULL,
    total_amount BIGINT      NOT NULL DEFAULT 0, -- só para pix aprovados
    UNIQUE (from_id, to_id, link_type)
);
CREATE INDEX ix_link_to ON account_link (to_id, link_type, last_seen);
CREATE INDEX ix_link_from ON account_link (from_id, link_type, last_seen);
```

**Consultas que o módulo precisa**, todas com janela e índice:

| Para | Consulta |
| --- | --- |
| E2 | quanto a conta recebeu em 30 dias e quanto disso veio de contas com E1; aparelhos compartilhados com contas E1 |
| E3 | titulares distintos que enviaram à conta na última hora, e quantos nunca tinham enviado antes |
| E5 | quanto a conta recebeu em 24h, de quantos titulares |
| Repasse | quanto o pagador recebeu e quanto enviou na última hora, em Pix aprovados |
| Relação anterior | primeira aprovação do pagador para o titular destino |
| Reputação | idade da conta e número de contrapartes distintas |

As arestas são gravadas no mesmo commit do Pix, para nunca haver Pix sem aresta ou aresta sem Pix. A identificação da conta de origem segue a premissa do guia: o payload não traz ISPB, então assumimos o banco do motor como participante único de origem.

## Testes e demo

Testes black box, só por HTTP, com o mock roteirizado por teste; cada um monta o próprio histórico pelo `POST`.

| Arquivo | Cobre |
| --- | --- |
| `test_laranja.py` | P01 a P13, um teste por cenário |
| `test_laranja_dict.py` | E1 por marcação e por 2 instituições; E4 com 1 e 2 notificações; DICT com timeout e com 429 (decisão sai sem ele); pagador lido do cache, sem chamada ao mock |
| `test_laranja_grafo.py` | direção (quem enviou para a marcada não ganha E2); trava de reputação (padaria antiga); proporção de 50%; expiração de 30 dias; L3 sem E2 por aparelho de conta não marcada; R$ 1 enviado de propósito não trava a conta |
| `test_laranja_ato.py` | gasto típico no limite de R$ 1.000; CNPJ com 89 e 90 dias; repasse em 49% e 50%; rateio do restaurante pago a CNPJ antigo |
| `test_laranja_concorrencia.py` | vários repasses simultâneos da mesma conta: o lock faz cada um enxergar os anteriores |

**Demo, em cinco minutos de história:**

1. L1 está marcada no DICT. Uma vítima nova tenta pagar: `rejected` (L1). A mãe que sempre mandava mesada paga: `approved`.
2. L1 paga a conta de luz: `approved`. L1 tenta repassar o que recebeu: `rejected` (L2). A mesma conta, dois destinos diferentes.
3. L2, conta nova que recebeu 91% do dinheiro de L1 e também de vários pagadores novos, tenta repassar: `rejected`.
4. A padaria que recebeu R$ 50 de L1 paga o fornecedor: `approved`. Receber de boa-fé não trava ninguém.
5. O DICT cai: o motor continua respondendo, só com as evidências locais, e registra a indisponibilidade.
6. Na tela, o grafo do cenário, gerado por um script com `networkx` fora da API.

A frase da apresentação: **"primeiro o motor classifica a conta, depois decide o ato: a laranja paga a luz, mas não repassa o dinheiro do golpe"**.

## Explicação, implementação e o que fica de fora

**Explicação.** A resposta continua com um único motivo. Quando L1, L2 ou L3 decide, o motivo traz o estado da conta, as evidências que o formaram e o tipo de ato, por exemplo: "pagador em `suspeita` (6 titulares em 1h, 4 de primeira vez) repassando 80% do recebido na última hora". Quando não decide, o estado não aparece na resposta; fica só em `rule_evaluation`, para auditoria. Nunca se expõe documento completo nem a identidade das contas marcadas.

**Implementação.**

- O estado é calculado na hora, a partir do histórico e da resposta do DICT. Não há job em segundo plano nem tabela de estado para manter consistente; o retrato do estado no momento da decisão fica gravado junto da análise, para o `GET` devolver a decisão original.
- Uma função `classify_account(conta, contexto)` devolve estado e evidências; `classify_act(pix, contexto)` devolve o tipo de ato; as três regras são combinações desses dois resultados. Tudo em `src/rules/laranja.py`, sem acesso ao banco.
- As consultas novas são janelas sobre `pix_transaction` (entradas da conta, titulares distintos, primeira vez) e `account_link` para o aparelho. As tabelas já previstas no guia bastam.
- O lock por conta pagadora, já previsto, mantém o cálculo de repasse coerente quando chegam vários Pix da mesma conta ao mesmo tempo.

**Fica de fora desta versão, como próximos passos:**

- **Renda declarada e gastos atuais:** compatibilidade entre movimentação e capacidade financeira viraria a evidência E6, via mock de cadastro. Precisa ser usada só como compatibilidade, nunca como perfil social, e o acordo retirou ajustes por saldo por falta de dado.
- **Situação cadastral do CPF e dados do CNPJ:** CPF cancelado ou de titular falecido, e empresa recém-aberta com capital mínimo, via mock da Receita.
- **Separar o dinheiro suspeito, não só a conta:** recusar apenas a parte da saída que excede o que entrou de fontes limpas, na lógica do MED 2.0. Exige registrar entradas e saídas com cuidado, porque o contrato não traz saldo.

## Riscos residuais e decisões para o time

**Riscos que a proposta aceita e deve apresentar:**

- A laranja pode disfarçar o repasse em vários "gastos típicos" de até R$ 1.000 para destinos conhecidos. R2 e R3 continuam valendo e limitam o volume.
- Uma laranja que só aparece em outros bancos, sem marcação no DICT, não é vista: o motor só enxerga os Pix que passam por ele.
- A "relação anterior" pode ser fabricada com Pix pequenos antes do golpe. Por isso ela só vale se for anterior à primeira evidência do destino.
- "Recebido" significa aprovado pelo motor, não liquidado; o repasse é aparente.
- Os parâmetros são do protótipo e precisariam de dados reais para calibrar.

**Decisões que o time precisa tomar:**

- [ ] Combinar a integração com quem faz R1 a R4, pelos itens da seção Fronteira com as regras base.
- [ ] Confirmar os limiares de gasto típico (R$ 1.000 e CNPJ com 90 dias) e de repasse (50% em 1h, mínimo de R$ 1.000 recebido).
- [ ] Confirmar se L2 deve rejeitar o ato "outro" (P05) ou só o repasse, aceitando mais risco em troca de menos fricção.
- [ ] Definir como a demo mostra o DICT fora do ar (P10).
