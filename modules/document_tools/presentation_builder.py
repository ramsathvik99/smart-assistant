"""
PowerPoint (.pptx) Presentation Generator for Smart Assistant.
Generates publication-quality, visually engaging, professionally structured presentations
with 14 distinct layout types, native vector diagrams, comparison tables, process flows,
worked technical examples, and speaker notes using python-pptx.
"""

from __future__ import annotations

import os
import re
import math
import logging
from typing import Dict, Any, List, Optional, Tuple, Union
from datetime import datetime

logger = logging.getLogger(__name__)


def get_default_output_dir() -> str:
    """
    Get user Desktop directory, checking OneDrive Desktop first then standard Desktop.
    """
    home = os.path.expanduser("~")
    onedrive_desktop = os.path.join(home, "OneDrive", "Desktop")
    if os.path.exists(onedrive_desktop) and os.path.isdir(onedrive_desktop):
        return onedrive_desktop
    standard_desktop = os.path.join(home, "Desktop")
    if os.path.exists(standard_desktop) and os.path.isdir(standard_desktop):
        return standard_desktop
    return home


# ============================================================================
# Color Palette Themes for Modern Professional Slides (16:9 Widescreen)
# ============================================================================

THEMES = {
    "navy": {
        "primary": (15, 23, 42),          # Deep Slate / Navy
        "accent": (14, 165, 233),         # Electric Sky Blue
        "secondary_accent": (99, 102, 241),# Indigo
        "background": (255, 255, 255),    # Clean White
        "surface": (241, 245, 249),       # Slate 100
        "surface_alt": (226, 232, 240),   # Slate 200
        "text": (30, 41, 59),             # Slate 800
        "muted_text": (100, 116, 139),    # Slate 500
        "header_text": (15, 23, 42),
        "card_border": (14, 165, 233),
    },
    "slate": {
        "primary": (30, 41, 59),          # Dark Slate
        "accent": (20, 184, 166),         # Teal 500
        "secondary_accent": (16, 185, 129),# Emerald 500
        "background": (255, 255, 255),
        "surface": (240, 253, 250),       # Mint/Teal Tint
        "surface_alt": (204, 251, 241),
        "text": (30, 41, 59),
        "muted_text": (100, 116, 139),
        "header_text": (30, 41, 59),
        "card_border": (20, 184, 166),
    },
    "corporate_blue": {
        "primary": (30, 58, 138),         # Deep Royal Navy
        "accent": (37, 99, 235),          # Cobalt Blue
        "secondary_accent": (56, 189, 248),# Sky 400
        "background": (255, 255, 255),
        "surface": (239, 246, 255),       # Ice Blue
        "surface_alt": (219, 234, 254),
        "text": (30, 41, 59),
        "muted_text": (100, 116, 139),
        "header_text": (30, 58, 138),
        "card_border": (37, 99, 235),
    },
    "academic": {
        "primary": (6, 78, 59),           # Deep Emerald
        "accent": (5, 150, 105),          # Forest Green
        "secondary_accent": (16, 185, 129),# Jade
        "background": (255, 255, 255),
        "surface": (240, 253, 244),       # Light Sage
        "surface_alt": (220, 252, 231),
        "text": (30, 41, 59),
        "muted_text": (100, 116, 139),
        "header_text": (6, 78, 59),
        "card_border": (5, 150, 105),
    },
    "crimson_executive": {
        "primary": (136, 19, 55),         # Rose Wine
        "accent": (225, 29, 72),          # Crimson Rose
        "secondary_accent": (245, 158, 11),# Amber
        "background": (255, 255, 255),
        "surface": (255, 241, 242),       # Rose Tint
        "surface_alt": (255, 228, 230),
        "text": (30, 41, 59),
        "muted_text": (100, 116, 139),
        "header_text": (136, 19, 55),
        "card_border": (225, 29, 72),
    }
}


# ============================================================================
# Reusable Slide Rendering Components
# ============================================================================

def _get_theme_palette(theme_name: str) -> Dict[str, Tuple[int, int, int]]:
    """Retrieve theme RGB dictionary with robust fallback."""
    key = str(theme_name).lower().strip()
    return THEMES.get(key, THEMES["navy"])


def _render_slide_header(
    slide: Any,
    title: str,
    subtitle: Optional[str] = None,
    category_tag: Optional[str] = None,
    pal: Dict[str, Tuple[int, int, int]] = None
) -> None:
    """
    Renders standardized, visually balanced slide header with category chip and subtitle.
    """
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE

    c_primary = RGBColor(*pal["primary"])
    c_accent = RGBColor(*pal["accent"])
    c_muted = RGBColor(*pal["muted_text"])

    # 1. Category Chip Pill
    if category_tag:
        chip = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(0.42), Inches(2.5), Inches(0.32))
        chip.fill.solid()
        chip.fill.fore_color.rgb = c_accent
        chip.line.fill.background()
        p_chip = chip.text_frame.paragraphs[0]
        p_chip.text = str(category_tag).upper()
        p_chip.font.name = "Calibri"
        p_chip.font.size = Pt(10)
        p_chip.font.bold = True
        p_chip.font.color.rgb = RGBColor(255, 255, 255)

    top_offset = Inches(0.82) if category_tag else Inches(0.55)
    h_box = slide.shapes.add_textbox(Inches(0.8), top_offset, Inches(11.733), Inches(0.85))
    tf = h_box.text_frame
    tf.word_wrap = True
    p_title = tf.paragraphs[0]
    p_title.text = title
    p_title.font.name = "Calibri"
    p_title.font.size = Pt(26)
    p_title.font.bold = True
    p_title.font.color.rgb = c_primary

    if subtitle:
        p_sub = tf.add_paragraph()
        p_sub.text = subtitle
        p_sub.font.name = "Calibri"
        p_sub.font.size = Pt(13)
        p_sub.font.color.rgb = c_muted
        p_sub.space_before = Pt(3)

    # Clean accent divider rule
    sep = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(1.68), Inches(11.733), Pt(1.5))
    sep.fill.solid()
    sep.fill.fore_color.rgb = RGBColor(*pal["surface_alt"])
    sep.line.fill.background()


def _render_title_slide(
    slide: Any,
    title: str,
    subtitle: Optional[str],
    author: str,
    category_tag: Optional[str],
    pal: Dict[str, Tuple[int, int, int]]
) -> None:
    """Hero Title Slide layout with accent bar and metadata footer."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE

    c_primary = RGBColor(*pal["primary"])
    c_accent = RGBColor(*pal["accent"])
    c_text = RGBColor(*pal["text"])

    # Left accent vertical bar
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(1.8), Inches(0.22), Inches(3.8))
    bar.fill.solid()
    bar.fill.fore_color.rgb = c_accent
    bar.line.fill.background()

    # Title Card Box
    box = slide.shapes.add_textbox(Inches(1.3), Inches(1.8), Inches(11.2), Inches(3.8))
    tf = box.text_frame
    tf.word_wrap = True

    if category_tag:
        p_tag = tf.paragraphs[0]
        p_tag.text = str(category_tag).upper()
        p_tag.font.name = "Calibri"
        p_tag.font.size = Pt(13)
        p_tag.font.bold = True
        p_tag.font.color.rgb = c_accent
        p_tag.space_after = Pt(10)
        p_title = tf.add_paragraph()
    else:
        p_title = tf.paragraphs[0]

    p_title.text = title
    p_title.font.name = "Calibri"
    p_title.font.size = Pt(42)
    p_title.font.bold = True
    p_title.font.color.rgb = c_primary

    sub_text = subtitle or f"Comprehensive Technical Masterclass & System Architecture • {datetime.now().strftime('%B %Y')}"
    p_sub = tf.add_paragraph()
    p_sub.text = sub_text
    p_sub.font.name = "Calibri"
    p_sub.font.size = Pt(18)
    p_sub.font.color.rgb = c_text
    p_sub.space_before = Pt(14)

    # Footer metadata box
    f_box = slide.shapes.add_textbox(Inches(1.3), Inches(5.8), Inches(11.2), Inches(0.8))
    tf_f = f_box.text_frame
    p_meta = tf_f.paragraphs[0]
    p_meta.text = f"Prepared by: {author}   |   Date: {datetime.now().strftime('%B %d, %Y')}   |   Status: Verified Production Deliverable"
    p_meta.font.name = "Calibri"
    p_meta.font.size = Pt(12)
    p_meta.font.color.rgb = RGBColor(*pal["muted_text"])


def _render_agenda_slide(
    slide: Any,
    spec: Dict[str, Any],
    pal: Dict[str, Tuple[int, int, int]]
) -> None:
    """Renders visual multi-card agenda and curriculum roadmap."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE

    _render_slide_header(slide, spec.get("title", "Presentation Scope & Roadmap"), spec.get("subtitle", "Curriculum Architecture & Module Progression"), spec.get("category_tag", "AGENDA"), pal)

    modules = spec.get("modules") or spec.get("cards") or [
        {"title": "Foundations & Architecture", "desc": "Three-Schema framework, data independence, relational algebra."},
        {"title": "Query & Optimization", "desc": "SQL parsing, catalog binding, cost-based physical plan execution."},
        {"title": "Transactions & Concurrency", "desc": "ACID guarantees, Strict 2PL locking protocols, MVCC snapshot isolation."},
        {"title": "Storage, Indexing & Recovery", "desc": "Slotted pages, B+ tree topology, WAL write-ahead logging & ARIES."},
        {"title": "Distributed & Modern Systems", "desc": "CAP theorem trade-offs, Two-Phase Commit, NoSQL vs NewSQL vs HTAP."}
    ]

    n = min(6, len(modules))
    # Render in 2 rows or 1 horizontal row
    if n <= 3:
        w = (Inches(11.733) - Inches(0.4) * (n - 1)) / n
        for i, m in enumerate(modules[:n]):
            left = Inches(0.8) + i * (w + Inches(0.4))
            card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, Inches(2.2), w, Inches(4.3))
            card.fill.solid()
            card.fill.fore_color.rgb = RGBColor(*pal["surface"])
            card.line.color.rgb = RGBColor(*pal["accent"])
            card.line.width = Pt(1.5)
            tf = card.text_frame
            tf.word_wrap = True
            tf.margin_left = Inches(0.2)
            tf.margin_top = Inches(0.2)
            p0 = tf.paragraphs[0]
            p0.text = f"MODULE 0{i+1}"
            p0.font.bold = True
            p0.font.size = Pt(12)
            p0.font.color.rgb = RGBColor(*pal["accent"])
            p1 = tf.add_paragraph()
            p1.text = m.get("title", "")
            p1.font.bold = True
            p1.font.size = Pt(17)
            p1.font.color.rgb = RGBColor(*pal["primary"])
            p1.space_before = Pt(8)
            p2 = tf.add_paragraph()
            p2.text = m.get("desc", "")
            p2.font.size = Pt(13)
            p2.font.color.rgb = RGBColor(*pal["text"])
            p2.space_before = Pt(8)
    else:
        # 2 rows of up to 3 columns
        cols = 3
        w = (Inches(11.733) - Inches(0.4) * 2) / 3
        h = Inches(2.1)
        for i, m in enumerate(modules[:6]):
            r_idx = i // cols
            c_idx = i % cols
            left = Inches(0.8) + c_idx * (w + Inches(0.4))
            top = Inches(2.0) + r_idx * (h + Inches(0.35))
            card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, w, h)
            card.fill.solid()
            card.fill.fore_color.rgb = RGBColor(*pal["surface"])
            card.line.color.rgb = RGBColor(*pal["accent"])
            card.line.width = Pt(1.2)
            tf = card.text_frame
            tf.word_wrap = True
            tf.margin_left = Inches(0.18)
            tf.margin_top = Inches(0.15)
            p0 = tf.paragraphs[0]
            p0.text = f"MODULE 0{i+1} • {m.get('title', '')}"
            p0.font.bold = True
            p0.font.size = Pt(13)
            p0.font.color.rgb = RGBColor(*pal["primary"])
            p1 = tf.add_paragraph()
            p1.text = m.get("desc", "")
            p1.font.size = Pt(11)
            p1.font.color.rgb = RGBColor(*pal["text"])
            p1.space_before = Pt(4)


def _render_section_divider(
    slide: Any,
    spec: Dict[str, Any],
    pal: Dict[str, Tuple[int, int, int]]
) -> None:
    """Bold transition section divider slide."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE

    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.8), Inches(11.733), Inches(3.8))
    card.fill.solid()
    card.fill.fore_color.rgb = RGBColor(*pal["primary"])
    card.line.fill.background()

    tf = card.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.6)
    tf.margin_top = Inches(0.6)

    p0 = tf.paragraphs[0]
    p0.text = spec.get("category_tag", "SECTION TRANSITION").upper()
    p0.font.name = "Calibri"
    p0.font.size = Pt(14)
    p0.font.bold = True
    p0.font.color.rgb = RGBColor(*pal["accent"])

    p1 = tf.add_paragraph()
    p1.text = spec.get("title", "")
    p1.font.name = "Calibri"
    p1.font.size = Pt(36)
    p1.font.bold = True
    p1.font.color.rgb = RGBColor(255, 255, 255)
    p1.space_before = Pt(12)

    if spec.get("subtitle"):
        p2 = tf.add_paragraph()
        p2.text = spec.get("subtitle")
        p2.font.name = "Calibri"
        p2.font.size = Pt(18)
        p2.font.color.rgb = RGBColor(*pal["surface_alt"])
        p2.space_before = Pt(10)


def _render_two_column_slide(
    slide: Any,
    spec: Dict[str, Any],
    pal: Dict[str, Tuple[int, int, int]]
) -> None:
    """Two balanced side-by-side comparison cards filling the slide space."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE

    _render_slide_header(slide, spec.get("title", ""), spec.get("subtitle"), spec.get("category_tag"), pal)

    columns = spec.get("columns") or [
        {"title": "Core Tenet A", "bullets": spec.get("bullets", [])[:len(spec.get("bullets", []))//2]},
        {"title": "Core Tenet B", "bullets": spec.get("bullets", [])[len(spec.get("bullets", []))//2:]}
    ]

    col_w = Inches(5.66)
    gap = Inches(0.4)

    for i, col in enumerate(columns[:2]):
        left = Inches(0.8) + i * (col_w + gap)
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, Inches(1.9), col_w, Inches(4.9))
        card.fill.solid()
        card.fill.fore_color.rgb = RGBColor(*pal["surface"])
        card.line.color.rgb = RGBColor(*pal["accent"]) if i == 0 else RGBColor(*pal["secondary_accent"])
        card.line.width = Pt(1.5)

        tf = card.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.25)
        tf.margin_right = Inches(0.25)
        tf.margin_top = Inches(0.25)

        p_head = tf.paragraphs[0]
        p_head.text = col.get("title", f"Pillar {i+1}")
        p_head.font.name = "Calibri"
        p_head.font.size = Pt(19)
        p_head.font.bold = True
        p_head.font.color.rgb = RGBColor(*pal["primary"])
        p_head.space_after = Pt(8)

        if col.get("lead_text"):
            p_lead = tf.add_paragraph()
            p_lead.text = col.get("lead_text")
            p_lead.font.size = Pt(13)
            p_lead.font.italic = True
            p_lead.font.color.rgb = RGBColor(*pal["muted_text"])
            p_lead.space_after = Pt(8)

        for b in col.get("bullets", []):
            pb = tf.add_paragraph()
            pb.text = f"•  {b}"
            pb.font.name = "Calibri"
            pb.font.size = Pt(13.5)
            pb.font.color.rgb = RGBColor(*pal["text"])
            pb.space_before = Pt(8)


def _render_cards_grid_slide(
    slide: Any,
    spec: Dict[str, Any],
    pal: Dict[str, Tuple[int, int, int]]
) -> None:
    """3 or 4 cards grid layout across the slide width with category tags and detailed descriptions."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE

    _render_slide_header(slide, spec.get("title", ""), spec.get("subtitle"), spec.get("category_tag"), pal)

    cards = spec.get("cards") or [
        {"title": f"Component {i+1}", "desc": b, "badge": "Core Principle"}
        for i, b in enumerate(spec.get("bullets", [])[:4])
    ]

    n = min(4, max(2, len(cards)))
    gap = Inches(0.3)
    card_w = (Inches(11.733) - gap * (n - 1)) / n

    for i, c in enumerate(cards[:n]):
        left = Inches(0.8) + i * (card_w + gap)
        shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, Inches(1.9), card_w, Inches(4.9))
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor(*pal["surface"])
        shape.line.color.rgb = RGBColor(*pal["accent"])
        shape.line.width = Pt(1.5)

        tf = shape.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.2)
        tf.margin_right = Inches(0.2)
        tf.margin_top = Inches(0.2)

        # Badge tag
        p_badge = tf.paragraphs[0]
        p_badge.text = str(c.get("badge", "ELEMENT")).upper()
        p_badge.font.name = "Calibri"
        p_badge.font.size = Pt(11)
        p_badge.font.bold = True
        p_badge.font.color.rgb = RGBColor(*pal["accent"])
        p_badge.space_after = Pt(6)

        p_title = tf.add_paragraph()
        p_title.text = c.get("title", "")
        p_title.font.name = "Calibri"
        p_title.font.size = Pt(18)
        p_title.font.bold = True
        p_title.font.color.rgb = RGBColor(*pal["primary"])
        p_title.space_after = Pt(8)

        p_desc = tf.add_paragraph()
        p_desc.text = c.get("desc", "")
        p_desc.font.name = "Calibri"
        p_desc.font.size = Pt(13)
        p_desc.font.color.rgb = RGBColor(*pal["text"])

        if c.get("bullets"):
            for b in c.get("bullets", []):
                pb = tf.add_paragraph()
                pb.text = f"• {b}"
                pb.font.size = Pt(12)
                pb.font.color.rgb = RGBColor(*pal["text"])
                pb.space_before = Pt(4)


def _render_process_flow_slide(
    slide: Any,
    spec: Dict[str, Any],
    pal: Dict[str, Tuple[int, int, int]]
) -> None:
    """Renders sequential execution pipeline with stage cards and connecting directional arrows."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE

    _render_slide_header(slide, spec.get("title", ""), spec.get("subtitle"), spec.get("category_tag"), pal)

    steps = spec.get("process_steps") or [
        {"step": i+1, "title": f"Phase {i+1}", "desc": b}
        for i, b in enumerate(spec.get("bullets", [])[:4])
    ]

    n = min(5, len(steps))
    gap = Inches(0.35)
    arrow_w = Inches(0.22)
    step_w = (Inches(11.733) - gap * (n - 1)) / n

    for i, s in enumerate(steps[:n]):
        left = Inches(0.8) + i * (step_w + gap)
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, Inches(1.9), step_w, Inches(4.9))
        card.fill.solid()
        card.fill.fore_color.rgb = RGBColor(*pal["surface"])
        card.line.color.rgb = RGBColor(*pal["accent"])
        card.line.width = Pt(1.5)

        tf = card.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.18)
        tf.margin_right = Inches(0.18)
        tf.margin_top = Inches(0.2)

        p0 = tf.paragraphs[0]
        p0.text = f"STAGE 0{s.get('step', i+1)}"
        p0.font.bold = True
        p0.font.size = Pt(11)
        p0.font.color.rgb = RGBColor(*pal["accent"])

        p1 = tf.add_paragraph()
        p1.text = s.get("title", "")
        p1.font.bold = True
        p1.font.size = Pt(17)
        p1.font.color.rgb = RGBColor(*pal["primary"])
        p1.space_before = Pt(6)

        p2 = tf.add_paragraph()
        p2.text = s.get("desc", "")
        p2.font.size = Pt(12.5)
        p2.font.color.rgb = RGBColor(*pal["text"])
        p2.space_before = Pt(8)

        if s.get("details"):
            p3 = tf.add_paragraph()
            p3.text = f"Invariant: {s.get('details')}"
            p3.font.size = Pt(11)
            p3.font.bold = True
            p3.font.color.rgb = RGBColor(*pal["muted_text"])
            p3.space_before = Pt(6)

        # Connecting arrow between stages
        if i < n - 1:
            arrow_left = left + step_w + Inches(0.06)
            arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, arrow_left, Inches(4.0), arrow_w, Inches(0.35))
            arrow.fill.solid()
            arrow.fill.fore_color.rgb = RGBColor(*pal["accent"])
            arrow.line.fill.background()


def _render_table_slide(
    slide: Any,
    spec: Dict[str, Any],
    pal: Dict[str, Tuple[int, int, int]]
) -> None:
    """Formatted comparison table with dark headers, alternating rows, and summary takeaway bar."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    from pptx.enum.shapes import MSO_SHAPE

    _render_slide_header(slide, spec.get("title", ""), spec.get("subtitle"), spec.get("category_tag"), pal)

    t_data = spec.get("table") or {}
    headers = t_data.get("headers", spec.get("headers", []))
    rows = t_data.get("rows", spec.get("rows", []))

    if not headers and not rows:
        _render_two_column_slide(slide, spec, pal)
        return

    num_rows = len(rows) + (1 if headers else 0)
    num_cols = len(headers) if headers else len(rows[0])

    tbl_h = min(Inches(4.2), Inches(0.55 * num_rows + 0.5))
    tbl_shape = slide.shapes.add_table(num_rows, num_cols, Inches(0.8), Inches(1.9), Inches(11.733), tbl_h)
    tbl = tbl_shape.table

    offset = 0
    if headers:
        for c_idx, h in enumerate(headers):
            cell = tbl.cell(0, c_idx)
            cell.text = str(h)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(*pal["primary"])
            p = cell.text_frame.paragraphs[0]
            p.font.name = "Calibri"
            p.font.bold = True
            p.font.size = Pt(12)
            p.font.color.rgb = RGBColor(255, 255, 255)
            p.alignment = PP_ALIGN.CENTER
        offset = 1

    font_sz = Pt(10.5) if num_rows > 6 else Pt(11.5)
    for r_idx, row_items in enumerate(rows):
        for c_idx, val in enumerate(row_items[:num_cols]):
            cell = tbl.cell(r_idx + offset, c_idx)
            cell.text = str(val)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(*pal["surface"]) if r_idx % 2 == 0 else RGBColor(255, 255, 255)
            p = cell.text_frame.paragraphs[0]
            p.font.name = "Calibri"
            p.font.size = font_sz
            p.font.color.rgb = RGBColor(*pal["text"])
            if c_idx > 0 and len(str(val)) < 15:
                p.alignment = PP_ALIGN.CENTER

    # Summary takeaway box beneath the table
    if spec.get("takeaway") or spec.get("notes"):
        bar_top = Inches(1.9) + tbl_h + Inches(0.2)
        if bar_top < Inches(6.5):
            takeaway_box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), bar_top, Inches(11.733), Inches(0.65))
            takeaway_box.fill.solid()
            takeaway_box.fill.fore_color.rgb = RGBColor(*pal["surface_alt"])
            takeaway_box.line.color.rgb = RGBColor(*pal["accent"])
            takeaway_box.line.width = Pt(1.0)
            tf_t = takeaway_box.text_frame
            tf_t.word_wrap = True
            p_t = tf_t.paragraphs[0]
            p_t.text = f"KEY TAKEAWAY: {spec.get('takeaway') or spec.get('notes')}"
            p_t.font.name = "Calibri"
            p_t.font.size = Pt(11.5)
            p_t.font.bold = True
            p_t.font.color.rgb = RGBColor(*pal["primary"])


def _render_worked_example_slide(
    slide: Any,
    spec: Dict[str, Any],
    pal: Dict[str, Tuple[int, int, int]]
) -> None:
    """Split layout dedicated to technical problem scenarios and step-by-step mathematical solutions."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE

    _render_slide_header(slide, spec.get("title", "Worked Technical Example"), spec.get("subtitle", "Scenario Formulation & Step-by-Step Derivation"), spec.get("category_tag", "WORKED EXAMPLE"), pal)

    w_scenario = Inches(5.1)
    w_solution = Inches(6.233)

    # 1. Left Container: Problem Scenario / Formulation
    left_card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.9), w_scenario, Inches(4.9))
    left_card.fill.solid()
    left_card.fill.fore_color.rgb = RGBColor(*pal["surface"])
    left_card.line.color.rgb = RGBColor(*pal["secondary_accent"])
    left_card.line.width = Pt(1.5)

    tf_l = left_card.text_frame
    tf_l.word_wrap = True
    tf_l.margin_left = Inches(0.25)
    tf_l.margin_right = Inches(0.25)
    tf_l.margin_top = Inches(0.25)

    p0 = tf_l.paragraphs[0]
    p0.text = "PROBLEM FORMULATION & GIVEN SCHEMA"
    p0.font.bold = True
    p0.font.size = Pt(12)
    p0.font.color.rgb = RGBColor(*pal["secondary_accent"])

    scenario_text = spec.get("scenario") or spec.get("lead_text") or "Formal Technical Scenario"
    p1 = tf_l.add_paragraph()
    p1.text = scenario_text
    p1.font.bold = True
    p1.font.size = Pt(15)
    p1.font.color.rgb = RGBColor(*pal["primary"])
    p1.space_before = Pt(8)

    scenario_items = spec.get("scenario_items") or spec.get("bullets", [])[:3]
    for itm in scenario_items:
        pb = tf_l.add_paragraph()
        pb.text = f"•  {itm}"
        pb.font.size = Pt(13)
        pb.font.color.rgb = RGBColor(*pal["text"])
        pb.space_before = Pt(6)

    # 2. Right Container: Step-by-Step Solution & Invariants
    right_card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.3), Inches(1.9), w_solution, Inches(4.9))
    right_card.fill.solid()
    right_card.fill.fore_color.rgb = RGBColor(255, 255, 255)
    right_card.line.color.rgb = RGBColor(*pal["accent"])
    right_card.line.width = Pt(1.5)

    tf_r = right_card.text_frame
    tf_r.word_wrap = True
    tf_r.margin_left = Inches(0.25)
    tf_r.margin_right = Inches(0.25)
    tf_r.margin_top = Inches(0.25)

    pr0 = tf_r.paragraphs[0]
    pr0.text = "STEP-BY-STEP DERIVATION & PROOF"
    pr0.font.bold = True
    pr0.font.size = Pt(12)
    pr0.font.color.rgb = RGBColor(*pal["accent"])

    solution_steps = spec.get("solution_steps") or spec.get("bullets", [])[3:] or [
        "Step 1: Compute closure of determinants to identify candidate keys.",
        "Step 2: Identify non-trivial dependencies where determinant is not a superkey.",
        "Step 3: Decompose into normalized projections satisfying lossless join invariants."
    ]
    for s_step in solution_steps:
        pb = tf_r.add_paragraph()
        pb.text = f"✔  {s_step}"
        pb.font.size = Pt(13)
        pb.font.color.rgb = RGBColor(*pal["text"])
        pb.space_before = Pt(8)

    if spec.get("invariant") or spec.get("verification"):
        inv = tf_r.add_paragraph()
        inv.text = f"VERIFICATION INVARIANT: {spec.get('invariant') or spec.get('verification')}"
        inv.font.bold = True
        inv.font.size = Pt(12)
        inv.font.color.rgb = RGBColor(*pal["primary"])
        inv.space_before = Pt(12)


def _render_diagram_split_slide(
    slide: Any,
    spec: Dict[str, Any],
    pal: Dict[str, Tuple[int, int, int]]
) -> None:
    """Split layout pairing technical mechanism prose with a crisp native shape vector diagram."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE

    _render_slide_header(slide, spec.get("title", ""), spec.get("subtitle"), spec.get("category_tag"), pal)

    w_text = Inches(5.3)
    w_diag = Inches(6.033)

    # Left Container: Detailed Technical Explanation
    text_card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.9), w_text, Inches(4.9))
    text_card.fill.solid()
    text_card.fill.fore_color.rgb = RGBColor(*pal["surface"])
    text_card.line.color.rgb = RGBColor(*pal["primary"])
    text_card.line.width = Pt(1.5)

    tf = text_card.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.25)
    tf.margin_right = Inches(0.25)
    tf.margin_top = Inches(0.25)

    p0 = tf.paragraphs[0]
    p0.text = "ARCHITECTURAL SPECIFICATION"
    p0.font.bold = True
    p0.font.size = Pt(11)
    p0.font.color.rgb = RGBColor(*pal["accent"])

    if spec.get("lead_text") or spec.get("body_text"):
        p_lead = tf.add_paragraph()
        p_lead.text = spec.get("lead_text") or spec.get("body_text")
        p_lead.font.size = Pt(13.5)
        p_lead.font.bold = True
        p_lead.font.color.rgb = RGBColor(*pal["primary"])
        p_lead.space_before = Pt(6)

    for b in spec.get("bullets", [])[:4]:
        pb = tf.add_paragraph()
        pb.text = f"•  {b}"
        pb.font.size = Pt(13)
        pb.font.color.rgb = RGBColor(*pal["text"])
        pb.space_before = Pt(7)

    # Right Container: Native Vector Diagram
    diag_type = spec.get("diagram_type", "").lower()
    diag_left = Inches(6.5)
    diag_top = Inches(1.9)

    # Check if an external image exists
    img_path = spec.get("image_path")
    if img_path and os.path.exists(img_path):
        try:
            slide.shapes.add_picture(img_path, diag_left, diag_top, w_diag, Inches(4.9))
            return
        except Exception:
            pass

    if "three_schema" in diag_type or "schema" in diag_type or "ansi" in diag_type:
        _draw_three_schema_diagram(slide, diag_left, diag_top, w_diag, Inches(4.9), pal)
    elif "bplus" in diag_type or "tree" in diag_type or "index" in diag_type:
        _draw_bplus_tree_diagram(slide, diag_left, diag_top, w_diag, Inches(4.9), pal)
    elif "slotted" in diag_type or "page" in diag_type or "storage" in diag_type:
        _draw_slotted_page_diagram(slide, diag_left, diag_top, w_diag, Inches(4.9), pal)
    else:
        _draw_general_architecture_diagram(slide, diag_left, diag_top, w_diag, Inches(4.9), pal, spec.get("diagram_components"))


def _draw_three_schema_diagram(
    slide: Any,
    left: Any,
    top: Any,
    w: Any,
    h: Any,
    pal: Dict[str, Tuple[int, int, int]]
) -> None:
    """Draws ANSI/SPARC 3-tier architecture with native shapes and bidirectional data independence arrows."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN

    # 1. External Level
    b1 = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top + Inches(0.1), w, Inches(1.15))
    b1.fill.solid()
    b1.fill.fore_color.rgb = RGBColor(*pal["surface"])
    b1.line.color.rgb = RGBColor(*pal["accent"])
    b1.line.width = Pt(1.5)
    p = b1.text_frame.paragraphs[0]
    p.text = "EXTERNAL LEVEL (User Views & Application Projections)"
    p.font.bold = True
    p.font.size = Pt(12.5)
    p.alignment = PP_ALIGN.CENTER
    p.font.color.rgb = RGBColor(*pal["primary"])
    p_sub = b1.text_frame.add_paragraph()
    p_sub.text = "Custom views tailored to specific departments/apps; shields apps from full schema."
    p_sub.font.size = Pt(10.5)
    p_sub.alignment = PP_ALIGN.CENTER
    p_sub.font.color.rgb = RGBColor(*pal["muted_text"])

    # Arrow 1: Logical Data Independence
    a1 = slide.shapes.add_shape(MSO_SHAPE.UP_DOWN_ARROW, left + w/2 - Inches(0.18), top + Inches(1.3), Inches(0.36), Inches(0.5))
    a1.fill.solid()
    a1.fill.fore_color.rgb = RGBColor(*pal["secondary_accent"])
    a1.line.fill.background()

    # 2. Conceptual Level
    b2 = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top + Inches(1.85), w, Inches(1.15))
    b2.fill.solid()
    b2.fill.fore_color.rgb = RGBColor(*pal["surface_alt"])
    b2.line.color.rgb = RGBColor(*pal["primary"])
    b2.line.width = Pt(1.5)
    p = b2.text_frame.paragraphs[0]
    p.text = "CONCEPTUAL LEVEL (Logical Community Schema)"
    p.font.bold = True
    p.font.size = Pt(12.5)
    p.alignment = PP_ALIGN.CENTER
    p.font.color.rgb = RGBColor(*pal["primary"])
    p_sub = b2.text_frame.add_paragraph()
    p_sub.text = "Defines all entities, relationships, constraints, and security invariants globally."
    p_sub.font.size = Pt(10.5)
    p_sub.alignment = PP_ALIGN.CENTER
    p_sub.font.color.rgb = RGBColor(*pal["text"])

    # Arrow 2: Physical Data Independence
    a2 = slide.shapes.add_shape(MSO_SHAPE.UP_DOWN_ARROW, left + w/2 - Inches(0.18), top + Inches(3.05), Inches(0.36), Inches(0.5))
    a2.fill.solid()
    a2.fill.fore_color.rgb = RGBColor(*pal["accent"])
    a2.line.fill.background()

    # 3. Internal Level
    b3 = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top + Inches(3.6), w, Inches(1.15))
    b3.fill.solid()
    b3.fill.fore_color.rgb = RGBColor(*pal["surface"])
    b3.line.color.rgb = RGBColor(*pal["accent"])
    b3.line.width = Pt(1.5)
    p = b3.text_frame.paragraphs[0]
    p.text = "INTERNAL LEVEL (Physical Storage & Access Paths)"
    p.font.bold = True
    p.font.size = Pt(12.5)
    p.alignment = PP_ALIGN.CENTER
    p.font.color.rgb = RGBColor(*pal["primary"])
    p_sub = b3.text_frame.add_paragraph()
    p_sub.text = "8KB Slotted Pages, B+ Tree Indexes, Disk Block Layouts, Compression & WAL."
    p_sub.font.size = Pt(10.5)
    p_sub.alignment = PP_ALIGN.CENTER
    p_sub.font.color.rgb = RGBColor(*pal["muted_text"])


def _draw_bplus_tree_diagram(
    slide: Any,
    left: Any,
    top: Any,
    w: Any,
    h: Any,
    pal: Dict[str, Tuple[int, int, int]]
) -> None:
    """Draws B+ Tree topology with root node, routing keys, and linked leaf nodes."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN

    # Root Node
    root_w = Inches(2.6)
    root = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left + w/2 - root_w/2, top + Inches(0.15), root_w, Inches(0.85))
    root.fill.solid()
    root.fill.fore_color.rgb = RGBColor(*pal["primary"])
    p = root.text_frame.paragraphs[0]
    p.text = "Root Node: [ 50 | • ]"
    p.font.bold = True
    p.font.size = Pt(12)
    p.alignment = PP_ALIGN.CENTER
    p.font.color.rgb = RGBColor(255, 255, 255)

    # Internal Nodes (2 branches)
    int_w = Inches(2.3)
    int1 = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left + Inches(0.3), top + Inches(1.5), int_w, Inches(0.85))
    int1.fill.solid()
    int1.fill.fore_color.rgb = RGBColor(*pal["secondary_accent"])
    p = int1.text_frame.paragraphs[0]
    p.text = "Internal: [ 20 | 35 ]"
    p.font.bold = True
    p.font.size = Pt(11)
    p.alignment = PP_ALIGN.CENTER
    p.font.color.rgb = RGBColor(255, 255, 255)

    int2 = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left + w - int_w - Inches(0.3), top + Inches(1.5), int_w, Inches(0.85))
    int2.fill.solid()
    int2.fill.fore_color.rgb = RGBColor(*pal["secondary_accent"])
    p = int2.text_frame.paragraphs[0]
    p.text = "Internal: [ 65 | 80 ]"
    p.font.bold = True
    p.font.size = Pt(11)
    p.alignment = PP_ALIGN.CENTER
    p.font.color.rgb = RGBColor(255, 255, 255)

    # Leaf Pages (4 connected leaf pages with bidirectional range pointers)
    leaf_w = Inches(1.3)
    labels = ["[ 10, 15 ]", "[ 20, 30 ]", "[ 50, 60 ]", "[ 80, 95 ]"]
    for j, lbl in enumerate(labels):
        pos_x = left + Inches(0.15) + j * Inches(1.48)
        leaf = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, pos_x, top + Inches(3.0), leaf_w, Inches(1.1))
        leaf.fill.solid()
        leaf.fill.fore_color.rgb = RGBColor(*pal["surface"])
        leaf.line.color.rgb = RGBColor(*pal["accent"])
        leaf.line.width = Pt(1.5)
        p = leaf.text_frame.paragraphs[0]
        p.text = f"Leaf {j+1}\n{lbl}"
        p.font.bold = True
        p.font.size = Pt(10)
        p.alignment = PP_ALIGN.CENTER
        p.font.color.rgb = RGBColor(*pal["primary"])

    # Range scan arrow at bottom
    scan_box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left + Inches(0.15), top + Inches(4.25), w - Inches(0.3), Inches(0.45))
    scan_box.fill.solid()
    scan_box.fill.fore_color.rgb = RGBColor(*pal["surface_alt"])
    scan_box.line.fill.background()
    p = scan_box.text_frame.paragraphs[0]
    p.text = "⇄  Bidirectional Linked Leaf Pages Enabling O(log N) + Range Scan Traversals"
    p.font.bold = True
    p.font.size = Pt(10.5)
    p.alignment = PP_ALIGN.CENTER
    p.font.color.rgb = RGBColor(*pal["accent"])


def _draw_slotted_page_diagram(
    slide: Any,
    left: Any,
    top: Any,
    w: Any,
    h: Any,
    pal: Dict[str, Tuple[int, int, int]]
) -> None:
    """Draws 8KB Slotted Page frame showing Header, Slot Directory, Free Space, and Tuples."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN

    # Frame Box
    frame = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, w, h)
    frame.fill.solid()
    frame.fill.fore_color.rgb = RGBColor(248, 250, 252)
    frame.line.color.rgb = RGBColor(*pal["primary"])
    frame.line.width = Pt(2.0)

    # 1. Page Header
    hdr = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left + Inches(0.2), top + Inches(0.2), w - Inches(0.4), Inches(0.85))
    hdr.fill.solid()
    hdr.fill.fore_color.rgb = RGBColor(*pal["primary"])
    p = hdr.text_frame.paragraphs[0]
    p.text = "PAGE HEADER: LSN | Free Space Pointer | Slot Count"
    p.font.bold = True
    p.font.size = Pt(11)
    p.alignment = PP_ALIGN.CENTER
    p.font.color.rgb = RGBColor(255, 255, 255)

    # 2. Slot Directory (Growing Downward)
    sdir = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left + Inches(0.2), top + Inches(1.15), w - Inches(0.4), Inches(0.8))
    sdir.fill.solid()
    sdir.fill.fore_color.rgb = RGBColor(*pal["secondary_accent"])
    p = sdir.text_frame.paragraphs[0]
    p.text = "SLOT DIRECTORY: [ Slot 1: Offset | Slot 2: Offset | Slot 3: Offset ] 🡇"
    p.font.bold = True
    p.font.size = Pt(10.5)
    p.alignment = PP_ALIGN.CENTER
    p.font.color.rgb = RGBColor(255, 255, 255)

    # 3. Contiguous Free Space
    fspace = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left + Inches(0.2), top + Inches(2.05), w - Inches(0.4), Inches(1.2))
    fspace.fill.solid()
    fspace.fill.fore_color.rgb = RGBColor(*pal["surface_alt"])
    p = fspace.text_frame.paragraphs[0]
    p.text = "--- CONTIGUOUS FREE SPACE GAP ---"
    p.font.bold = True
    p.font.size = Pt(11)
    p.alignment = PP_ALIGN.CENTER
    p.font.color.rgb = RGBColor(*pal["muted_text"])

    # 4. Tuple Records (Growing Upward)
    trec = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left + Inches(0.2), top + Inches(3.35), w - Inches(0.4), Inches(1.25))
    trec.fill.solid()
    trec.fill.fore_color.rgb = RGBColor(*pal["accent"])
    p = trec.text_frame.paragraphs[0]
    p.text = "🡅 TUPLE DATA STORE: [ Record 3 (Var-Len) | Record 2 | Record 1 ]"
    p.font.bold = True
    p.font.size = Pt(10.5)
    p.alignment = PP_ALIGN.CENTER
    p.font.color.rgb = RGBColor(255, 255, 255)


def _draw_general_architecture_diagram(
    slide: Any,
    left: Any,
    top: Any,
    w: Any,
    h: Any,
    pal: Dict[str, Tuple[int, int, int]],
    components: Optional[List[str]] = None
) -> None:
    """Draws 3 or 4 connected subsystem containers."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN

    comps = components or [
        "Client Application & Query Interface",
        "Orchestration & Verification Subsystem",
        "Distributed Execution & Transaction Engine",
        "Persistent Storage & Write-Ahead Log Store"
    ]
    box_h = Inches(0.9)
    gap = Inches(0.35)
    for i, c in enumerate(comps[:4]):
        b = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top + i * (box_h + gap), w, box_h)
        b.fill.solid()
        b.fill.fore_color.rgb = RGBColor(*pal["surface"])
        b.line.color.rgb = RGBColor(*pal["accent"]) if i % 2 == 0 else RGBColor(*pal["primary"])
        b.line.width = Pt(1.5)
        p = b.text_frame.paragraphs[0]
        p.text = f"LAYER 0{i+1}: {c}"
        p.font.bold = True
        p.font.size = Pt(12)
        p.alignment = PP_ALIGN.CENTER
        p.font.color.rgb = RGBColor(*pal["primary"])


def _render_conclusion_slide(
    slide: Any,
    spec: Dict[str, Any],
    pal: Dict[str, Tuple[int, int, int]]
) -> None:
    """Executive synthesis slide with top takeaway card and 3 architectural pillars."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE

    _render_slide_header(slide, spec.get("title", "Synthesis & Architectural Blueprint"), spec.get("subtitle", "Strategic Invariants, Takeaways & Future Directions"), spec.get("category_tag", "SYNTHESIS"), pal)

    # Top Hero Takeaway Card
    hero = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.9), Inches(11.733), Inches(1.3))
    hero.fill.solid()
    hero.fill.fore_color.rgb = RGBColor(*pal["primary"])
    hero.line.fill.background()
    tf_h = hero.text_frame
    tf_h.word_wrap = True
    tf_h.margin_left = Inches(0.3)
    tf_h.margin_top = Inches(0.2)

    p0 = tf_h.paragraphs[0]
    p0.text = "CORE SYNTHESIS"
    p0.font.bold = True
    p0.font.size = Pt(11)
    p0.font.color.rgb = RGBColor(*pal["accent"])

    p1 = tf_h.add_paragraph()
    p1.text = spec.get("lead_text") or spec.get("body_text") or "Relational database engines represent computing's most resilient abstraction, unifying mathematical algebra with persistent crash-recovery guarantees."
    p1.font.bold = True
    p1.font.size = Pt(14)
    p1.font.color.rgb = RGBColor(255, 255, 255)
    p1.space_before = Pt(4)

    # 3 Takeaway Pillars Below
    pillars = spec.get("pillars") or spec.get("bullets", [])[:3]
    w = (Inches(11.733) - Inches(0.4) * 2) / 3
    for i, pil in enumerate(pillars[:3]):
        left = Inches(0.8) + i * (w + Inches(0.4))
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, Inches(3.45), w, Inches(3.35))
        card.fill.solid()
        card.fill.fore_color.rgb = RGBColor(*pal["surface"])
        card.line.color.rgb = RGBColor(*pal["accent"])
        card.line.width = Pt(1.5)

        tf_p = card.text_frame
        tf_p.word_wrap = True
        tf_p.margin_left = Inches(0.2)
        tf_p.margin_right = Inches(0.2)
        tf_p.margin_top = Inches(0.2)

        pt0 = tf_p.paragraphs[0]
        pt0.text = f"PILLAR 0{i+1}"
        pt0.font.bold = True
        pt0.font.size = Pt(11)
        pt0.font.color.rgb = RGBColor(*pal["accent"])

        pt1 = tf_p.add_paragraph()
        if isinstance(pil, dict):
            pt0.text = str(pil.get("pillar") or f"PILLAR 0{i+1}").upper()
            pt1.text = pil.get("title", f"Principle {i+1}")
            pt1.font.bold = True
            pt1.font.size = Pt(14)
            pt1.font.color.rgb = RGBColor(*pal["primary"])
            pt1.space_before = Pt(4)

            if pil.get("desc"):
                pt2 = tf_p.add_paragraph()
                pt2.text = str(pil.get("desc"))
                pt2.font.size = Pt(11.5)
                pt2.font.color.rgb = RGBColor(*pal["text"])
                pt2.space_before = Pt(4)
        else:
            pt1.text = str(pil)
            pt1.font.size = Pt(13)
            pt1.font.color.rgb = RGBColor(*pal["text"])
            pt1.space_before = Pt(6)


def _render_references_slide(
    slide: Any,
    spec: Dict[str, Any],
    pal: Dict[str, Tuple[int, int, int]]
) -> None:
    """Authoritative reference bibliography slide in two balanced columns."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE

    _render_slide_header(slide, spec.get("title", "Authoritative References & Academic Bibliography"), spec.get("subtitle", "Foundational Literature, Standards & Industry Benchmarks"), spec.get("category_tag", "BIBLIOGRAPHY"), pal)

    refs = spec.get("references") or spec.get("bullets") or [
        "Codd, E. F. (1970). A Relational Model of Data for Large Shared Data Banks. Communications of the ACM, 13(6).",
        "Mohan, C., et al. (1992). ARIES: A Transaction Recovery Method Supporting Fine-Granularity Locking. ACM TODS.",
        "Gray, J., & Reuter, A. (1993). Transaction Processing: Concepts and Techniques. Morgan Kaufmann.",
        "Kleppmann, M. (2017). Designing Data-Intensive Applications: The Big Ideas Behind Reliable Systems. O'Reilly Media.",
        "Silberschatz, A., Korth, H., & Sudarshan, S. (2020). Database System Concepts (7th ed.). McGraw-Hill."
    ]

    col_w = Inches(5.66)
    gap = Inches(0.4)
    half = math.ceil(len(refs) / 2)
    col1 = refs[:half]
    col2 = refs[half:]

    for c_idx, col_items in enumerate([col1, col2]):
        left = Inches(0.8) + c_idx * (col_w + gap)
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, Inches(1.9), col_w, Inches(4.9))
        card.fill.solid()
        card.fill.fore_color.rgb = RGBColor(*pal["surface"])
        card.line.color.rgb = RGBColor(*pal["accent"])
        card.line.width = Pt(1.5)

        tf = card.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.25)
        tf.margin_right = Inches(0.25)
        tf.margin_top = Inches(0.25)

        p0 = tf.paragraphs[0]
        p0.text = "PRIMARY CITATIONS" if c_idx == 0 else "SYSTEM STANDARDS & MONOGRAPHS"
        p0.font.bold = True
        p0.font.size = Pt(12)
        p0.font.color.rgb = RGBColor(*pal["accent"])

        for itm_idx, itm in enumerate(col_items):
            pb = tf.add_paragraph()
            pb.text = f"[{c_idx * half + itm_idx + 1}]  {itm}"
            pb.font.size = Pt(11.5)
            pb.font.color.rgb = RGBColor(*pal["text"])
            pb.space_before = Pt(8)


def _render_content_slide(
    slide: Any,
    spec: Dict[str, Any],
    pal: Dict[str, Tuple[int, int, int]]
) -> None:
    """Enhanced fallback content layout with lead narrative card and structured 2-column bullet containers."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE

    _render_slide_header(slide, spec.get("title", ""), spec.get("subtitle"), spec.get("category_tag"), pal)

    bullets = spec.get("bullets", [])
    lead = spec.get("lead_text") or spec.get("body_text")

    # If 4 or more bullets, render as 2 balanced cards
    if len(bullets) >= 4:
        half = math.ceil(len(bullets) / 2)
        columns = [
            {"title": "Foundational Principles", "lead_text": lead, "bullets": bullets[:half]},
            {"title": "Operational Mechanisms & Invariants", "bullets": bullets[half:]}
        ]
        _render_two_column_slide(slide, {**spec, "columns": columns}, pal)
    else:
        # Single wide container
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.9), Inches(11.733), Inches(4.9))
        card.fill.solid()
        card.fill.fore_color.rgb = RGBColor(*pal["surface"])
        card.line.color.rgb = RGBColor(*pal["accent"])
        card.line.width = Pt(1.5)

        tf = card.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.3)
        tf.margin_right = Inches(0.3)
        tf.margin_top = Inches(0.3)

        if lead:
            p_lead = tf.paragraphs[0]
            p_lead.text = lead
            p_lead.font.size = Pt(15)
            p_lead.font.bold = True
            p_lead.font.color.rgb = RGBColor(*pal["primary"])
            p_lead.space_after = Pt(10)

        for b in bullets:
            pb = tf.add_paragraph()
            pb.text = f"•  {b}"
            pb.font.size = Pt(14)
            pb.font.color.rgb = RGBColor(*pal["text"])
            pb.space_before = Pt(10)


# ============================================================================
# Main Authoritative create_presentation Function
# ============================================================================

def create_presentation(
    title: str,
    subtitle: Optional[str] = None,
    slides: Optional[List[Union[Dict[str, Any], Any]]] = None,
    filename: Optional[str] = None,
    author: Optional[str] = None,
    theme: str = "navy",
    audience: Optional[str] = None,
    genre: Optional[str] = None,
    category_tag: Optional[str] = None,
    overwrite: bool = True
) -> Dict[str, Any]:
    """
    Authoritative presentation generator for Smart Assistant.
    Produces enterprise-grade, visually engaging PowerPoint presentations (.pptx)
    with intentional layouts (tables, diagrams, process flows, worked examples, cards).
    """
    try:
        from pptx import Presentation
        from pptx.util import Inches
        from instance.config import get_branding_author

        author = get_branding_author(author)

        prs = Presentation()
        prs.slide_width = Inches(13.333)   # 16:9 Widescreen
        prs.slide_height = Inches(7.5)
        blank_layout = prs.slide_layouts[6]

        try:
            prs.core_properties.title = title
            prs.core_properties.author = author
        except Exception:
            pass

        pal = _get_theme_palette(theme)

        # 1. Slide 1: Hero Title Slide
        title_slide = prs.slides.add_slide(blank_layout)
        _render_title_slide(
            slide=title_slide,
            title=title,
            subtitle=subtitle,
            author=author,
            category_tag=category_tag or (f"{genre.upper()} PRESENTATION" if genre else "TECHNICAL MASTERCLASS"),
            pal=pal
        )
        title_notes = title_slide.notes_slide
        title_notes.notes_text_frame.text = f"Presentation Title: {title}. Prepared by {author} for {audience or 'Engineering Professionals'} on {datetime.now().strftime('%Y-%m-%d')}."

        # 2. Render Subsequent Slides
        if slides:
            for s_raw in slides:
                # Normalize SlideSpec objects or dictionaries
                if hasattr(s_raw, "to_dict"):
                    s_info = s_raw.to_dict()
                elif hasattr(s_raw, "layout"):
                    s_info = {
                        "layout": getattr(s_raw.layout, "value", str(s_raw.layout)),
                        "title": getattr(s_raw, "title", ""),
                        "subtitle": getattr(s_raw, "subtitle", None),
                        "category_tag": getattr(s_raw, "category_tag", None),
                        "body_text": getattr(s_raw, "body_text", None),
                        "lead_text": getattr(s_raw, "body_text", None),
                        "bullets": getattr(s_raw, "bullets", []),
                        "columns": getattr(s_raw, "columns", None),
                        "cards": getattr(s_raw, "cards", None),
                        "process_steps": getattr(s_raw, "process_steps", None),
                        "kpis": getattr(s_raw, "kpis", None),
                        "table": getattr(s_raw, "table", None),
                        "notes": getattr(s_raw, "speaker_notes", None),
                    }
                elif isinstance(s_raw, dict):
                    s_info = s_raw
                else:
                    s_info = {"title": str(s_raw), "bullets": []}

                explicit_layout = (s_info.get("layout") or s_info.get("type") or "").lower().replace("-", "_")
                t_lower = (s_info.get("title") or "").lower()

                if explicit_layout and explicit_layout not in ("content", "default"):
                    s_type = explicit_layout
                elif s_info.get("table") or s_info.get("rows"):
                    s_type = "table"
                elif s_info.get("process_steps") or s_info.get("steps"):
                    s_type = "process_flow"
                elif s_info.get("cards"):
                    s_type = "cards_grid"
                elif s_info.get("scenario") or s_info.get("solution_steps"):
                    s_type = "worked_example"
                elif s_info.get("diagram_type") or s_info.get("diagram_components"):
                    s_type = "diagram_split"
                elif s_info.get("pillars") or any(k in t_lower for k in ["synthesis", "takeaway", "conclusion"]):
                    s_type = "conclusion"
                elif s_info.get("references") or s_info.get("citations") or any(k in t_lower for k in ["reference", "bibliography"]):
                    s_type = "references"
                elif s_info.get("modules") or any(k in t_lower for k in ["agenda", "roadmap", "curriculum"]):
                    s_type = "agenda"
                elif s_info.get("columns") or len(s_info.get("bullets", [])) >= 4:
                    s_type = "two_column"
                else:
                    s_type = explicit_layout or "content"

                slide = prs.slides.add_slide(blank_layout)

                if s_type in ("agenda", "table_of_contents", "roadmap"):
                    _render_agenda_slide(slide, s_info, pal)
                elif s_type in ("section", "section_divider"):
                    _render_section_divider(slide, s_info, pal)
                elif s_type in ("two_column", "two_columns", "comparison"):
                    _render_two_column_slide(slide, s_info, pal)
                elif s_type in ("cards", "cards_grid", "card_grid"):
                    _render_cards_grid_slide(slide, s_info, pal)
                elif s_type in ("process_flow", "pipeline", "process", "workflow"):
                    _render_process_flow_slide(slide, s_info, pal)
                elif s_type in ("table", "comparison_table"):
                    _render_table_slide(slide, s_info, pal)
                elif s_type in ("worked_example", "case_study", "problem_solution"):
                    _render_worked_example_slide(slide, s_info, pal)
                elif s_type in ("diagram_split", "architecture_diagram", "diagram"):
                    _render_diagram_split_slide(slide, s_info, pal)
                elif s_type in ("conclusion", "summary", "takeaways"):
                    _render_conclusion_slide(slide, s_info, pal)
                elif s_type in ("references", "bibliography", "citations"):
                    _render_references_slide(slide, s_info, pal)
                else:
                    _render_content_slide(slide, s_info, pal)

                # Attach Speaker Notes
                notes_text = s_info.get("notes") or s_info.get("speaker_notes")
                if notes_text:
                    n_slide = slide.notes_slide
                    n_slide.notes_text_frame.text = str(notes_text)

        # Output Path Resolution using Canonical SemanticFileNamingService
        from core.semantic_file_naming import get_semantic_file_naming_service
        namer = get_semantic_file_naming_service()

        if not filename:
            target_path, _ = namer.resolve_output_path(
                task_description=title,
                title=title,
                artifact_type="presentation",
                extension=".pptx"
            )
            out_dir = os.path.dirname(target_path)
        else:
            clean_name = namer.sanitize_filename(filename)
            if not clean_name.endswith(".pptx"):
                clean_name += ".pptx"
            if os.path.isabs(filename):
                target_path = filename
                out_dir = os.path.dirname(target_path)
            else:
                out_dir = namer.get_default_output_dir()
                if overwrite:
                    target_path = os.path.join(out_dir, clean_name)
                else:
                    target_path = namer.get_unique_path(out_dir, os.path.splitext(clean_name)[0], ".pptx")

        os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
        prs.save(target_path)
        logger.info(f"[PPTX] High-quality presentation saved to: {target_path}")

        total_slides = len(prs.slides)
        return {
            "success": True,
            "status": "success",
            "filepath": target_path,
            "filename": os.path.basename(target_path),
            "slide_count": total_slides,
            "message": f"PowerPoint presentation '{os.path.basename(target_path)}' with {total_slides} slides created in {out_dir}."
        }
    except Exception as e:
        logger.error(f"[PPTX] Failed to create presentation: {e}", exc_info=True)
        return {
            "success": False,
            "status": "error",
            "error": str(e),
            "message": f"Failed to create PowerPoint presentation: {e}"
        }


# Alias for backward compatibility
build_presentation = create_presentation
