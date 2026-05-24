# Generates a clean clinical PDF report from a RAG answer.
# Uses ReportLab — pure Python, no external binaries needed.
# The single public function generate_pdf() returns raw bytes


from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    HRFlowable, Table, TableStyle,
)
from reportlab.lib import colors


# ── Brand colours ─────────────────────────────────────────────
# Defined once here — change here and the whole PDF updates.
TEAL        = colors.HexColor("#1D9E75")
TEAL_LIGHT  = colors.HexColor("#E1F5EE")
TEAL_DARK   = colors.HexColor("#085041")
AMBER       = colors.HexColor("#EF9F27")
AMBER_LIGHT = colors.HexColor("#FEF9F0")
AMBER_DARK  = colors.HexColor("#633806")
GRAY        = colors.HexColor("#888780")
GRAY_LIGHT  = colors.HexColor("#F1EFE8")
BLUE        = colors.HexColor("#185FA5")
BLACK       = colors.HexColor("#111111")
WHITE       = colors.white


# ── Paragraph styles ──────────────────────────────────────────
# ReportLab uses style objects to control typography.
# Define all styles up front — keeps the builder functions clean.

def _styles():
    return {
        "brand": ParagraphStyle(
            "brand",
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=TEAL,
            leading=14,
        ),
        "meta": ParagraphStyle(
            "meta",
            fontName="Helvetica",
            fontSize=8,
            textColor=GRAY,
            leading=12,
            alignment=TA_RIGHT,
        ),
        "label": ParagraphStyle(
            "label",
            fontName="Helvetica-Bold",
            fontSize=7,
            textColor=TEAL,
            leading=10,
            # Simulates letter-spacing with word spacing
            wordSpace=2,
        ),
        "question": ParagraphStyle(
            "question",
            fontName="Times-Bold",
            fontSize=15,
            textColor=BLACK,
            leading=22,
            spaceAfter=4,
        ),
        "answer": ParagraphStyle(
            "answer",
            fontName="Times-Roman",
            fontSize=11,
            textColor=colors.HexColor("#222222"),
            leading=18,
            spaceAfter=6,
        ),
        "source_num": ParagraphStyle(
            "source_num",
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=TEAL,
            leading=14,
        ),
        "source_url": ParagraphStyle(
            "source_url",
            fontName="Helvetica",
            fontSize=9,
            textColor=BLUE,
            leading=14,
        ),
        "followup": ParagraphStyle(
            "followup",
            fontName="Helvetica",
            fontSize=10,
            textColor=colors.HexColor("#444444"),
            leading=15,
            leftIndent=12,
        ),
        "disclaimer": ParagraphStyle(
            "disclaimer",
            fontName="Helvetica",
            fontSize=8,
            textColor=AMBER_DARK,
            leading=13,
        ),
        "footer": ParagraphStyle(
            "footer",
            fontName="Helvetica",
            fontSize=7,
            textColor=GRAY,
            leading=11,
        ),
        "footer_right": ParagraphStyle(
            "footer_right",
            fontName="Helvetica",
            fontSize=7,
            textColor=GRAY,
            leading=11,
            alignment=TA_RIGHT,
        ),
    }


# ── Confidence bar ────────────────────────────────────────────
# ReportLab has no native progress bar — we fake one with a
# two-cell Table: filled cell + empty cell, widths proportional
# to the confidence score.

def _confidence_bar(confidence, page_width):
    s = _styles()
    bar_total  = page_width - 40*mm   # leave margin
    filled     = bar_total * (confidence / 100)
    empty      = bar_total - filled

    bar_table = Table(
        [["", ""]],
        colWidths=[filled, empty],
        rowHeights=[5],
    )
    bar_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), TEAL),
        ("BACKGROUND", (1, 0), (1, 0), TEAL_LIGHT),
        ("LINEABOVE",  (0, 0), (-1, 0), 0, colors.transparent),
        ("LINEBELOW",  (0, 0), (-1, 0), 0, colors.transparent),
        ("LINEBEFORE", (0, 0), (-1, 0), 0, colors.transparent),
        ("LINEAFTER",  (0, 0), (-1, 0), 0, colors.transparent),
        ("ROUNDEDCORNERS", [3]),
    ]))

    # Wrap the bar in a container table with the label and percentage
    container = Table(
        [[
            Paragraph("Evidence confidence", s["label"]),
            bar_table,
            Paragraph(f"<b>{confidence}%</b>", s["source_num"]),
        ]],
        colWidths=[100, bar_total - 60, 40],
        rowHeights=[20],
    )
    container.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), TEAL_LIGHT),
        ("LEFTPADDING",  (0, 0), (-1, 0), 10),
        ("RIGHTPADDING", (0, 0), (-1, 0), 10),
        ("TOPPADDING",   (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING",(0, 0), (-1, 0), 7),
        ("ROUNDEDCORNERS", [4]),
        ("BOX", (0, 0), (-1, -1), 0.5,
         colors.HexColor("#9FE1CB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return container


# ── Numbered Canvas for Dynamic Page Numbering ─────────────────
# ReportLab processes pages in order. To draw a "Page X of Y" footer,
# we need a two-pass canvas that saves the state of each page,
# calculates the total count, and draws the footers retroactively before saving.

from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 7)
        self.setFillColor(colors.HexColor("#888780"))
        
        # Draw a thin horizontal dividing line above the footer
        self.setStrokeColor(colors.HexColor("#E1EFE8"))
        self.setLineWidth(0.5)
        self.line(20*mm, 15*mm, A4[0] - 20*mm, 15*mm)
        
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(A4[0] - 20*mm, 10*mm, page_text)
        
        self.drawString(20*mm, 10*mm, "ClinicalRAG · Generated clinical report · Evidance")
        self.restoreState()


# ── Main builder ──────────────────────────────────────────────
# Assembles all the flowable elements in document order across all
# conversation turns, then builds the PDF with dynamic page footers.

from reportlab.platypus import PageBreak

def generate_pdf(history, name="Anonymous"):
    buffer     = BytesIO()
    page_w, _  = A4
    s          = _styles()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20*mm,
        rightMargin=20*mm,
        topMargin=18*mm,
        bottomMargin=20*mm,  # Extra bottom margin to clear the footer
    )

    timestamp = datetime.utcnow().strftime("%d %b %Y · %H:%M UTC")
    elements  = []

    # ── Header (First Page Only) ──────────────────────────────
    header_table = Table(
        [[
            Paragraph("ClinicalRAG", s["brand"]),
            Paragraph(
                f"Generated: {timestamp}<br/>"
                f"Prepared for: <b>{name}</b><br/>"
                f"Source: PubMed literature database",
                s["meta"],
            ),
        ]],
        colWidths=[page_w * 0.4, page_w * 0.45],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW",     (0, 0), (-1, 0),  1.5, TEAL),
        ("BOTTOMPADDING", (0, 0), (-1, 0),  10),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 14))

    # ── Iterate Turns ─────────────────────────────────────────
    for idx, turn in enumerate(history, 1):
        question   = turn.get("question", "")
        answer     = turn.get("answer", "")
        sources    = turn.get("sources", [])
        confidence = turn.get("confidence", 0)

        # ── Turn Header ───────────────────────────────────────
        elements.append(Paragraph(f"CLINICAL QUESTION {idx}", s["label"]))
        elements.append(Spacer(1, 5))
        elements.append(Paragraph(question, s["question"]))
        elements.append(Spacer(1, 10))

        # ── Confidence Bar ────────────────────────────────────
        elements.append(_confidence_bar(confidence, page_w))
        elements.append(Spacer(1, 16))

        # ── Answer ────────────────────────────────────────────
        elements.append(Paragraph("EVIDENCE-BASED ANSWER", s["label"]))
        elements.append(HRFlowable(
            width="100%", thickness=0.5,
            color=GRAY_LIGHT, spaceAfter=8,
        ))
        formatted_answer = answer.replace("\n\n", "<br/><br/>").replace("\n", " ")
        elements.append(Paragraph(formatted_answer, s["answer"]))
        elements.append(Spacer(1, 16))

        # ── Ghana NHIS & Drug Registry (If Available) ─────────
        drugs = turn.get("drugs", [])
        if drugs:
            elements.append(Paragraph("GHANA NHIS & REGIONAL DRUG REGISTRY", s["label"]))
            elements.append(HRFlowable(
                width="100%", thickness=0.5,
                color=GRAY_LIGHT, spaceAfter=8,
            ))
            
            # Headers
            table_data = [[
                Paragraph("<b>Medication Name</b>", s["source_num"]),
                Paragraph("<b>NHIS Status</b>", s["source_num"]),
                Paragraph("<b>Facility Availability / Clinical Notes</b>", s["source_num"]),
            ]]
            
            # Add drug rows
            for drug in drugs:
                nhis_text = drug.get("nhis", "Unknown")
                if nhis_text == "Covered":
                    nhis_styled = f'<font color="{TEAL_DARK}"><b>Covered</b></font>'
                elif nhis_text == "Free Program":
                    nhis_styled = f'<font color="{BLUE}"><b>Free Program</b></font>'
                else:
                    nhis_styled = f'<b>{nhis_text}</b>'
                    
                table_data.append([
                    Paragraph(drug.get("name", ""), s["followup"]),
                    Paragraph(nhis_styled, s["followup"]),
                    Paragraph(drug.get("status", ""), s["followup"]),
                ])
                
            drug_table = Table(table_data, colWidths=[130, 90, page_w - 40*mm - 220])
            drug_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), TEAL_LIGHT),
                ("GRID", (0, 0), (-1, -1), 0.5, GRAY_LIGHT),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]))
            elements.append(drug_table)
            elements.append(Spacer(1, 16))


        # ── Sources ───────────────────────────────────────────
        if sources:
            elements.append(Paragraph("PUBMED SOURCES", s["label"]))
            elements.append(HRFlowable(
                width="100%", thickness=0.5,
                color=GRAY_LIGHT, spaceAfter=8,
            ))
            for i, url in enumerate(sources, 1):
                row = Table(
                    [[
                        Paragraph(f"[{i}]", s["source_num"]),
                        Paragraph(f'<link href="{url}">{url}</link>', s["source_url"]),
                    ]],
                    colWidths=[20, page_w - 60*mm - 20],
                )
                row.setStyle(TableStyle([
                    ("VALIGN",       (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
                ]))
                elements.append(row)
            elements.append(Spacer(1, 16))

        # Add page break if there are subsequent turns
        if idx < len(history):
            elements.append(PageBreak())

    # ── Disclaimer (At the very end) ──────────────────────────
    elements.append(Spacer(1, 8))
    disclaimer_table = Table(
        [[Paragraph(
            "<b>Research use only.</b> This document was generated by an AI system "
            "using PubMed literature retrieval and does not constitute clinical advice. "
            "Always consult a qualified healthcare professional before making clinical "
            "decisions. Evidence may not reflect local treatment guidelines.",
            s["disclaimer"],
        )]],
        colWidths=[page_w - 40*mm],
    )
    disclaimer_table.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), AMBER_LIGHT),
        ("LINEBEFORE",   (0, 0), (0, -1),  3, AMBER),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
    ]))
    elements.append(disclaimer_table)

    # Build the document using the dynamic NumberedCanvas
    doc.build(elements, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer.read()