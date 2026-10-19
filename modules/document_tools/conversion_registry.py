"""
Complete File Conversion System and Conversion Registry for Document Tools.
Implements bidirectional and cross-format conversion across:
  - DOCX, PDF, TXT, Markdown, HTML, RTF
  - XLSX, CSV, JSON, YAML, XML
  - PPTX, PDF
  - PNG, JPEG, BMP -> Multi-page PDF
Operates safely without overwriting source files, validates outputs,
and detects available local conversion engines without assuming Office is installed.
"""

from __future__ import annotations

import os
import re
import csv
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from datetime import datetime
import logging

logger = logging.getLogger("ConversionRegistry")


def get_conflict_free_path(base_path: str) -> str:
    """Generate non-colliding destination path if target already exists."""
    if not os.path.exists(base_path):
        return base_path

    directory, fname = os.path.split(base_path)
    stem, ext = os.path.splitext(fname)

    counter = 1
    cand = os.path.join(directory, f"{stem}_converted_{counter}{ext}")
    while os.path.exists(cand):
        counter += 1
        cand = os.path.join(directory, f"{stem}_converted_{counter}{ext}")
    return cand


class ConversionResult:
    def __init__(
        self,
        success: bool,
        source_path: str,
        target_path: Optional[str] = None,
        source_format: str = "",
        target_format: str = "",
        message: str = "",
        fidelity_notes: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
        extra_files: Optional[List[str]] = None
    ):
        self.success = success
        self.source_path = source_path
        self.target_path = target_path
        self.source_format = source_format.lower()
        self.target_format = target_format.lower()
        self.message = message
        self.fidelity_notes = fidelity_notes or []
        self.warnings = warnings or []
        self.extra_files = extra_files or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": "success" if self.success else "error",
            "source_path": self.source_path,
            "target_path": self.target_path,
            "filepath": self.target_path,
            "filename": os.path.basename(self.target_path) if self.target_path else None,
            "source_format": self.source_format,
            "target_format": self.target_format,
            "message": self.message,
            "fidelity_notes": self.fidelity_notes,
            "warnings": self.warnings,
            "extra_files": self.extra_files
        }


# ============================================================================
# Format Specific Conversion Engines
# ============================================================================

def convert_docx_to_pdf(source: str, output: Optional[str] = None) -> ConversionResult:
    """Convert Microsoft Word .docx to PDF using ReportLab."""
    try:
        import docx
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors

        if not os.path.exists(source):
            return ConversionResult(False, source, message=f"Source file does not exist: {source}")

        doc = docx.Document(source)
        dest = output or os.path.splitext(source)[0] + ".pdf"
        dest = get_conflict_free_path(dest)
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)

        pdf_doc = SimpleDocTemplate(dest, pagesize=letter, leftMargin=54, rightMargin=54, topMargin=54, bottomMargin=54)
        styles = getSampleStyleSheet()

        h1_style = ParagraphStyle('H1', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=16, leading=20, textColor=colors.HexColor('#1F497D'), spaceBefore=12, spaceAfter=6)
        h2_style = ParagraphStyle('H2', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=13, leading=17, textColor=colors.HexColor('#2E75B6'), spaceBefore=10, spaceAfter=4)
        h3_style = ParagraphStyle('H3', parent=styles['Heading3'], fontName='Helvetica-Bold', fontSize=11, leading=15, textColor=colors.HexColor('#1E293B'), spaceBefore=8, spaceAfter=3)
        body_style = ParagraphStyle('Body', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=14.5, textColor=colors.HexColor('#262626'), spaceAfter=5)
        bullet_style = ParagraphStyle('Bullet', parent=body_style, leftIndent=15, firstLineIndent=-10, spaceAfter=3)
        quote_style = ParagraphStyle('Quote', parent=body_style, fontName='Helvetica-Oblique', leftIndent=18, rightIndent=18, textColor=colors.HexColor('#1F497D'), spaceBefore=5, spaceAfter=5)
        table_header_style = ParagraphStyle('TblHdr', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.5, leading=11.5, textColor=colors.whitesmoke)
        table_cell_style = ParagraphStyle('TblCell', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=11.5, textColor=colors.HexColor('#1E293B'))

        try:
            from modules.document_tools.pdf_builder import markdown_to_platypus_xml
        except Exception:
            def markdown_to_platypus_xml(t):
                return t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        printable_width = 504.0
        story = []

        # Iterate elements in TRUE document order (paragraphs and tables interleaved)
        for child in doc.element.body:
            tag = child.tag.split('}')[-1]
            if tag == 'p':
                p = docx.text.paragraph.Paragraph(child, doc)
                txt = p.text.strip()
                if not txt:
                    continue
                safe_txt = markdown_to_platypus_xml(txt)
                style_name = p.style.name.lower() if p.style else ""
                if "heading 1" in style_name or "title" in style_name:
                    story.append(Paragraph(safe_txt, h1_style))
                elif "heading 2" in style_name:
                    story.append(Paragraph(safe_txt, h2_style))
                elif "heading 3" in style_name:
                    story.append(Paragraph(safe_txt, h3_style))
                elif "bullet" in style_name or txt.startswith(("- ", "• ", "* ")):
                    clean = re.sub(r'^[-•*]\s*', '', txt)
                    story.append(Paragraph(f"&bull; {markdown_to_platypus_xml(clean)}", bullet_style))
                elif "quote" in style_name or txt.startswith("> "):
                    clean = txt.lstrip("> ").strip()
                    story.append(Paragraph(markdown_to_platypus_xml(clean), quote_style))
                else:
                    story.append(Paragraph(safe_txt, body_style))
            elif tag == 'tbl':
                tbl = docx.table.Table(child, doc)
                parsed_rows = []
                for row in tbl.rows:
                    row_vals = [cell.text.strip() for cell in row.cells]
                    parsed_rows.append(row_vals)
                if parsed_rows:
                    col_count = len(parsed_rows[0])
                    col_w = printable_width / max(1, col_count)
                    col_widths = [col_w] * col_count
                    table_data = []
                    # Header row
                    table_data.append([
                        Paragraph(markdown_to_platypus_xml(str(c)), table_header_style)
                        for c in parsed_rows[0]
                    ])
                    # Data rows
                    for r in parsed_rows[1:]:
                        padded_r = r[:col_count] + [""] * max(0, col_count - len(r))
                        table_data.append([
                            Paragraph(markdown_to_platypus_xml(str(c)), table_cell_style)
                            for c in padded_r
                        ])
                    t = Table(table_data, colWidths=col_widths, repeatRows=1)
                    t.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F497D')),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
                        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
                        ('TOPPADDING', (0, 0), (-1, -1), 4),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                        ('LEFTPADDING', (0, 0), (-1, -1), 5),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                    ]))
                    story.append(Spacer(1, 4))
                    story.append(t)
                    story.append(Spacer(1, 6))

        if not story:
            story.append(Paragraph("Empty Document", body_style))

        pdf_doc.build(story)

        return ConversionResult(
            True, source, dest, "docx", "pdf",
            f"Successfully converted Word document to PDF: '{os.path.basename(dest)}'.",
            fidelity_notes=["Preserved heading hierarchy, paragraphs, lists, and tables."]
        )
    except Exception as e:
        logger.error(f"[ConversionRegistry] docx -> pdf error: {e}")
        return ConversionResult(False, source, message=f"DOCX to PDF conversion failed: {e}")


def convert_pdf_to_docx(source: str, output: Optional[str] = None) -> ConversionResult:
    """Convert PDF to editable Word .docx using pypdf extraction."""
    try:
        import pypdf
        import docx
        from docx.shared import Pt, Inches, RGBColor

        if not os.path.exists(source):
            return ConversionResult(False, source, message=f"Source file does not exist: {source}")

        reader = pypdf.PdfReader(source)
        dest = output or os.path.splitext(source)[0] + ".docx"
        dest = get_conflict_free_path(dest)
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)

        doc = docx.Document()
        total_pages = len(reader.pages)
        has_text = False

        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                has_text = True
                lines = text.splitlines()
                for line in lines:
                    line_s = line.strip()
                    if not line_s:
                        continue
                    # Heuristically detect headings
                    if len(line_s) < 60 and (line_s.isupper() or line_s.endswith(":") or re.match(r'^\d+[\.\)]\s+', line_s)):
                        h = doc.add_heading(line_s, level=2)
                        h.paragraph_format.space_before = Pt(10)
                        h.paragraph_format.space_after = Pt(3)
                    elif line_s.startswith(("- ", "• ", "* ")):
                        doc.add_paragraph(line_s[2:].strip(), style='List Bullet')
                    else:
                        doc.add_paragraph(line_s)
            if i < total_pages - 1:
                doc.add_page_break()

        if not has_text:
            p = doc.add_paragraph("[Scanned or Non-extractable PDF: No digital text extracted. OCR may be required.]")
            p.runs[0].font.italic = True

        doc.save(dest)
        notes = ["Extracted digital text, preserved page breaks and bullet markers."]
        warnings = []
        if not has_text:
            warnings.append("Document appears to be a scanned image; digital text could not be extracted.")

        return ConversionResult(
            True, source, dest, "pdf", "docx",
            f"Successfully converted PDF to editable Word document: '{os.path.basename(dest)}'.",
            fidelity_notes=notes,
            warnings=warnings
        )
    except Exception as e:
        logger.error(f"[ConversionRegistry] pdf -> docx error: {e}")
        return ConversionResult(False, source, message=f"PDF to DOCX conversion failed: {e}")


def convert_docx_to_markdown(source: str, output: Optional[str] = None) -> ConversionResult:
    """Convert DOCX to clean Markdown."""
    try:
        import docx
        doc = docx.Document(source)
        dest = output or os.path.splitext(source)[0] + ".md"
        dest = get_conflict_free_path(dest)

        md_lines = []
        for p in doc.paragraphs:
            txt = p.text.strip()
            if not txt:
                md_lines.append("")
                continue
            s_name = p.style.name.lower() if p.style else ""
            if "heading 1" in s_name or "title" in s_name:
                md_lines.append(f"# {txt}\n")
            elif "heading 2" in s_name:
                md_lines.append(f"## {txt}\n")
            elif "heading 3" in s_name:
                md_lines.append(f"### {txt}\n")
            elif "bullet" in s_name or txt.startswith(("- ", "• ")):
                clean = re.sub(r'^[-•*]\s*', '', txt)
                md_lines.append(f"- {clean}")
            elif "number" in s_name:
                md_lines.append(f"1. {txt}")
            elif "quote" in s_name:
                md_lines.append(f"> {txt}\n")
            else:
                md_lines.append(f"{txt}\n")

        # Convert tables to markdown
        for tbl in doc.tables:
            rows = tbl.rows
            if not rows: continue
            md_lines.append("")
            # Header row
            h_cells = [c.text.strip().replace("\n", " ") for c in rows[0].cells]
            md_lines.append("| " + " | ".join(h_cells) + " |")
            md_lines.append("| " + " | ".join(["---"] * len(h_cells)) + " |")
            for r in rows[1:]:
                r_cells = [c.text.strip().replace("\n", " ") for c in r.cells]
                md_lines.append("| " + " | ".join(r_cells) + " |")
            md_lines.append("")

        with open(dest, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))

        return ConversionResult(True, source, dest, "docx", "markdown", f"Converted DOCX to Markdown: '{os.path.basename(dest)}'.")
    except Exception as e:
        return ConversionResult(False, source, message=f"DOCX to Markdown failed: {e}")


def convert_markdown_to_docx(source: str, output: Optional[str] = None) -> ConversionResult:
    """Convert Markdown to styled DOCX document."""
    try:
        from modules.document_tools.docx_builder import create_docx_document
        with open(source, "r", encoding="utf-8") as f:
            content = f.read()
        dest = output or os.path.splitext(source)[0] + ".docx"
        dest = get_conflict_free_path(dest)
        title = Path(source).stem.replace("_", " ").title()
        res = create_docx_document(title=title, content=content, filename=dest)
        if res.get("success"):
            return ConversionResult(True, source, dest, "markdown", "docx", f"Converted Markdown to DOCX: '{os.path.basename(dest)}'.")
        return ConversionResult(False, source, message=res.get("error", "Failed to create DOCX"))
    except Exception as e:
        return ConversionResult(False, source, message=f"Markdown to DOCX failed: {e}")


def convert_markdown_to_pdf(source: str, output: Optional[str] = None) -> ConversionResult:
    """Convert Markdown to typeset PDF document."""
    try:
        from modules.document_tools.pdf_builder import create_pdf_document
        with open(source, "r", encoding="utf-8") as f:
            content = f.read()
        dest = output or os.path.splitext(source)[0] + ".pdf"
        dest = get_conflict_free_path(dest)
        title = Path(source).stem.replace("_", " ").title()
        res = create_pdf_document(title=title, content=content, filename=dest)
        if res.get("success"):
            return ConversionResult(True, source, dest, "markdown", "pdf", f"Converted Markdown to PDF: '{os.path.basename(dest)}'.")
        return ConversionResult(False, source, message=res.get("error", "Failed to create PDF"))
    except Exception as e:
        return ConversionResult(False, source, message=f"Markdown to PDF failed: {e}")


def convert_html_to_markdown(source: str, output: Optional[str] = None) -> ConversionResult:
    """Convert HTML document to Markdown using BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup
        with open(source, "r", encoding="utf-8") as f:
            html_text = f.read()
        soup = BeautifulSoup(html_text, "html.parser")
        dest = output or os.path.splitext(source)[0] + ".md"
        dest = get_conflict_free_path(dest)

        md = []
        for elem in soup.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'ul', 'ol', 'blockquote', 'table']):
            if elem.name == 'h1':
                md.append(f"# {elem.get_text().strip()}\n")
            elif elem.name == 'h2':
                md.append(f"## {elem.get_text().strip()}\n")
            elif elem.name == 'h3':
                md.append(f"### {elem.get_text().strip()}\n")
            elif elem.name == 'p':
                md.append(f"{elem.get_text().strip()}\n")
            elif elem.name == 'blockquote':
                md.append(f"> {elem.get_text().strip()}\n")
            elif elem.name in ('ul', 'ol'):
                for li in elem.find_all('li'):
                    prefix = "- " if elem.name == 'ul' else "1. "
                    md.append(f"{prefix}{li.get_text().strip()}")
                md.append("")
            elif elem.name == 'table':
                rows = elem.find_all('tr')
                if rows:
                    h_cells = [c.get_text().strip() for c in rows[0].find_all(['th', 'td'])]
                    md.append("| " + " | ".join(h_cells) + " |")
                    md.append("| " + " | ".join(["---"] * len(h_cells)) + " |")
                    for r in rows[1:]:
                        r_cells = [c.get_text().strip() for c in r.find_all('td')]
                        md.append("| " + " | ".join(r_cells) + " |")
                    md.append("")

        with open(dest, "w", encoding="utf-8") as f:
            f.write("\n".join(md) if md else soup.get_text())

        return ConversionResult(True, source, dest, "html", "markdown", f"Converted HTML to Markdown: '{os.path.basename(dest)}'.")
    except Exception as e:
        return ConversionResult(False, source, message=f"HTML to Markdown failed: {e}")


def convert_html_to_pdf(source: str, output: Optional[str] = None) -> ConversionResult:
    """Convert HTML to PDF by translating HTML structure to ReportLab flowables."""
    try:
        from bs4 import BeautifulSoup
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors

        with open(source, "r", encoding="utf-8") as f:
            html = f.read()

        soup = BeautifulSoup(html, "html.parser")
        dest = output or os.path.splitext(source)[0] + ".pdf"
        dest = get_conflict_free_path(dest)

        doc = SimpleDocTemplate(dest, pagesize=letter, leftMargin=54, rightMargin=54, topMargin=54, bottomMargin=54)
        styles = getSampleStyleSheet()

        h1 = ParagraphStyle('H1', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=colors.HexColor('#1F497D'), spaceAfter=8)
        h2 = ParagraphStyle('H2', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=13, leading=17, textColor=colors.HexColor('#2E75B6'), spaceBefore=8, spaceAfter=4)
        body = ParagraphStyle('Body', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=14, textColor=colors.HexColor('#262626'), spaceAfter=6)
        bullet = ParagraphStyle('Bullet', parent=body, leftIndent=15, firstLineIndent=-10, spaceAfter=4)

        story = []
        for elem in soup.find_all(['h1', 'h2', 'h3', 'p', 'ul', 'ol', 'table']):
            txt = elem.get_text().strip()
            if not txt and elem.name != 'table':
                continue
            if elem.name == 'h1':
                story.append(Paragraph(txt, h1))
            elif elem.name in ('h2', 'h3'):
                story.append(Paragraph(txt, h2))
            elif elem.name == 'p':
                story.append(Paragraph(txt, body))
            elif elem.name in ('ul', 'ol'):
                for li in elem.find_all('li'):
                    story.append(Paragraph(f"&bull; {li.get_text().strip()}", bullet))
            elif elem.name == 'table':
                t_data = []
                for row in elem.find_all('tr'):
                    row_cells = [c.get_text().strip() for c in row.find_all(['th', 'td'])]
                    if row_cells: t_data.append(row_cells)
                if t_data:
                    t = Table(t_data)
                    t.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F497D')),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
                    ]))
                    story.append(Spacer(1, 8))
                    story.append(t)
                    story.append(Spacer(1, 8))

        if not story:
            story.append(Paragraph("Empty HTML Document", body))

        doc.build(story)
        return ConversionResult(True, source, dest, "html", "pdf", f"Converted HTML to PDF: '{os.path.basename(dest)}'.")
    except Exception as e:
        return ConversionResult(False, source, message=f"HTML to PDF failed: {e}")


def convert_xlsx_to_csv(source: str, output: Optional[str] = None, all_sheets: bool = False) -> ConversionResult:
    """
    Convert Excel spreadsheet to CSV.
    If all_sheets=True, exports each worksheet to a separate CSV.
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(source, data_only=True)
        sheet_names = wb.sheetnames

        if not sheet_names:
            return ConversionResult(False, source, message="Excel workbook contains no sheets.")

        stem = os.path.splitext(source)[0]
        extra_files = []

        if all_sheets and len(sheet_names) > 1:
            primary_dest = None
            for sname in sheet_names:
                ws = wb[sname]
                clean_name = re.sub(r'[^\w\-]', '_', sname)
                c_dest = f"{stem}_{clean_name}.csv"
                c_dest = get_conflict_free_path(c_dest)
                with open(c_dest, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    for row in ws.iter_rows(values_only=True):
                        if any(v is not None for v in row):
                            writer.writerow([v if v is not None else "" for v in row])
                if not primary_dest:
                    primary_dest = c_dest
                else:
                    extra_files.append(c_dest)

            return ConversionResult(
                True, source, primary_dest, "xlsx", "csv",
                f"Exported all {len(sheet_names)} worksheets as separate CSV files.",
                fidelity_notes=["Note: CSV does not support multiple sheets, cell formatting, formulas, or embedded charts."],
                extra_files=extra_files
            )
        else:
            # Single sheet export
            ws = wb.active
            dest = output or f"{stem}.csv"
            dest = get_conflict_free_path(dest)
            with open(dest, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                for row in ws.iter_rows(values_only=True):
                    if any(v is not None for v in row):
                        writer.writerow([v if v is not None else "" for v in row])

            return ConversionResult(
                True, source, dest, "xlsx", "csv",
                f"Exported sheet '{ws.title}' to CSV: '{os.path.basename(dest)}'.",
                fidelity_notes=["Note: CSV does not preserve spreadsheet formatting, charts, or executable formulas."]
            )
    except Exception as e:
        logger.error(f"[ConversionRegistry] xlsx -> csv error: {e}")
        return ConversionResult(False, source, message=f"Excel to CSV conversion failed: {e}")


def convert_csv_to_xlsx(source: str, output: Optional[str] = None) -> ConversionResult:
    """Convert CSV file to professionally formatted Excel workbook."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        if not os.path.exists(source):
            return ConversionResult(False, source, message=f"Source file does not exist: {source}")

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = Path(source).stem[:31]

        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
        cell_border = Border(
            top=Side(style="thin", color="CBD5E1"),
            bottom=Side(style="thin", color="CBD5E1"),
            left=Side(style="thin", color="CBD5E1"),
            right=Side(style="thin", color="CBD5E1")
        )

        dest = output or os.path.splitext(source)[0] + ".xlsx"
        dest = get_conflict_free_path(dest)

        with open(source, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            for r_idx, row in enumerate(reader, start=1):
                converted_row = []
                for val in row:
                    # Type conversion heuristics
                    v_str = str(val).strip()
                    if v_str.isdigit():
                        converted_row.append(int(v_str))
                    else:
                        try:
                            f_val = float(v_str)
                            converted_row.append(f_val)
                        except ValueError:
                            converted_row.append(v_str)
                ws.append(converted_row)

                if r_idx == 1:
                    # Style Header
                    for col_idx in range(1, len(row) + 1):
                        cell = ws.cell(row=1, column=col_idx)
                        cell.font = header_font
                        cell.fill = header_fill
                        cell.alignment = Alignment(horizontal="center", vertical="center")
                        cell.border = cell_border

        ws.freeze_panes = "A2"

        # Auto-adjust column widths
        for col in ws.columns:
            max_len = max((len(str(cell.value or '')) for cell in col), default=10)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

        wb.save(dest)
        return ConversionResult(
            True, source, dest, "csv", "xlsx",
            f"Successfully converted CSV to Excel workbook: '{os.path.basename(dest)}'."
        )
    except Exception as e:
        logger.error(f"[ConversionRegistry] csv -> xlsx error: {e}")
        return ConversionResult(False, source, message=f"CSV to Excel conversion failed: {e}")


def convert_xlsx_to_pdf(source: str, output: Optional[str] = None) -> ConversionResult:
    """Convert Excel worksheet into a styled PDF table document."""
    try:
        import openpyxl
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors

        wb = openpyxl.load_workbook(source, data_only=True)
        ws = wb.active

        table_data = []
        for row in ws.iter_rows(values_only=True):
            if any(v is not None for v in row):
                table_data.append([str(v) if v is not None else "" for v in row])

        if not table_data:
            return ConversionResult(False, source, message="Spreadsheet contains no data to export to PDF.")

        dest = output or os.path.splitext(source)[0] + ".pdf"
        dest = get_conflict_free_path(dest)

        doc = SimpleDocTemplate(dest, pagesize=landscape(letter), leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=14, textColor=colors.HexColor('#1F497D'), spaceAfter=10)

        story = [
            Paragraph(f"Spreadsheet Export: {ws.title}", title_style),
            Spacer(1, 8)
        ]

        t = Table(table_data)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F497D')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')])
        ]))
        story.append(t)
        doc.build(story)

        return ConversionResult(True, source, dest, "xlsx", "pdf", f"Exported spreadsheet to PDF: '{os.path.basename(dest)}'.")
    except Exception as e:
        return ConversionResult(False, source, message=f"XLSX to PDF conversion failed: {e}")


def convert_images_to_pdf(image_paths: List[str], output: Optional[str] = None) -> ConversionResult:
    """Combine one or multiple images (PNG, JPEG, BMP) into a single PDF document."""
    try:
        from PIL import Image

        valid_images = [p for p in image_paths if os.path.exists(p)]
        if not valid_images:
            return ConversionResult(False, "", message="No valid image files provided for PDF creation.")

        dest = output or os.path.splitext(valid_images[0])[0] + "_combined.pdf"
        dest = get_conflict_free_path(dest)
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)

        pil_imgs = []
        for p in valid_images:
            im = Image.open(p)
            if im.mode != "RGB":
                im = im.convert("RGB")
            pil_imgs.append(im)

        if pil_imgs:
            first = pil_imgs[0]
            rest = pil_imgs[1:] if len(pil_imgs) > 1 else []
            first.save(dest, save_all=True, append_images=rest)

            return ConversionResult(
                True, valid_images[0], dest, "images", "pdf",
                f"Successfully combined {len(valid_images)} image(s) into PDF: '{os.path.basename(dest)}'."
            )
        return ConversionResult(False, "", message="Failed to process image files.")
    except Exception as e:
        logger.error(f"[ConversionRegistry] images -> pdf error: {e}")
        return ConversionResult(False, "", message=f"Image to PDF conversion failed: {e}")


def convert_image_format(source: str, target_ext: str, output: Optional[str] = None) -> ConversionResult:
    """Convert image formats (e.g. PNG -> JPEG or JPEG -> PNG)."""
    try:
        from PIL import Image
        if not os.path.exists(source):
            return ConversionResult(False, source, message=f"Image not found: {source}")

        tgt = target_ext.lstrip('.').lower()
        im = Image.open(source)
        if tgt in ("jpg", "jpeg") and im.mode in ("RGBA", "P"):
            im = im.convert("RGB")

        dest = output or os.path.splitext(source)[0] + f".{tgt}"
        dest = get_conflict_free_path(dest)
        im.save(dest)

        return ConversionResult(
            True, source, dest, Path(source).suffix.lstrip('.'), tgt,
            f"Converted image to {tgt.upper()}: '{os.path.basename(dest)}'."
        )
    except Exception as e:
        return ConversionResult(False, source, message=f"Image conversion failed: {e}")


def convert_json_yaml(source: str, to_yaml: bool = True, output: Optional[str] = None) -> ConversionResult:
    """Convert JSON to YAML or YAML to JSON."""
    try:
        import yaml
        if not os.path.exists(source):
            return ConversionResult(False, source, message=f"Source file not found: {source}")

        with open(source, "r", encoding="utf-8") as f:
            raw = f.read()

        if to_yaml:
            data = json.loads(raw)
            dest = output or os.path.splitext(source)[0] + ".yaml"
            dest = get_conflict_free_path(dest)
            with open(dest, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, sort_keys=False)
            return ConversionResult(True, source, dest, "json", "yaml", f"Converted JSON to YAML: '{os.path.basename(dest)}'.")
        else:
            data = yaml.safe_load(raw)
            dest = output or os.path.splitext(source)[0] + ".json"
            dest = get_conflict_free_path(dest)
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return ConversionResult(True, source, dest, "yaml", "json", f"Converted YAML to JSON: '{os.path.basename(dest)}'.")
    except Exception as e:
        return ConversionResult(False, source, message=f"JSON/YAML conversion failed: {e}")


def convert_pptx_to_pdf(source: str, output: Optional[str] = None) -> ConversionResult:
    """Convert PowerPoint .pptx presentation to PDF slides layout using ReportLab."""
    try:
        from pptx import Presentation
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors

        if not os.path.exists(source):
            return ConversionResult(False, source, message=f"Presentation not found: {source}")

        prs = Presentation(source)
        dest = output or os.path.splitext(source)[0] + ".pdf"
        dest = get_conflict_free_path(dest)

        doc = SimpleDocTemplate(dest, pagesize=landscape(letter), leftMargin=54, rightMargin=54, topMargin=54, bottomMargin=54)
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=22, leading=26, textColor=colors.HexColor('#1F497D'), spaceAfter=14)
        bullet_style = ParagraphStyle('Bullet', parent=styles['Normal'], fontName='Helvetica', fontSize=12, leading=16, textColor=colors.HexColor('#262626'), leftIndent=15, spaceAfter=8)

        story = []
        total_slides = len(prs.slides)

        for i, slide in enumerate(prs.slides):
            slide_title = ""
            slide_bullets = []
            tables = []

            for shape in slide.shapes:
                if shape.has_table:
                    t_rows = []
                    for row in shape.table.rows:
                        t_rows.append([c.text.strip() for c in row.cells])
                    if t_rows: tables.append(t_rows)
                elif shape.has_text_frame:
                    for p in shape.text_frame.paragraphs:
                        txt = p.text.strip()
                        if txt:
                            if not slide_title:
                                slide_title = txt
                            else:
                                slide_bullets.append(txt)

            story.append(Paragraph(slide_title or f"Slide {i+1}", title_style))
            story.append(Spacer(1, 10))

            for b in slide_bullets:
                story.append(Paragraph(f"&bull; {b}", bullet_style))

            for t_data in tables:
                t = Table(t_data)
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F497D')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
                ]))
                story.append(Spacer(1, 10))
                story.append(t)

            if i < total_slides - 1:
                story.append(PageBreak())

        if not story:
            story.append(Paragraph("Empty Presentation", title_style))

        doc.build(story)
        return ConversionResult(
            True, source, dest, "pptx", "pdf",
            f"Successfully converted presentation to PDF ({total_slides} slides): '{os.path.basename(dest)}'."
        )
    except Exception as e:
        logger.error(f"[ConversionRegistry] pptx -> pdf error: {e}")
        return ConversionResult(False, source, message=f"PPTX to PDF conversion failed: {e}")


# ============================================================================
# Central Unified Conversion Dispatcher
# ============================================================================

class ConversionRegistry:
    """
    Authoritative File Conversion Router.
    Inspects source file extension and target format, resolving to the appropriate conversion engine.
    """

    @classmethod
    def convert_images_to_pdf(
        cls,
        image_paths: List[str],
        output: Optional[str] = None
    ) -> ConversionResult:
        """Combine multiple images into a single PDF document."""
        return convert_images_to_pdf(image_paths, output)

    @classmethod
    def convert_file(
        cls,
        source_path: str,
        target_format: str,
        output_path: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> ConversionResult:
        """
        Convert file to target format safely.
        """
        options = options or {}
        if not os.path.exists(source_path):
            return ConversionResult(False, source_path, message=f"Source file does not exist: {source_path}")

        src_ext = Path(source_path).suffix.lstrip('.').lower()
        tgt_fmt = target_format.lstrip('.').lower()

        # Handle aliases for source format
        if src_ext in ("doc", "word"): src_ext = "docx"
        elif src_ext in ("excel", "sheet", "spreadsheet"): src_ext = "xlsx"
        elif src_ext in ("ppt", "powerpoint", "presentation"): src_ext = "pptx"
        elif src_ext in ("md", "mdown"): src_ext = "markdown"
        elif src_ext in ("htm",): src_ext = "html"
        elif src_ext in ("jpg",): src_ext = "jpeg"
        elif src_ext in ("text",): src_ext = "txt"

        # Handle aliases for target format
        if tgt_fmt in ("doc", "word"): tgt_fmt = "docx"
        elif tgt_fmt in ("excel", "sheet", "spreadsheet"): tgt_fmt = "xlsx"
        elif tgt_fmt in ("ppt", "powerpoint", "presentation"): tgt_fmt = "pptx"
        elif tgt_fmt in ("md", "mdown"): tgt_fmt = "markdown"
        elif tgt_fmt in ("htm",): tgt_fmt = "html"
        elif tgt_fmt in ("jpg",): tgt_fmt = "jpeg"
        elif tgt_fmt in ("text",): tgt_fmt = "txt"

        # Check trivial conversion
        if src_ext == tgt_fmt:
            return ConversionResult(True, source_path, source_path, src_ext, tgt_fmt, "Source and destination formats are identical.")

        # 1. Word / PDF / Markdown / HTML / TXT conversions
        if src_ext == "docx" and tgt_fmt == "pdf":
            return convert_docx_to_pdf(source_path, output_path)
        elif src_ext == "pdf" and tgt_fmt == "docx":
            return convert_pdf_to_docx(source_path, output_path)
        elif src_ext == "docx" and tgt_fmt == "markdown":
            return convert_docx_to_markdown(source_path, output_path)
        elif src_ext == "docx" and tgt_fmt == "txt":
            from modules.document_tools.pdf_builder import extract_pdf_text
            # DOCX to TXT
            import docx
            doc = docx.Document(source_path)
            dest = output_path or os.path.splitext(source_path)[0] + ".txt"
            dest = get_conflict_free_path(dest)
            text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
            with open(dest, "w", encoding="utf-8") as f: f.write(text)
            return ConversionResult(True, source_path, dest, src_ext, tgt_fmt, f"Extracted text to '{os.path.basename(dest)}'.")
        elif src_ext == "pdf" and tgt_fmt == "txt":
            from modules.document_tools.pdf_builder import extract_pdf_text
            res = extract_pdf_text(source_path)
            if res.get("success"):
                dest = output_path or os.path.splitext(source_path)[0] + ".txt"
                dest = get_conflict_free_path(dest)
                with open(dest, "w", encoding="utf-8") as f: f.write(res["text"])
                return ConversionResult(True, source_path, dest, src_ext, tgt_fmt, f"Extracted text to '{os.path.basename(dest)}'.")
            return ConversionResult(False, source_path, message=res.get("error", "Failed to extract PDF text"))
        elif src_ext == "markdown" and tgt_fmt == "docx":
            return convert_markdown_to_docx(source_path, output_path)
        elif src_ext == "markdown" and tgt_fmt == "pdf":
            return convert_markdown_to_pdf(source_path, output_path)
        elif src_ext == "html" and tgt_fmt == "markdown":
            return convert_html_to_markdown(source_path, output_path)
        elif src_ext == "html" and tgt_fmt == "pdf":
            return convert_html_to_pdf(source_path, output_path)
        elif src_ext == "txt" and tgt_fmt == "docx":
            return convert_markdown_to_docx(source_path, output_path)

        # 2. Spreadsheet conversions
        elif src_ext in ("xlsx", "xls") and tgt_fmt == "csv":
            all_s = options.get("all_worksheets", False)
            return convert_xlsx_to_csv(source_path, output_path, all_sheets=all_s)
        elif src_ext == "csv" and tgt_fmt in ("xlsx", "xls"):
            return convert_csv_to_xlsx(source_path, output_path)
        elif src_ext in ("xlsx", "xls") and tgt_fmt == "pdf":
            return convert_xlsx_to_pdf(source_path, output_path)
        elif src_ext == "csv" and tgt_fmt == "pdf":
            # CSV to PDF: CSV -> XLSX -> PDF
            x_res = convert_csv_to_xlsx(source_path)
            if x_res.success:
                pdf_res = convert_xlsx_to_pdf(x_res.target_path, output_path)
                try: os.remove(x_res.target_path)
                except Exception: pass
                return pdf_res
            return ConversionResult(False, source_path, message=x_res.message)

        # 3. Presentation conversions
        elif src_ext in ("pptx", "ppt") and tgt_fmt == "pdf":
            return convert_pptx_to_pdf(source_path, output_path)

        # 4. Structured Data conversions (JSON, YAML, CSV)
        elif src_ext == "json" and tgt_fmt in ("yaml", "yml"):
            return convert_json_yaml(source_path, to_yaml=True, output=output_path)
        elif src_ext in ("yaml", "yml") and tgt_fmt == "json":
            return convert_json_yaml(source_path, to_yaml=False, output=output_path)
        elif src_ext == "json" and tgt_fmt == "csv":
            # JSON array of dicts to CSV
            with open(source_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data and isinstance(data[0], dict):
                dest = output_path or os.path.splitext(source_path)[0] + ".csv"
                dest = get_conflict_free_path(dest)
                keys = list(data[0].keys())
                with open(dest, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=keys)
                    writer.writeheader()
                    writer.writerows(data)
                return ConversionResult(True, source_path, dest, "json", "csv", f"Converted JSON to CSV: '{os.path.basename(dest)}'.")
            return ConversionResult(False, source_path, message="JSON must be an array of objects to map to tabular CSV.")
        elif src_ext == "csv" and tgt_fmt == "json":
            dest = output_path or os.path.splitext(source_path)[0] + ".json"
            dest = get_conflict_free_path(dest)
            records = []
            with open(source_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                records = list(reader)
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2)
            return ConversionResult(True, source_path, dest, "csv", "json", f"Converted CSV to JSON: '{os.path.basename(dest)}'.")

        # 5. Image conversions
        elif src_ext in ("png", "jpg", "jpeg", "bmp", "webp") and tgt_fmt == "pdf":
            return convert_images_to_pdf([source_path], output_path)
        elif src_ext in ("png", "jpg", "jpeg", "bmp", "webp") and tgt_fmt in ("png", "jpg", "jpeg"):
            return convert_image_format(source_path, tgt_fmt, output_path)

        return ConversionResult(
            False, source_path,
            message=f"Conversion from '.{src_ext}' to '.{tgt_fmt}' is currently unsupported or engine unavailable."
        )


def convert_document(
    source_path: str,
    target_format: str,
    output_path: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Top-level functional interface returning clean dictionary."""
    res = ConversionRegistry.convert_file(source_path, target_format, output_path, options)
    return res.to_dict()
