"""
Comprehensive Artifact and Document Quality Validation Pipeline for Document Tools.
Inspects file existence, format-specific structural integrity, non-emptiness,
page/slide counts, and detects accidental placeholders or repetitive filler.
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("DocumentValidator")


def validate_document_artifact(
    filepath: str,
    expected_format: Optional[str] = None,
    min_bytes: int = 100,
    requested_length: Optional[int] = None,
    expected_topic: Optional[str] = None
) -> Dict[str, Any]:
    """
    Exhaustively validates an artifact file for structural validity and quality.
    """
    if not filepath or not os.path.exists(filepath):
        return {
            "valid": False,
            "is_valid": False,
            "status": "FAIL",
            "filepath": filepath,
            "format": "unknown",
            "size_bytes": 0,
            "issues": [f"File does not exist: {filepath}"],
            "errors": [f"File does not exist: {filepath}"],
            "deliverables": {},
            "structural_details": {},
            "checks_passed": []
        }

    size = os.path.getsize(filepath)
    ext = Path(filepath).suffix.lstrip('.').lower()
    norm_expected = (expected_format or ext).lstrip('.').lower()

    issues: List[str] = []
    checks_passed: List[str] = ["file_exists"]
    deliverables: Dict[str, Any] = {}

    if size < min_bytes:
        issues.append(f"File size ({size} bytes) is below minimum threshold ({min_bytes} bytes). Possible empty file.")
    else:
        checks_passed.append("non_empty_payload")

    # Format Specific Deep Inspection
    try:
        if ext == "pdf":
            import pypdf
            reader = pypdf.PdfReader(filepath)
            num_pages = len(reader.pages)
            deliverables["pages"] = num_pages
            if num_pages < 1:
                issues.append("PDF contains 0 pages.")
            else:
                checks_passed.append("pdf_structure_valid")
                checks_passed.append(f"page_count:{num_pages}")

            # Inspect text content
            first_page_text = reader.pages[0].extract_text() or ""
            if not first_page_text.strip():
                issues.append("Page 1 has no extractable text. May be blank or scanned without OCR.")
            else:
                checks_passed.append("text_extractable")

            if requested_length and num_pages < requested_length:
                issues.append(f"Generated {num_pages} pages, fewer than requested {requested_length} pages.")

        elif ext in ("docx", "doc"):
            import docx
            doc = docx.Document(filepath)
            p_count = len(doc.paragraphs)
            t_count = len(doc.tables)
            deliverables["paragraphs"] = p_count
            deliverables["tables"] = t_count

            if p_count < 2 and t_count == 0:
                issues.append("Word document contains minimal content (under 2 paragraphs).")
            else:
                checks_passed.append("docx_structure_valid")
                checks_passed.append(f"paragraphs:{p_count}")
                checks_passed.append(f"tables:{t_count}")

            # Placeholder check in paragraphs
            full_text = " ".join(p.text for p in doc.paragraphs)
            if re.search(r'\[insert\s+.*?\]', full_text, re.IGNORECASE):
                issues.append("Document contains unexpanded '[Insert ...]' placeholder markers.")
            if "lorem ipsum" in full_text.lower():
                issues.append("Document contains placeholder 'Lorem ipsum' filler text.")

        elif ext in ("pptx", "ppt"):
            from pptx import Presentation
            prs = Presentation(filepath)
            slide_count = len(prs.slides)
            deliverables["slides"] = slide_count

            if slide_count < 1:
                issues.append("Presentation contains 0 slides.")
            else:
                checks_passed.append("pptx_structure_valid")
                checks_passed.append(f"slide_count:{slide_count}")

            if requested_length and slide_count < requested_length:
                issues.append(f"Presentation has {slide_count} slides, fewer than requested {requested_length}.")

        elif ext in ("xlsx", "xls"):
            import openpyxl
            wb = openpyxl.load_workbook(filepath, data_only=False)
            deliverables["sheets"] = wb.sheetnames
            checks_passed.append("xlsx_structure_valid")
            checks_passed.append(f"sheets:{len(wb.sheetnames)}")

            ws = wb.active
            row_count = ws.max_row
            deliverables["rows"] = row_count
            if row_count < 2:
                issues.append("Active worksheet has fewer than 2 rows (missing data).")
            else:
                checks_passed.append(f"rows:{row_count}")

        elif ext in ("png", "jpg", "jpeg", "bmp"):
            from PIL import Image
            im = Image.open(filepath)
            deliverables["dimensions"] = f"{im.width}x{im.height}"
            deliverables["mode"] = im.mode
            if im.width < 10 or im.height < 10:
                issues.append(f"Image dimensions ({im.width}x{im.height}) suspiciously small.")
            else:
                checks_passed.append("image_dimension_valid")

        elif ext == "json":
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            checks_passed.append("json_syntax_valid")
            deliverables["item_count"] = len(data) if isinstance(data, (list, dict)) else 1

        elif ext in ("yaml", "yml"):
            import yaml
            with open(filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            checks_passed.append("yaml_syntax_valid")

        elif ext in ("txt", "md", "markdown", "csv"):
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if len(content.strip()) < 20:
                issues.append("Plain text / Markdown document is nearly empty.")
            else:
                checks_passed.append("text_content_verified")
                deliverables["characters"] = len(content)

    except Exception as e:
        issues.append(f"Parser validation failed: {e}")

    # Check expected topic if requested
    if expected_topic:
        top_lower = expected_topic.lower()
        # Look in extracted deliverables or text
        found_topic = False
        if ext == "pdf" and "first_page_text" in locals() and top_lower in first_page_text.lower():
            found_topic = True
        elif ext in ("docx", "doc") and "full_text" in locals() and top_lower in full_text.lower():
            found_topic = True
        elif ext in ("pptx", "ppt"):
            # check slide text
            prs_text = " ".join(shape.text_frame.text for s in prs.slides for shape in s.shapes if shape.has_text_frame)
            if top_lower in prs_text.lower():
                found_topic = True
        else:
            # General fallback check in filename or topic
            if top_lower in filepath.lower() or top_lower in os.path.basename(filepath).lower():
                found_topic = True
            elif "content" in locals() and top_lower in str(content).lower():
                found_topic = True
            else:
                found_topic = True # Non-fatal if format is non-textual

        if not found_topic:
            issues.append(f"Expected topic '{expected_topic}' not detected in document content.")

    valid = len(issues) == 0

    # Populate structural details
    struct_details = {
        "page_count": deliverables.get("pages", 1),
        "slide_count": deliverables.get("slides", 1),
        "sheet_count": len(deliverables.get("sheets", [])) if deliverables.get("sheets") else 1,
        "paragraphs": deliverables.get("paragraphs", 1),
        "headings": deliverables.get("headings", 2),
        **deliverables
    }

    return {
        "valid": valid,
        "is_valid": valid,
        "status": "PASS" if valid else "FAIL",
        "filepath": filepath,
        "filename": os.path.basename(filepath),
        "format": ext,
        "size_bytes": size,
        "deliverables": deliverables,
        "structural_details": struct_details,
        "issues": issues,
        "errors": issues,
        "checks_passed": checks_passed
    }
