"""
assistant_os/browser_manager/browser_manager.py
===========================================
NOVA OS - Browser Automation Manager

Architecture:
    This class is the implementation of the Browser Automation Manager.
    It reuses:
        - BrowserEngine (from extensions/browser_engine.py) to launch and navigate.
    And extends it to support:
        - click(x, y) via PyAutoGUI.
        - fill(text) via PyAutoGUI.
        - extract(url) via requests + BeautifulSoup.
        - screenshot(output_path) via PyAutoGUI.

SDD Reference: Section 22 (Browser Automation Manager).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Dict, Any, Optional
import requests
from bs4 import BeautifulSoup

# Re-use existing BrowserEngine
from extensions.browser_engine import BrowserEngine

logger = logging.getLogger("assistant_os.browser_manager")


class BrowserAutomationManager:
    """
    Manages browser automation by combining OS-level browser launching,
    DOM extraction (scraping), and GUI automation (mouse/keyboard events).
    """

    def __init__(self):
        self.browser_engine = BrowserEngine()
        logger.info("[BrowserAutomationManager] Initialized successfully.")

    def navigate(self, name: str, url: str) -> str:
        """
        Navigate to a specific URL using the preferred web browser.
        
        Args:
            name: Label for the active browser context.
            url: The destination web address.
        """
        logger.info(f"[BrowserAutomationManager] Navigating to {url} ({name})")
        return self.browser_engine.open_page(name, url)

    def click(self, x: int, y: int) -> str:
        """
        Perform a native mouse click at specified screen coordinates (x, y).
        
        Args:
            x: Horizontal pixel coordinate.
            y: Vertical pixel coordinate.
        """
        logger.info(f"[BrowserAutomationManager] Clicking coordinates: ({x}, {y})")
        try:
            import pyautogui
            # Safety checks to prevent infinite loops / offscreen errors
            pyautogui.FAILSAFE = True
            pyautogui.click(x, y)
            return f"Clicked at ({x}, {y}) successfully."
        except Exception as e:
            logger.error(f"Click failed: {e}")
            return f"Failed to click at ({x}, {y}): {e}"

    def fill(self, text: str) -> str:
        """
        Type text into the currently active text field.
        
        Args:
            text: String to type.
        """
        logger.info(f"[BrowserAutomationManager] Typing text length: {len(text)}")
        try:
            import pyautogui
            pyautogui.write(text, interval=0.01)
            return "Text filled successfully."
        except Exception as e:
            logger.error(f"Type failed: {e}")
            return f"Failed to fill text: {e}"

    def extract(self, url: str) -> Dict[str, Any]:
        """
        Extract clean text and structure from a web page.
        
        Args:
            url: Page to extract content from.
        """
        logger.info(f"[BrowserAutomationManager] Extracting page content: {url}")
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                # Remove non-content tags
                for tag in soup(["script", "style", "nav", "footer"]):
                    tag.decompose()
                
                title = soup.title.string.strip() if soup.title else ""
                text = soup.get_text()
                
                # Cleanup spacing
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                clean_text = "\n".join(chunk for chunk in chunks if chunk)
                
                return {
                    "status": "success",
                    "title": title,
                    "text": clean_text[:5000],  # Return up to 5000 chars context
                }
            return {"status": "error", "error": f"HTTP status {resp.status_code}"}
        except Exception as e:
            logger.error(f"Page extraction failed: {e}")
            return {"status": "error", "error": str(e)}

    def screenshot(self, output_path: str) -> str:
        """
        Capture a full screenshot of the current active screen.
        
        Args:
            output_path: File path to save the screenshot (PNG).
        """
        logger.info(f"[BrowserAutomationManager] Capturing screenshot: {output_path}")
        try:
            import pyautogui
            # Ensure target folder exists
            dir_name = os.path.dirname(output_path)
            if dir_name and not os.path.exists(dir_name):
                os.makedirs(dir_name)
                
            screenshot = pyautogui.screenshot()
            screenshot.save(output_path)
            return f"Screenshot saved to {output_path}."
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return f"Failed to capture screenshot: {e}"

    def close(self) -> str:
        """Close active browser session context."""
        logger.info("[BrowserAutomationManager] Closing active browser context.")
        return self.browser_engine.close_browser()
