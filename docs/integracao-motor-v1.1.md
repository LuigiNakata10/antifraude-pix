# Integração da revisão v1.1 em feat/motor-antifraude

Base: `origin/feat/motor-antifraude`, commit `a2fd72d`. Revisão mantida em `v2/feat/motor-antifraude`.

## O que foi aproveitado desta branch

Foram mantidas as camadas do Base Service, repositories separados, indicadores calculados por SQL, cache append-only, consultas paralelas ao mock, trava `FOR NO KEY UPDATE`, tratamento de espera com 503, respostas sem reavaliação e scripts de seed/grafo. Não houve cópia integral da outra implementação nem mudança no schema.

O deadlock de upsert de vínculos encontrado na outra versão não existe da mesma forma aqui: esta branch grava uma linha por evento, sem atualizar uma aresta agregada compartilhada. Preservamos essa escolha e os testes de concorrência existentes.

## Alterações incorporadas

- Política `pix-v1.1`: estado `suspeita_elevada` por E1 ou E2+E4, exclusivamente. E3+E5 e os demais pares permanecem suspeita, sem afirmar fraude confirmada.
- `repasse_aparente` prevalece sobre `gasto_tipico`; destinatário conhecido não descaracteriza a saída concentrada.
- E3 de CNPJ exige 30 titulares e pelo menos 3 estreantes, conforme a revisão documental.
- E2 por aparelho exige aprovações anteriores de ambas as contas. Tentativas rejeitadas e pedidos de 2FA não criam vínculos.
- Contrapartes são contas distintas na janela de 30 dias. Titulares distintos continuam sendo a unidade de E3/E5.
- Arestas só são criadas para aprovações; todas as análises, incluindo rejeição e 2FA, continuam em `pix_analysis`.
- U+0000 e Unicode inválido são erros 400 no POST/GET antes das consultas.
- Titular/abertura divergentes do histórico retornam 422 `QIT003007`, inclusive para impedir alterar a idade da conta e contornar R1.
- O motivo explica contadores e janelas de E1, valores locais e proporção de repasse, mantendo um motivo único e sem identificar terceiros.
- O início da evidência não é inventado a partir da consulta ou do início da janela. A extensão própria do mock `EvidenceSince` pode informar `E1`/`E4` com data ISO e fuso. Campo ausente significa desconhecido; E2+E4 não possui início histórico reconstruível e não presume relação anterior.
- Dependência networkx fixada em versão compatível com Python 3.11. Perfil `tests` no Compose permite rodar a suíte e a demo sem Python instalado no host.

Os documentos v1 permanecem preservados. Os arquivos v1.1 foram adicionados para registrar a política usada nesta integração.

## Diferenças preservadas conscientemente

Não foram transplantadas convenções técnicas exclusivas da outra implementação:

- Datas incoerentes e pedidos retroativos continuam sendo 422. O sistema chamador continua sendo a fonte da data; esta branch ainda não restringe datas futuras.
- Cache continua por conta: pagador 24h; destino ao vivo com reserva de 1h; relógio técnico do servidor para validade. Isso diverge da proposta de cache único por titular. Aceita-se atraso na marcação do pagador, documentado no README.
- E2 monetária usa o E1 registrado na análise aprovada de entrada e, no aparelho, no uso aprovado observado. Não reconsulta todos os antigos remetentes a cada pedido nem presume conhecer o estado externo atual deles. A evidência expira em 30 dias. Isso difere da outra versão baseada em snapshots atuais.
- O mock não é apresentado como uma reprodução oficial da API DICT. `EvidenceSince` é uma extensão fictícia para os cenários, não um campo oficial.
- Análises antigas preservam versão, códigos e resposta; somente pedidos novos usam a revisão.

## Método de validação

A referência anterior à mudança passou em 204 testes. A rodada inicial de regressões teve 15 falhas e 2 casos já corretos; após as correções, os 17 passaram. A proteção de identidade também foi conduzida por dois testes que inicialmente receberam 201 quando esperavam 422 e passaram após a correção. Os testes históricos foram atualizados apenas onde afirmavam a política substituída ou a versão anterior.

O restante da validação e seus resultados finais são registrados ao concluir a integração. As fontes são mocks e dados fictícios, sem avaliação empírica de eficácia antifraude.

## Resultado final

- Suíte completa: **229 testes aprovados em 37,89 s**, contra a API com PostgreSQL e Mockserver isolados dos serviços da outra implementação.
- P12 foi ajustado para quatro titulares e E5 somente, e validado separadamente; P14 mantém cinco titulares e verifica E3+E5 sem elevação.
- Flake8 passou em `src`, `tests` e `scripts`; `git diff --check` sem erros.
- Demo: **7 de 7 decisões** esperadas. O grafo distingue aprovações e tentativas rejeitadas, usando análises para desenhar tentativas e apenas vínculos aprovados para aparelhos. A versão de NetworkX agora funciona com Python 3.11.
- A consulta ao mock agora libera a transação de leitura antes da espera HTTP e grava o cache em uma transação curta posterior.

Esta revisão tem sua própria branch `v2/feat/motor-antifraude`; a branch de origem e a outra implementação foram preservadas. Esta validação demonstra aderência aos cenários, sem afirmar eficácia contra fraudes reais.
