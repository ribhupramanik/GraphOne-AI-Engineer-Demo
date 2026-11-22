from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")
OUT = ROOT / "architecture.pdf"

NAVY = colors.HexColor("#13253A")
TEAL = colors.HexColor("#168F95")
GRAY = colors.HexColor("#526479")

head = ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=17, leading=22, textColor=NAVY, spaceAfter=15)
section = ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=TEAL, spaceBefore=7, spaceAfter=13)
body = ParagraphStyle("body", fontName="Helvetica", fontSize=10.6, leading=15.8, textColor=NAVY, spaceAfter=16, alignment=TA_LEFT)


def make_markup(paragraph):
    markup = escape(paragraph)
    parts = markup.split("**")
    return "".join("<b>" + s + "</b>" if i % 2 else s for i, s in enumerate(parts))


def draw_background(canvas, doc):
    canvas.saveState()
    w, h = doc.pagesize
    canvas.setFillColor(NAVY)
    canvas.rect(0, h - 10, w, 10, fill=1, stroke=0)
    canvas.setFillColor(TEAL)
    canvas.rect(44, h - 44, 30, 3, fill=1, stroke=0)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(GRAY)
    canvas.drawString(44, 38, "GraphOne / FrontierAtlas  |  AI Engineer Demo Task")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(w - 44, 38, f"ARCHITECTURE  /  {doc.page} OF 3")
    canvas.restoreState()


class ThreePageDoc(BaseDocTemplate):
    def __init__(self, filename):
        super().__init__(filename, pagesize=(612, 792), leftMargin=44, rightMargin=44,
                         topMargin=53, bottomMargin=52, title="GraphOne | Three-Page Architecture", author="AI Engineer Assessment")
        frame = Frame(44, 52, 524, 688, leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0)
        self.addPageTemplates(PageTemplate(id="main", frames=[frame], onPage=draw_background))


sections = TEXT.split("\n## ")[1:]
story = []
for idx, chunk in enumerate(sections):
    title_line, body_text = chunk.split("\n", 1)
    if idx:
        story.append(PageBreak())
    story.append(Paragraph("GRAPH INTELLIGENCE  /  SYSTEM DESIGN", head))
    story.append(Paragraph(escape(title_line), section))
    if idx == 0:
        flow = Table([["SOURCE APIs", "ASYNC WORKERS", "EVIDENCE + DB", "EXPORT"]], colWidths=[116, 133, 149, 126], rowHeights=[33])
        flow.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EDF6F7")),
            ("TEXTCOLOR", (0, 0), (-1, -1), NAVY),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.3),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -1), 1, TEAL),
        ]))
        story.append(flow)
        story.append(Spacer(1, 12))
    for para in body_text.strip().split("\n\n"):
        if para.strip():
            story.append(Paragraph(make_markup(para.strip()), body))
ThreePageDoc(str(OUT)).build(story)
print(OUT)
