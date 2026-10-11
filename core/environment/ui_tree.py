"""
Accessibility & UI Automation Tree Inspector (Tier 2 Observation)
Uses Windows UIAutomation COM interfaces, Chrome DevTools Protocol (CDP),
and filesystem inspection to extract rich, structured context without blind screen polling.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import urllib.parse
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# UIAutomation GUID: CLSID_CUIAutomation
CLSID_CUIAutomation = "{ff48dba4-60ef-4201-aa87-54103eef594e}"

_uia_instance = None
_uia_failed = False


def _get_uia():
    """Lazily initialize the IUIAutomation COM interface."""
    global _uia_instance, _uia_failed
    if _uia_failed or sys.platform != "win32":
        return None
    if _uia_instance is not None:
        return _uia_instance

    try:
        import comtypes
        import comtypes.client
        comtypes.CoInitialize()
        mod = comtypes.client.GetModule("UIAutomationCore.dll")
        _uia_instance = comtypes.client.CreateObject(mod.CUIAutomation, interface=mod.IUIAutomation)
        return _uia_instance
    except Exception as exc:
        logger.debug("[UI_TREE] UIAutomation COM initialization unavailable: %s", exc)
        _uia_failed = True
        return None


def try_get_browser_cdp_info(title_hint: str = "", port: int = 9222) -> Optional[Dict[str, Any]]:
    """
    Attempt to fetch active browser tab metadata via Chrome DevTools Protocol (CDP).
    Connects to http://127.0.0.1:{port}/json with a tight 0.15s timeout.
    Returns target metadata dict or None if CDP is unavailable.
    """
    try:
        import urllib.request
        url = f"http://127.0.0.1:{port}/json"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "SmartAssistantEnvironmentObserver/1.0"}
        )
        with urllib.request.urlopen(req, timeout=0.15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(data, list):
                return None
            pages = [t for t in data if t.get("type") == "page"]
            if not pages:
                return None

            matched = None
            if title_hint:
                t_low = title_hint.lower()
                for p in pages:
                    p_title = (p.get("title") or "").lower()
                    if p_title in t_low or t_low in p_title:
                        matched = p
                        break
            if not matched:
                matched = pages[0]

            target_url = matched.get("url", "")
            return {
                "url": target_url,
                "title": matched.get("title", ""),
                "target_id": matched.get("id"),
                "ws_url": matched.get("webSocketDebuggerUrl"),
            }
    except Exception:
        return None


def try_get_browser_url(hwnd: int, browser_name: str, title_hint: str = "") -> Optional[str]:
    """
    Attempt to extract the active URL from Chrome, Edge, or Brave address bar
    using CDP, UIAutomation accessibility tree, or Win32 edit control search.
    Returns None if not accessible.
    """
    # 1. Check CDP first (Tier 1 API)
    cdp = try_get_browser_cdp_info(title_hint=title_hint)
    if cdp and cdp.get("url"):
        return cdp["url"]

    if not hwnd or sys.platform != "win32":
        return None

    # 2. Check UIAutomation COM (Tier 2 Accessibility)
    try:
        uia = _get_uia()
        if uia:
            elem = uia.ElementFromHandle(hwnd)
            if elem:
                try:
                    import comtypes.gen.UIAutomationClient as uac
                    cond = uia.CreatePropertyCondition(uac.UIA_ControlTypePropertyId, uac.UIA_EditControlTypeId)
                    edit_elems = elem.FindAll(uac.TreeScope_Descendants, cond)
                    if edit_elems:
                        for i in range(min(5, edit_elems.Length)):
                            val = edit_elems.GetElement(i).CurrentName
                            if val and ("." in val or "http" in val) and " " not in val.strip():
                                cand = val.strip()
                                if not cand.startswith("http://") and not cand.startswith("https://"):
                                    cand = f"https://{cand}"
                                return cand
                except Exception:
                    pass
    except Exception:
        pass

    # 3. Fallback to Win32 child windows
    try:
        import win32gui
        urls: List[str] = []

        def enum_child_cb(child_hwnd, _):
            cls_name = win32gui.GetClassName(child_hwnd)
            if "edit" in cls_name.lower() or "address" in cls_name.lower():
                text = win32gui.GetWindowText(child_hwnd)
                if text and ("http" in text or "." in text) and " " not in text:
                    urls.append(text.strip())

        win32gui.EnumChildWindows(hwnd, enum_child_cb, None)
        if urls:
            cand = urls[0]
            if not cand.startswith("http://") and not cand.startswith("https://"):
                cand = f"https://{cand}"
            return cand
    except Exception:
        pass

    return None


def try_resolve_git_branch(
    workspace_path: Optional[str] = None,
    project_name: Optional[str] = None
) -> Optional[str]:
    """
    Resolve active git branch by reading .git/HEAD directly.
    Deterministic, sub-millisecond, pure filesystem read.
    """
    candidates: List[str] = []
    if workspace_path and os.path.isdir(workspace_path):
        candidates.append(workspace_path)
    if project_name:
        cwd = os.getcwd()
        if os.path.basename(cwd).lower() == project_name.lower():
            candidates.append(cwd)
        # Check workspaceStorage
        ws_info = try_resolve_vscode_workspace(project_name)
        if ws_info and ws_info.get("folder"):
            candidates.append(ws_info["folder"])

    for folder in candidates:
        head_file = os.path.join(folder, ".git", "HEAD")
        if os.path.exists(head_file):
            try:
                with open(head_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()
                    if content.startswith("ref: refs/heads/"):
                        return content.replace("ref: refs/heads/", "").strip()
                    if len(content) >= 7 and all(c in "0123456789abcdef" for c in content[:7].lower()):
                        return content[:7]
            except Exception:
                pass
    return None


def try_resolve_vscode_workspace(project_name: str) -> Optional[Dict[str, Any]]:
    """
    Resolve workspace folder path and metadata from VS Code's workspaceStorage.
    """
    if not project_name:
        return None
    try:
        appdata = os.getenv("APPDATA", "")
        if not appdata:
            return None
        ws_dir = os.path.join(appdata, "Code", "User", "workspaceStorage")
        if not os.path.isdir(ws_dir):
            return None

        target = project_name.lower()
        for entry in os.listdir(ws_dir):
            w_json = os.path.join(ws_dir, entry, "workspace.json")
            if os.path.exists(w_json):
                try:
                    with open(w_json, "r", encoding="utf-8", errors="ignore") as f:
                        data = json.load(f)
                        f_uri = data.get("folder", "")
                        if f_uri.startswith("file:///"):
                            f_path = urllib.parse.unquote(f_uri[8:])
                            if os.path.basename(f_path).lower() == target:
                                return {
                                    "folder": f_path,
                                    "storage_id": entry,
                                    "storage_path": os.path.join(ws_dir, entry),
                                }
                except Exception:
                    continue
    except Exception:
        pass
    return None


def try_get_vscode_status_bar(hwnd: int) -> Optional[Dict[str, Any]]:
    """
    Extract cursor line/col and selection from VS Code status bar via UIAutomation.
    Returns dict or None.
    """
    if not hwnd or sys.platform != "win32":
        return None
    try:
        uia = _get_uia()
        if not uia:
            return None
        elem = uia.ElementFromHandle(hwnd)
        if not elem:
            return None
        import comtypes.gen.UIAutomationClient as uac
        cond = uia.CreatePropertyCondition(uac.UIA_ControlTypePropertyId, uac.UIA_TextControlTypeId)
        text_elems = elem.FindAll(uac.TreeScope_Descendants, cond)
        if text_elems:
            res: Dict[str, Any] = {}
            for i in range(min(15, text_elems.Length)):
                txt = text_elems.GetElement(i).CurrentName
                if not txt:
                    continue
                m_pos = re.search(r'\bLn\s+(\d+),\s*Col\s+(\d+)\b', txt)
                if m_pos:
                    res["cursor_position"] = f"Ln {m_pos.group(1)}, Col {m_pos.group(2)}"
                m_sel = re.search(r'\((\d+)\s+selected\)', txt)
                if m_sel:
                    res["selection"] = f"{m_sel.group(1)} selected"
            if res:
                return res
    except Exception:
        pass
    return None


def try_get_calculator_value(hwnd: int) -> Optional[str]:
    """
    Query calculator display value from child controls if available.
    """
    if not hwnd or sys.platform != "win32":
        return None

    try:
        import win32gui
        values = []

        def enum_cb(child_hwnd, _):
            t = win32gui.GetWindowText(child_hwnd)
            if t and t.replace(",", "").replace(".", "").replace("-", "").isdigit():
                values.append(t.strip())

        win32gui.EnumChildWindows(hwnd, enum_cb, None)
        if values:
            return values[0]
    except Exception:
        pass
    return None
