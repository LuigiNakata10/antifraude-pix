"""Gera o PDF de proposta a partir de docs/dados-e-fluxo.md.

Requer Python 3.11+ e reportlab. Execute da raiz: python scripts/gerar_pdf_dados_fluxo.py
O renderer suporta somente o subconjunto Markdown usado por este documento.
Os blocos Mermaid têm equivalentes vetoriais desenhados abaixo.
"""

from pathlib import Path
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Flowable, PageBreak, Paragraph, Preformatted,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "dados-e-fluxo.md"
OUTPUT = ROOT / "output" / "pdf" / "dados-e-fluxo-antifraude-pix.pdf"
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
                          leading=27, textColor=NAVY, spaceAfter=14))
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
        self.height = {"model": 184, "post": 327, "decision": 280}[kind]

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

    def model(self):
        c = self.canv
        cards = [
            (0, 185, "payer_account", ["id (PK)", "branch", "account_number", "created_at"]),
            (265, WIDTH - 265, "pix_analysis", ["id (PK), transaction_id (UNIQUE)", "key (UNIQUE)", "payer_account_id (FK)", "payload + decisão + metadata"]),
        ]
        for x, w, title, fields in cards:
            c.setStrokeColor(LINE)
            c.setFillColor(WHITE)
            c.roundRect(x, 12, w, 164, 7, fill=1, stroke=1)
            c.setFillColor(NAVY)
            c.roundRect(x, 140, w, 36, 7, fill=1, stroke=0)
            c.rect(x, 140, w, 14, fill=1, stroke=0)
            c.setFillColor(WHITE)
            c.setFont("Helvetica-Bold", 12)
            c.drawString(x + 12, 153, title)
            for i, field in enumerate(fields):
                self.text(field, x + 12, 126 - i * 27, w - 24, "NodeSmall")
        self.arrow(185, 90, 265, 90)
        c.setFillColor(TEAL)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(225, 103, "1 : N")

    def post(self):
        labels = ["1. Validar e normalizar", "2. Consultar o ID", "3. Obter e travar a conta",
                  "4. Rever ID e consultar histórico", "5. Aplicar R1 > R2 > R4 > R3",
                  "6. Gravar análise e fazer commit", "7. Responder o contrato"]
        main_w, side_x = 303, 348
        ys = [self.height - 36 - i * 47 for i in range(len(labels))]
        for i, (label, y) in enumerate(zip(labels, ys)):
            self.box(label, 0, y, main_w, 35)
            if i:
                self.arrow(main_w / 2, ys[i - 1], main_w / 2, y + 35)
        self.box("Erro de entrada", side_x, ys[0], WIDTH - side_x, 35, style="NodeSmall")
        self.arrow(main_w, ys[0] + 17.5, side_x, ys[0] + 17.5)
        self.text("inválido", main_w + 1, ys[0] + 34, side_x - main_w, "NodeSmall")
        self.box("ID existente:<br/>mesmos dados: original<br/>outros dados: conflito",
                 side_x, ys[1] - 28, WIDTH - side_x, 70, style="NodeSmall")
        self.arrow(main_w, ys[1] + 17.5, side_x, ys[1] + 17.5)
        self.text("novo ID", main_w / 2 + 7, ys[1] - 2, 90, "NodeSmall")
        self.text("Unidade de trabalho no banco: leitura consistente, decisão e gravação.",
                  side_x, ys[3] + 33, WIDTH - side_x, "NodeSmall")
        self.text("Falha de gravação:<br/>rollback e erro técnico.",
                  side_x, ys[5] + 34, WIDTH - side_x, "NodeSmall")

    def decision(self):
        main_w, side_x, h, gap = 303, 348, 39, 16
        checks = ["R1: conta nova e total > R$ 1.000?", "R2: total > R$ 10.000?",
                  "R4: Pix >= R$ 5.000 e aparelho novo?", "R3: ao menos 3 tentativas em 2min?"]
        results = ["rejected<br/><b>Motivo: R1</b>", "rejected<br/><b>Motivo: R2</b>",
                   "two_factor_required<br/><b>Motivo: R4</b>", "two_factor_required<br/><b>Motivo: R3</b>"]
        ys = [self.height - h - i * (h + gap) for i in range(5)]
        for i, check in enumerate(checks):
            self.box(check, 0, ys[i], main_w, h)
            self.box(results[i], side_x, ys[i], WIDTH - side_x, h, style="NodeSmall")
            self.arrow(main_w, ys[i] + h / 2, side_x, ys[i] + h / 2, "sim")
            self.arrow(main_w / 2, ys[i], main_w / 2, ys[i + 1] + h)
            self.text("não", main_w / 2 + 8, ys[i] - 1, 35, "NodeSmall")
        self.box("approved: POLICY_PASSED", 0, ys[4], main_w, h)

    def draw(self):
        getattr(self, self.kind)()


def make_table(lines):
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in lines]
    rows = [row for row in rows if not all(re.fullmatch(r"[:\- ]+", c) for c in row)]
    n = len(rows[0])
    if n == 3:
        if rows[0][0] == "Campo":
            widths = [130, 117, WIDTH - 247]
        elif rows[0][0] == "Ordem":
            widths = [66, WIDTH - 191, 125]
        elif rows[0][0] == "Indicador":
            widths = [133, WIDTH - 177, 44]
        else:
            widths = [WIDTH / 3] * 3
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
                out.append(Preformatted("\n".join(code), styles["CodeCopy"]))
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
    c.drawRightString(A4[0] - 44, A4[1] - 33, "PROPOSTA TÉCNICA 0.1")
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
            self.drawString(44, 23, "17.10.2026  |  Dados, regras e fluxo de análise")
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
                            topMargin=59, bottomMargin=51, title="Antifraude Pix - Dados e fluxo de análise",
                            author="Projeto do Bootcamp QI Tech", subject="Proposta técnica inicial 0.1")
    doc.build(story, onFirstPage=page_header, onLaterPages=page_header, canvasmaker=NumberedCanvas)
    print(OUTPUT)


if __name__ == "__main__":
    main()
