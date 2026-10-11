"""
Document Reference Resolver for Smart Assistant.
Implements the 5-tier strict priority order for resolving document references:
  Priority 1: Explicit filenames/names in request (with disambiguation and progressive search)
  Priority 2: Currently selected/highlighted files in File Explorer (structured OS state)
  Priority 3: Active open document / application context
  Priority 4: Conversation and dialogue document context (ordinal & contextual references)
  Priority 5: Current folder / context ("here", "all PDFs here")

Strictly adheres to:
- No guessing rule (asks user when ambiguous or missing)
- Partial resolution reporting
- Document reference evidence tracking (source, evidence, confidence)
- General Document abstraction (PDF, DOCX, PPTX, TXT, MD, XLSX, CSV)
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("DocumentReferenceResolver")

SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",
    ".pptx": "pptx",
    ".ppt": "pptx",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".txt": "text",
    ".md": "markdown",
    ".csv": "csv",
}


class ResolutionSource(str, Enum):
    EXPLICIT_FILENAME = "EXPLICIT_FILENAME"
    FILE_EXPLORER_SELECTION = "FILE_EXPLORER_SELECTION"
    ACTIVE_DOCUMENT = "ACTIVE_DOCUMENT"
    CONVERSATION_CONTEXT = "CONVERSATION_CONTEXT"
    RECENT_DOCUMENT = "RECENT_DOCUMENT"
    CURRENT_FOLDER = "CURRENT_FOLDER"


class ConfidenceLevel(str, Enum):
    EXPLICIT = "explicit"
    HIGH = "high"
    MEDIUM = "medium"
    AMBIGUOUS = "ambiguous"


@dataclass
class DocumentReference:
    """Evidence-backed resolved document reference."""
    document_path: str
    filename: str
    file_type: str = "pdf"
    resolution_source: ResolutionSource = ResolutionSource.EXPLICIT_FILENAME
    evidence: Dict[str, Any] = field(default_factory=dict)
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH

    @property
    def document_name(self) -> str:
        return self.filename

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_path": self.document_path,
            "filename": self.filename,
            "document_name": self.filename,
            "file_type": self.file_type,
            "resolution_source": self.resolution_source.value,
            "evidence": dict(self.evidence),
            "confidence": self.confidence.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DocumentReference:
        src_val = data.get("resolution_source", ResolutionSource.EXPLICIT_FILENAME)
        src = ResolutionSource(src_val) if isinstance(src_val, str) else src_val
        conf_val = data.get("confidence", ConfidenceLevel.HIGH)
        conf = ConfidenceLevel(conf_val) if isinstance(conf_val, str) else conf_val

        return cls(
            document_path=str(data.get("document_path", "")),
            filename=str(data.get("filename") or data.get("document_name", "")),
            file_type=str(data.get("file_type", "pdf")),
            resolution_source=src,
            evidence=dict(data.get("evidence", {})),
            confidence=conf,
        )


@dataclass
class DocumentResolutionResult:
    """Result of document reference resolution."""
    status: str  # "success", "ambiguous", "missing", "none_found"
    resolved_documents: List[DocumentReference] = field(default_factory=list)
    missing_files: List[str] = field(default_factory=list)
    clarification_prompt: Optional[str] = None
    resolution_source: Optional[ResolutionSource] = None
    ambiguity_candidates: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status.lower() == "success" and len(self.resolved_documents) > 0

    @property
    def candidates(self) -> List[str]:
        if self.ambiguity_candidates:
            return next(iter(self.ambiguity_candidates.values()))
        return []


class DocumentReferenceResolver:
    """
    Main resolver adhering to the 5-tier priority resolution protocol.
    """

    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = workspace_root or os.getcwd()
        self._doc_search_cache: Dict[str, List[str]] = {}

    def resolve(
        self,
        user_input: str,
        environment_snapshot: Optional[Any] = None,
        dialogue_state: Optional[Any] = None,
        user_id: int = 1,
        search_roots: Optional[List[str]] = None,
    ) -> DocumentResolutionResult:
        """
        Execute 5-tier resolution priority.
        """
        clean_input = user_input.strip()
        low_input = clean_input.lower()

        # --------------------------------------------------------------------
        # Priority 1: Explicit filenames / names in the user's request
        # --------------------------------------------------------------------
        explicit_names = self._extract_explicit_document_names(clean_input)
        if explicit_names:
            return self._resolve_priority_1_explicit(explicit_names, environment_snapshot, search_roots=search_roots)

        # --------------------------------------------------------------------
        # Priority 2: Currently selected/highlighted files in File Explorer
        # --------------------------------------------------------------------
        if self._refers_to_selection(low_input):
            p2_res = self._resolve_priority_2_selected(environment_snapshot)
            if p2_res.is_success:
                return p2_res

        # --------------------------------------------------------------------
        # Priority 3: Current document / application context
        # --------------------------------------------------------------------
        if self._refers_to_active_document(low_input):
            p3_res = self._resolve_priority_3_active(environment_snapshot, search_roots=search_roots)
            if p3_res.is_success:
                return p3_res

        # --------------------------------------------------------------------
        # Priority 4: Conversation / document context
        # --------------------------------------------------------------------
        p4_res = self._resolve_priority_4_context(low_input, dialogue_state, search_roots=search_roots)
        if p4_res.is_success:
            return p4_res

        # --------------------------------------------------------------------
        # Priority 5: Current folder / context ("here", "all PDFs here")
        # --------------------------------------------------------------------
        if self._refers_to_current_folder(low_input):
            return self._resolve_priority_5_current_folder(environment_snapshot)

        # --------------------------------------------------------------------
        # Fallback Check: Did the user say "these PDFs" / "these documents"
        # but nothing was selected or open?
        # Enforce Section 8: NO DOCUMENT GUESSING!
        # --------------------------------------------------------------------
        if any(phrase in low_input for phrase in ("these pdf", "these document", "those pdf", "summarize these", "compare these", "read these", "these")):
            return DocumentResolutionResult(
                status="NO_DOCUMENTS",
                clarification_prompt="Please select the PDFs you want me to summarize in File Explorer.",
            )

        if any(phrase in low_input for phrase in ("this pdf", "this document", "summarize this", "read this", "read aloud")):
            return DocumentResolutionResult(
                status="none_found",
                clarification_prompt="I couldn't identify which document you are referring to. Please open it, select it in File Explorer, or state its name.",
            )

        return DocumentResolutionResult(
            status="none_found",
            clarification_prompt="Please specify the documents or select them in File Explorer.",
        )

    # ========================================================================
    # Priority Handlers
    # ========================================================================

    def _resolve_priority_1_explicit(
        self,
        names: List[str],
        env_snapshot: Optional[Any] = None,
        search_roots: Optional[List[str]] = None,
    ) -> DocumentResolutionResult:
        resolved: List[DocumentReference] = []
        missing: List[str] = []
        ambiguous: Dict[str, List[str]] = {}

        current_folder = getattr(env_snapshot, "current_folder", None) if env_snapshot else None

        for name in names:
            matches = self._find_document_progressive(name, current_folder, search_roots=search_roots)
            if len(matches) == 1:
                p = matches[0]
                ext = Path(p).suffix.lower()
                ftype = SUPPORTED_EXTENSIONS.get(ext, "pdf")
                resolved.append(DocumentReference(
                    document_path=p,
                    filename=os.path.basename(p),
                    file_type=ftype,
                    resolution_source=ResolutionSource.EXPLICIT_FILENAME,
                    evidence={"explicit_request": name, "matched_path": p},
                    confidence=ConfidenceLevel.EXPLICIT,
                ))
            elif len(matches) > 1:
                ambiguous[name] = matches
            else:
                missing.append(name)

        # Handle Ambiguity (Section 2 & 11)
        if ambiguous:
            name, cands = next(iter(ambiguous.items()))
            options = "\n".join([f"{i+1}: {p}" for i, p in enumerate(cands[:4])])
            count_str = "two" if len(cands) == 2 else str(len(cands))
            prompt = f"I found {count_str} files named {name}. Which one do you want?\n{options}"
            return DocumentResolutionResult(
                status="AMBIGUOUS",
                resolved_documents=resolved,
                clarification_prompt=prompt,
                resolution_source=ResolutionSource.EXPLICIT_FILENAME,
                ambiguity_candidates=ambiguous,
            )

        # Handle Partial Resolution (Section 9)
        if missing and resolved:
            found_str = " and ".join([r.filename for r in resolved]) if len(resolved) == 2 else ", ".join([r.filename for r in resolved])
            miss_str = ", ".join(missing)
            prompt = (
                f"I found {found_str}, but I couldn't find {miss_str}. "
                f"Do you want me to continue with the two I found?" if len(resolved) == 2 else
                f"I found {found_str}, but I couldn't find {miss_str}. Do you want me to continue with the {len(resolved)} I found?"
            )
            return DocumentResolutionResult(
                status="PARTIAL",
                resolved_documents=resolved,
                missing_files=missing,
                clarification_prompt=prompt,
                resolution_source=ResolutionSource.EXPLICIT_FILENAME,
            )

        if missing and not resolved:
            miss_str = ", ".join(missing)
            return DocumentResolutionResult(
                status="none_found",
                missing_files=missing,
                clarification_prompt=f"I couldn't find {miss_str} in your accessible document locations.",
                resolution_source=ResolutionSource.EXPLICIT_FILENAME,
            )

        return DocumentResolutionResult(
            status="success",
            resolved_documents=resolved,
            resolution_source=ResolutionSource.EXPLICIT_FILENAME,
        )

    def _resolve_priority_2_selected(
        self,
        env_snapshot: Optional[Any],
    ) -> DocumentResolutionResult:
        if not env_snapshot:
            return DocumentResolutionResult(status="none_found")

        selected_paths = getattr(env_snapshot, "selected_files", []) or []
        supported_selected = []
        for p in selected_paths:
            if os.path.exists(p) and not os.path.isdir(p):
                ext = Path(p).suffix.lower()
                if ext in SUPPORTED_EXTENSIONS:
                    supported_selected.append(p)

        if not supported_selected:
            return DocumentResolutionResult(status="none_found")

        resolved = []
        for p in supported_selected:
            ext = Path(p).suffix.lower()
            resolved.append(DocumentReference(
                document_path=p,
                filename=os.path.basename(p),
                file_type=SUPPORTED_EXTENSIONS.get(ext, "pdf"),
                resolution_source=ResolutionSource.FILE_EXPLORER_SELECTION,
                evidence={"selected_in_file_explorer": True, "file_path": p},
                confidence=ConfidenceLevel.EXPLICIT,
            ))

        return DocumentResolutionResult(
            status="success",
            resolved_documents=resolved,
            resolution_source=ResolutionSource.FILE_EXPLORER_SELECTION,
        )

    def _resolve_priority_3_active(
        self,
        env_snapshot: Optional[Any],
        search_roots: Optional[List[str]] = None,
    ) -> DocumentResolutionResult:
        if not env_snapshot:
            return DocumentResolutionResult(status="none_found")

        active_doc = getattr(env_snapshot, "active_document", None)
        if not active_doc:
            return DocumentResolutionResult(status="none_found")

        doc_path = None
        fname = None
        if isinstance(active_doc, str):
            doc_path = active_doc if os.path.exists(active_doc) else None
            fname = os.path.basename(active_doc)
            if not doc_path:
                current_folder = getattr(env_snapshot, "current_folder", None)
                matches = self._find_document_progressive(fname, current_folder, search_roots=search_roots)
                doc_path = matches[0] if matches else None
        elif isinstance(active_doc, dict):
            fname = active_doc.get("filename")
            doc_path = active_doc.get("filepath")
            if not doc_path or not os.path.exists(doc_path):
                current_folder = getattr(env_snapshot, "current_folder", None)
                matches = self._find_document_progressive(fname or "", current_folder, search_roots=search_roots)
                doc_path = matches[0] if matches else None

        if doc_path and os.path.exists(doc_path):
            ext = Path(doc_path).suffix.lower()
            ref = DocumentReference(
                document_path=doc_path,
                filename=os.path.basename(doc_path),
                file_type=SUPPORTED_EXTENSIONS.get(ext, "pdf"),
                resolution_source=ResolutionSource.ACTIVE_DOCUMENT,
                evidence={"active_viewer": str(active_doc)},
                confidence=ConfidenceLevel.HIGH,
            )
            return DocumentResolutionResult(
                status="success",
                resolved_documents=[ref],
                resolution_source=ResolutionSource.ACTIVE_DOCUMENT,
            )

        return DocumentResolutionResult(status="none_found")

    def _resolve_priority_4_context(
        self,
        low_input: str,
        dialogue_state: Optional[Any],
        search_roots: Optional[List[str]] = None,
    ) -> DocumentResolutionResult:
        if not dialogue_state:
            return DocumentResolutionResult(status="none_found")

        # Collect recent documents from dialogue state & context
        recent_docs: List[str] = []

        # 1. Active artifact in dialogue state
        art = getattr(dialogue_state, "active_artifact", None)
        if art and isinstance(art, dict):
            p = art.get("filepath") or art.get("path")
            if p and os.path.exists(p) and p not in recent_docs:
                recent_docs.append(p)

        # 2. Session context recent & resolved documents
        s_ctx = getattr(dialogue_state, "session_context", {}) or {}
        for k in ("resolved_documents", "selected_files", "recent_documents"):
            if k in s_ctx and isinstance(s_ctx[k], list):
                for p in s_ctx[k]:
                    if os.path.exists(p) and p not in recent_docs:
                        recent_docs.append(p)

        # 3. Recent actions command signatures
        rec_actions = getattr(dialogue_state, "recent_actions", []) or []
        for act in reversed(rec_actions):
            cmd = act.get("command", "") or act.get("raw_input", "")
            m = re.findall(r'([a-zA-Z0-9_\-\s\\]+\.(?:pdf|docx|pptx|xlsx|txt|md))', cmd, re.I)
            for fname in m:
                clean_fn = fname.strip()
                matches = self._find_document_progressive(clean_fn, search_roots=search_roots)
                if matches and matches[0] not in recent_docs:
                    recent_docs.append(matches[0])

        if not recent_docs:
            return DocumentResolutionResult(status="none_found")

        # Ordinal resolution
        resolved_paths: List[str] = []
        if "first two" in low_input:
            resolved_paths = recent_docs[:2]
        elif "first one" in low_input or "first document" in low_input or "the first" in low_input:
            resolved_paths = recent_docs[:1]
        elif "second one" in low_input and len(recent_docs) >= 2:
            resolved_paths = [recent_docs[1]]
        elif any(w in low_input for w in ("last one", "previous document", "that pdf", "this pdf", "the pdf", "this document", "summarize this")):
            resolved_paths = [recent_docs[-1]]
        elif any(w in low_input for w in ("these pdfs", "those documents", "these documents", "these", "big picture", "into a pdf", "make a pdf", "summary pdf", "compare", "read it", "read the summary")):
            resolved_paths = recent_docs
        elif len(recent_docs) > 0 and any(w in low_input for w in ("big picture", "summary", "pdf", "compare", "that")):
            resolved_paths = recent_docs

        if not resolved_paths:
            return DocumentResolutionResult(status="none_found")

        refs = []
        for p in resolved_paths:
            ext = Path(p).suffix.lower()
            refs.append(DocumentReference(
                document_path=p,
                filename=os.path.basename(p),
                file_type=SUPPORTED_EXTENSIONS.get(ext, "pdf"),
                resolution_source=ResolutionSource.CONVERSATION_CONTEXT,
                evidence={"conversational_reference": low_input, "matched_context": p},
                confidence=ConfidenceLevel.HIGH,
            ))

        return DocumentResolutionResult(
            status="success",
            resolved_documents=refs,
            resolution_source=ResolutionSource.CONVERSATION_CONTEXT,
        )

    def _resolve_priority_5_current_folder(
        self,
        env_snapshot: Optional[Any],
    ) -> DocumentResolutionResult:
        folder = getattr(env_snapshot, "current_folder", None) if env_snapshot else None
        if not folder or not os.path.exists(folder):
            folder = os.getcwd()

        found = []
        try:
            for entry in os.scandir(folder):
                if entry.is_file():
                    ext = Path(entry.name).suffix.lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        found.append(entry.path)
        except Exception as e:
            logger.warning(f"[DOC_RESOLVER] Could not scan folder '{folder}': {e}")

        if not found:
            return DocumentResolutionResult(
                status="none_found",
                clarification_prompt=f"No supported documents were found in '{os.path.basename(folder)}'.",
                resolution_source=ResolutionSource.CURRENT_FOLDER,
            )

        refs = []
        for p in sorted(found):
            ext = Path(p).suffix.lower()
            refs.append(DocumentReference(
                document_path=p,
                filename=os.path.basename(p),
                file_type=SUPPORTED_EXTENSIONS.get(ext, "pdf"),
                resolution_source=ResolutionSource.CURRENT_FOLDER,
                evidence={"scanned_folder": folder},
                confidence=ConfidenceLevel.HIGH,
            ))

        return DocumentResolutionResult(
            status="success",
            resolved_documents=refs,
            resolution_source=ResolutionSource.CURRENT_FOLDER,
        )

    # ========================================================================
    # Progressive Safe Filesystem Search (Section 7)
    # ========================================================================

    def _find_document_progressive(
        self,
        name: str,
        current_folder: Optional[str] = None,
        search_roots: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Progressive search strategy:
          1. Direct path check if absolute
          2. search_roots if explicitly provided (safe test or drive scope)
          3. Recent / active current_folder
          4. Workspace root
          5. Known user document folders (Documents, Desktop, Downloads)
        """
        clean_name = self._normalize_filename(name)

        # 1. Absolute path check
        if os.path.isabs(name) and os.path.exists(name):
            return [name]

        # Check in-memory cache
        cache_key = f"{clean_name}::{current_folder}::{search_roots}"
        if cache_key in self._doc_search_cache:
            return self._doc_search_cache[cache_key]

        candidates = set()

        # Target extensions to check
        ext = Path(clean_name).suffix.lower()
        search_patterns = [clean_name]
        if not ext:
            search_patterns.extend([f"{clean_name}{e}" for e in (".pdf", ".docx", ".pptx", ".txt")])

        # Priority search roots if provided
        if search_roots:
            for s_root in search_roots:
                if os.path.exists(s_root):
                    self._scan_dir_exact(s_root, search_patterns, candidates)

        # Tier 1: Current Explorer / active folder
        if current_folder and os.path.exists(current_folder):
            self._scan_dir_exact(current_folder, search_patterns, candidates)

        # Tier 2: Workspace root
        if os.path.exists(self.workspace_root):
            self._scan_dir_exact(self.workspace_root, search_patterns, candidates)

        # Tier 3: Standard User Folders
        home = os.path.expanduser("~")
        for folder_name in ("Documents", "Desktop", "Downloads"):
            fpath = os.path.join(home, folder_name)
            if os.path.exists(fpath):
                self._scan_dir_exact(fpath, search_patterns, candidates, max_depth=2)

        results = sorted(list(candidates))
        self._doc_search_cache[cache_key] = results
        return results

    def _scan_dir_exact(
        self,
        root_dir: str,
        search_names: List[str],
        results: Set[str],
        max_depth: int = 2,
    ) -> None:
        """Bounded safe directory search avoiding deep system directories."""
        norm_names = [self._normalize_filename(n).lower() for n in search_names]
        root_depth = root_dir.rstrip(os.sep).count(os.sep)

        try:
            for root, dirs, files in os.walk(root_dir):
                # Skip hidden/system folders
                dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in ("node_modules", "appdata", "windows", "program files")]

                curr_depth = root.rstrip(os.sep).count(os.sep) - root_depth
                if curr_depth > max_depth:
                    dirs.clear()
                    continue

                for f in files:
                    if self._normalize_filename(f).lower() in norm_names:
                        results.add(os.path.join(root, f))
        except (PermissionError, OSError):
            pass

    # ========================================================================
    # Name & Natural Language Extraction Helpers
    # ========================================================================

    def _extract_explicit_document_names(self, text: str) -> List[str]:
        """
        Extract explicit document filenames from request.
        Matches e.g. "Economics Unit 1.pdf and Demand.pdf" or "document.docx".
        """
        found = []
        # Pattern 1: explicit file extensions
        matches = re.findall(r'([a-zA-Z0-9_\-\s]+\.(?:pdf|docx|doc|pptx|ppt|xlsx|xls|txt|md|csv))', text, re.IGNORECASE)
        for m in matches:
            clean = m.strip()
            # Clean common preceding preposition words
            clean = re.sub(r'^(?:and|summarize|read|compare|open|find|from|to)\s+', '', clean, flags=re.I).strip()
            if clean and clean not in found:
                found.append(clean)

        return found

    def _refers_to_selection(self, low_text: str) -> bool:
        return any(p in low_text for p in (
            "summarize these", "summarize these pdfs", "these documents", "those pdfs",
            "compare these", "these pdf", "read these", "make a summary of these",
            "create one pdf from these", "from these", "these"
        ))

    def _refers_to_active_document(self, low_text: str) -> bool:
        return any(p in low_text for p in (
            "summarize this", "summarize this pdf", "this document", "read this",
            "read this pdf", "this pdf", "the active pdf", "open pdf"
        ))

    def _refers_to_current_folder(self, low_text: str) -> bool:
        return any(p in low_text for p in (
            "here", "all the pdfs here", "all pdfs here", "in this folder",
            "documents here", "files here"
        ))

    def _normalize_filename(self, filename: str) -> str:
        """Unicode normalization and whitespace cleanup."""
        return unicodedata.normalize("NFC", filename.strip())


_resolver_instance: Optional[DocumentReferenceResolver] = None


def get_document_reference_resolver() -> DocumentReferenceResolver:
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = DocumentReferenceResolver()
    return _resolver_instance
