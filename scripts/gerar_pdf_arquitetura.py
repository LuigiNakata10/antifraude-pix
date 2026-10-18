"""Gera o PDF da arquitetura (v2) a partir de docs/arquitetura-e-dados-v2.md.

Requer Python 3.11+ e reportlab (`pip install -r scripts/requirements.txt`).
Execute da raiz: python scripts/gerar_pdf_arquitetura.py

O PDF da proposta técnica v1 fica em output/pdf/historico/ e não é regerado
por este script. O renderer suporta somente o subconjunto Markdown
usado por este documento (títulos, parágrafos, listas, tabelas, blocos de código
e os marcadores `<!-- diagram:X -->` e `<!-- page -->`). Os blocos Mermaid têm
equivalentes vetoriais desenhados abaixo: mudou um diagrama no Markdown, o
desenho correspondente precisa acompanhar.
"""

from pathlib import Path
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Flowable, KeepTogether, PageBreak, Paragraph, Preformatted,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
VERSION = "2"
SOURCE = ROOT / "docs" / f"arquitetura-e-dados-v{VERSION}.md"
OUTPUT = ROOT / "output" / "pdf" / f"arquitetura-e-dados-v{VERSION}.pdf"
NAVY = colors.HexColor("#172D43")
TEAL = colors.HexColor("#147E83")
INK = colors.HexColor("#25394B")
MUTED = colors.HexColor("#617482")
LIGHT = colors.HexColor("#EEF5F6")
LINE = colors.HexColor("#D9E4E8")
WHITE = colors.white
WIDTH = A4[0] - 88

styles = getSampleStyleSheet()
styles.add(ParagraphStyle("PageTitle", fontName="Helvetica-Bold", fontSize=22,
                          leading=27, textColor=NAVY, spaceBefore=10, spaceAfter=14,
                          keepWithNext=True))
styles.add(ParagraphStyle("Hero", fontName="Helvetica-Bold", fontSize=34,
                          leading=38, textColor=NAVY, spaceAfter=8))
styles.add(ParagraphStyle("SubTitle", fontName="Helvetica", fontSize=19,
                          leading=24, textColor=TEAL, spaceAfter=17))
styles.add(ParagraphStyle("Section", fontName="Helvetica-Bold", fontSize=11.6,
                          leading=15, textColor=TEAL, spaceBefore=13, spaceAfter=7,
                          keepWithNext=True))
styles.add(ParagraphStyle("Copy", fontName="Helvetica", fontSize=10,
                          leading=14.1, textColor=INK, spaceAfter=8))
styles.add(ParagraphStyle("BulletCopy", parent=styles["Copy"], leftIndent=11,
                          firstLineIndent=-9, spaceAfter=5))
styles.add(ParagraphStyle("Cell", fontName="Helvetica", fontSize=8.4,
                          leading=11.4, textColor=INK))
styles.add(ParagraphStyle("CellHead", parent=styles["Cell"], fontName="Helvetica-Bold",
                          textColor=WHITE, fontSize=8.5))
styles.add(ParagraphStyle("Node", fontName="Helvetica-Bold", fontSize=9.3,
                          leading=12.5, textColor=NAVY))
styles.add(ParagraphStyle("NodeSmall", fontName="Helvetica", fontSize=8.5,
                          leading=11.3, textColor=INK))
styles.add(ParagraphStyle("CodeCopy", fontName="Courier", fontSize=7.8,
                          leading=10.4, textColor=NAVY, backColor=LIGHT,
                          borderColor=LINE, borderWidth=0.5, borderPadding=9,
                          spaceBefore=4, spaceAfter=11))


def rich(text):
    text = escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+)`", r'<font name="Courier" size="8.5">\1</font>', text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)",
                  r'<link href="\2" color="#147E83">\1</link>', text)
    for tag in ("br/", "b", "/b"):
        text = text.replace(escape(f"<{tag}>"), f"<{tag}>")
    return text


def para(text, name="Copy"):
    return Paragraph(rich(text), styles[name])


class Diagram(Flowable):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.width = WIDTH
        self.height = {"model": 360, "post": 372, "decision": 500}[kind]

    def text(self, text, x, y, w, style="Node", max_height=60):
        p = para(text, style)
        _, h = p.wrap(w, max_height)
        p.drawOn(self.canv, x, y - h)
        return h

    def box(self, text, x, y, w, h, fill=LIGHT, style="Node", stroke=LINE):
        c = self.canv
        c.setFillColor(fill)
        c.setStrokeColor(stroke)
        c.roundRect(x, y, w, h, 6, stroke=1, fill=1)
        p = para(text, style)
        _, ph = p.wrap(w - 19, h - 12)
        if ph > h - 9:
            raise ValueError(f"Texto excede o nó: {text}")
        p.drawOn(c, x + 9.5, y + (h - ph) / 2)

    def arrow(self, x1, y1, x2, y2, label=None):
        c = self.canv
        c.setStrokeColor(MUTED)
        c.setFillColor(MUTED)
        c.setLineWidth(0.9)
        c.line(x1, y1, x2, y2)
        path = c.beginPath()
        if abs(y2 - y1) > abs(x2 - x1):
            direction = 1 if y2 > y1 else -1
            path.moveTo(x2, y2)
            path.lineTo(x2 - 3, y2 - direction * 5)
            path.lineTo(x2 + 3, y2 - direction * 5)
        else:
            direction = 1 if x2 > x1 else -1
            path.moveTo(x2, y2)
            path.lineTo(x2 - direction * 5, y2 - 3)
            path.lineTo(x2 - direction * 5, y2 + 3)
        path.close()
        c.drawPath(path, fill=1, stroke=0)
        if label:
            c.setFont("Helvetica", 7)
            c.drawString((x1 + x2) / 2 + 3, (y1 + y2) / 2 + 4, label)

    def card(self, x, y, w, h, title, fields):
        c = self.canv
        c.setStrokeColor(LINE)
        c.setFillColor(WHITE)
        c.roundRect(x, y, w, h, 7, fill=1, stroke=1)
        c.setFillColor(NAVY)
        c.roundRect(x, y + h - 36, w, 36, 7, fill=1, stroke=0)
        c.rect(x, y + h - 36, w, 14, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 11.5)
        c.drawString(x + 12, y + h - 23, title)
        for i, field in enumerate(fields):
            self.text(field, x + 12, y + h - 44 - i * 25, w - 24, "NodeSmall")

    def model(self):
        c = self.canv
        top, h = 168, 190
        self.card(0, top, 140, h, "payer_account", ["id (PK)", "branch + account_number (UNIQUE)", "created_at"])
        self.card(165, top, 190, h, "pix_analysis", [
            "id (PK), transaction_id (UNIQUE)", "analysis_key (UNIQUE), payer_account_id (FK)",
            "valor, datas, aparelho, destino", "payer_dict_e1/e4, destination_dict_e1/e4",
            "status, reason_code, metadata", "analysis_details, request_payload"])
        self.card(380, top, WIDTH - 380, h, "account_link", [
            "id (PK)", "pix_analysis_id (FK)", "from_key, to_key", "link_type: pix, device, document",
            "amount (só pix), seen_at"])
        self.arrow(140, top + 95, 165, top + 95)
        self.arrow(355, top + 95, 380, top + 95)
        c.setFillColor(TEAL)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(152, top + 103, "1:N")
        c.drawCentredString(367, top + 103, "1:N")
        self.card(165, 0, 190, 146, "dict_lookup", ["id (PK)", "account_key (ispb:agência:conta)", "response (JSONB)", "fetched_at"])
        self.text("Cache do DICT, append-only: vale a linha mais recente dentro da validade (pagador 24h, destino 1h).",
                  0, 134, 150, "NodeSmall")
        self.text("Sem chave estrangeira: a conta é identificada pela chave ispb:agência:conta, a mesma do grafo.",
                  380, 134, WIDTH - 380, "NodeSmall")

    def post(self):
        labels = ["1. Validar e normalizar", "2. Consultar o ID", "3. Consultar o DICT (cache ou ao vivo)",
                  "4. Obter e travar a conta", "5. Rever ID, ordem e identidade; montar contexto",
                  "6. Aplicar R1 > R2 > L1 > L2 > L3 > R4 > R3 > R5", "7. Gravar análise (e arestas, se aprovada); commit",
                  "8. Responder o contrato"]
        main_w, side_x = 303, 348
        ys = [self.height - 36 - i * 46 for i in range(len(labels))]
        for i, (label, y) in enumerate(zip(labels, ys)):
            self.box(label, 0, y, main_w, 35)
            if i:
                self.arrow(main_w / 2, ys[i - 1], main_w / 2, y + 35)
        self.box("Erro de entrada: 400 ou 422", side_x, ys[0], WIDTH - side_x, 35, style="NodeSmall")
        self.arrow(main_w, ys[0] + 17.5, side_x, ys[0] + 17.5)
        self.text("inválido", main_w + 1, ys[0] + 34, side_x - main_w, "NodeSmall")
        self.box("ID existente:<br/>mesmos dados: original (200)<br/>outros dados: conflito (409)",
                 side_x, ys[1] - 8, WIDTH - side_x, 50, style="NodeSmall")
        self.arrow(main_w, ys[1] + 17.5, side_x, ys[1] + 17.5)
        self.text("novo ID", main_w / 2 + 7, ys[1] - 2, 90, "NodeSmall")
        self.text("Fora da transação, prazo de 200 ms. Indisponível: desconhecido, nunca decisão.",
                  side_x, ys[2] + 33, WIDTH - side_x, "NodeSmall")
        self.text("FOR NO KEY UPDATE. Espera acima de 5 s: 503, sem gravar.",
                  side_x, ys[3] + 33, WIDTH - side_x, "NodeSmall")
        self.text("Retroativo ou identidade divergente: 422.",
                  side_x, ys[4] + 33, WIDTH - side_x, "NodeSmall")
        self.text("Falha de gravação:<br/>rollback e erro técnico.",
                  side_x, ys[6] + 34, WIDTH - side_x, "NodeSmall")

    def decision(self):
        main_w, side_x, h, gap = 303, 348, 39, 15
        checks = ["R1: conta nova e total > R$ 1.000?", "R2: total > R$ 20.000?",
                  "L1: destino em suspeita elevada e sem relação?",
                  "L2: pagador em suspeita elevada e ato não típico?",
                  "L3: pagador em suspeita e repasse aparente?",
                  "R4: Pix >= R$ 5.000 e aparelho novo?", "R3: ao menos 3 tentativas em 2min?",
                  "R5: Pix > 10 x maior(média, R$ 500)?"]
        results = ["rejected<br/><b>Motivo: R1</b>", "rejected<br/><b>Motivo: R2</b>",
                   "rejected<br/><b>Motivo: L1</b>", "rejected<br/><b>Motivo: L2</b>",
                   "rejected<br/><b>Motivo: L3</b>",
                   "two_factor_required<br/><b>Motivo: R4</b>", "two_factor_required<br/><b>Motivo: R3</b>",
                   "two_factor_required<br/><b>Motivo: R5</b>"]
        ys = [self.height - 5 - h - i * (h + gap) for i in range(len(checks) + 1)]
        for i, check in enumerate(checks):
            self.box(check, 0, ys[i], main_w, h)
            self.box(results[i], side_x, ys[i], WIDTH - side_x, h, style="NodeSmall")
            self.arrow(main_w, ys[i] + h / 2, side_x, ys[i] + h / 2, "sim")
            self.arrow(main_w / 2, ys[i], main_w / 2, ys[i + 1] + h)
            self.text("não", main_w / 2 + 8, ys[i] - 1, 35, "NodeSmall")
        self.box("approved: POLICY_PASSED", 0, ys[len(checks)], main_w, h)

    def draw(self):
        getattr(self, self.kind)()


def make_table(lines):
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in lines]
    rows = [row for row in rows if not all(re.fullmatch(r"[:\- ]+", c) for c in row)]
    n = len(rows[0])
    first = rows[0][0]
    if n == 3:
        widths = {
            "Campo": [130, 117, WIDTH - 247],
            "Ordem": [66, WIDTH - 191, 125],
            "Indicador": [133, WIDTH - 177, 44],
            "Tema": [92, (WIDTH - 92) / 2, (WIDTH - 92) / 2],
            "Tabela": [92, 235, WIDTH - 327],
            "Situação": [210, 120, WIDTH - 330],
            "Camada": [80, 175, WIDTH - 255],
        }.get(first, [WIDTH / 3] * 3)
    elif n == 4:
        widths = [88, 170, 110, WIDTH - 368]
    else:
        widths = [145, WIDTH - 145]
    data = [[para(c, "CellHead" if i == 0 else "Cell") for c in row]
            for i, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, TEAL),
        ("LINEBELOW", (0, 1), (-1, -1), 0.35, LINE),
    ]))
    return [t, Spacer(1, 9)]


def parse_page(text, index):
    lines = text.strip().splitlines()
    out, i = [], 0
    diagram_kind = None
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("<!-- diagram:"):
            diagram_kind = line.split(":", 1)[1].split("-->")[0].strip()
            i += 1
            continue
        if line.startswith("```"):
            language = line[3:]
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            if language == "mermaid":
                if not diagram_kind:
                    raise ValueError("Diagrama sem equivalente vetorial")
                out.extend([Diagram(diagram_kind), Spacer(1, 8)])
                diagram_kind = None
            else:
                out.append(KeepTogether([Preformatted("\n".join(code), styles["CodeCopy"])]))
            i += 1
            continue
        if line.startswith("|"):
            table = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table.append(lines[i])
                i += 1
            out.extend(make_table(table))
            continue
        if line.startswith("### "):
            out.append(para(line[4:], "Section"))
        elif line.startswith("## "):
            out.append(para(line[3:], "SubTitle" if index == 0 else "Section"))
        elif line.startswith("# "):
            out.append(para(line[2:], "Hero" if index == 0 else "PageTitle"))
        elif line.startswith("- ") or re.match(r"\d+\. ", line):
            label = "- " if line.startswith("- ") else re.match(r"\d+\. ", line).group()
            out.append(para(label + line[len(label):], "BulletCopy"))
        else:
            paragraph = [line]
            while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r"^(#|\||-|\d+\. |```|<!--)", lines[i + 1].strip()):
                i += 1
                paragraph.append(lines[i].strip())
            out.append(para(" ".join(paragraph)))
        i += 1
    return out


def page_header(c, doc):
    c.saveState()
    c.setFillColor(TEAL)
    c.rect(0, A4[1] - 8, A4[0], 8, stroke=0, fill=1)
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(44, A4[1] - 33, "QI TECH BOOTCAMP  /  ANTIFRAUDE PIX")
    c.setFont("Helvetica", 8)
    c.drawRightString(A4[0] - 44, A4[1] - 33, f"IMPLEMENTAÇÃO  /  VERSÃO {VERSION}")
    c.setStrokeColor(LINE)
    c.line(44, 37, A4[0] - 44, 37)
    c.restoreState()


class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.states = []

    def showPage(self):
        self.states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self.states)
        for state in self.states:
            self.__dict__.update(state)
            self.saveState()
            self.setFillColor(MUTED)
            self.setFont("Helvetica", 8)
            self.drawString(44, 23, f"18.10.2026  |  Arquitetura e dados (v{VERSION}, pix-v1.3)")
            self.setFont("Helvetica-Bold", 8)
            self.drawRightString(A4[0] - 44, 23, f"{self._pageNumber:02d} / {total:02d}")
            self.restoreState()
            super().showPage()
        super().save()


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    source = SOURCE.read_text(encoding="utf-8")
    source = source.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    pages = source.split("<!-- page -->")
    story = []
    for i, page in enumerate(pages):
        if i:
            story.append(PageBreak())
        story.extend(parse_page(page, i))
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=A4, rightMargin=44, leftMargin=44,
                            topMargin=59, bottomMargin=51, title=f"Antifraude Pix - Arquitetura e dados (v{VERSION})",
                            author="Projeto do Bootcamp QI Tech", subject=f"Como o motor foi implementado - versão {VERSION}")
    doc.build(story, onFirstPage=page_header, onLaterPages=page_header, canvasmaker=NumberedCanvas)
    print(OUTPUT)


if __name__ == "__main__":
    main()
