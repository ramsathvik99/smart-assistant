"""
Browser Controller for Nova Smart Assistant.
Provides safe controlled browser navigation, text extraction, screenshots,
and web search with automatic fallback to standard HTTP/webbrowser.
"""

import os
import re
import logging
import webbrowser
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class _HTMLTextExtractor(HTMLParser):
    """Simple parser to strip HTML tags and extract readable page text."""
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self._ignore = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'header', 'footer', 'nav'):
            self._ignore = True

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'header', 'footer', 'nav'):
            self._ignore = False

    def handle_data(self, data):
        if not self._ignore:
            cleaned = data.strip()
            if cleaned:
                self.text_parts.append(cleaned)

    def get_text(self):
        return " ".join(self.text_parts)


def open_url(url: str) -> Dict[str, Any]:
    """
    Open URL in default system browser.
    """
    try:
        target = url.strip()
        if not target.startswith("http://") and not target.startswith("https://"):
            target = f"https://{target}"

        webbrowser.open(target)
        return {
            "success": True,
            "status": "success",
            "url": target,
            "message": f"Opened '{target}' in your default browser."
        }
    except Exception as e:
        logger.error(f"[BROWSER] Failed to open URL: {e}")
        return {"success": False, "status": "error", "message": f"Failed to open browser: {e}"}


def extract_page_text(url: str, max_chars: int = 8000, max_length: Optional[int] = None) -> Dict[str, Any]:
    """
    Extract clean article/page text from a web page.
    Attempts Playwright headless extraction first, falling back to urllib request.
    """
    limit = max_length or max_chars
    target = url.strip()
    if not target.startswith("http://") and not target.startswith("https://"):
        target = f"https://{target}"

    # Try Playwright
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(target, timeout=8000, wait_until="domcontentloaded")
            title = page.title()
            text = page.inner_text("body")
            browser.close()

            clean_text = " ".join(text.split())[:limit]
            return {
                "success": True,
                "status": "success",
                "url": target,
                "title": title,
                "text": clean_text,
                "message": f"Extracted {len(clean_text)} characters from '{title}'."
            }
    except Exception as pw_err:
        logger.info(f"[BROWSER] Playwright unavailable or timed out ({pw_err}), using HTTP fallback.")

    # Fallback to urllib
    try:
        req = urllib.request.Request(
            target, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            parser = _HTMLTextExtractor()
            parser.feed(html)
            text = parser.get_text()
            clean_text = " ".join(text.split())[:limit]

            title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else target

            return {
                "success": True,
                "status": "success",
                "url": target,
                "title": title,
                "text": clean_text,
                "message": f"Extracted {len(clean_text)} characters from '{title}' via HTTP."
            }
    except Exception as http_err:
        logger.error(f"[BROWSER] Text extraction failed: {http_err}")
        return {
            "success": False,
            "status": "error",
            "url": target,
            "message": f"Could not extract content from '{target}': {http_err}"
        }


def take_page_screenshot(url: str, output_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Capture a headless screenshot of a web page using Playwright.
    """
    target = url.strip()
    if not target.startswith("http://") and not target.startswith("https://"):
        target = f"https://{target}"

    if not output_path:
        from datetime import datetime
        home = os.path.expanduser("~")
        desktop = os.path.join(home, "Desktop")
        out_dir = desktop if os.path.exists(desktop) else home
        output_path = os.path.join(out_dir, f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_viewport_size({"width": 1280, "height": 800})
            page.goto(target, timeout=10000, wait_until="networkidle")
            page.screenshot(path=output_path)
            browser.close()

        return {
            "success": True,
            "status": "success",
            "filepath": output_path,
            "url": target,
            "message": f"Web page screenshot saved to '{os.path.basename(output_path)}'."
        }
    except Exception as e:
        logger.error(f"[BROWSER] Screenshot failed: {e}")
        return {
            "success": False,
            "status": "error",
            "url": target,
            "message": f"Failed to capture web screenshot: {e}"
        }


def search_web(query: str, search_engine: str = "google", open_browser: bool = True) -> Dict[str, Any]:
    """
    Perform a web search by opening the search query in the browser.
    """
    try:
        encoded = urllib.parse.quote(query)
        engine = search_engine.lower().strip()
        if "bing" in engine:
            search_url = f"https://www.bing.com/search?q={encoded}"
        elif "duck" in engine:
            search_url = f"https://duckduckgo.com/?q={encoded}"
        else:
            search_url = f"https://www.google.com/search?q={encoded}"

        if open_browser:
            webbrowser.open(search_url)

        return {
            "success": True,
            "status": "success",
            "engine": engine,
            "query": query,
            "url": search_url,
            "message": f"Searching {engine.capitalize()} for '{query}'."
        }
    except Exception as e:
        return {"success": False, "status": "error", "message": f"Web search failed: {e}"}
