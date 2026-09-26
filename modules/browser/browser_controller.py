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


def click_element(url: str, selector: Optional[str] = None, text: Optional[str] = None) -> Dict[str, Any]:
    """
    Interactively click an element on a web page using Playwright.
    """
    target = url.strip()
    if not target.startswith("http://") and not target.startswith("https://"):
        target = f"https://{target}"

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(target, timeout=12000, wait_until="domcontentloaded")
            
            clicked = False
            if text:
                locator = page.get_by_text(text, exact=False).first
                locator.click(timeout=5000)
                clicked = True
            elif selector:
                page.locator(selector).first.click(timeout=5000)
                clicked = True

            final_url = page.url
            title = page.title()
            browser.close()

            return {
                "success": True,
                "status": "success",
                "clicked": clicked,
                "target": text or selector,
                "final_url": final_url,
                "title": title,
                "message": f"Successfully clicked '{text or selector}' on '{title}'."
            }
    except Exception as e:
        logger.error(f"[BROWSER] Click error: {e}")
        return {"success": False, "status": "error", "message": f"Could not click element: {e}"}


def type_into_element(url: str, selector: Optional[str] = None, text: str = "", clear_first: bool = True) -> Dict[str, Any]:
    """
    Type text into a focused or selected input field on a web page.
    """
    target = url.strip()
    if not target.startswith("http://") and not target.startswith("https://"):
        target = f"https://{target}"

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(target, timeout=12000, wait_until="domcontentloaded")

            locator = page.locator(selector).first if selector else page.locator(":focus")
            if clear_first:
                locator.fill(text, timeout=5000)
            else:
                locator.type(text, timeout=5000)

            title = page.title()
            browser.close()

            return {
                "success": True,
                "status": "success",
                "typed_text": text,
                "selector": selector or ":focus",
                "message": f"Typed '{text}' into input field on '{title}'."
            }
    except Exception as e:
        logger.error(f"[BROWSER] Type error: {e}")
        return {"success": False, "status": "error", "message": f"Could not type into element: {e}"}


def scroll_page(url: str, direction: str = "down", amount: int = 500) -> Dict[str, Any]:
    """
    Scroll up or down on a web page.
    """
    target = url.strip()
    if not target.startswith("http://") and not target.startswith("https://"):
        target = f"https://{target}"

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(target, timeout=12000, wait_until="domcontentloaded")

            delta = amount if direction.lower() == "down" else -amount
            page.mouse.wheel(0, delta)
            page.wait_for_timeout(500)
            title = page.title()
            browser.close()

            return {
                "success": True,
                "status": "success",
                "direction": direction,
                "amount": amount,
                "message": f"Scrolled {direction} {amount}px on '{title}'."
            }
    except Exception as e:
        logger.error(f"[BROWSER] Scroll error: {e}")
        return {"success": False, "status": "error", "message": f"Could not scroll page: {e}"}


def press_key(url: str, key: str = "Enter") -> Dict[str, Any]:
    """
    Simulate pressing a keyboard key (e.g. 'Enter', 'Tab', 'Escape', 'ArrowDown') on a page.
    """
    target = url.strip()
    if not target.startswith("http://") and not target.startswith("https://"):
        target = f"https://{target}"

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(target, timeout=12000, wait_until="domcontentloaded")
            page.keyboard.press(key)
            title = page.title()
            browser.close()

            return {
                "success": True,
                "status": "success",
                "key": key,
                "message": f"Pressed key '{key}' on '{title}'."
            }
    except Exception as e:
        logger.error(f"[BROWSER] Key press error: {e}")
        return {"success": False, "status": "error", "message": f"Could not press key '{key}': {e}"}


def fill_form_fields(url: str, fields: Dict[str, str]) -> Dict[str, Any]:
    """
    Batch fill multiple form input fields by selector/name.
    """
    target = url.strip()
    if not target.startswith("http://") and not target.startswith("https://"):
        target = f"https://{target}"

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(target, timeout=12000, wait_until="domcontentloaded")

            results = {}
            for sel, val in fields.items():
                try:
                    page.locator(sel).first.fill(str(val), timeout=4000)
                    results[sel] = "filled"
                except Exception as ex:
                    results[sel] = f"error: {ex}"

            title = page.title()
            browser.close()

            return {
                "success": True,
                "status": "success",
                "fields": results,
                "message": f"Filled {len([v for v in results.values() if v == 'filled'])} form fields on '{title}'."
            }
    except Exception as e:
        logger.error(f"[BROWSER] Form fill error: {e}")
        return {"success": False, "status": "error", "message": f"Could not fill form fields: {e}"}


def extract_page_links(url: str, max_links: int = 20) -> Dict[str, Any]:
    """
    Extract visible hyperlinks (text and href) from a web page.
    """
    target = url.strip()
    if not target.startswith("http://") and not target.startswith("https://"):
        target = f"https://{target}"

    try:
        req = urllib.request.Request(
            target, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        links = []
        for match in re.finditer(r'<a\s+(?:[^>]*?\s+)?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
            href = match.group(1).strip()
            anchor_text = " ".join(re.sub(r'<[^>]+>', '', match.group(2)).split())
            if href and not href.startswith('#') and not href.startswith('javascript:'):
                full_url = urllib.parse.urljoin(target, href)
                links.append({"text": anchor_text or full_url, "url": full_url})
            if len(links) >= max_links:
                break

        return {
            "success": True,
            "status": "success",
            "url": target,
            "count": len(links),
            "links": links,
            "message": f"Found {len(links)} hyperlinks on '{target}'."
        }
    except Exception as e:
        return {"success": False, "status": "error", "message": f"Failed to extract links: {e}"}


def extract_page_tables(url: str) -> Dict[str, Any]:
    """
    Extract structured tabular data (rows and columns) from HTML tables on a web page.
    """
    target = url.strip()
    if not target.startswith("http://") and not target.startswith("https://"):
        target = f"https://{target}"

    try:
        req = urllib.request.Request(
            target, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        tables = []
        for t_match in re.finditer(r'<table[^>]*>(.*?)</table>', html, re.DOTALL | re.IGNORECASE):
            t_content = t_match.group(1)
            rows = []
            for r_match in re.finditer(r'<tr[^>]*>(.*?)</tr>', t_content, re.DOTALL | re.IGNORECASE):
                r_content = r_match.group(1)
                cells = []
                for c_match in re.finditer(r'<(?:td|th)[^>]*>(.*?)</(?:td|th)>', r_content, re.DOTALL | re.IGNORECASE):
                    cell_text = " ".join(re.sub(r'<[^>]+>', '', c_match.group(1)).split())
                    cells.append(cell_text)
                if cells:
                    rows.append(cells)
            if rows:
                tables.append(rows)

        return {
            "success": True,
            "status": "success",
            "url": target,
            "table_count": len(tables),
            "tables": tables,
            "message": f"Extracted {len(tables)} table(s) from '{target}'."
        }
    except Exception as e:
        return {"success": False, "status": "error", "message": f"Failed to extract tables: {e}"}


def build_flight_search_url(
    origin: str, 
    destination: str, 
    departure_date: Optional[str] = None, 
    return_date: Optional[str] = None, 
    adults: int = 1,
    open_browser: bool = True
) -> Dict[str, Any]:
    """
    Construct a structured Google Flights query and optionally launch it in the browser.
    """
    query = f"flights from {origin} to {destination}"
    if departure_date:
        query += f" on {departure_date}"
    if return_date:
        query += f" returning {return_date}"
    
    encoded = urllib.parse.quote(query)
    flight_url = f"https://www.google.com/travel/flights?q={encoded}"

    if open_browser:
        webbrowser.open(flight_url)

    return {
        "success": True,
        "status": "success",
        "origin": origin,
        "destination": destination,
        "departure_date": departure_date,
        "return_date": return_date,
        "adults": adults,
        "url": flight_url,
        "message": f"Flight search for {origin} to {destination} opened: {flight_url}"
    }

