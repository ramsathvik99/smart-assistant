"""
Universal OS Operations — Contextual Reference Resolver
Resolves natural pronouns and anaphoric references:
- "this", "that", "it", "there", "here"
- "the file", "the folder", "the project", "the process", "that process"
- "the drive", "the other drive"
- "what I was working on", "the thing you just opened", "what you just did"
Using environment state, dialogue context, action history, and filesystem inspection.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class OSContextResolver:
    """
    Intelligently resolves contextual references to concrete OS entities
    (paths, PIDs, processes, drive letters, URLs, window handles).
    """

    def resolve_target(
        self,
        reference_str: str,
        user_id: Any = 1,
        entity_hint: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Resolves a reference string into a concrete target.
        """
        if not reference_str:
            return None

        clean_ref = reference_str.strip().strip(' "\'')
        ref_low = clean_ref.lower()

        # If it's already an absolute path or drive, return it directly
        if re.match(r'^[a-zA-Z]:\\', clean_ref) or re.match(r'^[a-zA-Z]:/?$', clean_ref):
            return clean_ref

        # 1. Drive references: "D drive", "on D", "D:", "the other drive", "external drive"
        m_drive = re.search(r'\b([a-zA-Z])(?:\s+drive|\s*:\s*|(?:\s+)?drive)?\b', ref_low)
        if ref_low in ("d", "d:", "d drive", "on d", "to d") or (m_drive and m_drive.group(1).upper() in ("D", "E", "F", "G", "C")):
            drive_letter = m_drive.group(1).upper() if m_drive else ("D" if "d" in ref_low else "C")
            return f"{drive_letter}:\\"

        if "other drive" in ref_low or "external drive" in ref_low:
            from core.os_gateway.storage_ops import list_accessible_drives
            drives = list_accessible_drives()
            for d in drives:
                if d.get("drive_letter") != "C:":
                    return d.get("mount_point", f"{d.get('drive_letter')}\\")
            return "D:\\"

        # 2. Process references: "that process", "the process", "it", "what's using port 8000"
        if entity_hint == "PROCESS" or any(w in ref_low for w in ["that process", "the process", "it", "process"]):
            # Check context passed directly
            if context and context.get("target_pid"):
                return str(context["target_pid"])
            if context and context.get("target_process"):
                return str(context["target_process"])

            # Check dialogue state manager
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager
                dm = get_dialogue_manager(str(user_id))
                last_proc = dm.current_state.session_context.get("last_inspected_process")
                if last_proc:
                    if isinstance(last_proc, dict):
                        return str(last_proc.get("pid") or last_proc.get("name"))
                    return str(last_proc)
                last_pid = dm.current_state.session_context.get("last_port_pid")
                if last_pid:
                    return str(last_pid)
            except Exception:
                pass

            # Check action history
            from core.os_gateway.action_history import get_os_action_history
            actions = get_os_action_history().get_recent_actions(user_id=user_id, limit=5)
            for a in actions:
                if a.get("capability") == "PROCESS" or a.get("operation_type") in ("INSPECT_PORT", "FIND_BY_PORT", "LIST_PROCESSES"):
                    data = a.get("result_data", {})
                    if data.get("pid"):
                        return str(data["pid"])
                    if data.get("process_name"):
                        return str(data["process_name"])
                    if a.get("target"):
                        return str(a["target"])

        # 3. File references: "this file", "that file", "the file", "it", "what I was working on"
        if entity_hint in ("FILE", "PATH") or any(w in ref_low for w in ["this file", "that file", "the file", "this", "that", "it"]):
            # Check environment state (active window / IDE document)
            try:
                from core.environment import get_state_engine
                engine = get_state_engine()
                cur_state = engine.get_current_state(str(user_id))
                if cur_state:
                    entities = cur_state.entities or {}
                    # If IDE open, check active_file
                    if entities.get("active_file") and os.path.exists(entities["active_file"]):
                        return entities["active_file"]
                    if entities.get("active_document") and os.path.exists(entities["active_document"]):
                        return entities["active_document"]
                    if cur_state.active_application == "VS Code" or "code" in (cur_state.active_application or "").lower():
                        # Window title often has filename: "filename.ext - Workspace - Visual Studio Code"
                        title = cur_state.window_title or ""
                        m_f = re.match(r'^\s*([^\s\-•]+?\.[a-zA-Z0-9]+)', title)
                        if m_f:
                            cand_name = m_f.group(1).strip()
                            # Search in workspace
                            ws = os.getcwd()
                            cand_p = os.path.join(ws, cand_name)
                            if os.path.exists(cand_p):
                                return cand_p
            except Exception:
                pass

            # Check dialogue state manager artifacts
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager
                dm = get_dialogue_manager(str(user_id))
                if dm.current_state.active_artifact:
                    art_p = dm.current_state.active_artifact.get("filepath") or dm.current_state.active_artifact.get("path")
                    if art_p and os.path.exists(art_p):
                        return art_p
                if dm.current_state.active_file:
                    return dm.current_state.active_file
            except Exception:
                pass

            # Check action history for last created or moved file
            from core.os_gateway.action_history import get_os_action_history
            actions = get_os_action_history().get_recent_actions(user_id=user_id, limit=5)
            for a in actions:
                if a.get("capability") == "FILESYSTEM":
                    p = a.get("result_data", {}).get("path") or a.get("result_data", {}).get("destination") or a.get("target")
                    if p and os.path.exists(p):
                        return p

        # 4. Folder / Project references: "the project", "the folder", "my project folder", "project folder on D"
        if any(w in ref_low for w in ["project", "folder", "directory", "there", "workspace"]):
            # Look for project on D: drive if user says "my D drive project folder" or "project on D"
            if "d" in ref_low:
                d_candidates = ["D:\\Projects", "D:\\Project", "D:\\Workspace", "D:\\Dev", "D:\\code", "D:\\smart_assistant"]
                for cand in d_candidates:
                    if os.path.exists(cand) and os.path.isdir(cand):
                        return cand
                if os.path.exists("D:\\"):
                    return "D:\\"

            # Check current working directory or dialogue state
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager
                dm = get_dialogue_manager(str(user_id))
                if dm.current_state.active_folder:
                    return dm.current_state.active_folder
            except Exception:
                pass

            return os.getcwd()

        # 5. Application references: "what you just opened", "the thing you opened"
        if any(w in ref_low for w in ["what you just opened", "thing you opened", "what i just opened"]):
            from core.os_gateway.action_history import get_os_action_history
            actions = get_os_action_history().get_recent_actions(user_id=user_id, limit=5)
            for a in actions:
                if a.get("operation_type") in ("OPEN_APPLICATION", "START_PROCESS"):
                    if a.get("target"):
                        return a["target"]

        # 6. Action / Operation references (Section 9 Integration)
        action_phrases = [
            "that operation", "the operation", "what you just did", "the thing you just did",
            "the previous action", "last action", "the failed step", "failed action",
            "the file you moved", "moved file", "the file we moved",
            "the file you deleted", "deleted file",
            "the process you killed", "the process you started",
        ]
        if any(p in ref_low for p in action_phrases) or "operation" in ref_low or "action" in ref_low:
            act = self.resolve_action_reference(clean_ref, user_id=user_id)
            if act:
                res = act.get("affected_resource") or act.get("target")
                if not res and act.get("result_data"):
                    res = act["result_data"].get("destination") or act["result_data"].get("path")
                if res:
                    return str(res)
                return str(act.get("operation_type") or act.get("record_id"))

        return clean_ref

    def resolve_action_reference(self, reference_str: str, user_id: Any = 1) -> Optional[Dict[str, Any]]:
        """
        Resolves action/operation references:
        - "that operation"
        - "the thing you just did"
        - "the previous action"
        - "the failed step"
        - "the file you moved"
        Returns the structured ActionRecord dictionary or None.
        """
        try:
            from core.persistent_execution_records import get_persistent_execution_records_manager
            mgr = get_persistent_execution_records_manager()
            rec = mgr.find_action_by_reference(reference_str, user_id=user_id)
            if rec:
                return rec.to_dict()
        except Exception as exc:
            logger.debug("[OSContextResolver] Failed to resolve action reference '%s': %s", reference_str, exc)
        return None

    def resolve_destination(self, dest_str: str, source_path: Optional[str] = None) -> str:
        """
        Resolves a destination phrase into an absolute destination path.
        e.g. "my D drive project folder" -> "D:\\Projects"
             "on D" -> "D:\\"
             "the folder we created" -> last created folder
        """
        clean_d = dest_str.strip().strip(' "\'')
        d_low = clean_d.lower()

        # Direct absolute path
        if re.match(r'^[a-zA-Z]:\\', clean_d):
            return clean_d

        # "D drive project folder" or "project folder on D"
        if "d" in d_low and ("project" in d_low or "folder" in d_low):
            d_cand = ["D:\\Projects", "D:\\Project", "D:\\Workspace", "D:\\smart_assistant"]
            for cand in d_cand:
                if os.path.exists(cand) and os.path.isdir(cand):
                    return cand
            if os.path.exists("D:\\"):
                return "D:\\"

        # Drive root
        m_drv = re.match(r'^([a-zA-Z])(?:\s+drive|\s*:)?$', d_low)
        if m_drv:
            return f"{m_drv.group(1).upper()}:\\"

        if d_low in ("d", "d:", "d drive", "on d", "to d"):
            return "D:\\"

        # Named folder resolution
        from modules.system_controller.file_manager import resolve_directory_name
        return resolve_directory_name(clean_d)


_context_resolver: Optional[OSContextResolver] = None


def get_context_resolver() -> OSContextResolver:
    global _context_resolver
    if _context_resolver is None:
        _context_resolver = OSContextResolver()
    return _context_resolver
