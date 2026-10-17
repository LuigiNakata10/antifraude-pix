# Política antifraude Pix — proposta inicial

Status: proposta para discussão, sem implementação e sem calibração validada.

## 1. Objetivo e referências

Decidir, antes da saída de um Pix, se a solicitação deve ser aprovada, exigir segundo fator ou ser rejeitada. Usar os dados recebidos e o histórico local, com baixo tempo de resposta e motivos verificáveis.

Os documentos `Hackathon Antifraude Pix.pdf` e `Desafio Antifraude Pix.pdf`, fornecidos pelo usuário, definem o contrato, escopo e critérios. O ZIP da biblioteca é apenas referência de organização. O Base Service oficial deverá orientar a integração quando estiver disponível.

Esta política propõe regras do protótipo; não representa uma política regulatória nem eficácia comprovada em produção.

## 2. Princípios de decisão

1. Preferir poucas regras determinísticas, com parâmetros explícitos.
2. Uma novidade isolada não caracteriza fraude: dispositivo novo, destinatário novo ou conta recente precisam de contexto.
3. Distinguir informação ausente de evidência desfavorável.
4. Usar 2FA quando existe dúvida relevante de identidade. O retorno apenas solicita 2FA: este serviço não executa nem recebe sua conclusão.
5. Rejeitar por impedimento explícito da política ou por uma combinação forte previamente descrita. Rejeição não afirma fraude confirmada.
6. Aprovação anterior não confirma legitimidade nem liquidação. Não atribuir confiança ilimitada ao histórico de decisões do próprio motor.
7. Falha técnica não deve ser transformada silenciosamente em aprovação, rejeição ou pedido de 2FA.
8. Toda escolha deve ter um teste que demonstre o comportamento e um caso legítimo de contraste quando aplicável.

## 3. Escopo funcional

- Receber o contrato de `POST /pix/transaction`.
- Persistir cada solicitação válida e sua análise, incluindo rejeições e pedidos de 2FA.
- Retornar `key`, `status` e `metadata`.
- Recuperar a análise persistida por `GET /pix/transaction/{id}`.
- Manter regras, testes, README e apresentação.

Não executar movimentação financeira, consultar saldo, cadastrar contas, realizar análise manual, implementar interface ou integrar consultas externas como dependência da decisão.

## 4. Identidade, valores e histórico

### Identificação

- O `id` identifica a solicitação; `key` identifica sua análise. O ID de entrada é texto, não necessariamente UUID.
- Documentos devem ser normalizados de maneira consistente, preservando zeros iniciais. O formato aceito deve acompanhar o contrato oficial; não copiar a restrição de CPF da biblioteca.
- Para concentração no destinatário, agrupar pelo documento do titular. Contas diferentes do mesmo titular não devem fragmentar esse agregado.
- Para dispositivo, relacionar `device_id` ao pagador. Compartilhamento de IP, isoladamente, não vincula pessoas nem comprova fraude.
- A origem não fornece ISPB. A identidade de conta de origem e a hipótese de um único participante de origem precisam ser explicitadas antes de usar agência e conta como chave global.

### Valores

- Valores são inteiros em centavos, sem arredondamento de ponto flutuante.
- Valor positivo, limites de representação e datas válidas são validações do pedido. Não usar entrada inválida como fraude rejeitada.
- Não rejeitar automaticamente transferência entre contas do mesmo titular: isso não é proibido pelo desafio.

### O que sabemos

O histórico comprova solicitações recebidas e decisões emitidas. Não comprova saldo, recursos recebidos, liquidação, conclusão de 2FA ou fraude confirmada.

Consequências:

- Frequência e montante de todas as solicitações serão chamados de frequência e montante de tentativas.
- Reenvios idempotentes não entram novamente nas contagens.
- O perfil de referência pode usar análises aprovadas, descritas como tal; isso é uma aproximação sujeita a viés e manipulação.
- Não implementar detecção de dinheiro que entrou e saiu, lista de fraudadores confirmados ou reputação baseada em confirmação que não existe no contrato.

## 5. Semântica temporal proposta

- Guardar `transaction_date` e `received_at` separadamente, com fuso e normalização para UTC.
- Usar `received_at` para as janelas de tentativas: é o instante observado pelo serviço e evita que o cliente contorne velocity alterando a data do payload.
- Na leitura histórica, considerar somente solicitações anteriores observadas pelo serviço. Acrescentar a solicitação atual uma única vez ao agregado para avaliar limites.
- Definir janelas como `(t - janela, t]`, usando o instante de recebimento da solicitação atual como `t`.
- Usar a data de transação para interpretar o evento, incluindo idade da conta; inconsistências com datas de abertura precisam de validação explícita.
- Não criar regra de horário noturno no MVP: o fuso é fornecido, mas não há agenda nem rotina suficiente para justificar um bloqueio por horário isolado.

Justificativa: uma referência única de tempo simplifica concorrência, testes e proteção contra timestamps manipulados. Se os organizadores fornecerem carga histórica para simular o tempo dos eventos, deverá existir uma decisão documentada sobre replay; não mudar o relógio implicitamente.

## 6. Indicadores do primeiro recorte

| Código | Indicador | Histórico considerado | Finalidade |
|---|---|---|---|
| V | Quantidade de tentativas em janela curta por pagador | Todas as solicitações válidas, sem reenvios | Identificar rajada |
| M | Montante de tentativas em janela por pagador | Todas as solicitações válidas, sem reenvios | Identificar exposição acumulada |
| F | Quantidade, montante e contas distintas para o mesmo titular destinatário | Tentativas do mesmo pagador para o mesmo documento | Identificar possível fragmentação |
| D | Dispositivo diferente dos anteriormente observados | Solicitações anteriores do pagador | Contextualizar acesso |
| N | Primeiro destinatário observado para o pagador | Solicitações anteriores do pagador, por documento destinatário | Contextualizar relação |
| A | Valor muito superior à referência do pagador | Amostra delimitada de análises aprovadas anteriores | Identificar ruptura de valor |
| C | Conta destinatária recente | Data de abertura recebida no payload | Agravar um cenário já suspeito |

`F` aprofunda a regra de montante: não deve somar outra penalidade pelo mesmo valor já contado em `M`.

No primeiro pedido, `D` e `N` são desconhecidos para fins de risco, não dois sinais negativos. Sem amostra mínima, `A` também é desconhecido. Continuam valendo os controles absolutos de tentativas e montante.

Não incluir inicialmente geolocalização, comparação de IP ou reputação global do recebedor. São evoluções possíveis, mas acrescentam interpretação, falsos positivos e requisitos de concorrência. O contrato opcional de localização deve continuar sendo aceito e preservado.

## 7. Composição da decisão proposta

Usar precedência explícita, sem pontuação geral e sem probabilidade de fraude inventada.

| Ordem | Condição | Resultado | Justificativa |
|---|---|---|---|
| 1 | Teto rígido de quantidade ou montante de tentativas excedido | `rejected` | Impedimento operacional da política, independentemente da identidade |
| 2 | Histórico suficiente e combinação `D + N + A + C` | `rejected` | Ruptura simultânea de acesso, relação e valor, agravada por conta recente |
| 3 | Faixa de atenção de quantidade/montante atingida, inclusive concentração em `F` | `two_factor_required` | Exposição elevada antes do teto rígido; identidade deve ser confirmada, sem alegar que isso elimina o risco de golpe |
| 4 | Histórico suficiente e combinação `D + A` ou `N + A` | `two_factor_required` | Valor muito atípico combinado com novidade relevante |
| 5 | Nenhuma condição anterior | `approved` | Não há evidência suficiente para impor fricção nesta política |

Uma conta recente isolada, um novo destinatário isolado ou um aparelho novo isolado não geram rejeição ou 2FA no recorte inicial. Essa escolha reduz fricção, mas aceita risco residual, que deve aparecer na avaliação.

Pedir 2FA não resolve por si só engenharia social. O serviço não pode assumir que um pedido de 2FA foi concluído, nem liberar automaticamente uma nova tentativa por ter emitido esse status antes.

A condição de rejeição contextual da ordem 2 é uma hipótese a validar com cenários legítimos, como troca de celular seguida de pagamento excepcional para fornecedor novo. Se não houver separação convincente, deve ser rebaixada a 2FA ou retirada.

## 8. Parâmetros e calibração

Não fixar números como se tivessem validação de mercado. Antes de implementar a política final, preencher:

| Parâmetro | Como escolher e justificar |
|---|---|
| Janela curta e janela de montante | Cenários de rajada e acumulação, incluindo limites exatos da janela |
| Faixa de atenção e teto rígido | Comparar rejeições, pedidos de 2FA e aprovações nos casos de fraude simulada e legítimos |
| Amostra mínima e horizonte do perfil | Evitar inferir normalidade a partir de uma ou duas observações; limitar custo da consulta |
| Referência e multiplicador de valor atípico | Comparar uma referência simples, como mediana de amostra limitada, e testar sensibilidade a valores extremos |
| Piso absoluto para valor atípico | Evitar que pequenas diferenças em valores muito baixos gerem fricção |
| Idade de conta recente | Testar conta nova legítima e seu papel apenas como agravante |

Usar uma configuração pequena e versionada. Separar cenários de desenvolvimento dos cenários de avaliação. Os resultados sintéticos demonstram comportamento e trade-offs, não eficácia real no mercado.

Não usar ML ou serviço de IA no caminho principal nesta versão: faltam dados rotulados e evidência de ganho que justifique dependência, custo e latência adicionais.

## 9. Persistência, idempotência e concorrência

- Mesmo ID e conteúdo semanticamente equivalente devolvem a análise original, sem atualizar indicadores.
- Mesmo ID com conteúdo diferente gera conflito; normalização e equivalência precisam de definição explícita.
- O GET devolve a análise original, mesmo que a política tenha mudado.
- Solicitação válida, análise e atualização de estado auxiliar, se existir, devem ser confirmadas de maneira atômica.
- Decisões `rejected` e `two_factor_required` são resultados persistidos, não exceções que descartam a solicitação.
- Leituras e gravações do mesmo pagador precisam de coordenação no banco para impedir que pedidos concorrentes atravessem limites juntos. Não usar trava global de todos os pagadores.
- O recorte evita limite global rígido por destinatário, reduzindo a necessidade de coordenar pagadores distintos.
- Erro de banco ou timeout é falha técnica. Reenvio do mesmo ID permite recuperar uma análise eventualmente confirmada.

## 10. Explicação e desempenho

O `metadata` deve permitir reconstruir a decisão: versão da política, códigos dos motivos, indicadores relevantes, limiares aplicados e quantidade de histórico usada. Registrar motivos positivos ou ausência de condições de bloqueio de forma objetiva, sem chamar aprovação de garantia de segurança.

Não devolver documentos completos, IP ou coordenadas no metadata sem necessidade. Preservar o payload no armazenamento não exige copiá-lo para respostas ou logs.

Buscar indicadores em consultas delimitadas e indexadas. Não carregar todo o histórico nem consultar o banco uma vez por regra. Começar com PostgreSQL, sem cache ou filas adicionais até haver necessidade medida.

Medir o tempo total, incluindo fila, pool, espera de trava, consultas e commit. Reportar p50, p95 e p99, volume de histórico, concorrência, erros e ambiente. O desafio exige poucos segundos, mas não fixa SLA numérico; qualquer meta mais restrita será meta interna.

## 11. Cenários mínimos de validação

1. Primeiro Pix sem histórico: ausência de histórico não vira rejeição automática.
2. Valor alto habitual e dispositivo conhecido: aprova se não exceder impedimentos.
3. Novo dispositivo isolado: aprova no recorte proposto.
4. Novo dispositivo e valor atípico com amostra suficiente: pede 2FA.
5. Novo destinatário e valor atípico: pede 2FA.
6. Ruptura completa com conta recente: avalia a hipótese de rejeição e seu contraste legítimo.
7. Conta recente isolada: aprova se não houver outras condições.
8. Fragmentação entre contas do mesmo documento: soma como um único destino econômico.
9. Quantidade/montante na faixa de atenção e acima do teto: decisões seguem a precedência.
10. Mesmo ID repetido ou concorrente: uma análise e uma contribuição nos agregados.
11. IDs distintos concorrentes do mesmo pagador: limite é respeitado.
12. Eventos na borda da janela, com fusos diferentes e chegada atrasada: semântica documentada é preservada.
13. Pedidos rejeitados entram em tentativas, mas não no perfil de aprovações.
14. Mudança de política não altera GET de análise anterior.
15. Falha na gravação não devolve sucesso sem análise persistida.
16. Carga com histórico crescente mede latência e taxa de falhas.

## 12. Decisões a fechar antes da implementação

- Confirmar o Base Service e suas convenções.
- Confirmar premissa de identidade do pagador e normalização de documentos.
- Definir comportamento para replay histórico e datas inconsistentes.
- Preencher parâmetros com cenários e análise de sensibilidade.
- Validar se a rejeição contextual agrega valor ou deve permanecer como 2FA.
- Definir respostas HTTP técnicas segundo o contrato e convenções disponíveis, sem confundir status HTTP com decisão antifraude.

O próximo resultado esperado é uma tabela de regras com parâmetros preenchidos e casos de contraste; a arquitetura deve implementar essa política, não definir o negócio por acidente.
