from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer


ROOT = Path(__file__).resolve().parents[1]
REPORT_MD = ROOT / "reports" / "factor_research_report.md"
REPORT_PDF = ROOT / "reports" / "factor_research_report.pdf"


def _register_fonts() -> tuple[str, str]:
    candidates = [
        (Path("C:/Windows/Fonts/Deng.ttf"), Path("C:/Windows/Fonts/Dengb.ttf")),
        (Path("C:/Windows/Fonts/simhei.ttf"), Path("C:/Windows/Fonts/simhei.ttf")),
    ]
    for regular_path, bold_path in candidates:
        if regular_path.exists() and bold_path.exists():
            pdfmetrics.registerFont(TTFont("AshareReport", str(regular_path)))
            pdfmetrics.registerFont(TTFont("AshareReportBold", str(bold_path)))
            return "AshareReport", "AshareReportBold"
    raise RuntimeError("No embeddable Chinese font found. Expected Deng.ttf or simhei.ttf in C:/Windows/Fonts.")


def _styles(font_name: str, bold_font_name: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName=bold_font_name, fontSize=20, leading=26, spaceAfter=18),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName=bold_font_name,
            fontSize=14,
            leading=20,
            spaceBefore=12,
            spaceAfter=8,
            textColor=colors.HexColor("#222222"),
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=10.5,
            leading=16,
            firstLineIndent=18,
            spaceAfter=7,
        ),
    }


def _clean(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("`", "")


def _markdown_image(line: str) -> Path | None:
    if not line.startswith("![") or "](" not in line or not line.endswith(")"):
        return None
    rel = line.split("](", 1)[1][:-1]
    path = (REPORT_MD.parent / rel).resolve()
    return path if path.exists() else None


def build_pdf() -> Path:
    body_font, bold_font = _register_fonts()
    styles = _styles(body_font, bold_font)
    story = []
    for raw_line in REPORT_MD.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 0.12 * cm))
            continue
        image_path = _markdown_image(line)
        if image_path is not None:
            story.append(Spacer(1, 0.1 * cm))
            story.append(Image(str(image_path), width=15.5 * cm, height=8.7 * cm, kind="proportional"))
            story.append(Spacer(1, 0.2 * cm))
            continue
        if line.startswith("# "):
            story.append(Paragraph(_clean(line[2:]), styles["title"]))
        elif line.startswith("## "):
            story.append(Paragraph(_clean(line[3:]), styles["h2"]))
        else:
            story.append(Paragraph(_clean(line), styles["body"]))

    doc = SimpleDocTemplate(
        str(REPORT_PDF),
        pagesize=A4,
        rightMargin=1.8 * cm,
        leftMargin=1.8 * cm,
        topMargin=1.7 * cm,
        bottomMargin=1.7 * cm,
    )
    def _decorate_page(canvas, document) -> None:
        canvas.saveState()
        canvas.setFont(body_font, 8)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(1.8 * cm, 0.9 * cm, "A-share multi-factor research framework")
        canvas.drawRightString(A4[0] - 1.8 * cm, 0.9 * cm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_decorate_page, onLaterPages=_decorate_page)
    return REPORT_PDF


if __name__ == "__main__":
    print(build_pdf())
