"""
Document & PDF Environment Adapter
Specialized observer for document readers and office applications
(Adobe Acrobat, SumatraPDF, Edge/Foxit PDF, MS Word, MS Excel, PowerPoint, Notepad, WordPad).
Extracts document name, file path, type, and reading/editing context.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, Optional, Tuple

from core.environment.adapters.base_adapter import BaseEnvironmentAdapter
from core.environment.models import EnvironmentState


class DocumentEnvironmentAdapter(BaseEnvironmentAdapter):
    """
    Adapter for PDF readers, Word processors, and text editors.
    Extracts document titles, extensions, and user reading/editing context.
    """

    name = "document"
    app_category = "document"

    DOC_APPS = {
        "acrobat", "acrord32", "sumatrapdf", "foxit", "winword", "word",
        "excel", "powerpnt", "powerpoint", "notepad", "wordpad"
    }

    def can_handle(self, app_name: str, window_info: Dict[str, Any]) -> bool:
        clean_app = (app_name or "").lower().strip()
        cls_name = (window_info.get("class_name") or "").lower()
        title = (window_info.get("title") or "").lower()

        if any(a in clean_app for a in self.DOC_APPS):
            return True
        if any(k in cls_name for k in ("acrobat", "sumatra", "wordpadclass", "notepad", "opusapp")):
            return True
        if any(k in title for k in ("adobe acrobat", "sumatrapdf", "foxit reader", " - word", " - excel", " - powerpoint", " - notepad")):
            return True
        if re.search(r'\.(pdf|docx|doc|xlsx|pptx|txt|rtf|md)\b', title, re.IGNORECASE):
            return True
        return False

    def extract_state(self, window_info: Dict[str, Any], hierarchy_level: int = 1) -> Optional[EnvironmentState]:
        title = (window_info.get("title") or "").strip()
        cls_name = window_info.get("class_name", "")
        pid = window_info.get("pid", 0)
        hwnd = window_info.get("hwnd", 0)
        t_low = title.lower()

        # Determine application type
        app_name = "notepad"
        doc_type = "text"
        if "acrobat" in t_low or "acrobat" in cls_name.lower():
            app_name = "acrobat"
            doc_type = "pdf"
        elif "sumatra" in t_low:
            app_name = "sumatrapdf"
            doc_type = "pdf"
        elif "word" in t_low or "opusapp" in cls_name.lower() or "winword" in t_low:
            app_name = "word"
            doc_type = "word"
        elif "excel" in t_low:
            app_name = "excel"
            doc_type = "spreadsheet"
        elif "powerpoint" in t_low or "powerpnt" in t_low:
            app_name = "powerpoint"
            doc_type = "presentation"
        elif "wordpad" in t_low:
            app_name = "wordpad"
            doc_type = "document"
        elif ".pdf" in t_low:
            app_name = "pdf_reader"
            doc_type = "pdf"
        else:
            app_name = "notepad"
            doc_type = "text"

        is_dirty = title.startswith("*")
        clean_title = title[1:].strip() if is_dirty else title

        # Strip application suffix
        clean_title = re.sub(
            r'\s*-\s*(?:Adobe\s+Acrobat(?:\s+Reader)?(?:\s*\(\d+-bit\))?|SumatraPDF|Foxit\s+Reader|Word|Excel|PowerPoint|Notepad|WordPad)$',
            '', clean_title, flags=re.IGNORECASE
        ).strip()

        # Extract page number if present in title (e.g. "[Page 5] report.pdf" or "report.pdf (Page 3)")
        page_num: Optional[int] = None
        m_page = re.search(r'(?:\[|\()(?:page\s*)?(\d+)(?:\]|\))', clean_title, re.IGNORECASE)
        if m_page:
            try:
                page_num = int(m_page.group(1))
            except Exception:
                pass
            clean_title = re.sub(r'(?:\[|\()(?:page\s*)?\d+(?:\]|\))', '', clean_title).strip()

        doc_name = clean_title or ("Untitled" if not is_dirty else "Untitled (unsaved)")
        entities: Dict[str, Any] = {
            "document_name": doc_name,
            "doc_type": doc_type,
            "application": app_name,
            "is_modified": is_dirty,
            "raw_title": title,
        }
        if page_num:
            entities["page"] = page_num

        if "." in doc_name:
            entities["file_extension"] = doc_name.rsplit(".", 1)[-1].lower()

        # Build human-readable content context
        page_str = f" on page {page_num}" if page_num else ""
        if doc_type == "pdf":
            content_ctx = f"Reading PDF '{doc_name}'{page_str} in {app_name.capitalize()}"
        elif doc_type == "word":
            content_ctx = f"Editing document '{doc_name}' in Microsoft Word"
        elif doc_type == "spreadsheet":
            content_ctx = f"Working on spreadsheet '{doc_name}' in Microsoft Excel"
        elif doc_type == "presentation":
            content_ctx = f"Editing presentation '{doc_name}' in PowerPoint"
        else:
            content_ctx = f"Editing '{doc_name}' in Notepad"

        return EnvironmentState(
            timestamp=time.time(),
            application=app_name,
            window_title=title,
            window_hwnd=hwnd,
            window_pid=pid,
            process_name=f"{app_name}.exe",
            app_category="document",
            active_entities=entities,
            content_context=content_ctx,
            visible_text=doc_name,
            user_action_summary=f"Viewing {doc_type} '{doc_name}'",
            source_tier="integration",
            metadata={"doc_type": doc_type, "is_dirty": is_dirty},
        )

    def detect_action(
        self,
        before: EnvironmentState,
        after: EnvironmentState,
    ) -> Tuple[str, str, str]:
        if before.application != after.application:
            return (
                "APP_SWITCH",
                f"Switched to {after.application.capitalize()}",
                f"Switched from {before.application} to {after.application}",
            )

        b_doc = before.get_entity("document_name")
        a_doc = after.get_entity("document_name")
        b_page = before.get_entity("page")
        a_page = after.get_entity("page")

        if a_doc and b_doc and a_doc != b_doc:
            return (
                "DOCUMENT_SWITCH",
                f"Switched document to '{a_doc}'",
                f"Document reader: switched from '{b_doc}' to '{a_doc}'",
            )

        if a_page and b_page and a_page != b_page:
            return (
                "PAGE_TURN",
                f"Turned to page {a_page}",
                f"Document: changed page from {b_page} to {a_page}",
            )

        if after.get_entity("is_modified") and not before.get_entity("is_modified"):
            return (
                "DOCUMENT_MODIFIED",
                f"Edited document '{a_doc}'",
                f"Document '{a_doc}' was modified",
            )

        return ("NO_CHANGE", "No change", "Document state remained stable")
