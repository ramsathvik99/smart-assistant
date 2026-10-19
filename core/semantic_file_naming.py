"""
Universal Semantic File Naming & Path Resolution Service.

Provides a unified, system-wide canonical service for:
1. Deriving concise, descriptive, filesystem-safe filenames from natural language requests,
   artifact type, conversation context, and generated content.
2. Cross-platform filename sanitization, character filtering, and Windows reserved name guards.
3. Safe duplicate resolution without silent overwrites (incrementing _2, _3, etc.).
4. Strict path traversal guards and directory boundary containment.
5. Project directory naming and multi-file project workspace organization.
6. Recording artifact metadata and task lineage in the Artifact Context Graph.
"""

from __future__ import annotations

import os
import re
import threading
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("SemanticFileNaming")

# Windows reserved device names (must not be used even with extensions)
_WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9"
}

# Standard command action verbs to strip
_COMMAND_VERBS = {
    "create", "created", "generate", "generated", "write", "wrote", "make", "made",
    "build", "built", "produce", "draft", "export", "save", "prepare", "provide",
    "give", "develop", "implement", "construct", "code", "run", "display", "show"
}

# Courtesy prefixes and question phrases
_PREFIX_PHRASES = [
    r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)[,\s:]*',
    r'^(?:test\s+(?:the\s+)?actual\s+output\s+(?:to\s+)?|test\s+(?:the\s+)?output\s+(?:to\s+)?|test\s+)',
    r'^(?:can\s+you\s+|could\s+you\s+|please\s+|kindly\s+|i\s+want\s+you\s+to\s+|i\s+need\s+you\s+to\s+|i\s+need\s+(?:a|an)?\s*)',
    r'^(?:give\s+me\s+(?:a|an)?\s*)',
]

# Common filler adjectives to strip from topics
_FILLER_ADJECTIVES = {
    "a", "an", "the", "some", "any", "my", "our", "this", "that", "me", "us",
    "detailed", "comprehensive", "simple", "quick", "full",
    "new", "professional", "complete", "basic", "advanced", "sample", "example",
    "powerful", "high-yield", "high", "yield", "strategic", "executive", "short", "brief"
}

# Standard artifact noun descriptors
_ARTIFACT_DESCRIPTORS = {
    "notes": "notes",
    "note": "notes",
    "study notes": "notes",
    "study_notes": "notes",
    "report": "report",
    "research report": "report",
    "summary": "summary",
    "executive summary": "summary",
    "brief": "summary",
    "proposal": "proposal",
    "project proposal": "proposal",
    "business proposal": "proposal",
    "specification": "specification",
    "spec": "specification",
    "documentation": "documentation",
    "cheatsheet": "cheatsheet",
    "cheat sheet": "cheatsheet",
    "calendar": "calendar",
    "schedule": "calendar",
    "study schedule": "calendar",
    "presentation": "presentation",
    "ppt": "presentation",
    "pptx": "presentation",
    "powerpoint": "presentation",
    "powerpoint presentation": "presentation",
    "slides": "presentation",
    "slide deck": "presentation",
    "deck": "presentation",
    "spreadsheet": "spreadsheet",
    "expense sheet": "expense_sheet",
    "sheet": "sheet",
    "data": "data",
    "dataset": "dataset",
    "tracker": "tracker",
    "model": "model",
    "website": "website",
    "portfolio": "portfolio_website",
    "portfolio website": "portfolio_website",
    "app": "app",
    "application": "application",
    "script": "script",
    "tool": "tool",
    "diagram": "diagram",
    "architecture diagram": "architecture_diagram",
    "chart": "chart",
    "flowchart": "flowchart",
}

# Standard extension mappings
_EXTENSION_MAP = {
    "word": ".docx",
    "doc": ".docx",
    "docx": ".docx",
    "pdf": ".pdf",
    "powerpoint": ".pptx",
    "ppt": ".pptx",
    "pptx": ".pptx",
    "excel": ".xlsx",
    "xls": ".xlsx",
    "xlsx": ".xlsx",
    "csv": ".csv",
    "python": ".py",
    "py": ".py",
    "javascript": ".js",
    "js": ".js",
    "typescript": ".ts",
    "ts": ".ts",
    "html": ".html",
    "htm": ".html",
    "css": ".css",
    "java": ".java",
    "c++": ".cpp",
    "cpp": ".cpp",
    "c": ".c",
    "c#": ".cs",
    "cs": ".cs",
    "csharp": ".cs",
    "sql": ".sql",
    "markdown": ".md",
    "md": ".md",
    "text": ".txt",
    "txt": ".txt",
    "json": ".json",
    "xml": ".xml",
    "yaml": ".yaml",
    "yml": ".yaml",
    "png": ".png",
    "jpg": ".jpg",
    "jpeg": ".jpg",
    "ics": ".ics"
}


class SemanticFileNamingService:
    """
    Authoritative canonical service for generating semantic, context-aware,
    filesystem-safe filenames across the entire assistant ecosystem.
    """

    def __init__(self):
        self._lock = threading.Lock()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Output Directory Resolution & Path Safety
    # ─────────────────────────────────────────────────────────────────────────

    def get_default_output_dir(self, artifact_type: Optional[str] = None) -> str:
        """
        Resolve standard user-facing deliverable directory.
        Checks OneDrive Desktop, Standard Desktop, Downloads, and Documents.
        """
        home = os.path.expanduser("~")
        onedrive_desktop = os.path.join(home, "OneDrive", "Desktop")
        if os.path.exists(onedrive_desktop) and os.path.isdir(onedrive_desktop):
            return onedrive_desktop
        standard_desktop = os.path.join(home, "Desktop")
        if os.path.exists(standard_desktop) and os.path.isdir(standard_desktop):
            return standard_desktop
        onedrive_docs = os.path.join(home, "OneDrive", "Documents")
        if os.path.exists(onedrive_docs) and os.path.isdir(onedrive_docs):
            return onedrive_docs
        standard_docs = os.path.join(home, "Documents")
        if os.path.exists(standard_docs) and os.path.isdir(standard_docs):
            return standard_docs
        return home

    def get_downloads_dir(self) -> str:
        """Resolve standard user Downloads directory."""
        home = os.path.expanduser("~")
        dl = os.path.join(home, "Downloads")
        os.makedirs(dl, exist_ok=True)
        return dl

    def is_safe_path(self, target_path: str, allowed_roots: Optional[List[str]] = None) -> bool:
        """
        Verify target path does not escape allowed directories or attempt path traversal.
        """
        try:
            abs_target = os.path.abspath(target_path)
            # Check for null bytes
            if "\x00" in target_path:
                return False

            if allowed_roots is None:
                import tempfile
                home = os.path.expanduser("~")
                cwd = os.getcwd()
                allowed_roots = [
                    home,
                    os.path.join(home, "OneDrive", "Desktop"),
                    os.path.join(home, "Desktop"),
                    os.path.join(home, "OneDrive", "Documents"),
                    os.path.join(home, "Documents"),
                    os.path.join(home, "Downloads"),
                    cwd,
                    os.path.join(cwd, "data"),
                    tempfile.gettempdir(),
                    os.environ.get("TEMP", "C:\\temp"),
                    os.environ.get("TMP", "C:\\temp")
                ]

            for root in allowed_roots:
                if not root:
                    continue
                abs_root = os.path.abspath(root)
                try:
                    if os.path.commonpath([abs_root, abs_target]) == abs_root:
                        return True
                except ValueError:
                    # Different drive letters on Windows
                    continue

            return False
        except Exception:
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Extension Normalization
    # ─────────────────────────────────────────────────────────────────────────

    def normalize_extension(self, extension_or_format: str, default: str = ".txt") -> str:
        """Convert any format name or extension string into a standard dot-prefixed extension."""
        if not extension_or_format:
            return default
        raw = extension_or_format.strip().lower()
        if raw in _EXTENSION_MAP:
            return _EXTENSION_MAP[raw]
        cleaned = raw if raw.startswith(".") else f".{raw}"
        # Validate that cleaned extension contains only alphanumeric chars after dot
        if re.match(r'^\.[a-z0-9]+$', cleaned):
            return cleaned
        return default

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Filename Sanitization & OS Compliance
    # ─────────────────────────────────────────────────────────────────────────

    def sanitize_filename(
        self,
        filename: str,
        max_length: int = 70,
        default_name: str = "artifact",
        target_extension: Optional[str] = None,
        **kwargs: Any
    ) -> str:
        """
        Sanitizes a filename to be 100% compliant with Windows and POSIX filesystems.
        - Removes control characters and invalid chars (<>:"/\\|?*[](){}'`).
        - Prevents Windows reserved device names (CON, NUL, AUX, etc.).
        - Trims leading/trailing whitespace and dots.
        - Enforces length limit without breaking words awkwardly.
        """
        if not filename:
            return f"{default_name}{self.normalize_extension(target_extension) if target_extension else ''}"

        # Split stem and extension if extension exists
        stem, ext = os.path.splitext(filename)
        if target_extension:
            ext = self.normalize_extension(target_extension)
        elif ext and not re.match(r'^\.[a-zA-Z0-9]{1,10}$', ext):
            stem = filename
            ext = ""

        # Remove control characters and invalid filesystem characters including brackets/quotes
        cleaned = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*\[\]\(\)\{\}\'\`]+', '_', stem)
        # Replace multiple spaces, hyphens, and underscores with a single underscore
        cleaned = re.sub(r'[\s\-]+', '_', cleaned)
        cleaned = re.sub(r'_+', '_', cleaned)
        cleaned = cleaned.strip('._ ')

        # Enforce lowercase convention
        cleaned = cleaned.lower()

        # Check for Windows reserved names
        if cleaned in _WINDOWS_RESERVED_NAMES or any(cleaned == res or cleaned.startswith(f"{res}_") for res in ("con", "prn", "aux", "nul", "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9", "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9")):
            cleaned = f"safe_{cleaned}"

        if not cleaned:
            cleaned = default_name

        # Enforce max length at word boundary
        if len(cleaned) > max_length:
            truncated = cleaned[:max_length].rstrip('_')
            last_under = truncated.rfind('_')
            if last_under > max_length // 2:
                cleaned = truncated[:last_under]
            else:
                cleaned = truncated

        return f"{cleaned}{ext.lower()}"

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Semantic Derivation Engine
    # ─────────────────────────────────────────────────────────────────────────

    def derive_semantic_filename(
        self,
        task_description: str = "",
        title: Optional[str] = None,
        artifact_type: Optional[str] = None,
        extension: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        content_preview: Optional[str] = None,
        is_project_dir: bool = False
    ) -> str:
        """
        Derive a concise, descriptive semantic filename from the user's prompt,
        task context, artifact type, and actual content.

        Guarantees:
        - Output is in lowercase snake_case (e.g. `neural_networks_notes.docx`).
        - Never uses full raw prompt as filename.
        - Preserves subject, purpose, and artifact type.
        - Free of random numbers, IDs, or timestamps by default.
        """
        context = context or {}
        raw_cmd = (task_description or title or "").strip()

        # Step A: Check for explicit quoted filename in user command
        # e.g. 'save as "monthly_report.docx"' or "named 'app.py'"
        m_explicit = re.search(r'["\']([a-zA-Z0-9_\-\.\s]+?\.[a-zA-Z0-9]{1,6})["\']', raw_cmd)
        if m_explicit:
            cand = m_explicit.group(1).strip()
            return self.sanitize_filename(cand)

        # Step B: Determine Extension
        ext = ""
        if not is_project_dir:
            ext = self._resolve_target_extension(raw_cmd, artifact_type, extension)

        # Step C: Detect Follow-Up / Refinement of Active Artifact
        # If user says "add speech output to that program", preserve the existing project/program name
        is_refinement = any(re.search(p, raw_cmd.lower()) for p in [
            r'\b(?:add|append|update|modify|edit|refine|change)\b.*?\b(?:to|in|on)\s+(?:that|the|this)\s+(?:program|code|file|script|report|document|project)\b',
            r'\b(?:make\s+it|turn\s+it|convert\s+it)\b',
            r'\b(?:add\s+references\s+to\s+both)\b',
            r'\b(?:that\s+program|that\s+script|that\s+document|that\s+file)\b'
        ])
        if is_refinement:
            candidate_ref = None
            for k in ("last_artifact_name", "active_project", "last_file", "last_artifact", "active_document", "active_artifact", "topic"):
                val = context.get(k)
                if isinstance(val, dict):
                    candidate_ref = val.get("filepath") or val.get("path") or val.get("filename") or val.get("name")
                elif isinstance(val, str) and val.strip():
                    candidate_ref = val.strip()
                if candidate_ref:
                    break

            if candidate_ref:
                base = Path(candidate_ref).stem
                if base and base not in ("artifact", "code", "document"):
                    clean_ref_base = self.sanitize_filename(base)
                    return f"{clean_ref_base}{ext or Path(candidate_ref).suffix}"

        # Step D: Extract Core Semantic Components from Query
        clean = raw_cmd
        for pat in _PREFIX_PHRASES:
            clean = re.sub(pat, '', clean, flags=re.IGNORECASE).strip()

        # Extract explicit artifact noun / descriptor mentioned in query
        detected_descriptor = self._extract_artifact_descriptor(clean, artifact_type)

        # Extract topic subject
        subject = self._extract_subject_from_query(clean, detected_descriptor)

        # Fallback to title if subject extraction is sparse or generic
        if (not subject or len(subject) < 3 or subject.lower() in ("test_actual_output", "actual_output", "output")) and title:
            subject = self._clean_title_to_subject(title)

        # Fallback to content inspection if query/title were ambiguous or generic
        generic_subjects = ("output", "result", "document", "file", "assistant", "code", "some", "item", "artifact", "program", "script", "generate")
        if not subject or len(subject) < 2 or subject.lower() in generic_subjects:
            content_sub = self._extract_subject_from_content(content_preview, ext)
            if content_sub:
                subject = content_sub

        if not subject or subject.lower() in generic_subjects:
            subject = "generated_artifact" if is_project_dir else "artifact"

        # Step E: Combine Subject and Artifact Descriptor Cleanly
        # Avoid redundant duplicate words (e.g. "sales_data" + "data" -> "sales_data")
        final_base = self._assemble_base_name(subject, detected_descriptor, is_project_dir, ext)

        sanitized_base = self.sanitize_filename(final_base, max_length=55)

        if is_project_dir:
            return sanitized_base
        return f"{sanitized_base}{ext}"

    def _resolve_target_extension(
        self,
        query: str,
        artifact_type: Optional[str] = None,
        explicit_ext: Optional[str] = None
    ) -> str:
        """Resolve the canonical file extension from explicit input, query keywords, or artifact type."""
        if explicit_ext:
            return self.normalize_extension(explicit_ext)

        q_low = query.lower()

        # Check explicit extension in query (.py, .docx, .pdf, etc.)
        m_ext = re.search(r'\b\.([a-zA-Z0-9]{1,5})\b', q_low)
        if m_ext:
            return self.normalize_extension(m_ext.group(1))

        # Check keyword matches
        if any(k in q_low for k in ["python", " py "]) or q_low.endswith(" in python") or q_low.endswith(" with python"):
            return ".py"
        if any(k in q_low for k in ["javascript", " js "]):
            return ".js"
        if any(k in q_low for k in ["typescript", " ts "]):
            return ".ts"
        if any(k in q_low for k in ["html", "website", "web page", "webpage"]):
            return ".html"
        if any(k in q_low for k in ["css", "stylesheet"]):
            return ".css"
        if any(k in q_low for k in ["java "]) or q_low.endswith(" in java"):
            return ".java"
        if any(k in q_low for k in ["c++", "cpp"]):
            return ".cpp"
        if any(k in q_low for k in ["excel", "xlsx", "spreadsheet", "expense sheet"]):
            return ".xlsx"
        if any(k in q_low for k in ["csv"]):
            return ".csv"
        if any(k in q_low for k in ["powerpoint", "presentation", "pptx", "slide deck", "slides"]):
            return ".pptx"
        if any(k in q_low for k in ["word", "docx", "doc"]):
            return ".docx"
        if any(k in q_low for k in ["pdf"]):
            return ".pdf"
        if any(k in q_low for k in ["markdown", " md "]):
            return ".md"
        if any(k in q_low for k in ["json"]):
            return ".json"
        if any(k in q_low for k in ["xml"]):
            return ".xml"
        if any(k in q_low for k in ["image", "diagram", "chart", "flowchart", "png"]):
            return ".png"
        if any(k in q_low for k in ["ics", "icalendar"]):
            return ".ics"

        # Check artifact_type fallback
        if artifact_type:
            at = artifact_type.lower()
            if at in _EXTENSION_MAP:
                return _EXTENSION_MAP[at]
            if at in ("document", "notes", "report"):
                return ".docx"
            if at in ("code", "script", "program"):
                return ".py"
            if at == "presentation":
                return ".pptx"
            if at in ("spreadsheet", "sheet"):
                return ".xlsx"
            if at in ("diagram", "chart", "visual"):
                return ".png"

        return ".docx"

    def _extract_artifact_descriptor(self, query: str, artifact_type: Optional[str] = None) -> Optional[str]:
        """Detect artifact qualifier word (notes, report, calendar, proposal, model, website, etc.)."""
        q_low = query.lower()
        for k, v in _ARTIFACT_DESCRIPTORS.items():
            if re.search(r'\b' + re.escape(k) + r'\b', q_low):
                return v

        if artifact_type:
            at_clean = artifact_type.lower().replace('-', '_').strip()
            if at_clean in _ARTIFACT_DESCRIPTORS:
                return _ARTIFACT_DESCRIPTORS[at_clean]
            if at_clean in ("notes", "report", "summary", "proposal", "specification", "calendar", "presentation", "spreadsheet"):
                return at_clean
            if at_clean in ("ppt", "pptx", "powerpoint"):
                return "presentation"

        return None

    def _extract_subject_from_query(self, query: str, descriptor: Optional[str] = None) -> str:
        """Extract the core substantive subject from user prompt."""
        clean = query

        # Strip initial command verbs
        clean = re.sub(
            r'^(?:can\s+you\s+|please\s+)?(?:test\s+(?:the\s+)?actual\s+output\s+to\s+)?(?:create|created|generate|generated|make|made|write|wrote|build|built|provide|prepared?|draft|produce|give|export|save)\s+(?:an?|the)?\s*',
            '', clean, flags=re.IGNORECASE
        ).strip()

        # Handle specific query patterns:
        # 1. "notes on <subject>" / "report on <subject>" / "calendar of <subject>" / "website for <subject>"
        m_prep = re.search(
            r'^(?:notes|report|summary|brief|proposal|specification|spec|documentation|overview|calendar|schedule|presentation|slides|spreadsheet|sheet|script|program|code|website|app)\s+(?:on|about|of|for)\s+(.+?)(?:\s+(?:in|using|with|as)\s+.*)?$',
            clean, re.IGNORECASE
        )
        if m_prep:
            raw_sub = m_prep.group(1).strip()
            return self._normalize_words_to_subject(raw_sub)

        # 2. "portfolio website" / "website for a portfolio"
        m_web = re.search(r'\bwebsite\s+(?:for\s+(?:a\s+)?)?(.+?)$', clean, re.IGNORECASE)
        if m_web:
            raw_sub = m_web.group(1).strip()
            sub_words = self._normalize_words_to_subject(raw_sub)
            if "portfolio" in sub_words:
                return "personal_portfolio" if "personal" in clean.lower() else "portfolio"
            return sub_words

        # 3. Strip trailing language clauses like "in python", "using javascript", "with worked problems", "as a pdf"
        clean = re.sub(r'\s+(?:in|using|with|written\s+in)\s+(?:python|javascript|typescript|java|c\+\+|cpp|c|html|css|sql|react|vue|node).*$', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'\s+(?:as|in|into)\s+(?:a\s+|an\s+)?(?:pdf|word|docx|doc|excel|xlsx|spreadsheet|csv|markdown|md|powerpoint|pptx|html).*$', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'\s+with\s+(?:mathematical|worked|equations?|diagrams?|tables?|architecture).*$', '', clean, flags=re.IGNORECASE)

        # 4. Strip language/format adjectives from beginning or end
        clean = re.sub(r'\b(?:python|javascript|typescript|java|c\+\+|cpp|html|css|sql)\s+(?:program|script|code|file|model)\b', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'\b(?:word\s+doc(?:ument)?|docx|pdf(?:\s+document|\s+report)?|excel(?:\s+expense\s+sheet|\s+sheet|\s+spreadsheet|\s+file)?|spreadsheet|xlsx|powerpoint(?:\s+presentation)?|presentation|pptx|ppt|slides|document|report|proposal|study\s+notes|notes|executive\s+summary|summary)\b', '', clean, flags=re.IGNORECASE).strip()

        # Strip remaining prepositions and content clauses
        clean = re.sub(r'^(?:with\s+)?(?:all\s+)?(?:the\s*)?(?:content|thecontent|info|information)?\s*(?:about|on|for|of|titled|named)\s+', '', clean, flags=re.IGNORECASE).strip()
        clean = re.sub(r'^(?:about|on|for|of|titled|named)\s+', '', clean, flags=re.IGNORECASE).strip()

        return self._normalize_words_to_subject(clean)

    def _normalize_words_to_subject(self, raw: str) -> str:
        """Filter noise and filler words, producing a clean snake_case subject."""
        words = re.findall(r'[a-zA-Z0-9]+', raw.lower())
        filtered = [w for w in words if w not in _FILLER_ADJECTIVES and w not in _COMMAND_VERBS and len(w) > 1]
        # Keep maximum 5-6 substantive subject words
        return "_".join(filtered[:5])

    def _clean_title_to_subject(self, title: str) -> str:
        """Extract clean subject from an existing title string."""
        # Remove colon suffixes like ": Comprehensive Guide" or " - Technical Report"
        clean = re.split(r'[:\-–—]', title)[0].strip()
        return self._normalize_words_to_subject(clean)

    def _extract_subject_from_content(self, content: Optional[str], ext: str) -> str:
        """Inspect generated content as a consistency check when query is generic."""
        if not content:
            return ""
        c_text = content[:2000]

        # For Python/code: Look for class or function definitions
        if ext in (".py", ".js", ".ts", ".java", ".cpp"):
            m_class = re.search(r'class\s+([A-Za-z0-9]+)', c_text)
            if m_class and m_class.group(1).lower() not in ("test", "main", "base", "app"):
                # Convert CamelCase to snake_case
                c_name = m_class.group(1)
                s = re.sub(r'(?<!^)(?=[A-Z])', '_', c_name).lower()
                return s

            m_def = re.search(r'def\s+([a-zA-Z0-9_]+)', c_text)
            if m_def and m_def.group(1) not in ("main", "__init__", "run", "test"):
                return m_def.group(1).lower()

        # For Markdown/Text: Look for top heading # ...
        m_head = re.search(r'^#\s+([^\n]+)', c_text, re.MULTILINE)
        if m_head:
            h_text = m_head.group(1)
            h_clean = re.split(r'[:\-–—]', h_text)[0].strip()
            return self._normalize_words_to_subject(h_clean)

        return ""

    def _assemble_base_name(
        self,
        subject: str,
        descriptor: Optional[str],
        is_project_dir: bool,
        ext: str
    ) -> str:
        """
        Assemble the final base name ensuring descriptive quality without repetition.
        e.g.:
        - subject="neural_networks", descriptor="notes" -> "neural_networks_notes"
        - subject="quantum_computing", descriptor="report" -> "quantum_computing_report"
        - subject="monthly_sales_data", descriptor="data" -> "monthly_sales_data"
        - subject="study_sessions", descriptor="calendar" -> "study_schedule_calendar" (or "study_sessions_calendar")
        - subject="multilingual_text_to_speech", descriptor="program" -> "multilingual_text_to_speech"
        """
        if not descriptor:
            return subject

        desc_norm = descriptor.lower().strip()
        sub_norm = subject.lower().strip()

        # Check if subject already contains the descriptor or close variant
        if desc_norm in sub_norm:
            return sub_norm

        # Check for study sessions / calendar nuance
        if desc_norm == "calendar" and "study" in sub_norm:
            if "schedule" not in sub_norm and "session" in sub_norm:
                return "study_schedule_calendar"
            return f"{sub_norm}_calendar"

        # Code files: if descriptor is generic (script, program, code), subject alone is cleaner
        if ext in (".py", ".js", ".ts", ".java", ".cpp", ".cs") and desc_norm in ("script", "program", "code", "app"):
            return sub_norm

        # Website descriptor: if subject is portfolio -> personal_portfolio_website
        if desc_norm == "website" and "portfolio" in sub_norm:
            return f"{sub_norm}_website"

        # Otherwise append descriptor
        return f"{sub_norm}_{desc_norm}"

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Unique Conflict-Free Path Resolution
    # ─────────────────────────────────────────────────────────────────────────

    def get_unique_path(
        self,
        directory: str,
        base_name: Optional[str] = None,
        extension: Optional[str] = None,
        allow_overwrite: bool = False,
        touch: bool = False
    ) -> str:
        """
        Determine a conflict-free absolute filepath without race conditions.
        Supports both:
        - get_unique_path("/path/to/file.docx")
        - get_unique_path("/path/to/dir", "file", ".docx")
        - If allow_overwrite is True and file exists, returns exact path.
        - If file does not exist, returns exact path.
        - If file already exists, appends _2, _3, etc. (e.g. neural_networks_notes_2.docx).
        """
        if base_name is None:
            parent_dir, fname = os.path.split(directory)
            stem, ext_part = os.path.splitext(fname)
            clean_base = self.sanitize_filename(stem)
            ext = self.normalize_extension(extension or ext_part)
            target_directory = parent_dir or self.get_desktop_dir()
        else:
            target_directory = directory
            clean_base = self.sanitize_filename(base_name)
            ext = self.normalize_extension(extension) if extension else ""

        os.makedirs(target_directory, exist_ok=True)
        primary_path = os.path.join(target_directory, f"{clean_base}{ext}")

        if allow_overwrite:
            return primary_path

        with self._lock:
            if not os.path.exists(primary_path):
                if touch:
                    Path(primary_path).touch()
                return primary_path

            # Check if clean_base already ends with an integer suffix e.g. name_2
            m_suf = re.match(r'^(.*?)_(\d+)$', clean_base)
            if m_suf:
                stem_root = m_suf.group(1)
                counter = int(m_suf.group(2)) + 1
            else:
                stem_root = clean_base
                counter = 2

            while True:
                candidate = os.path.join(target_directory, f"{stem_root}_{counter}{ext}")
                if not os.path.exists(candidate):
                    if touch:
                        Path(candidate).touch()
                    return candidate
                counter += 1

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Canonical High-Level Output Path Resolution
    # ─────────────────────────────────────────────────────────────────────────

    def resolve_output_path(
        self,
        task_description: str = "",
        title: Optional[str] = None,
        artifact_type: Optional[str] = None,
        extension: Optional[str] = None,
        output_dir: Optional[str] = None,
        output_directory: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        content_preview: Optional[str] = None,
        content_sample: Optional[str] = None,
        content: Optional[str] = None,
        allow_overwrite: bool = False,
        touch: bool = False,
        user_id: Optional[int] = None,
        task_id: Optional[str] = None,
        **kwargs: Any
    ) -> Tuple[str, str]:
        """
        Canonical one-stop entry point used across all file-producing features.

        Returns:
            Tuple[str, str]: (absolute_resolved_filepath, semantic_filename)
        """
        eff_desc = task_description or kwargs.get("command") or kwargs.get("prompt") or ""
        eff_content = content_preview or content_sample or content
        eff_dir = output_dir or output_directory or kwargs.get("parent_dir")
        eff_ext = extension or kwargs.get("ext")
        eff_touch = touch or kwargs.get("touch", False)

        ext = self._resolve_target_extension(eff_desc or title or "", artifact_type, eff_ext)

        # 1. Resolve semantic filename base
        semantic_filename = self.derive_semantic_filename(
            task_description=eff_desc,
            title=title,
            artifact_type=artifact_type,
            extension=ext,
            context=context,
            content_preview=eff_content,
            is_project_dir=False
        )

        stem = os.path.splitext(semantic_filename)[0]

        # 2. Determine target directory
        if eff_dir:
            target_dir = os.path.abspath(eff_dir)
        elif ext in (".py", ".js", ".ts", ".html", ".css", ".java", ".cpp", ".sql"):
            target_dir = self.get_downloads_dir()
        else:
            target_dir = self.get_default_output_dir(artifact_type=artifact_type)

        # 3. Path safety check
        if not self.is_safe_path(target_dir):
            logger.warning(f"[Security] Output dir '{target_dir}' rejected. Falling back to default output dir.")
            target_dir = self.get_default_output_dir()

        # 4. Resolve conflict-free unique path
        final_path = self.get_unique_path(
            directory=target_dir,
            base_name=stem,
            extension=ext,
            allow_overwrite=allow_overwrite,
            touch=eff_touch
        )

        final_filename = os.path.basename(final_path)

        # 5. Record metadata in task manager if active
        if task_id:
            try:
                from core.document_task_state import get_document_task_manager
                doc_task_mgr = get_document_task_manager()
                task = doc_task_mgr.get_task(task_id)
                if task:
                    task.deliverables.append({
                        "file_path": final_path,
                        "filename": final_filename,
                        "type": ext.lstrip('.'),
                        "title": title or stem.replace('_', ' ').title()
                    })
            except Exception as e:
                logger.debug(f"[SemanticFileNaming] Task tracking note: {e}")

        logger.info(f"[SemanticFileNaming] Resolved output path: '{final_path}' for request: '{task_description}'")
        return final_path, final_filename

    def derive_project_directory(
        self,
        command: str = "",
        base_name: Optional[str] = None,
        parent_dir: Optional[str] = None
    ) -> str:
        """
        Derives a clean, semantic project directory for multi-file projects without random timestamps.
        If the directory already exists, increments cleanly with _2, _3.
        """
        if not parent_dir:
            from modules.code_generator.constants import GENERATED_CODE_DIR
            parent_dir = GENERATED_CODE_DIR

        os.makedirs(parent_dir, exist_ok=True)

        folder_name = self.derive_semantic_filename(
            task_description=command,
            title=base_name,
            artifact_type="project",
            is_project_dir=True
        )

        target_path = os.path.join(parent_dir, folder_name)
        if not os.path.exists(target_path):
            os.makedirs(target_path, exist_ok=True)
            return target_path

        # If already exists, increment counter
        counter = 2
        while True:
            candidate = os.path.join(parent_dir, f"{folder_name}_{counter}")
            if not os.path.exists(candidate):
                os.makedirs(candidate, exist_ok=True)
                return candidate
            counter += 1


# Global thread-safe singleton
_naming_service_instance: Optional[SemanticFileNamingService] = None
_instance_lock = threading.Lock()


def get_semantic_file_naming_service() -> SemanticFileNamingService:
    """Return the global SemanticFileNamingService instance."""
    global _naming_service_instance
    if _naming_service_instance is None:
        with _instance_lock:
            if _naming_service_instance is None:
                _naming_service_instance = SemanticFileNamingService()
    return _naming_service_instance


# Convenience facade functions
def derive_semantic_filename(*args, **kwargs) -> str:
    return get_semantic_file_naming_service().derive_semantic_filename(*args, **kwargs)


def resolve_output_path(*args, **kwargs) -> Tuple[str, str]:
    return get_semantic_file_naming_service().resolve_output_path(*args, **kwargs)


def sanitize_filename(filename: str, max_length: int = 70) -> str:
    return get_semantic_file_naming_service().sanitize_filename(filename, max_length=max_length)


def get_unique_path(directory: str, base_name: str, extension: str, allow_overwrite: bool = False) -> str:
    return get_semantic_file_naming_service().get_unique_path(directory, base_name, extension, allow_overwrite)
