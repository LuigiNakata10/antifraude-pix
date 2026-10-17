# Antifraude Pix - protótipo de estudo

Documentação inicial para o desafio do Bootcamp QI Tech 2026. O motor ainda não está implementado; o repositório registra a política e uma proposta de dados e fluxo para revisão.

## Documentos

- [Dados e fluxo de análise - PDF](output/pdf/dados-e-fluxo-antifraude-pix.pdf): modelo de duas tabelas, histórico necessário, fluxos do POST e da decisão, persistência e pendências.
- [Fonte editável do desenho](docs/dados-e-fluxo.md): mesma estrutura e conteúdo do PDF, com diagramas Mermaid.
- [Política de negócio](docs/regras-de-negocio.md): regras acordadas, justificativas, limitações e 21 cenários esperados.

As convenções técnicas do desenho são propostas, não substituem as decisões de negócio. Os parâmetros são próprios do protótipo e não representam eficácia comprovada ou limites universais dos bancos.

## Gerar o PDF

Com Python 3.11 ou superior e a biblioteca `reportlab` instalada:

```bash
python scripts/gerar_pdf_dados_fluxo.py
```

O script lê a fonte Markdown e atualiza `output/pdf/dados-e-fluxo-antifraude-pix.pdf`. Os fluxos do PDF são desenhos vetoriais equivalentes aos blocos Mermaid. Este renderer é específico para o documento, não um conversor Markdown genérico.
