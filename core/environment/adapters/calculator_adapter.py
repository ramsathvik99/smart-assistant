"""
Calculator Environment Adapter
Specialized observer for the Windows Calculator application.
Extracts calculation expressions, displayed results, and math context.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

from core.environment.adapters.base_adapter import BaseEnvironmentAdapter
from core.environment.models import EnvironmentState


class CalculatorEnvironmentAdapter(BaseEnvironmentAdapter):
    """
    Adapter for the Windows Calculator application.
    Extracts displayed values and calculator state.
    """

    name = "calculator"
    app_category = "utility"

    def can_handle(self, app_name: str, window_info: Dict[str, Any]) -> bool:
        clean_app = (app_name or "").lower().strip()
        cls_name = (window_info.get("class_name") or "").lower()
        title = (window_info.get("title") or "").lower()

        if clean_app in ("calculator", "calc", "calculatorapp"):
            return True
        if "calc" in cls_name or "applicationframehost" in cls_name and "calculator" in title:
            return True
        if title == "calculator":
            return True
        return False

    def extract_state(self, window_info: Dict[str, Any], hierarchy_level: int = 1) -> Optional[EnvironmentState]:
        title = (window_info.get("title") or "Calculator").strip()
        cls_name = window_info.get("class_name", "")
        pid = window_info.get("pid", 0)
        hwnd = window_info.get("hwnd", 0)

        entities: Dict[str, Any] = {
            "application": "calculator",
            "raw_title": title,
        }

        # Try to query calculation result via UIAutomation if hierarchy allows
        disp_value = None
        source_tier = "os_window"
        if hierarchy_level <= 2 and hwnd:
            try:
                from core.environment.ui_tree import try_get_calculator_value
                disp_value = try_get_calculator_value(hwnd)
                if disp_value:
                    source_tier = "accessibility"
                    entities["result"] = disp_value
            except Exception:
                pass

        if disp_value:
            content_ctx = f"Windows Calculator is active (Display: {disp_value})"
        else:
            content_ctx = "Windows Calculator is active"

        return EnvironmentState(
            timestamp=time.time(),
            application="calculator",
            window_title=title,
            window_hwnd=hwnd,
            window_pid=pid,
            process_name="calculator.exe",
            app_category="utility",
            active_entities=entities,
            content_context=content_ctx,
            visible_text=str(disp_value or title),
            user_action_summary="Using Calculator",
            source_tier=source_tier,
            metadata={"utility": "calculator"},
        )

    def detect_action(
        self,
        before: EnvironmentState,
        after: EnvironmentState,
    ) -> Tuple[str, str, str]:
        if before.application != after.application:
            return (
                "APP_SWITCH",
                "Opened Calculator",
                f"Switched from {before.application} to Calculator",
            )

        b_res = before.get_entity("result")
        a_res = after.get_entity("result")
        if a_res and b_res and a_res != b_res:
            return (
                "CALCULATION_PERFORMED",
                f"Calculated value {a_res}",
                f"Calculator display changed from {b_res} to {a_res}",
            )

        return ("NO_CHANGE", "No change", "Calculator state remained stable")
