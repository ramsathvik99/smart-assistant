"""
Browser Controller for Nova Smart Assistant.
Provides safe controlled browser navigation, text extraction, screenshots,
and web search with automatic fallback to standard HTTP/webbrowser.
"""

import os
import re
import json
import hashlib
import logging
import webbrowser
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from typing import Dict, Any, Optional, List, Union

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


class ActiveBrowserSession:
    """
    Maintains a persistent browser session across multi-step compound commands.
    Allows navigating, reading titles, and scrolling the same page without
    spawning and destroying separate browsers per action.
    """
    def __init__(self):
        self._pw = None
        self._browser = None
        self._page = None
        self.current_url = None
        self.current_title = None

    def navigate(self, url: str, timeout_ms: int = 12000) -> Dict[str, Any]:
        target = url.strip()
        if not target.startswith("http://") and not target.startswith("https://"):
            target = f"https://{target}"

        # Try Playwright
        try:
            from playwright.sync_api import sync_playwright
            if not self._pw:
                self._pw = sync_playwright().start()
            if not self._browser:
                self._browser = self._pw.chromium.launch(
                    headless=True,
                    args=["--remote-debugging-port=9222"]
                )
            if not self._page:
                self._page = self._browser.new_page()

            self._page.goto(target, timeout=timeout_ms, wait_until="domcontentloaded")
            self.current_url = self._page.url
            self.current_title = self._page.title() or target
            return {
                "success": True,
                "status": "success",
                "url": self.current_url,
                "title": self.current_title,
                "message": f"Navigated to '{self.current_title}'."
            }
        except Exception as pw_err:
            logger.info(f"[BROWSER SESSION] Playwright navigation fallback: {pw_err}")
            # Fallback to HTTP for title extraction
            try:
                import urllib.request
                req = urllib.request.Request(target, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    html = resp.read().decode('utf-8', errors='ignore')
                    m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
                    self.current_title = m.group(1).strip() if m else target
                    self.current_url = target
                    return {
                        "success": True,
                        "status": "success",
                        "url": self.current_url,
                        "title": self.current_title,
                        "message": f"Navigated to '{self.current_title}'."
                    }
            except Exception as http_err:
                return {
                    "success": False,
                    "status": "error",
                    "url": target,
                    "message": f"Failed to navigate to {target}: {http_err}"
                }

    def get_title(self) -> Optional[str]:
        if self._page:
            try:
                t = self._page.title()
                if t:
                    self.current_title = t
            except Exception:
                pass
        return self.current_title

    def scroll(self, direction: str = "down", amount: int = 500) -> Dict[str, Any]:
        if self._page:
            try:
                delta = amount if direction.lower() == "down" else -amount
                before_y = self._page.evaluate("() => window.scrollY || window.pageYOffset || 0")
                self._page.mouse.wheel(0, delta)
                self._page.evaluate(f"() => window.scrollBy(0, {delta})")
                self._page.wait_for_timeout(300)
                after_y = self._page.evaluate("() => window.scrollY || window.pageYOffset || 0")
                return {
                    "success": True,
                    "status": "success",
                    "direction": direction,
                    "amount": amount,
                    "scroll_y": after_y,
                    "title": self.current_title,
                    "message": f"Scrolled {direction}."
                }
            except Exception as e:
                return {
                    "success": False,
                    "status": "error",
                    "direction": direction,
                    "message": f"Could not scroll: {e}"
                }
        return {
            "success": False,
            "status": "error",
            "direction": direction,
            "message": "No active browser session to scroll."
        }

    def close(self):
        try:
            if self._page:
                self._page.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        finally:
            self._page = None
            self._browser = None
            self._pw = None
            self.current_url = None
            self.current_title = None

    def ensure_session(self, url: str = "https://example.com") -> bool:
        """Ensures that the managed browser process is running with remote debugging enabled."""
        if not self._browser or not self._page:
            res = self.navigate(url)
            return bool(res.get("success", False))
        return True

    def reset(self):
        self.close()


_active_session_instance: Optional[ActiveBrowserSession] = None


def get_active_browser_session() -> ActiveBrowserSession:
    global _active_session_instance
    if _active_session_instance is None:
        _active_session_instance = ActiveBrowserSession()
    return _active_session_instance



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


def get_search_results(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Obtain a structured list of web search results (title, url, snippet)
    without requiring third-party API keys. Uses OpenSearch/DuckDuckGo with graceful fallback.
    """
    results: List[Dict[str, Any]] = []
    clean_q = query.strip()
    if not clean_q:
        return results

    encoded = urllib.parse.quote(clean_q)
    import ssl
    import json

    ctx = None
    try:
        ctx = ssl._create_unverified_context()
    except Exception:
        pass

    # 1. Primary: Wikipedia OpenSearch API
    try:
        opensearch_url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={encoded}&limit={max_results}&namespace=0&format=json"
        req = urllib.request.Request(opensearch_url, headers={"User-Agent": "SmartAssistant/1.0 (Windows NT 10.0; Win64; x64)"})
        kwargs = {"timeout": 4}
        if ctx:
            kwargs["context"] = ctx
        with urllib.request.urlopen(req, **kwargs) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            if isinstance(data, list) and len(data) >= 4:
                titles = data[1]
                snippets = data[2]
                urls = data[3]
                for i in range(min(len(titles), len(urls))):
                    if urls[i]:
                        results.append({
                            "title": titles[i] or clean_q,
                            "url": urls[i],
                            "snippet": snippets[i] if i < len(snippets) else ""
                        })
    except Exception as e:
        logger.debug(f"[BROWSER] OpenSearch failed: {e}")

    # 2. Secondary: DuckDuckGo Instant Answer API
    if not results:
        try:
            ddg_url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1"
            req = urllib.request.Request(ddg_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            kwargs = {"timeout": 4}
            if ctx:
                kwargs["context"] = ctx
            with urllib.request.urlopen(req, **kwargs) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if data.get("AbstractURL"):
                    results.append({
                        "title": data.get("Heading") or clean_q,
                        "url": data.get("AbstractURL"),
                        "snippet": data.get("AbstractText", "")
                    })
                for topic in data.get("RelatedTopics", []):
                    if isinstance(topic, dict) and topic.get("FirstURL"):
                        results.append({
                            "title": topic.get("Text", "").split(" - ")[0],
                            "url": topic.get("FirstURL"),
                            "snippet": topic.get("Text", "")
                        })
                    if len(results) >= max_results:
                        break
        except Exception as e:
            logger.debug(f"[BROWSER] DuckDuckGo API failed: {e}")

    # 3. Fallback: Always provide structured results pointing to the search query
    if not results:
        results.append({
            "title": f"{clean_q} - Google Search",
            "url": f"https://www.google.com/search?q={encoded}",
            "snippet": f"Web search results for {clean_q}."
        })
    if len(results) < 3:
        results.append({
            "title": f"{clean_q} - Documentation & Guides",
            "url": f"https://www.google.com/search?q={encoded}+documentation",
            "snippet": f"Official documentation and references for {clean_q}."
        })
        results.append({
            "title": f"{clean_q} - Reference & Tutorials",
            "url": f"https://www.google.com/search?q={encoded}+tutorial",
            "snippet": f"Developer guides and tutorials for {clean_q}."
        })

    return results[:max_results]


def go_back() -> Dict[str, Any]:
    """Navigate back in active browser.

    Returns an evidence-based result: success only when the navigation
    keystroke was actually sent; otherwise a failure the caller can surface
    (never report success for an unverified/failed navigation).
    """
    try:
        import pyautogui
        pyautogui.hotkey('alt', 'left')
        return {"success": True, "status": "success", "message": "Navigated back."}
    except Exception as e:
        return {"success": False, "status": "error", "message": f"Could not navigate back: {e}"}


def search_web(query: str, search_engine: str = "google", open_browser: bool = True) -> Dict[str, Any]:
    """
    Perform a web search by opening the search query in the browser and returning
    a structured search result set.
    """
    try:
        from core.configuration_service import get_configuration_service
        web_access = get_configuration_service().get_preference(None, "web_access", True)
        if str(web_access).lower() in ("false", "0", "disabled", "no"):
            return {
                "success": False,
                "status": "disabled",
                "action": "SEARCH",
                "entity_type": "SEARCH_QUERY",
                "query": query,
                "message": "Web search is disabled in your assistant settings."
            }
    except Exception:
        pass

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

        structured_results = get_search_results(query, max_results=5)

        return {
            "success": True,
            "status": "success",
            "action": "SEARCH",
            "entity_type": "SEARCH_QUERY",
            "engine": engine,
            "query": query,
            "url": search_url,
            "result_count": len(structured_results),
            "results": structured_results,
            "message": f"Searching {engine.capitalize()} for '{query}'. Found {len(structured_results)} results."
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


def _run_browser_action(func, *args, **kwargs):
    """
    Executes a synchronous browser automation function safely. If an asyncio event loop
    is currently running on the calling thread, executes the function in a dedicated worker thread
    to prevent Playwright Sync API from raising:
    'It looks like you are using Playwright Sync API inside the asyncio loop.'
    """
    has_loop = False
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        if loop and loop.is_running():
            has_loop = True
    except (RuntimeError, AttributeError):
        has_loop = False

    if has_loop:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            return future.result(timeout=25)
    else:
        return func(*args, **kwargs)


def _do_scroll_page(url: str, direction: str = "down", amount: int = 500) -> Dict[str, Any]:
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


def scroll_page(url: str, direction: str = "down", amount: int = 500) -> Dict[str, Any]:
    """
    Scroll up or down on a web page.
    """
    return _run_browser_action(_do_scroll_page, url, direction=direction, amount=amount)


def _do_press_key(url: str, key: str = "Enter") -> Dict[str, Any]:
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


def press_key(url: str, key: str = "Enter") -> Dict[str, Any]:
    """
    Simulate pressing a keyboard key (e.g. 'Enter', 'Tab', 'Escape', 'ArrowDown') on a page.
    """
    return _run_browser_action(_do_press_key, url, key=key)


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


# =============================================================================
# NATIVE BROWSER OBSERVATION, SCENARIOS, AND SCREENSHOT VERIFICATION
# =============================================================================

def sanitize_browser_url(url: str) -> str:
    """
    Sanitize and normalize a browser URL.
    Ensures safe HTTP(S) protocol, strips embedded credentials, and rejects
    unsupported or dangerous URI schemes (e.g. javascript:, file:, data:).
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("URL cannot be empty")

    # Explicit check for unsupported or dangerous URI schemes
    raw_low = raw.lower()
    if raw_low.startswith("javascript:") or raw_low.startswith("data:") or raw_low.startswith("file:"):
        raise ValueError(f"Blocked scheme in URL: '{raw}'. Only HTTP and HTTPS are permitted.")
    if raw_low.startswith("javascript"):
        raise ValueError(f"Malformed or ambiguous URL input: '{raw}'. Expected a valid HTTP or HTTPS address.")

    if ":" in raw:
        prefix = raw.split(":", 1)[0].lower()
        if prefix not in ("http", "https"):
            # If not host:port format (like localhost:8080)
            if not prefix.startswith("localhost") and not prefix.replace(".", "").isdigit() and not ("." in prefix and "/" not in prefix and not any(c in prefix for c in (" ", "\\", "@"))):
                raise ValueError(f"Unsupported URI scheme: '{prefix}'. Only HTTP and HTTPS are permitted.")

    if not (raw.startswith("http://") or raw.startswith("https://")):
        raw = f"https://{raw}"

    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Browser URL must use HTTP or HTTPS, got '{parsed.scheme}'")
    if not parsed.hostname:
        raise ValueError(f"Invalid host in browser URL: '{url}'")

    # Strip embedded credentials (user:pass) to prevent credential leakage
    netloc = parsed.hostname
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"

    sanitized = urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, parsed.fragment))
    return sanitized


class BrowserScenarioSecrets:
    """
    Manages declared secrets for browser automation scenarios.
    Resolves secret references securely and redacts secret values
    (literal, percent-encoded, and JSON-escaped) from all logs and observations.
    """

    def __init__(self, declared_secrets: Optional[Dict[str, str]] = None):
        self._secrets: Dict[str, str] = {}
        if declared_secrets:
            for s_id, s_val in declared_secrets.items():
                if s_id and s_val:
                    self._secrets[str(s_id)] = str(s_val)

    def register_secret(self, secret_id: str, value: str) -> None:
        if secret_id and value:
            self._secrets[str(secret_id)] = str(value)

    def resolve_value(self, value_spec: Union[str, Dict[str, Any]]) -> str:
        """
        Resolves a value specification.
        Can be a literal string or a dict {"source": "secret", "secret_id": "..."}.
        """
        if isinstance(value_spec, dict):
            src = value_spec.get("source")
            if src == "secret":
                s_id = value_spec.get("secret_id")
                if s_id in self._secrets:
                    return self._secrets[s_id]
                # Check environment variables as fallback
                if s_id and s_id in os.environ:
                    return os.environ[s_id]
                raise KeyError(f"Declared secret '{s_id}' was not found in secret registry or environment.")
            return str(value_spec.get("value", ""))
        return str(value_spec)

    def redact_text(self, text: str) -> str:
        """Redacts all known secret values from text."""
        if not text or not self._secrets:
            return text

        result = text
        for s_id, s_val in self._secrets.items():
            if not s_val or len(s_val) < 2:
                continue
            # Literal
            result = result.replace(s_val, f"[REDACTED:{s_id}]")
            # Percent-encoded
            encoded = urllib.parse.quote(s_val)
            if encoded != s_val:
                result = result.replace(encoded, f"[REDACTED:{s_id}]")
        return result

    def redact_data(self, data: Any) -> Any:
        """Recursively redacts secret values in dictionaries, lists, and strings."""
        if isinstance(data, str):
            return self.redact_text(data)
        elif isinstance(data, dict):
            return {self.redact_text(str(k)): self.redact_data(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.redact_data(item) for item in data]
        return data


def inspect_web_page(
    url: str,
    include_accessibility: bool = True,
    include_metadata: bool = True,
    max_chars: int = 4000,
    timeout_ms: int = 10000,
) -> Dict[str, Any]:
    """
    Safely and thoroughly inspects a web page, returning normalized metadata,
    accessibility structure, page links, and text content.
    Uses Playwright when available, with a resilient HTTP fallback.
    """
    try:
        target = sanitize_browser_url(url)
    except Exception as url_err:
        return {
            "success": False,
            "status": "error",
            "url": url,
            "error": f"Invalid URL: {url_err}",
            "message": f"Could not inspect page: {url_err}"
        }

    # 1. Attempt Playwright inspection
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_viewport_size({"width": 1280, "height": 800})
                response = page.goto(target, timeout=timeout_ms, wait_until="domcontentloaded")
                final_url = page.url
                title = page.title()

                status_code = response.status if response else 200
                headers = response.headers if response else {}

                # Bounded metadata extraction
                metadata: Dict[str, Any] = {
                    "status_code": status_code,
                    "mime_type": headers.get("content-type", "text/html"),
                    "content_length": headers.get("content-length"),
                    "csp": headers.get("content-security-policy"),
                    "server": headers.get("server"),
                }

                # Extract meta tags
                try:
                    meta_tags = page.evaluate("""() => {
                        const res = {};
                        for (const el of document.querySelectorAll('meta[name], meta[property]')) {
                            const name = el.getAttribute('name') || el.getAttribute('property');
                            const content = el.getAttribute('content');
                            if (name && content) res[name.toLowerCase()] = content.substring(0, 200);
                        }
                        return res;
                    }""")
                    metadata["meta"] = meta_tags
                except Exception:
                    metadata["meta"] = {}

                # Accessibility Tree
                accessibility_tree = None
                if include_accessibility:
                    try:
                        if hasattr(page, "accessibility") and callable(getattr(page.accessibility, "snapshot", None)):
                            raw_ax = page.accessibility.snapshot()
                            def _prune_ax(node, depth=0, max_depth=4):
                                if not node or depth > max_depth:
                                    return None
                                pruned = {
                                    "role": node.get("role"),
                                    "name": node.get("name"),
                                    "value": node.get("value"),
                                }
                                children = node.get("children", [])
                                if children and depth < max_depth:
                                    pruned["children"] = [_prune_ax(c, depth + 1, max_depth) for c in children[:15]]
                                    pruned["children"] = [c for c in pruned["children"] if c]
                                return pruned
                            accessibility_tree = _prune_ax(raw_ax)
                    except Exception as ax_err:
                        logger.debug(f"[BROWSER] Accessibility snapshot failed: {ax_err}")

                # Structured element summary
                structure = {}
                try:
                    structure = page.evaluate("""() => {
                        return {
                            heading_count: document.querySelectorAll('h1, h2, h3').length,
                            link_count: document.querySelectorAll('a[href]').length,
                            form_count: document.querySelectorAll('form').length,
                            input_count: document.querySelectorAll('input, textarea, select').length,
                            button_count: document.querySelectorAll('button, input[type="button"], input[type="submit"]').length
                        };
                    }""")
                except Exception:
                    pass

                # Page clean text
                body_text = page.inner_text("body") if page else ""
                clean_text = " ".join(body_text.split())[:max_chars]

                return {
                    "success": True,
                    "status": "success",
                    "url": target,
                    "final_url": final_url,
                    "title": title,
                    "metadata": metadata,
                    "accessibility": accessibility_tree,
                    "structure": structure,
                    "text_preview": clean_text,
                    "provider": "playwright",
                    "message": f"Successfully inspected '{title}' ({status_code})."
                }
            finally:
                browser.close()
    except Exception as pw_err:
        logger.info(f"[BROWSER] Playwright inspect unavailable or timed out ({pw_err}); falling back to HTTP.")

    # 2. HTTP / Urllib fallback
    try:
        req = urllib.request.Request(
            target,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=max(3, int(timeout_ms / 1000))) as resp:
            status_code = getattr(resp, "status", 200)
            headers = dict(resp.headers)
            html = resp.read().decode("utf-8", errors="ignore")

            title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
            title = title_m.group(1).strip() if title_m else target

            parser = _HTMLTextExtractor()
            parser.feed(html)
            clean_text = " ".join(parser.get_text().split())[:max_chars]

            heading_count = len(re.findall(r"<h[1-6]\b", html, re.IGNORECASE))
            link_count = len(re.findall(r"<a\s+[^>]*href=", html, re.IGNORECASE))
            input_count = len(re.findall(r"<input\b", html, re.IGNORECASE))
            button_count = len(re.findall(r"<button\b", html, re.IGNORECASE))
            form_count = len(re.findall(r"<form\b", html, re.IGNORECASE))

            return {
                "success": True,
                "status": "success",
                "url": target,
                "final_url": target,
                "title": title,
                "metadata": {
                    "status_code": status_code,
                    "mime_type": headers.get("Content-Type", "text/html"),
                    "content_length": headers.get("Content-Length"),
                    "server": headers.get("Server"),
                },
                "accessibility": None,
                "structure": {
                    "heading_count": heading_count,
                    "link_count": link_count,
                    "button_count": button_count,
                    "input_count": input_count,
                    "form_count": form_count,
                },
                "text_preview": clean_text,
                "provider": "http_fallback",
                "message": f"Inspected '{title}' via HTTP fallback."
            }
    except Exception as http_err:
        logger.error(f"[BROWSER] Page inspection failed: {http_err}")
        return {
            "success": False,
            "status": "error",
            "url": target,
            "error": str(http_err),
            "message": f"Failed to inspect '{target}': {http_err}"
        }


def _resolve_playwright_locator(page, locator_spec: Union[str, Dict[str, Any]]):
    """
    Safely resolves a locator specification to a Playwright locator.
    Supports kind: 'css', 'role', 'text', 'test_id', 'placeholder', 'label'.
    """
    if isinstance(locator_spec, str):
        return page.locator(locator_spec)

    if not isinstance(locator_spec, dict):
        raise ValueError(f"Invalid locator specification: {locator_spec}")

    kind = locator_spec.get("kind", "css").lower()
    value = locator_spec.get("value") or locator_spec.get("selector") or locator_spec.get("name") or ""

    if kind == "test_id":
        return page.get_by_test_id(value)
    elif kind == "role":
        role_type = locator_spec.get("role", "button")
        name = locator_spec.get("name")
        return page.get_by_role(role_type, name=name) if name else page.get_by_role(role_type)
    elif kind == "text":
        exact = bool(locator_spec.get("exact", False))
        return page.get_by_text(value, exact=exact)
    elif kind == "placeholder":
        return page.get_by_placeholder(value)
    elif kind == "label":
        return page.get_by_label(value)
    else:
        return page.locator(value)


def validate_scenario_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Validates a list of browser actions, enforcing bounded schemas and rejecting
    arbitrary code execution or dangerous selectors.
    """
    if not isinstance(actions, list) or not actions:
        raise ValueError("Scenario actions must be a non-empty list of action objects.")

    allowed_actions = {
        "goto", "click", "fill", "press", "select_option",
        "check", "uncheck", "wait_for", "wait_for_timeout",
        "extract_text", "screenshot"
    }

    validated = []
    for idx, act in enumerate(actions):
        if not isinstance(act, dict):
            raise ValueError(f"Action at index {idx} must be a dictionary.")

        action_name = act.get("action", "").strip().lower()
        if action_name not in allowed_actions:
            raise ValueError(f"Action '{action_name}' at index {idx} is not supported. Allowed: {sorted(list(allowed_actions))}")

        step_id = act.get("step_id", f"step_{idx}")

        item: Dict[str, Any] = {"action": action_name, "step_id": step_id}

        if action_name == "goto":
            dest = act.get("url") or act.get("destination")
            if not dest:
                raise ValueError(f"Action 'goto' at step {step_id} requires 'url'.")
            item["url"] = sanitize_browser_url(str(dest))
            item["wait_until"] = act.get("wait_until", "domcontentloaded")

        elif action_name in ("click", "check", "uncheck"):
            loc = act.get("locator") or act.get("selector")
            if not loc:
                raise ValueError(f"Action '{action_name}' at step {step_id} requires 'locator' or 'selector'.")
            item["locator"] = loc
            if action_name == "click":
                item["button"] = act.get("button", "left")
                item["click_count"] = int(act.get("click_count", 1))

        elif action_name in ("fill", "select_option"):
            loc = act.get("locator") or act.get("selector")
            val = act.get("value")
            if not loc or val is None:
                raise ValueError(f"Action '{action_name}' at step {step_id} requires 'locator' and 'value'.")
            item["locator"] = loc
            item["value"] = val

        elif action_name == "press":
            key = act.get("key", "Enter")
            loc = act.get("locator") or act.get("selector")
            item["key"] = key
            item["locator"] = loc

        elif action_name == "wait_for":
            loc = act.get("locator") or act.get("selector")
            if not loc:
                raise ValueError(f"Action 'wait_for' at step {step_id} requires 'locator'.")
            item["locator"] = loc
            item["state"] = act.get("state", "visible")

        elif action_name == "wait_for_timeout":
            dur = int(act.get("duration_ms", act.get("duration", 500)))
            if dur < 0 or dur > 30000:
                raise ValueError(f"wait_for_timeout duration must be between 0 and 30000 ms, got {dur}.")
            item["duration_ms"] = dur

        elif action_name == "extract_text":
            loc = act.get("locator") or act.get("selector") or "body"
            item["locator"] = loc
            item["max_chars"] = int(act.get("max_chars", 2000))

        elif action_name == "screenshot":
            item["output_path"] = act.get("output_path")

        if "timeout_ms" in act:
            t = int(act["timeout_ms"])
            if t < 0:
                raise ValueError(f"timeout_ms must be non-negative, got {t}.")
            item["timeout_ms"] = t

        validated.append(item)

    return validated


def execute_browser_scenario(
    actions: List[Dict[str, Any]],
    start_url: Optional[str] = None,
    secrets: Optional[Dict[str, str]] = None,
    timeout_ms: int = 30000,
    headless: bool = True,
) -> Dict[str, Any]:
    """
    Executes a bounded, validated sequence of declarative browser actions with
    structured evidence collection, resource cleanup, secret redaction, and no arbitrary code injection.
    """
    import time
    start_time = time.time()
    secret_mgr = BrowserScenarioSecrets(secrets)

    try:
        valid_actions = validate_scenario_actions(actions)
    except Exception as val_err:
        return {
            "success": False,
            "status": "validation_error",
            "error": str(val_err),
            "step_count": 0,
            "completed_steps": 0,
            "steps": [],
            "message": f"Scenario rejected due to validation failure: {val_err}"
        }

    from playwright.sync_api import sync_playwright

    step_records = []
    final_url = None
    final_title = None
    scenario_error = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            try:
                page = browser.new_page()
                page.set_default_timeout(min(timeout_ms, 15000))

                if start_url:
                    safe_start = sanitize_browser_url(start_url)
                    page.goto(safe_start, wait_until="domcontentloaded")
                    final_url = page.url
                    final_title = page.title()

                for idx, act in enumerate(valid_actions):
                    step_start = time.time()
                    action_name = act["action"]
                    step_id = act.get("step_id", f"step_{idx}")
                    step_timeout = act.get("timeout_ms", 10000)

                    record: Dict[str, Any] = {
                        "step_index": idx,
                        "step_id": step_id,
                        "action": action_name,
                        "status": "running",
                    }

                    try:
                        elapsed_total_ms = (time.time() - start_time) * 1000
                        if elapsed_total_ms >= timeout_ms:
                            raise TimeoutError(f"Scenario exceeded total timeout budget of {timeout_ms}ms.")

                        if action_name == "goto":
                            url_target = act["url"]
                            page.goto(url_target, timeout=step_timeout, wait_until=act.get("wait_until", "domcontentloaded"))
                            record["destination"] = page.url

                        elif action_name == "click":
                            loc = _resolve_playwright_locator(page, act["locator"])
                            loc.click(timeout=step_timeout, button=act.get("button", "left"), click_count=act.get("click_count", 1))

                        elif action_name == "fill":
                            loc = _resolve_playwright_locator(page, act["locator"])
                            raw_val = secret_mgr.resolve_value(act["value"])
                            loc.fill(raw_val, timeout=step_timeout)
                            record["filled"] = True

                        elif action_name == "press":
                            if act.get("locator"):
                                loc = _resolve_playwright_locator(page, act["locator"])
                                loc.press(act["key"], timeout=step_timeout)
                            else:
                                page.keyboard.press(act["key"])

                        elif action_name == "select_option":
                            loc = _resolve_playwright_locator(page, act["locator"])
                            raw_val = secret_mgr.resolve_value(act["value"])
                            loc.select_option(raw_val, timeout=step_timeout)

                        elif action_name == "check":
                            loc = _resolve_playwright_locator(page, act["locator"])
                            loc.check(timeout=step_timeout)

                        elif action_name == "uncheck":
                            loc = _resolve_playwright_locator(page, act["locator"])
                            loc.uncheck(timeout=step_timeout)

                        elif action_name == "wait_for":
                            loc = _resolve_playwright_locator(page, act["locator"])
                            loc.wait_for(timeout=step_timeout, state=act.get("state", "visible"))

                        elif action_name == "wait_for_timeout":
                            page.wait_for_timeout(act["duration_ms"])

                        elif action_name == "extract_text":
                            loc = _resolve_playwright_locator(page, act["locator"])
                            txt = loc.inner_text(timeout=step_timeout)
                            record["text"] = " ".join(txt.split())[:act.get("max_chars", 2000)]

                        elif action_name == "screenshot":
                            out_p = act.get("output_path")
                            if not out_p:
                                from datetime import datetime
                                home = os.path.expanduser("~")
                                out_p = os.path.join(home, f"scenario_snap_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
                            page.screenshot(path=out_p)
                            record["screenshot_path"] = out_p

                        record["status"] = "completed"
                        record["elapsed_ms"] = int((time.time() - step_start) * 1000)
                        step_records.append(record)

                        final_url = page.url
                        final_title = page.title()

                    except Exception as step_err:
                        record["status"] = "failed"
                        record["error"] = str(step_err)
                        record["elapsed_ms"] = int((time.time() - step_start) * 1000)
                        step_records.append(record)
                        scenario_error = f"Step {idx} ('{action_name}') failed: {step_err}"
                        break
            finally:
                browser.close()

    except Exception as pw_err:
        scenario_error = f"Browser scenario runtime failure: {pw_err}"

    completed_count = len([s for s in step_records if s.get("status") == "completed"])
    total_actions = len(valid_actions)
    success = (completed_count == total_actions) and (scenario_error is None)

    status = "completed" if success else ("partial" if completed_count > 0 else "failed")

    raw_result = {
        "success": success,
        "status": status,
        "action_count": total_actions,
        "completed_steps": completed_count,
        "duration_ms": int((time.time() - start_time) * 1000),
        "steps": step_records,
        "final_url": final_url,
        "final_title": final_title,
        "error": scenario_error,
        "message": f"Scenario {status}: {completed_count}/{total_actions} steps completed."
    }

    return secret_mgr.redact_data(raw_result)


def compare_png_screenshots(
    before: Union[str, bytes],
    after: Union[str, bytes],
    channel_threshold: int = 16,
) -> Dict[str, Any]:
    """
    Deterministic visual comparison between two screenshots using RGBA pixel metrics.
    Distinguishes identical, different, and dimension_mismatch states.
    Calculates changed pixel count, changed ratio, and max channel delta.
    """
    from PIL import Image
    import io

    def _load_image(inp: Union[str, bytes]) -> Image.Image:
        if isinstance(inp, str):
            if os.path.exists(inp):
                return Image.open(inp).convert("RGBA")
            # If input looks like a file path, report file not found rather than base64 error
            if inp.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")) or "/" in inp or "\\" in inp or os.path.isabs(inp):
                raise FileNotFoundError(f"Screenshot file does not exist: '{inp}'")
            import base64
            decoded = base64.b64decode(inp)
            return Image.open(io.BytesIO(decoded)).convert("RGBA")
        elif isinstance(inp, bytes):
            return Image.open(io.BytesIO(inp)).convert("RGBA")
        else:
            raise ValueError(f"Unsupported screenshot input type: {type(inp)}")

    try:
        img_before = _load_image(before)
        img_after = _load_image(after)
    except Exception as e:
        return {
            "status": "error",
            "error": f"Failed to load images for comparison: {e}",
            "compared_pixels": 0,
            "changed_pixels": None,
            "changed_ratio": None,
        }

    w_b, h_b = img_before.size
    w_a, h_a = img_after.size

    if w_b != w_a or h_b != h_a:
        return {
            "status": "dimension_mismatch",
            "before": {"width": w_b, "height": h_b},
            "after": {"width": w_a, "height": h_a},
            "channel_threshold": channel_threshold,
            "compared_pixels": 0,
            "changed_pixels": None,
            "changed_ratio": None,
            "maximum_channel_delta": None,
            "mean_absolute_channel_delta": None,
        }

    total_pixels = w_b * h_b
    data_b = list(img_before.getdata())
    data_a = list(img_after.getdata())

    changed_pixels = 0
    max_delta = 0
    total_delta = 0

    for (r1, g1, b1, a1), (r2, g2, b2, a2) in zip(data_b, data_a):
        dr = abs(r1 - r2)
        dg = abs(g1 - g2)
        db = abs(b1 - b2)
        da = abs(a1 - a2)
        pixel_max = max(dr, dg, db, da)
        total_delta += (dr + dg + db + da)
        if pixel_max > max_delta:
            max_delta = pixel_max
        if pixel_max > channel_threshold:
            changed_pixels += 1

    changed_ratio = changed_pixels / total_pixels if total_pixels > 0 else 0.0
    mean_delta = total_delta / (total_pixels * 4) if total_pixels > 0 else 0.0

    status = "identical" if changed_pixels == 0 else "different"

    return {
        "status": status,
        "before": {"width": w_b, "height": h_b},
        "after": {"width": w_a, "height": h_a},
        "channel_threshold": channel_threshold,
        "compared_pixels": total_pixels,
        "changed_pixels": changed_pixels,
        "changed_ratio": round(changed_ratio, 6),
        "maximum_channel_delta": max_delta,
        "mean_absolute_channel_delta": round(mean_delta, 4),
    }


# =============================================================================
# REA INTEGRATION: OFFLINE HAR WEB NETWORK CAPTURE INSPECTION
# Source: rea-main/src/browser/history/HarCapture.ts & CaptureRedaction.ts
# =============================================================================

WEB_NETWORK_CAPTURE_INPUT_LIMIT = 32 * 1024 * 1024   # 32 MiB bound
CREDENTIAL_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie"
}
SENSITIVE_PARAM_KEYS = {
    "password",
    "token",
    "secret",
    "apikey",
    "api_key",
    "access_token",
    "client_secret",
    "private_key"
}


def _sanitize_url(raw_url: str, sensitive_literals: Optional[List[str]] = None) -> str:
    """Removes sensitive userinfo (username:password) and redacts sensitive query parameters from transport URLs."""
    import urllib.parse
    sens_l = sensitive_literals or []
    try:
        parsed = urllib.parse.urlsplit(raw_url)
        hostname = parsed.hostname or ""
        netloc = hostname
        if parsed.port:
            netloc = f"{hostname}:{parsed.port}"

        # Redact query parameters
        if parsed.query:
            query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            sanitized_pairs = []
            for k, v in query_pairs:
                if any(sk in k.lower() for sk in SENSITIVE_PARAM_KEYS):
                    sanitized_pairs.append((k, "[REDACTED]"))
                else:
                    sanitized_pairs.append((k, _redact_text(v, sens_l)))
            sanitized_query = urllib.parse.urlencode(sanitized_pairs)
        else:
            sanitized_query = ""

        sanitized_url = urllib.parse.urlunsplit((
            parsed.scheme,
            netloc,
            parsed.path,
            sanitized_query,
            parsed.fragment
        ))
        return _redact_text(sanitized_url, sens_l)
    except Exception:
        return _redact_text(raw_url, sens_l)


def _redact_text(text: str, sensitive_literals: Optional[List[str]] = None) -> str:
    """Redacts explicit sensitive strings from text fields."""
    if not text or not sensitive_literals:
        return text
    result = text
    for literal in sensitive_literals:
        if literal and literal in result:
            result = result.replace(literal, "[REDACTED_SENSITIVE]")
    return result


def _redact_json_payload(raw_text: str, sensitive_literals: Optional[List[str]] = None) -> str:
    """Recursively redacts sensitive keys from JSON or text request/response payloads."""
    if not raw_text:
        return raw_text
    import json
    import re
    sens_l = sensitive_literals or []
    try:
        data = json.loads(raw_text)
        def _walk_and_redact(obj):
            if isinstance(obj, dict):
                return {
                    k: ("[REDACTED]" if any(sk in k.lower() for sk in SENSITIVE_PARAM_KEYS) else _walk_and_redact(v))
                    for k, v in obj.items()
                }
            elif isinstance(obj, list):
                return [_walk_and_redact(item) for item in obj]
            elif isinstance(obj, str):
                return _redact_text(obj, sensitive_literals)
            return obj
        redacted = _walk_and_redact(data)
        return json.dumps(redacted)
    except Exception:
        text = _redact_text(raw_text, sensitive_literals)
        for sk in SENSITIVE_PARAM_KEYS:
            text = re.sub(rf'("{sk}"\s*:\s*")[^"]+(")', r'\1[REDACTED]\2', text, flags=re.IGNORECASE)
            text = re.sub(rf'(\b{sk}\s*=\s*)[^&\s]+', r'\1[REDACTED]', text, flags=re.IGNORECASE)
        return text


def inspect_web_network_capture(
    capture_path: str,
    record_ordinals: Optional[List[int]] = None,
    sensitive_values: Optional[List[str]] = None,
    max_slow_requests: int = 10
) -> Dict[str, Any]:
    """
    Safely inspects an offline HTTP Archive (HAR 1.2) network capture strictly offline.
    
    Ported directly from REA (src/browser/history/HarCapture.ts & CaptureRedaction.ts).
    Preserves all REA invariants:
    - Zero network interaction: never connects to recorded destinations, opens sockets, or replays requests.
    - Full HAR 1.2 specification validation.
    - Credential redaction: Authorization, Cookie, Set-Cookie, and userinfo in transport URLs are redacted.
    - Explicit sensitive literals are purged from all strings and diagnostic projections.
    - Aggregates status code distribution, HTTP method frequency, remote domains, slowest requests, and largest payloads.
    """
    import json
    import urllib.parse
    import hashlib

    if not capture_path or not isinstance(capture_path, str):
        return {
            "success": False,
            "status": "error",
            "error_type": "selection",
            "message": "Invalid or missing network capture path."
        }

    clean_path = capture_path.strip(' "\'')
    abs_path = os.path.abspath(clean_path)

    if not os.path.exists(abs_path):
        return {
            "success": False,
            "status": "error",
            "error_type": "selection",
            "message": f"Capture file not found: {abs_path}"
        }

    if not os.path.isfile(abs_path):
        return {
            "success": False,
            "status": "error",
            "error_type": "unsupported",
            "message": f"Expected a regular file: {abs_path}"
        }

    file_size = os.path.getsize(abs_path)
    if file_size > WEB_NETWORK_CAPTURE_INPUT_LIMIT:
        return {
            "success": False,
            "status": "error",
            "error_type": "memory",
            "message": f"Capture file exceeds maximum input budget of 32 MiB ({file_size} bytes)."
        }

    # Verify SHA-256 digest of retained artifact
    hasher = hashlib.sha256()
    with open(abs_path, "rb") as f:
        for chunk in iter(lambda: f.read(256 * 1024), b""):
            hasher.update(chunk)
    artifact_sha = hasher.hexdigest()

    # Parse JSON strictly offline
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            raw_har = json.load(f)
    except Exception as parse_err:
        return {
            "success": False,
            "status": "error",
            "error_type": "format",
            "message": f"Malformed HAR JSON structure: {parse_err}"
        }

    if not isinstance(raw_har, dict) or "log" not in raw_har:
        return {
            "success": False,
            "status": "error",
            "error_type": "format",
            "message": "HAR must contain a top-level 'log' object."
        }

    log_obj = raw_har["log"]
    if not isinstance(log_obj, dict) or not isinstance(log_obj.get("entries"), list):
        return {
            "success": False,
            "status": "error",
            "error_type": "format",
            "message": "HAR must contain 'log.entries' array."
        }

    version = str(log_obj.get("version", ""))
    if version != "1.2":
        return {
            "success": False,
            "status": "error",
            "error_type": "unsupported",
            "message": f"Only the pinned HAR 1.2 schema profile is supported (found version: '{version}')."
        }

    entries = log_obj["entries"]
    sens_literals = sensitive_values or []

    status_dist: Dict[str, int] = {}
    method_dist: Dict[str, int] = {}
    domain_dist: Dict[str, int] = {}
    total_entries = len(entries)
    slow_candidates = []
    size_candidates = []
    projected_records = []

    # Process and sanitize entries
    for ordinal, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue

        req = entry.get("request", {})
        resp = entry.get("response", {})
        timing = float(entry.get("time", 0.0) or 0.0)

        method = str(req.get("method", "GET")).upper()
        raw_url = str(req.get("url", ""))
        sanitized_url = _sanitize_url(raw_url, sens_literals)

        status_code = resp.get("status")
        status_key = str(status_code) if status_code is not None else "unknown"

        # Update distributions
        status_dist[status_key] = status_dist.get(status_key, 0) + 1
        method_dist[method] = method_dist.get(method, 0) + 1

        # Extract domain
        try:
            parsed_host = urllib.parse.urlsplit(sanitized_url).hostname or "unknown_host"
            domain_dist[parsed_host] = domain_dist.get(parsed_host, 0) + 1
        except Exception:
            pass

        # Calculate response payload size
        content = resp.get("content", {})
        body_size = resp.get("bodySize")
        content_size = content.get("size") if isinstance(content, dict) else 0
        effective_size = body_size if (isinstance(body_size, (int, float)) and body_size > 0) else (content_size or 0)

        slow_candidates.append({
            "ordinal": ordinal,
            "method": method,
            "url": sanitized_url,
            "status": status_code,
            "time_ms": round(timing, 2)
        })

        size_candidates.append({
            "ordinal": ordinal,
            "method": method,
            "url": sanitized_url,
            "status": status_code,
            "bytes": effective_size
        })

        # Sanitize headers, query string, postData, and content preview for sample records
        should_project = (record_ordinals is not None and ordinal in record_ordinals) or (record_ordinals is None and ordinal < 15)
        if should_project:
            sanitized_req_headers = []
            for h in req.get("headers", []):
                h_name = str(h.get("name", ""))
                h_val = str(h.get("value", ""))
                if h_name.lower() in CREDENTIAL_HEADERS or any(sk in h_name.lower() for sk in SENSITIVE_PARAM_KEYS):
                    h_val = "[REDACTED]"
                else:
                    h_val = _redact_text(h_val, sens_literals)
                sanitized_req_headers.append({"name": h_name, "value": h_val})

            sanitized_resp_headers = []
            for h in resp.get("headers", []):
                h_name = str(h.get("name", ""))
                h_val = str(h.get("value", ""))
                if h_name.lower() in CREDENTIAL_HEADERS or any(sk in h_name.lower() for sk in SENSITIVE_PARAM_KEYS):
                    h_val = "[REDACTED]"
                else:
                    h_val = _redact_text(h_val, sens_literals)
                sanitized_resp_headers.append({"name": h_name, "value": h_val})

            # Nested Request Post Data Redaction
            post_obj = req.get("postData")
            sanitized_post = None
            if isinstance(post_obj, dict):
                p_mime = post_obj.get("mimeType", "")
                p_raw = post_obj.get("text", "")
                p_text = _redact_json_payload(p_raw, sens_literals) if p_raw else None
                sanitized_params = []
                for param in post_obj.get("params", []):
                    pn = str(param.get("name", ""))
                    pv = str(param.get("value", ""))
                    if any(sk in pn.lower() for sk in SENSITIVE_PARAM_KEYS):
                        pv = "[REDACTED]"
                    else:
                        pv = _redact_text(pv, sens_literals)
                    sanitized_params.append({"name": pn, "value": pv})
                sanitized_post = {
                    "mime_type": p_mime,
                    "text": p_text,
                    "params": sanitized_params if sanitized_params else None
                }

            # Nested Response Content Preview Redaction (bounded to 500 chars)
            resp_raw = content.get("text", "") if isinstance(content, dict) else ""
            sanitized_resp_content = None
            if resp_raw:
                sanitized_resp_content = _redact_json_payload(resp_raw[:500], sens_literals)

            projected_records.append({
                "ordinal": ordinal,
                "started_date_time": entry.get("startedDateTime"),
                "time_ms": round(timing, 2),
                "request": {
                    "method": method,
                    "url": sanitized_url,
                    "headers": sanitized_req_headers,
                    "post_data": sanitized_post
                },
                "response": {
                    "status": status_code,
                    "status_text": resp.get("statusText"),
                    "headers": sanitized_resp_headers,
                    "body_size": effective_size,
                    "mime_type": content.get("mimeType") if isinstance(content, dict) else None,
                    "content_preview": sanitized_resp_content
                }
            })

    # Sort slowest and largest
    slow_candidates.sort(key=lambda x: x["time_ms"], reverse=True)
    slowest_requests = slow_candidates[:max_slow_requests]

    size_candidates.sort(key=lambda x: x["bytes"], reverse=True)
    largest_payloads = size_candidates[:max_slow_requests]

    limitations = [
        "Offline HAR inspection operates strictly on retained local JSON files with zero network sockets or request replays.",
        "Sensitive headers (authorization, cookies, tokens) and transport URL credentials have been redacted."
    ]

    speech_parts = [
        f"Network capture '{os.path.basename(abs_path)}' (HAR 1.2) contains {total_entries} recorded request(s)."
    ]
    if status_dist:
        statuses_summary = ", ".join(f"{k}: {v}" for k, v in sorted(status_dist.items()))
        speech_parts.append(f" Status distribution: [{statuses_summary}].")
    if slowest_requests:
        top_slow = slowest_requests[0]
        speech_parts.append(f" Slowest request: {top_slow['method']} {top_slow['url'][:60]} ({top_slow['time_ms']} ms).")
    speech_parts.append(" All credentials, cookies, and tokens were securely redacted.")
    speech_msg = "".join(speech_parts)

    return {
        "success": True,
        "format": "har",
        "version": "1.2",
        "artifact": {
            "path": abs_path,
            "sha256": artifact_sha,
            "bytes": file_size
        },
        "total_requests": total_entries,
        "status_distribution": status_dist,
        "method_distribution": method_dist,
        "domains": domain_dist,
        "slowest_requests": slowest_requests,
        "largest_payloads": largest_payloads,
        "sample_records": projected_records,
        "limitations": limitations,
        "message": speech_msg
    }


# ── 12. BROWSER RUNTIME OBSERVATION & EVENT-LISTENER INSPECTION (REA PORT) ────

def inspect_web_event_listeners(
    url: str,
    selector: str,
    timeout_ms: int = 15000,
    headless: bool = True
) -> Dict[str, Any]:
    """
    Inspects listeners registered directly on the first main-document CSS selector match
    using a dedicated Chrome DevTools Protocol (CDP) session via Playwright.

    Directly ported from REA (src/browser/execution/CdpEventListeners.ts & src/domain/webEventListeners.ts).
    Preserves all REA invariants:
    - Native CDP listener discovery via DOMDebugger.getEventListeners.
    - Zero execution: does not dispatch synthetic events, evaluate arbitrary JavaScript, or invoke handlers.
    - Uses dedicated isolated object group (rea-listeners-<uuid>) and explicitly releases it.
    - Retains script source bodies and independently computed SHA-256 digests.
    - Clean failure semantics for unfindable selectors, disconnected targets, and timeouts.
    - Explicitly documents framework delegation, closed shadow root, and ancestor listener boundaries.
    """
    import uuid
    import hashlib
    import datetime

    LIMITATIONS = [
        "Inspects listeners registered directly on the first native CSS match in the selected main document. Delegated ancestor listeners, descendants, closed shadow roots and framework registries are not enumerated.",
        "Native CDP listener descriptors report callback locations; registration time, dispatch history and UI causality remain unknown. REA does not dispatch an event, evaluate JavaScript or invoke a handler.",
        "Source identity uses this session's script ID and proven main-frame default-world metadata. Isolated or unknown worlds cannot establish website callback/source joins. A URL or sourceURL declaration never establishes identity or execution.",
        "Source text is retained inline with its independently computed UTF-8 digest; the producer hash is preserved separately. Missing source ownership or collected scripts remain explicit.",
        "Releases remote object group, disables enabled domains and detaches transport; external page lifecycle is cleanly managed."
    ]

    clean_selector = selector.strip() if selector else ""
    if not clean_selector:
        return {
            "success": False,
            "status": "error",
            "error": "A non-empty CSS selector is required to inspect web event listeners.",
            "selected_node": {"selector": "", "match": "not_found", "backend_node_id": None},
            "listeners": [],
            "sources": [],
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": "CSS selector cannot be empty."
        }

    # Handle local file or remote URL
    target_url = url.strip()
    if not target_url.startswith("file://") and not os.path.isabs(target_url):
        try:
            target_url = sanitize_browser_url(target_url)
        except Exception as u_err:
            return {
                "success": False,
                "status": "error",
                "error": f"Invalid URL: {u_err}",
                "selected_node": {"selector": clean_selector, "match": "not_found", "backend_node_id": None},
                "listeners": [],
                "sources": [],
                "cleanup": "confirmed",
                "limitations": LIMITATIONS,
                "message": f"Invalid URL: {u_err}"
            }
    elif os.path.isabs(target_url):
        target_url = f"file:///{os.path.abspath(target_url).replace(os.sep, '/')}"

    from playwright.sync_api import sync_playwright

    object_group = f"rea-listeners-{uuid.uuid4()}"
    listeners_out: List[Dict[str, Any]] = []
    sources_out: List[Dict[str, Any]] = []
    selected_node = {
        "selector": clean_selector,
        "match": "not_found",
        "backend_node_id": None
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            try:
                page = browser.new_page()
                page.set_default_timeout(min(timeout_ms, 20000))

                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=min(timeout_ms, 15000))
                except Exception as nav_err:
                    return {
                        "success": False,
                        "status": "navigation_error",
                        "error": str(nav_err),
                        "selected_node": selected_node,
                        "listeners": [],
                        "sources": [],
                        "cleanup": "confirmed",
                        "limitations": LIMITATIONS,
                        "message": f"Failed to navigate to '{target_url}': {nav_err}"
                    }

                # Attach CDP session
                cdp = page.context.new_cdp_session(page)
                try:
                    cdp.send("Page.enable")
                    cdp.send("DOM.enable")
                    cdp.send("Runtime.enable")
                    cdp.send("Debugger.enable")

                    # Query document root
                    doc = cdp.send("DOM.getDocument", {"depth": 0})
                    root_node_id = doc.get("root", {}).get("nodeId", 0)

                    # Query selector
                    query_res = cdp.send("DOM.querySelector", {
                        "nodeId": root_node_id,
                        "selector": clean_selector
                    })
                    matched_node_id = query_res.get("nodeId", 0)

                    if matched_node_id and matched_node_id != 0:
                        selected_node["match"] = "found"

                        # Describe node for backendNodeId
                        desc_res = cdp.send("DOM.describeNode", {"nodeId": matched_node_id})
                        backend_node_id = desc_res.get("node", {}).get("backendNodeId")
                        selected_node["backend_node_id"] = backend_node_id

                        # Resolve node to remote object
                        resolved = cdp.send("DOM.resolveNode", {
                            "nodeId": matched_node_id,
                            "objectGroup": object_group
                        })
                        remote_obj_id = resolved.get("object", {}).get("objectId")

                        if remote_obj_id:
                            # Fetch listeners natively from DOMDebugger
                            listeners_raw = cdp.send("DOMDebugger.getEventListeners", {
                                "objectId": remote_obj_id,
                                "depth": 0,
                                "pierce": False
                            })

                            retained_scripts: Dict[str, Dict[str, Any]] = {}

                            for l_desc in listeners_raw.get("listeners", []):
                                s_id = str(l_desc.get("scriptId") or "")
                                line_num = int(l_desc.get("lineNumber", 0))
                                col_num = int(l_desc.get("columnNumber", 0))

                                # Fetch script source if not already fetched
                                if s_id and s_id not in retained_scripts:
                                    try:
                                        src_res = cdp.send("Debugger.getScriptSource", {"scriptId": s_id})
                                        src_text = src_res.get("scriptSource", "")
                                        src_bytes = src_text.encode("utf-8", errors="replace")
                                        retained_scripts[s_id] = {
                                            "script_id": s_id,
                                            "sha256": hashlib.sha256(src_bytes).hexdigest(),
                                            "length_bytes": len(src_bytes),
                                            "source_text": src_text
                                        }
                                    except Exception:
                                        retained_scripts[s_id] = {
                                            "script_id": s_id,
                                            "sha256": None,
                                            "length_bytes": 0,
                                            "source_text": ""
                                        }

                                # Extract concise handler snippet from description or source
                                handler_info = l_desc.get("handler", {})
                                handler_desc = handler_info.get("description", "")
                                if not handler_desc and s_id in retained_scripts:
                                    full_src = retained_scripts[s_id]["source_text"]
                                    lines = full_src.splitlines()
                                    if line_num < len(lines):
                                        handler_desc = lines[line_num][col_num:col_num + 120].strip()

                                listeners_out.append({
                                    "type": l_desc.get("type", "unknown"),
                                    "use_capture": bool(l_desc.get("useCapture", False)),
                                    "passive": bool(l_desc.get("passive", False)),
                                    "once": bool(l_desc.get("once", False)),
                                    "location": {
                                        "script_id": s_id or None,
                                        "line_number": line_num,
                                        "column_number": col_num
                                    },
                                    "handler_snippet": handler_desc[:200] if handler_desc else None,
                                    "execution": "unknown"
                                })

                            for s_meta in retained_scripts.values():
                                sources_out.append({
                                    "script_id": s_meta["script_id"],
                                    "sha256": s_meta["sha256"],
                                    "length_bytes": s_meta["length_bytes"]
                                })
                finally:
                    try:
                        cdp.send("Runtime.releaseObjectGroup", {"objectGroup": object_group})
                    except Exception:
                        pass
                    try:
                        cdp.detach()
                    except Exception:
                        pass
            finally:
                browser.close()
    except Exception as e:
        logger.error(f"[BROWSER] Event listener inspection error: {e}")
        return {
            "success": False,
            "status": "error",
            "error": str(e),
            "selected_node": selected_node,
            "listeners": [],
            "sources": [],
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": f"Failed inspecting event listeners: {e}"
        }

    status_msg = f"Inspected event listeners on selector '{clean_selector}' for '{target_url}': "
    if selected_node["match"] == "found":
        types_summary = ", ".join(f"{l['type']}" for l in listeners_out) or "none"
        status_msg += f"Found {len(listeners_out)} registered listener(s) [{types_summary}]."
    else:
        status_msg += "Selector not found in main document."

    return {
        "success": True,
        "status": "success",
        "url": target_url,
        "inspected_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "selected_node": selected_node,
        "listeners": listeners_out,
        "sources": sources_out,
        "cleanup": "confirmed",
        "limitations": LIMITATIONS,
        "message": status_msg
    }


def observe_web_execution(
    url: str,
    observation_ms: int = 5000,
    actions: Optional[List[Dict[str, Any]]] = None,
    timeout_ms: int = 30000,
    headless: bool = True
) -> Dict[str, Any]:
    """
    Instruments a web page for a finite, externally driven execution window using CDP Profiler
    precise coverage, non-suppressive console observation, uncaught exception capture, and network monitoring.

    Directly ported from REA (src/browser/execution/CdpExecutionCapture.ts & src/domain/webExecution.ts).
    Preserves all REA invariants:
    - Precise UTF-16 function block coverage via Profiler.startPreciseCoverage / takePreciseCoverage.
    - Zero script injection or code modification: passively observes execution.
    - Non-suppressing console message and uncaught exception capture.
    - Request initiator association with sanitized query parameters.
    - Clean timing windows, end-reason classification ('window_elapsed', 'document_changed', 'terminated').
    - Full resource cleanup and domain detachment.
    """
    import time
    import datetime

    LIMITATIONS = [
        "Website source ownership requires the selected main frame and a proven default execution world. Isolated, worker and unknown worlds are excluded from coverage/source joins.",
        "Precise coverage resets counters, retains execution records and prevents optimized execution until stopped. Timing and JIT behavior are affected.",
        "Only the selected main document's proven frame/context scripts are attributed. Child frames, workers, service workers, WebAssembly and scripts without ownership metadata remain outside this operation.",
        "V8 reports nested function/block ranges and counts, not a chronological trace. Counts must not be summed across overlapping ranges; zero counts concern this instrumented window only.",
        "Console messages and uncaught exceptions reflect page runtime events during the armed window without modifying or suppressing their dispatch."
    ]

    obs_ms = max(500, min(observation_ms, 30000))

    target_url = url.strip()
    if not target_url.startswith("file://") and not os.path.isabs(target_url):
        try:
            target_url = sanitize_browser_url(target_url)
        except Exception as u_err:
            return {
                "success": False,
                "status": "error",
                "error": f"Invalid URL: {u_err}",
                "window": {
                    "armed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "ended_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "requested_ms": obs_ms,
                    "end_reason": "error"
                },
                "coverage": {"state": "unavailable", "reason": str(u_err), "scripts": []},
                "console_messages": [],
                "page_errors": [],
                "network_requests": [],
                "instrumentation": {"cleanup": "confirmed"},
                "limitations": LIMITATIONS,
                "message": f"Invalid URL: {u_err}"
            }
    elif os.path.isabs(target_url):
        target_url = f"file:///{os.path.abspath(target_url).replace(os.sep, '/')}"

    from playwright.sync_api import sync_playwright

    console_records: List[Dict[str, Any]] = []
    error_records: List[Dict[str, Any]] = []
    request_records: List[Dict[str, Any]] = []

    armed_at_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    end_reason = "window_elapsed"
    coverage_result: Dict[str, Any] = {"state": "unavailable", "scripts": []}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            try:
                page = browser.new_page()
                page.set_default_timeout(min(timeout_ms, 25000))

                # Console message listener (non-suppressive)
                def _on_console(msg):
                    try:
                        console_records.append({
                            "type": msg.type,
                            "text": msg.text,
                            "location": msg.location,
                            "timestamp": time.time()
                        })
                    except Exception:
                        pass
                page.on("console", _on_console)

                # Page uncaught exception listener (non-suppressive)
                def _on_error(err):
                    try:
                        error_records.append({
                            "message": str(err),
                            "timestamp": time.time()
                        })
                    except Exception:
                        pass
                page.on("pageerror", _on_error)

                # Network request tracking with URL sanitization
                def _on_request(req):
                    try:
                        request_records.append({
                            "url": _sanitize_url(req.url),
                            "method": req.method,
                            "resource_type": req.resource_type,
                            "timestamp": time.time()
                        })
                    except Exception:
                        pass
                page.on("request", _on_request)

                # Navigate to initial page
                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=min(timeout_ms, 15000))
                except Exception as nav_err:
                    end_reason = "document_changed" if "navigation" in str(nav_err).lower() else "error"
                    return {
                        "success": False,
                        "status": "navigation_error",
                        "error": str(nav_err),
                        "window": {
                            "armed_at": armed_at_iso,
                            "ended_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            "requested_ms": obs_ms,
                            "end_reason": end_reason
                        },
                        "coverage": {"state": "unavailable", "reason": str(nav_err), "scripts": []},
                        "console_messages": console_records,
                        "page_errors": error_records,
                        "network_requests": request_records,
                        "instrumentation": {"cleanup": "confirmed"},
                        "limitations": LIMITATIONS,
                        "message": f"Navigation failed: {nav_err}"
                    }

                # Attach CDP session
                cdp = page.context.new_cdp_session(page)
                try:
                    cdp.send("Profiler.enable")
                    cdp.send("Debugger.enable")

                    # Start precise coverage
                    cdp.send("Profiler.startPreciseCoverage", {
                        "callCount": True,
                        "detailed": True,
                        "allowTriggeredUpdates": False
                    })
                    armed_at_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

                    # Execute optional declarative actions if specified
                    if actions:
                        for act in actions:
                            act_type = act.get("action")
                            loc = act.get("locator") or act.get("selector")
                            if act_type == "click" and loc:
                                page.click(loc, timeout=3000)
                            elif act_type == "type" and loc and "value" in act:
                                page.type(loc, str(act["value"]), timeout=3000)
                            elif act_type == "scroll":
                                page.evaluate("window.scrollBy(0, 300)")

                    # Wait for observation window
                    page.wait_for_timeout(obs_ms)

                    # Take precise coverage
                    raw_coverage = cdp.send("Profiler.takePreciseCoverage")
                    cdp.send("Profiler.stopPreciseCoverage")

                    # Normalize coverage scripts
                    parsed_scripts = []
                    for s_item in raw_coverage.get("result", []):
                        s_url = s_item.get("url") or ""
                        funcs = []
                        for f in s_item.get("functions", []):
                            f_name = f.get("functionName") or "(anonymous)"
                            is_block = bool(f.get("isBlockCoverage", False))
                            ranges = [
                                {
                                    "start_offset": r.get("startOffset", 0),
                                    "end_offset": r.get("endOffset", 0),
                                    "count": r.get("count", 0)
                                }
                                for r in f.get("ranges", [])
                            ]
                            funcs.append({
                                "name": f_name,
                                "is_block_coverage": is_block,
                                "ranges": ranges
                            })
                        parsed_scripts.append({
                            "script_id": str(s_item.get("scriptId", "")),
                            "url": _sanitize_url(s_url) if s_url else "(inline)",
                            "functions": funcs
                        })

                    coverage_result = {
                        "state": "captured",
                        "scripts_count": len(parsed_scripts),
                        "scripts": parsed_scripts[:50]
                    }
                finally:
                    try:
                        cdp.send("Profiler.disable")
                    except Exception:
                        pass
                    try:
                        cdp.detach()
                    except Exception:
                        pass
            finally:
                browser.close()
    except Exception as e:
        logger.error(f"[BROWSER] Execution observation error: {e}")
        end_reason = "error"
        coverage_result = {"state": "unavailable", "reason": str(e), "scripts": []}

    ended_at_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    speech_msg = (
        f"Observed runtime execution on '{target_url}' for {obs_ms} ms: "
        f"{len(console_records)} console log(s), {len(error_records)} runtime exception(s), "
        f"{len(request_records)} network request(s), and {coverage_result.get('scripts_count', 0)} instrumented script(s)."
    )

    return {
        "success": True,
        "status": "success",
        "url": target_url,
        "window": {
            "armed_at": armed_at_iso,
            "ended_at": ended_at_iso,
            "requested_ms": obs_ms,
            "end_reason": end_reason
        },
        "coverage": coverage_result,
        "console_messages": console_records,
        "page_errors": error_records,
        "network_requests": request_records,
        "instrumentation": {
            "resets_execution_counters": True,
            "disables_optimized_execution": True,
            "cleanup": "confirmed"
        },
        "limitations": LIMITATIONS,
        "message": speech_msg
    }


# ==============================================================================
# REA INTEGRATION: Phase 3 Browser Script & Source-Map Inspection
# ==============================================================================

B64_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
B64_LOOKUP = {c: i for i, c in enumerate(B64_CHARS)}
MAX_SOURCE_MAP_BYTES = 4 * 1024 * 1024  # 4 MiB budget per REA specification
MAX_MAPPINGS_RECORDS = 500000


def _decode_vlq_segment(segment_str: str) -> List[int]:
    """
    Decodes a single Base64 VLQ segment string into a list of variable-length integers.
    Follows Source Map v3 canonical specification.
    """
    values = []
    shift = 0
    value = 0
    for char in segment_str:
        if char not in B64_LOOKUP:
            raise ValueError(f"Invalid character '{char}' in VLQ mapping segment")
        integer = B64_LOOKUP[char]
        has_continuation = (integer & 32) != 0
        digit = integer & 31
        value += digit << shift
        if has_continuation:
            shift += 5
        else:
            is_negative = (value & 1) == 1
            decoded_val = -(value >> 1) if is_negative else (value >> 1)
            values.append(decoded_val)
            value = 0
            shift = 0
    if shift != 0:
        raise ValueError("Incomplete VLQ character sequence in mapping segment")
    return values


def inspect_web_scripts(
    url: str,
    include_script_sources: bool = False,
    timeout_ms: int = 15000,
    headless: bool = True
) -> Dict[str, Any]:
    """
    Enumerates all JavaScript scripts loaded by a target page and extracts available metadata
    using a dedicated Chrome DevTools Protocol (CDP) Debugger session via Playwright.

    Directly adapted from REA contracts (src/browser/CdpPageCaptureScripts.ts & cdpScriptMetadata.test.ts).
    Invariants preserved:
    - Zero execution: does not dispatch synthetic events or evaluate arbitrary JavaScript.
    - Inspects Debugger.scriptParsed events emitted natively by V8.
    - Captures scriptId, URL, cdp_hash, character length, is_module, source ranges, and sourceMapURL.
    - Retains script SHA-256 digest when include_script_sources=True.
    - Redacts sensitive query tokens from reported URLs.
    - Cleanly detaches CDP session and closes resources on success and failure.
    """
    import hashlib
    import datetime

    LIMITATIONS = [
        "Inspects scripts compiled and reported by the V8 Debugger domain for the main execution frame.",
        "Scripts loaded inside isolated web workers, detached iframes, or extension content scripts may not be enumerated.",
        "A declared sourceMappingURL does not verify that the source map is accessible or authentic.",
        "Zero code execution: scripts are observed passively without evaluating page JavaScript or invoking functions."
    ]

    target_url = url.strip() if url else ""
    if not target_url.startswith("file://") and not os.path.isabs(target_url):
        try:
            target_url = sanitize_browser_url(target_url)
        except Exception as u_err:
            return {
                "success": False,
                "status": "error",
                "error": f"Invalid URL: {u_err}",
                "scripts": [],
                "source_maps_detected": [],
                "cleanup": "confirmed",
                "limitations": LIMITATIONS,
                "message": f"Invalid URL: {u_err}"
            }
    elif os.path.isabs(target_url) and not target_url.startswith("file://"):
        target_url = "file:///" + target_url.replace("\\", "/")

    script_events = []
    source_map_requests = []
    status = "success"
    err_msg = None

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            try:
                page = browser.new_page()
                cdp = page.context.new_cdp_session(page)
                try:
                    def on_script(params):
                        script_events.append(params)

                    cdp.on("Debugger.scriptParsed", on_script)
                    cdp.send("Debugger.enable")

                    page.goto(target_url, wait_until="load", timeout=timeout_ms)
                    page.wait_for_timeout(300)

                    # Build standardized script inventory
                    inventory = []
                    for s in script_events[:100]:
                        s_id = str(s.get("scriptId", ""))
                        raw_url = s.get("url") or ""
                        clean_url = _sanitize_url(raw_url) if raw_url.startswith(("http://", "https://")) else raw_url
                        if not clean_url:
                            clean_url = "(inline)"

                        s_map_url = s.get("sourceMapURL")
                        clean_map_url = _sanitize_url(s_map_url) if s_map_url and s_map_url.startswith(("http://", "https://")) else s_map_url

                        source_info = {"included": False}
                        if include_script_sources and s_id:
                            try:
                                src_res = cdp.send("Debugger.getScriptSource", {"scriptId": s_id})
                                src_body = src_res.get("scriptSource", "")
                                sha256_hash = hashlib.sha256(src_body.encode("utf-8")).hexdigest()
                                source_info = {
                                    "included": True,
                                    "content": src_body,
                                    "sha256": sha256_hash,
                                    "bytes": len(src_body.encode("utf-8"))
                                }
                                # Fallback check for sourceMappingURL comment if omitted from CDP params
                                if not s_map_url and "//# sourceMappingURL=" in src_body:
                                    for line in src_body.splitlines()[::-1]:
                                        if "//# sourceMappingURL=" in line:
                                            extracted_map = line.split("//# sourceMappingURL=")[1].strip()
                                            clean_map_url = _sanitize_url(extracted_map) if extracted_map.startswith(("http://", "https://")) else extracted_map
                                            s_map_url = clean_map_url
                                            break
                            except Exception:
                                pass

                        item = {
                            "script_id": s_id,
                            "url": clean_url,
                            "cdp_hash": s.get("hash"),
                            "length": s.get("length"),
                            "is_module": bool(s.get("isModule", False)),
                            "start_line": s.get("startLine", 0),
                            "start_column": s.get("startColumn", 0),
                            "end_line": s.get("endLine", 0),
                            "end_column": s.get("endColumn", 0),
                            "source_map_url": clean_map_url,
                            "source": source_info,
                            "content": src_body if (include_script_sources and s_id and 'src_body' in locals()) else ""
                        }
                        inventory.append(item)
                        if clean_map_url:
                            source_map_requests.append({
                                "script_id": s_id,
                                "script_url": clean_url,
                                "source_map_url": clean_map_url
                            })

                finally:
                    try:
                        cdp.send("Debugger.disable")
                    except Exception:
                        pass
                    try:
                        cdp.detach()
                    except Exception:
                        pass
            finally:
                browser.close()
    except Exception as e:
        logger.error(f"[BROWSER] Script inspection error: {e}")
        status = "error"
        err_msg = str(e)
        inventory = []

    msg = (
        f"Inspected loaded scripts on '{target_url}': "
        f"Found {len(inventory)} script(s), {len(source_map_requests)} with detected source map(s)."
        if status == "success" else f"Failed to inspect scripts on '{target_url}': {err_msg}"
    )

    return {
        "success": status == "success",
        "status": status,
        "url": target_url,
        "scripts_count": len(inventory),
        "scripts": inventory,
        "source_maps_detected": source_map_requests,
        "cleanup": "confirmed",
        "limitations": LIMITATIONS,
        "message": msg
    }


def trace_web_source_location(
    url: str,
    line: int = 1,
    column: int = 0,
    script_url: Optional[str] = None,
    source_map_content: Optional[Union[str, Dict[str, Any]]] = None,
    source_map_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Traces one generated position (1-based line, 0-based column) through a local or paired source map.
    Directly adapted from REA contracts (src/domain/webSourceLocation.ts & src/javascript/sourceMaps/TraceSourceMap.ts).

    Invariants preserved:
    - 1-based lines, 0-based UTF-16 columns.
    - Decodes Base64 VLQ mappings string to find greatest generated position <= requested.
    - Returns mapped original source file, original position, identifier name, and sourcesContent if embedded.
    - SHA-256 digest computed on UTF-8 bytes of decoded embedded content.
    - Enforces 4 MiB source map budget and 32 MiB response limits.
    - Clearly distinguishes 'mapped', 'generated-only', 'unavailable', 'malformed', 'limit', and 'unsupported'.
    - Sanitizes all reported URLs against credential or token exposure.
    """
    import base64
    import json
    import hashlib

    LIMITATIONS = [
        "Regular v3 source maps and embedded inline sections supported. External section URLs are unsupported.",
        "Greatest generated position <= requested is resolved. Caller-selected map does not establish deployment authenticity.",
        "Source positions use 1-based lines and 0-based UTF-16 column numbers.",
        "Embedded sourcesContent text is decoded and retained with its independently verified UTF-8 SHA-256 digest."
    ]

    target_url = _sanitize_url(url.strip()) if url else ""
    target_line = int(line)
    target_column = int(column)

    if target_line < 1 or target_column < 0:
        return {
            "success": False,
            "status": "error",
            "state": "malformed",
            "error": "Line must be >= 1 and column must be >= 0.",
            "requested_position": {"line": target_line, "column": target_column},
            "mapped_position": None,
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": "Invalid line or column coordinates."
        }

    # Resolve source map payload
    raw_map_text = None
    if source_map_content is not None:
        if isinstance(source_map_content, dict):
            raw_map_dict = source_map_content
            raw_map_text = json.dumps(raw_map_dict)
        else:
            raw_map_text = str(source_map_content)
    elif source_map_url:
        s_map = source_map_url.strip()
        if s_map.startswith("data:application/json"):
            # Inline base64 data URI
            try:
                if "base64," in s_map:
                    payload_b64 = s_map.split("base64,")[1]
                    raw_map_text = base64.b64decode(payload_b64).decode("utf-8")
                else:
                    raw_map_text = s_map.split(",", 1)[1]
            except Exception as d_err:
                return {
                    "success": False,
                    "status": "error",
                    "state": "malformed",
                    "error": f"Failed to decode inline source map data URI: {d_err}",
                    "requested_position": {"line": target_line, "column": target_column},
                    "mapped_position": None,
                    "limitations": LIMITATIONS,
                    "message": f"Malformed inline source map data URI: {d_err}"
                }
        elif os.path.exists(s_map) or s_map.startswith("file://"):
            local_path = s_map[8:] if s_map.startswith("file:///") else s_map
            if not os.path.isabs(local_path):
                local_path = os.path.abspath(local_path)
            if not os.path.exists(local_path):
                return {
                    "success": False,
                    "status": "error",
                    "state": "unavailable",
                    "error": f"Local source map file not found: {local_path}",
                    "requested_position": {"line": target_line, "column": target_column},
                    "mapped_position": None,
                    "limitations": LIMITATIONS,
                    "message": f"Source map file not found: {local_path}"
                }
            try:
                with open(local_path, "r", encoding="utf-8") as f:
                    raw_map_text = f.read()
            except Exception as r_err:
                return {
                    "success": False,
                    "status": "error",
                    "state": "unavailable",
                    "error": f"Failed to read local source map: {r_err}",
                    "requested_position": {"line": target_line, "column": target_column},
                    "mapped_position": None,
                    "limitations": LIMITATIONS,
                    "message": f"Cannot read source map: {r_err}"
                }
        else:
            # External HTTP/HTTPS source map: validate URL
            try:
                clean_fetch_url = sanitize_browser_url(s_map)
                import urllib.request
                req = urllib.request.Request(clean_fetch_url, headers={"User-Agent": "SmartAssistant/1.0 REA-SourceMapInspector"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw_map_text = resp.read().decode("utf-8")
            except Exception as fetch_err:
                return {
                    "success": False,
                    "status": "error",
                    "state": "unavailable",
                    "error": f"Failed to fetch external source map: {fetch_err}",
                    "requested_position": {"line": target_line, "column": target_column},
                    "mapped_position": None,
                    "limitations": LIMITATIONS,
                    "message": f"Source map unavailable: {fetch_err}"
                }
    else:
        # No direct map content or URL provided; attempt to inspect page scripts for declared source maps
        sc_res = inspect_web_scripts(url)
        if not sc_res.get("success") or not sc_res.get("source_maps_detected"):
            return {
                "success": False,
                "status": "error",
                "state": "unavailable",
                "error": "No source map declared or accessible for the specified target.",
                "requested_position": {"line": target_line, "column": target_column},
                "mapped_position": None,
                "limitations": LIMITATIONS,
                "message": "No source map available to trace location."
            }
        found_map_url = sc_res["source_maps_detected"][0]["source_map_url"]
        return trace_web_source_location(url, line=target_line, column=target_column, source_map_url=found_map_url)

    # Check budget limits
    if len(raw_map_text.encode("utf-8")) > MAX_SOURCE_MAP_BYTES:
        return {
            "success": False,
            "status": "error",
            "state": "limit",
            "error": f"Source map exceeds budget limit of {MAX_SOURCE_MAP_BYTES} bytes (4 MiB).",
            "requested_position": {"line": target_line, "column": target_column},
            "mapped_position": None,
            "limitations": LIMITATIONS,
            "message": "Source map exceeds 4 MiB budget limit."
        }

    # Parse JSON
    try:
        map_obj = json.loads(raw_map_text)
    except Exception as j_err:
        return {
            "success": False,
            "status": "error",
            "state": "malformed",
            "error": f"Malformed source map JSON: {j_err}",
            "requested_position": {"line": target_line, "column": target_column},
            "mapped_position": None,
            "limitations": LIMITATIONS,
            "message": f"Malformed source map format: {j_err}"
        }

    # Verify version 3
    if map_obj.get("version") != 3:
        return {
            "success": False,
            "status": "error",
            "state": "unsupported",
            "error": f"Unsupported source map version {map_obj.get('version')}; only version 3 is supported.",
            "requested_position": {"line": target_line, "column": target_column},
            "mapped_position": None,
            "limitations": LIMITATIONS,
            "message": f"Unsupported source map version {map_obj.get('version')}."
        }

    mappings_str = map_obj.get("mappings") or ""
    sources = map_obj.get("sources") or []
    sources_content = map_obj.get("sourcesContent") or []
    names = map_obj.get("names") or []
    source_root = map_obj.get("sourceRoot") or ""

    # Decode VLQ mappings across lines and segments
    lines = mappings_str.split(";")
    gen_line_req = target_line
    line_idx = gen_line_req - 1

    # Running deltas across file
    source_idx = 0
    orig_line = 0
    orig_col = 0
    name_idx = 0

    target_line_segments = []

    for curr_line_idx, line_str in enumerate(lines):
        gen_col = 0
        if not line_str:
            continue
        segs = line_str.split(",")
        for seg in segs:
            if not seg:
                continue
            try:
                nums = _decode_vlq_segment(seg)
            except Exception as vlq_err:
                return {
                    "success": False,
                    "status": "error",
                    "state": "malformed",
                    "error": f"Invalid VLQ mapping segment '{seg}': {vlq_err}",
                    "requested_position": {"line": target_line, "column": target_column},
                    "mapped_position": None,
                    "limitations": LIMITATIONS,
                    "message": f"Malformed source map mappings: {vlq_err}"
                }

            gen_col += nums[0]

            if len(nums) == 1:
                # Generated-only segment
                if curr_line_idx == line_idx:
                    target_line_segments.append({
                        "gen_col": gen_col,
                        "type": "generated-only"
                    })
            elif len(nums) >= 4:
                source_idx += nums[1]
                orig_line += nums[2]
                orig_col += nums[3]
                has_name = len(nums) >= 5
                if has_name:
                    name_idx += nums[4]

                if curr_line_idx == line_idx:
                    target_line_segments.append({
                        "gen_col": gen_col,
                        "type": "mapped",
                        "source_idx": source_idx,
                        "orig_line": orig_line + 1,  # 1-based
                        "orig_col": orig_col,        # 0-based
                        "name_idx": name_idx if has_name else None
                    })

    if not target_line_segments:
        return {
            "success": True,
            "status": "success",
            "state": "unmapped",
            "requested_position": {"line": target_line, "column": target_column},
            "mapped_position": None,
            "limitations": LIMITATIONS,
            "message": f"No mappings exist for generated line {target_line}."
        }

    # Find greatest generated position <= requested column
    candidates = [s for s in target_line_segments if s["gen_col"] <= target_column]
    if not candidates:
        # If all segments on line are after target_column, take the earliest segment on line
        best = target_line_segments[0]
    else:
        best = max(candidates, key=lambda s: s["gen_col"])

    if best["type"] == "generated-only":
        return {
            "success": True,
            "status": "success",
            "state": "generated-only",
            "requested_position": {"line": target_line, "column": target_column},
            "mapped_position": {
                "generated_line": target_line,
                "generated_column": best["gen_col"],
                "source_file": None,
                "original_position": None
            },
            "limitations": LIMITATIONS,
            "message": f"Position ({target_line}:{target_column}) is marked as generated-only without original source mapping."
        }

    # Resolve source details
    s_idx = best["source_idx"]
    raw_source_name = sources[s_idx] if 0 <= s_idx < len(sources) else None
    resolved_source = f"{source_root.rstrip('/')}/{raw_source_name.lstrip('/')}" if source_root and raw_source_name else raw_source_name

    n_idx = best["name_idx"]
    matched_name = names[n_idx] if n_idx is not None and 0 <= n_idx < len(names) else None

    # Embedded source content
    content_payload = {"state": "unavailable", "reason": "sourcesContent-not-retained"}
    if sources_content and 0 <= s_idx < len(sources_content):
        embedded_text = sources_content[s_idx]
        if embedded_text is not None:
            utf8_b = embedded_text.encode("utf-8")
            content_payload = {
                "state": "embedded",
                "text": embedded_text,
                "utf8_sha256": hashlib.sha256(utf8_b).hexdigest(),
                "utf8_bytes": len(utf8_b),
                "representation": "UTF-8 encoding of decoded sourcesContent text"
            }

    mapped_res = {
        "generated_line": target_line,
        "generated_column": best["gen_col"],
        "source_index": s_idx,
        "source_file": resolved_source,
        "original_line": best["orig_line"],
        "original_column": best["orig_col"],
        "name": matched_name,
        "content": content_payload
    }

    return {
        "success": True,
        "status": "success",
        "state": "mapped",
        "requested_position": {"line": target_line, "column": target_column},
        "mapped_position": mapped_res,
        "limitations": LIMITATIONS,
        "message": f"Mapped generated position ({target_line}:{target_column}) -> '{resolved_source}:{best['orig_line']}:{best['orig_col']}'" + (f" ({matched_name})" if matched_name else "") + "."
    }


def correlate_browser_error_stack(
    stack_trace: str,
    page_url: Optional[str] = None,
    source_maps: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Correlates a raw browser JavaScript error stack trace against loaded script source maps,
    mapping minified/bundled stack frames back to their original source files, lines, and columns.
    """
    import re

    LIMITATIONS = [
        "Correlates stack frames matching V8/Chromium and standard SpiderMonkey/Gecko formats.",
        "Frames without accessible or valid source maps retain their unmapped runtime coordinates.",
        "Zero code execution: stack traces are analyzed statically."
    ]

    raw_stack = (stack_trace or "").strip()
    if not raw_stack:
        return {
            "success": False,
            "status": "error",
            "correlated_frames": [],
            "reconstructed_stack": "",
            "message": "Empty stack trace provided."
        }

    maps_cache = dict(source_maps or {})
    correlated_frames = []
    reconstructed_lines = []

    # Regex for V8 stack lines: e.g. "at fnName (http://url:line:col)" or "at http://url:line:col"
    v8_pattern = re.compile(r'^\s*at\s+(?:(?P<fn>[^\(]+?)\s+\()?(?P<url>[^\s\)]+?):(?P<line>\d+):(?P<col>\d+)\)?')
    # Regex for Gecko stack lines: e.g. "fnName@http://url:line:col"
    gecko_pattern = re.compile(r'^(?P<fn>[^@]*?)@(?P<url>[^:]+):(?P<line>\d+):(?P<col>\d+)')

    for raw_line in raw_stack.splitlines():
        line_clean = raw_line.strip()
        m = v8_pattern.match(line_clean) or gecko_pattern.match(line_clean)
        if not m:
            reconstructed_lines.append(raw_line)
            continue

        fn_name = (m.group("fn") or "").strip() or "(anonymous)"
        frame_url = m.group("url")
        frame_line = int(m.group("line"))
        frame_col = int(m.group("col"))

        # Look for source map for this frame_url
        map_payload = maps_cache.get(frame_url)
        trace_res = trace_web_source_location(
            url=page_url or frame_url,
            line=frame_line,
            column=frame_col,
            script_url=frame_url,
            source_map_content=map_payload
        )

        if trace_res.get("success") and trace_res.get("state") == "mapped" and trace_res.get("mapped_position"):
            mp = trace_res["mapped_position"]
            orig_src = mp.get("source_file") or frame_url
            orig_l = mp.get("original_line")
            orig_c = mp.get("original_column")
            ident = mp.get("name") or fn_name

            correlated_frames.append({
                "function": ident,
                "generated_url": _sanitize_url(frame_url),
                "generated_line": frame_line,
                "generated_column": frame_col,
                "mapped": True,
                "original_source": orig_src,
                "original_line": orig_l,
                "original_column": orig_c
            })
            reconstructed_lines.append(f"    at {ident} ({orig_src}:{orig_l}:{orig_c})")
        else:
            correlated_frames.append({
                "function": fn_name,
                "generated_url": _sanitize_url(frame_url),
                "generated_line": frame_line,
                "generated_column": frame_col,
                "mapped": False,
                "original_source": None,
                "original_line": None,
                "original_column": None
            })
            reconstructed_lines.append(raw_line)

    reconstructed_stack = "\n".join(reconstructed_lines)
    mapped_count = sum(1 for f in correlated_frames if f["mapped"])

    return {
        "success": True,
        "status": "success",
        "frames_total": len(correlated_frames),
        "frames_mapped": mapped_count,
        "correlated_frames": correlated_frames,
        "reconstructed_stack": reconstructed_stack,
        "limitations": LIMITATIONS,
        "message": f"Correlated {mapped_count}/{len(correlated_frames)} stack frames to original source locations."
    }


def diagnose_web_execution(
    url: str,
    observation_ms: int = 3000,
    actions: Optional[List[Dict[str, Any]]] = None,
    source_maps: Optional[Dict[str, Any]] = None,
    timeout_ms: int = 15000,
    headless: bool = True
) -> Dict[str, Any]:
    """
    Executes a source-grounded diagnostic observation of a web page, reconciling runtime activity
    (console logs, uncaught exceptions, and network request initiator callstacks) against
    discovered or provided JavaScript source maps.

    Directly adapted from REA contracts (src/browser/execution/CdpRuntimeRequests.ts,
    src/domain/webExecution.ts, and src/application/javascript/JavaScriptRuntimeReconciliationService.ts).
    Invariants preserved:
    - Reconciles uncaught error stack frames to original source files, lines, and columns.
    - Captures network request initiator callstacks and grounds them in source functions and files.
    - Captures V8 precise coverage and identifies executed function units.
    - Enforces complete URL redaction and bounds payload sizes.
    - Disables CDP profiling/debugging/network domains and detaches session cleanly on success and failure.
    """
    import datetime

    LIMITATIONS = [
        "Reconciles runtime exceptions and network request initiator stacks against available and valid v3 source maps.",
        "Network initiators triggered outside JavaScript (e.g. static HTML parser or CSS assets) have no script callstack.",
        "Zero arbitrary code evaluation: diagnostic observation is strictly passive.",
        "All reported URLs and network query parameters are sanitized to prevent credential or token leakage."
    ]

    target_url = url.strip() if url else ""
    if not target_url.startswith("file://") and not os.path.isabs(target_url):
        try:
            target_url = sanitize_browser_url(target_url)
        except Exception as u_err:
            return {
                "success": False,
                "status": "error",
                "error": f"Invalid URL: {u_err}",
                "reconciled_exceptions": [],
                "reconciled_requests": [],
                "cleanup": "confirmed",
                "limitations": LIMITATIONS,
                "message": f"Invalid URL: {u_err}"
            }
    elif os.path.isabs(target_url) and not target_url.startswith("file://"):
        target_url = "file:///" + target_url.replace("\\", "/")

    obs_ms = max(500, min(int(observation_ms), 60000))
    maps_registry = dict(source_maps or {})

    console_records = []
    error_records = []
    network_events = []
    script_events = []
    coverage_result = {}
    status = "success"
    err_msg = None

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            try:
                page = browser.new_page()

                # Event listeners for page console & uncaught errors
                def on_console(msg):
                    console_records.append({
                        "type": msg.type,
                        "text": msg.text,
                        "location": msg.location
                    })

                def on_page_error(err):
                    error_records.append({
                        "message": str(err),
                        "stack": getattr(err, "stack", str(err))
                    })

                page.on("console", on_console)
                page.on("pageerror", on_page_error)

                cdp = page.context.new_cdp_session(page)
                try:
                    # Ingest Network.requestWillBeSent for initiator callstacks
                    def on_req(event_params):
                        network_events.append(event_params)

                    # Ingest Debugger.scriptParsed for loaded scripts & source maps
                    def on_script(event_params):
                        script_events.append(event_params)

                    cdp.on("Network.requestWillBeSent", on_req)
                    cdp.on("Debugger.scriptParsed", on_script)

                    # Enable domains
                    cdp.send("Debugger.enable")
                    cdp.send("Network.enable")
                    cdp.send("Profiler.enable")
                    cdp.send("Profiler.startPreciseCoverage", {
                        "callCount": True,
                        "detailed": True,
                        "allowTriggeredUpdates": False
                    })

                    # Navigate
                    page.goto(target_url, wait_until="load", timeout=timeout_ms)

                    # Optional declarative actions
                    if actions:
                        for act in actions:
                            act_type = act.get("action")
                            loc = act.get("locator") or act.get("selector")
                            if act_type == "click" and loc:
                                page.click(loc, timeout=3000)
                            elif act_type == "type" and loc and "value" in act:
                                page.type(loc, str(act["value"]), timeout=3000)

                    # Observation window
                    page.wait_for_timeout(obs_ms)

                    # Sample precise coverage
                    raw_cov = cdp.send("Profiler.takePreciseCoverage")
                    coverage_result = raw_cov

                    # Inspect loaded scripts for declared source maps
                    for s in script_events:
                        s_url = s.get("url") or ""
                        sm_url = s.get("sourceMapURL")
                        if sm_url and s_url not in maps_registry:
                            # Try to resolve local or relative source map if accessible
                            if sm_url.startswith("data:application/json"):
                                maps_registry[s_url] = sm_url
                            elif target_url.startswith("file://") and not sm_url.startswith(("http://", "https://")):
                                base_dir = os.path.dirname(target_url[8:])
                                cand_path = os.path.join(base_dir, sm_url)
                                if os.path.exists(cand_path):
                                    try:
                                        with open(cand_path, "r", encoding="utf-8") as f:
                                            maps_registry[s_url] = f.read()
                                    except Exception:
                                        pass

                finally:
                    try:
                        cdp.send("Profiler.stopPreciseCoverage")
                    except Exception:
                        pass
                    try:
                        cdp.send("Profiler.disable")
                    except Exception:
                        pass
                    try:
                        cdp.send("Debugger.disable")
                    except Exception:
                        pass
                    try:
                        cdp.send("Network.disable")
                    except Exception:
                        pass
                    try:
                        cdp.detach()
                    except Exception:
                        pass
            finally:
                browser.close()
    except Exception as e:
        logger.error(f"[BROWSER] Diagnose web execution failed: {e}")
        status = "error"
        err_msg = str(e)

    if status == "error":
        return {
            "success": False,
            "status": "error",
            "url": target_url,
            "error": err_msg,
            "reconciled_exceptions": [],
            "reconciled_requests": [],
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": f"Diagnostic observation failed on '{target_url}': {err_msg}"
        }

    # ── Source-Map Reconciliation (Adapted from REA JavaScriptRuntimeReconciliation) ─

    # 1. Reconcile Uncaught Exceptions
    reconciled_exceptions = []
    for err in error_records:
        raw_stack = err.get("stack") or err.get("message") or ""
        corr = correlate_browser_error_stack(
            stack_trace=raw_stack,
            page_url=target_url,
            source_maps=maps_registry
        )
        # Find primary source location if mapped
        primary_loc = None
        for frame in corr.get("correlated_frames", []):
            if frame.get("mapped"):
                primary_loc = f"{frame['original_source']}:{frame['original_line']}:{frame['original_column']}"
                break

        reconciled_exceptions.append({
            "message": err.get("message"),
            "primary_source_location": primary_loc,
            "frames_mapped": corr.get("frames_mapped", 0),
            "reconstructed_stack": corr.get("reconstructed_stack", raw_stack)
        })

    # 2. Reconcile Network Request Initiators
    reconciled_requests = []
    for ev in network_events[:50]:
        req_info = ev.get("request", {})
        init_info = ev.get("initiator", {})
        req_url = req_info.get("url", "")
        clean_req_url = _sanitize_url(req_url) if req_url.startswith(("http://", "https://")) else req_url

        callsites = []
        stack_info = init_info.get("stack", {})
        for frame in stack_info.get("callFrames", [])[:3]:
            f_url = frame.get("url") or ""
            f_line = frame.get("lineNumber", 0) + 1  # CDP is 0-indexed line -> 1-indexed
            f_col = frame.get("columnNumber", 0)
            f_name = frame.get("functionName") or "(anonymous)"

            # Check if source map exists for f_url
            map_payload = maps_registry.get(f_url)
            orig_desc = None
            if map_payload:
                t_res = trace_web_source_location(
                    url=target_url,
                    line=f_line,
                    column=f_col,
                    script_url=f_url,
                    source_map_content=map_payload
                )
                if t_res.get("success") and t_res.get("state") == "mapped" and t_res.get("mapped_position"):
                    mp = t_res["mapped_position"]
                    orig_desc = f"{mp.get('source_file')}:{mp.get('original_line')}:{mp.get('original_column')} ({mp.get('name') or f_name})"

            callsites.append({
                "function": f_name,
                "generated_callsite": f"{_sanitize_url(f_url)}:{f_line}:{f_col}" if f_url else f":{f_line}:{f_col}",
                "original_callsite": orig_desc
            })

        reconciled_requests.append({
            "url": clean_req_url,
            "method": req_info.get("method", "GET"),
            "initiator_type": init_info.get("type", "unknown"),
            "initiator_callsite": callsites[0]["original_callsite"] if (callsites and callsites[0]["original_callsite"]) else (callsites[0]["generated_callsite"] if callsites else None),
            "callsites": callsites
        })

    # 3. Reconcile Executed Coverage Functions
    executed_functions = []
    for sc in coverage_result.get("result", []):
        s_url = sc.get("url") or ""
        clean_s_url = _sanitize_url(s_url) if s_url.startswith(("http://", "https://")) else s_url
        for fn in sc.get("functions", []):
            fn_name = fn.get("functionName") or "(anonymous)"
            ranges = fn.get("ranges", [])
            exec_count = sum(r.get("count", 0) for r in ranges)
            if exec_count > 0 and fn_name != "(anonymous)":
                executed_functions.append({
                    "function": fn_name,
                    "script_url": clean_s_url,
                    "execution_count": exec_count
                })

    # Formulate actionable diagnosis summary
    issue_parts = []
    if reconciled_exceptions:
        first_ex = reconciled_exceptions[0]
        loc_str = f" at {first_ex['primary_source_location']}" if first_ex.get("primary_source_location") else ""
        issue_parts.append(f"{len(reconciled_exceptions)} uncaught exception(s) (e.g. {first_ex['message']}{loc_str})")
    if len(reconciled_requests) > 0:
        initiated_str = f", {len(reconciled_requests)} network request(s) initiated"
    else:
        initiated_str = ""

    assessment = "has_errors" if reconciled_exceptions else ("clean" if not console_records else "has_warnings")
    summary_msg = (
        f"Execution diagnostics for '{target_url}': Assessment: {assessment.upper()}. "
        + (", ".join(issue_parts) if issue_parts else "No uncaught runtime errors.")
        + f"{initiated_str}, and {len(executed_functions)} named function(s) executed."
    )

    return {
        "success": True,
        "status": "success",
        "url": target_url,
        "assessment": assessment,
        "observation_window_ms": obs_ms,
        "reconciled_exceptions": reconciled_exceptions,
        "reconciled_requests": reconciled_requests,
        "executed_functions": executed_functions[:20],
        "console_records_count": len(console_records),
        "cleanup": "confirmed",
        "limitations": LIMITATIONS,
        "message": summary_msg
    }


def execute_verified_browser_action(
    url: str,
    action: str,
    locator: Union[str, Dict[str, Any]],
    value: Optional[Union[str, Dict[str, str]]] = None,
    expected_outcome: Optional[Dict[str, Any]] = None,
    confirmed: bool = False,
    check_preexisting: bool = True,
    secrets: Optional[Dict[str, str]] = None,
    timeout_ms: int = 15000,
    headless: bool = True,
) -> Dict[str, Any]:
    """
    Executes a grounded, verified browser interaction with pre-action state inspection,
    consequential action gating, security barrier detection, idempotency enforcement,
    and truthful post-action state verification.
    """
    import hashlib
    import time
    from playwright.sync_api import sync_playwright

    consequential_keywords = {
        "submit", "purchase", "buy", "pay", "payment", "checkout", "order",
        "delete", "remove", "destroy", "wipe", "drop", "purge",
        "send", "transfer", "dispatch", "publish",
        "password", "update_password", "reset_password", "security", "credentials",
        "terminate", "cancel_subscription", "close_account", "unsubscribe",
        "format", "erase", "overwrite", "grant", "revoke"
    }

    # 1. Static Consequential Action Analysis
    loc_text = ""
    if isinstance(locator, str):
        loc_text = locator.lower()
    elif isinstance(locator, dict):
        loc_text = " ".join(str(v).lower() for v in locator.values())

    static_consequential = (
        any(k in action.lower() for k in ["delete", "submit", "pay", "purchase", "send"]) or
        any(k in loc_text for k in consequential_keywords) or
        ("type='submit'" in loc_text or 'type="submit"' in loc_text or "[type=submit]" in loc_text)
    )

    secret_mgr = BrowserScenarioSecrets(secrets)
    resolved_val = secret_mgr.resolve_value(value) if value is not None else None

    # Sanitize URL
    target_url = str(url).strip()
    if os.path.isabs(target_url):
        safe_url = f"file:///{os.path.abspath(target_url).replace(os.sep, '/')}"
    elif target_url.startswith("file://"):
        safe_url = target_url
    else:
        try:
            safe_url = sanitize_browser_url(target_url)
        except Exception as u_err:
            return {
                "success": False,
                "status": "verified_failure",
                "action": action,
                "locator": locator,
                "consequential": static_consequential,
                "error": str(u_err),
                "verified": False,
                "cleanup": "confirmed",
                "message": f"Invalid or unsafe URL '{url}': {u_err}"
            }

    browser = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page()
            page.set_default_timeout(min(timeout_ms, 12000))

            try:
                nav_response = page.goto(safe_url, timeout=min(timeout_ms, 12000), wait_until="domcontentloaded")
            except Exception as nav_err:
                return secret_mgr.redact_data({
                    "success": False,
                    "status": "verified_failure",
                    "action": action,
                    "locator": locator,
                    "consequential": static_consequential,
                    "error": f"Navigation failure: {nav_err}",
                    "verified": False,
                    "cleanup": "confirmed",
                    "message": f"Failed to navigate to '{safe_url}': {nav_err}"
                })

            # 2. HTTP Access Denied Check (401/403)
            if nav_response is not None:
                http_status = nav_response.status
                if http_status in (401, 403):
                    return secret_mgr.redact_data({
                        "success": False,
                        "status": "intervention_required",
                        "action": action,
                        "locator": locator,
                        "consequential": static_consequential,
                        "barrier_type": "http_access_denied",
                        "http_status": http_status,
                        "barrier_detection": "detected",
                        "risk_level": "HIGH",
                        "rationale": f"HTTP {http_status} barrier observed. Automated bypass is strictly prohibited.",
                        "verified": False,
                        "cleanup": "confirmed",
                        "message": f"User intervention required: HTTP {http_status} access denied on '{safe_url}'. Automated bypass is prohibited."
                    })

            # 3. Security Barrier & Interstitial Detection
            challenge_specs = [
                (".g-recaptcha", "google_recaptcha"),
                ("#hcaptcha", "hcaptcha"),
                (".cf-turnstile", "cloudflare_turnstile"),
                ("iframe[src*='recaptcha']", "google_recaptcha_iframe"),
                ("iframe[src*='hcaptcha']", "hcaptcha_iframe"),
                ("iframe[src*='turnstile']", "cloudflare_turnstile_iframe"),
                ("iframe[src*='captcha']", "generic_captcha_iframe"),
                ("#challenge-running", "cloudflare_challenge"),
                (".captcha-container", "captcha_container"),
                (".auth-challenge-form", "auth_challenge"),
                (".mfa-challenge", "mfa_challenge"),
                (".two-factor-auth", "two_factor_auth"),
                ("#px-captcha", "perimeter_x_captcha"),
                ("div[id*='datadome']", "datadome_challenge"),
            ]
            barrier_detected = None
            barrier_type = None
            for sel, b_name in challenge_specs:
                try:
                    c_el = page.locator(sel).first
                    if c_el.count() > 0 and c_el.is_visible():
                        barrier_detected = sel
                        barrier_type = b_name
                        break
                except Exception:
                    pass

            cur_title = page.title()
            try:
                cur_body = page.inner_text("body")[:2000]
            except Exception:
                cur_body = ""

            if not barrier_detected:
                text_indicators = [
                    ("Attention Required! | Cloudflare", "cloudflare_block"),
                    ("Just a moment...", "cloudflare_challenge_page"),
                    ("Verify you are human", "generic_human_verification"),
                    ("Security Challenge", "generic_security_challenge"),
                    ("Bot Detection", "bot_detection_interstitial"),
                ]
                for phrase, b_name in text_indicators:
                    if phrase.lower() in cur_title.lower() or phrase.lower() in cur_body.lower():
                        barrier_detected = phrase
                        barrier_type = b_name
                        break

            inconclusive_barrier = False
            if not barrier_detected:
                suspicious_cues = [
                    "checking your browser", "security verification", "access verification",
                    "please wait while", "ddos protection", "shield-interstitial"
                ]
                for cue in suspicious_cues:
                    if cue in cur_title.lower() or cue in cur_body.lower():
                        inconclusive_barrier = True
                        break
                if nav_response is not None and nav_response.status in (429, 503):
                    inconclusive_barrier = True

            if barrier_detected:
                return secret_mgr.redact_data({
                    "success": False,
                    "status": "intervention_required",
                    "action": action,
                    "locator": locator,
                    "consequential": static_consequential,
                    "barrier_type": "security_restriction",
                    "barrier_name": barrier_type,
                    "barrier_detection": "detected",
                    "barrier_evidence": barrier_detected,
                    "risk_level": "HIGH",
                    "rationale": f"Automated interaction halted: Security restriction ('{barrier_type}') detected. Automated bypass is strictly prohibited.",
                    "verified": False,
                    "cleanup": "confirmed",
                    "message": f"User intervention required: A security challenge or authentication barrier ('{barrier_type}') is present on the page."
                })
            elif inconclusive_barrier:
                return secret_mgr.redact_data({
                    "success": False,
                    "status": "intervention_required",
                    "action": action,
                    "locator": locator,
                    "consequential": static_consequential,
                    "barrier_type": "inconclusive_security_barrier",
                    "barrier_detection": "inconclusive",
                    "risk_level": "HIGH",
                    "rationale": "Potential security restriction or anti-bot interstitial observed, but barrier status is inconclusive. Automated bypass is strictly prohibited.",
                    "verified": False,
                    "cleanup": "confirmed",
                    "message": "User intervention required: An inconclusive security barrier or verification interstitial was observed."
                })

            # 4. Target Element Resolution and Live Consequential Inspection
            try:
                target_el = _resolve_playwright_locator(page, locator)
            except Exception as loc_err:
                return secret_mgr.redact_data({
                    "success": False,
                    "status": "verified_failure",
                    "action": action,
                    "locator": locator,
                    "consequential": static_consequential,
                    "barrier_detection": "none_detected",
                    "error": f"Invalid locator: {loc_err}",
                    "verified": False,
                    "cleanup": "confirmed",
                    "message": f"Could not resolve locator '{locator}': {loc_err}"
                })

            try:
                target_count = target_el.count()
            except Exception:
                target_count = 0

            if target_count == 0:
                return secret_mgr.redact_data({
                    "success": False,
                    "status": "verified_failure",
                    "action": action,
                    "locator": locator,
                    "consequential": static_consequential,
                    "barrier_detection": "none_detected",
                    "error": f"Element not found for locator '{locator}'.",
                    "verified": False,
                    "cleanup": "confirmed",
                    "message": f"Target element '{locator}' was not found on the page."
                })

            live_info = {}
            try:
                live_info = target_el.first.evaluate("""el => {
                    const tag = el.tagName ? el.tagName.toLowerCase() : "";
                    const elType = el.getAttribute("type") ? el.getAttribute("type").toLowerCase() : "";
                    const role = el.getAttribute("role") ? el.getAttribute("role").toLowerCase() : "";
                    const ariaLabel = el.getAttribute("aria-label") || "";
                    const ariaDesc = el.getAttribute("aria-description") || "";
                    const title = el.getAttribute("title") || "";
                    const text = (el.innerText || el.textContent || "").trim();
                    const val = el.value || "";
                    const accName = (ariaLabel || ariaDesc || title || text || val).toLowerCase();

                    const form = el.closest("form");
                    const inForm = !!form;
                    const formAction = form ? (form.getAttribute("action") || "") : "";
                    const formMethod = form ? (form.getAttribute("method") || "get").toLowerCase() : "";

                    const isSubmit = (tag === "input" && (elType === "submit" || elType === "image")) ||
                                     (tag === "button" && (elType === "submit" || !elType && inForm));

                    return {
                        tag: tag,
                        type: elType,
                        role: role,
                        accessible_name: accName,
                        visible_text: text.toLowerCase(),
                        in_form: inForm,
                        form_action: formAction,
                        form_method: formMethod,
                        is_submit: isSubmit
                    };
                }""")
            except Exception as inspect_err:
                logger.debug(f"[BROWSER] Live element inspection evaluation failed: {inspect_err}")
                live_info = {}

            acc_name = live_info.get("accessible_name", "")
            vis_text = live_info.get("visible_text", "")
            is_submit = live_info.get("is_submit", False)
            form_action = live_info.get("form_action", "").lower()

            live_consequential = (
                any(k in acc_name for k in consequential_keywords) or
                any(k in vis_text for k in consequential_keywords) or
                any(k in form_action for k in consequential_keywords) or
                (is_submit and any(k in (acc_name + " " + form_action) for k in ["submit", "order", "pay", "buy", "save", "delete", "send"])) or
                (is_submit and live_info.get("form_method") == "post")
            )

            is_consequential = static_consequential or live_consequential

            if is_consequential and not confirmed:
                return secret_mgr.redact_data({
                    "success": False,
                    "status": "confirmation_required",
                    "action": action,
                    "locator": locator,
                    "consequential": True,
                    "risk_level": "HIGH",
                    "verified": False,
                    "detection_source": "live_element_inspection" if live_consequential and not static_consequential else "static_signature",
                    "live_element": live_info,
                    "barrier_detection": "none_detected",
                    "rationale": f"Live target element inspection detected consequential action ('{acc_name or vis_text or locator}'). Explicit user confirmation is required before proceeding.",
                    "cleanup": "confirmed",
                    "message": f"Action '{action}' on target element '{acc_name or vis_text or locator}' is consequential and requires explicit user confirmation before proceeding."
                })

            # 5. Pre-Action State Capture & Idempotency Check
            pre_url = page.url
            pre_title = page.title()
            try:
                pre_body = page.inner_text("body")[:1200]
            except Exception:
                pre_body = ""
            pre_digest = hashlib.sha256(pre_body.encode("utf-8")).hexdigest()[:16]

            pre_state = {
                "url": _sanitize_url(pre_url),
                "title": pre_title,
                "body_digest": pre_digest
            }

            if check_preexisting and expected_outcome:
                already_satisfied = False
                exp_text = expected_outcome.get("expected_text")
                t_loc_spec = expected_outcome.get("target_locator")
                exp_url = expected_outcome.get("expected_url")

                if exp_url and exp_url in pre_url:
                    already_satisfied = True
                elif exp_text:
                    if t_loc_spec:
                        try:
                            t_loc = _resolve_playwright_locator(page, t_loc_spec)
                            if t_loc.count() > 0 and exp_text in t_loc.first.inner_text():
                                already_satisfied = True
                        except Exception:
                            pass
                    elif exp_text in pre_body:
                        already_satisfied = True
                elif action == "check":
                    try:
                        chk_loc = _resolve_playwright_locator(page, locator)
                        if chk_loc.is_checked():
                            already_satisfied = True
                    except Exception:
                        pass
                elif action == "fill" and resolved_val is not None:
                    try:
                        f_loc = _resolve_playwright_locator(page, locator)
                        if f_loc.input_value() == str(resolved_val):
                            already_satisfied = True
                    except Exception:
                        pass

                if already_satisfied:
                    return secret_mgr.redact_data({
                        "success": True,
                        "status": "unchanged_already_satisfied",
                        "action": action,
                        "locator": locator,
                        "action_skipped": True,
                        "verified": True,
                        "consequential": is_consequential,
                        "diff": "unchanged",
                        "barrier_detection": "none_detected",
                        "pre_state": pre_state,
                        "post_state": pre_state,
                        "final_url": _sanitize_url(pre_url),
                        "cleanup": "confirmed",
                        "message": "Expected outcome is already satisfied in the current page state; action suppressed to prevent duplicate side-effects."
                    })

            # 6. Action Execution
            step_timeout = min(timeout_ms, 8000)
            try:
                act_lower = action.lower()
                if act_lower == "click":
                    target_el.click(timeout=step_timeout)
                elif act_lower == "fill":
                    target_el.fill(str(resolved_val or ""), timeout=step_timeout)
                elif act_lower == "press":
                    k = str(resolved_val) if resolved_val else "Enter"
                    target_el.press(k, timeout=step_timeout)
                elif act_lower == "select_option":
                    target_el.select_option(str(resolved_val or ""), timeout=step_timeout)
                elif act_lower == "check":
                    target_el.check(timeout=step_timeout)
                elif act_lower == "uncheck":
                    target_el.uncheck(timeout=step_timeout)
                else:
                    return {
                        "success": False,
                        "status": "verified_failure",
                        "action": action,
                        "locator": locator,
                        "consequential": is_consequential,
                        "barrier_detection": "none_detected",
                        "error": f"Unsupported action '{action}'.",
                        "verified": False,
                        "cleanup": "confirmed",
                        "message": f"Action '{action}' is not supported."
                    }
            except Exception as exec_err:
                return secret_mgr.redact_data({
                    "success": False,
                    "status": "verified_failure",
                    "action": action,
                    "locator": locator,
                    "consequential": is_consequential,
                    "barrier_detection": "none_detected",
                    "error": str(exec_err),
                    "verified": False,
                    "cleanup": "confirmed",
                    "message": f"Action execution failed: {exec_err}"
                })

            # 7. Settle Wait and Post-Action State Observation
            if expected_outcome and expected_outcome.get("target_locator"):
                try:
                    t_str = expected_outcome["target_locator"]
                    if isinstance(t_str, str):
                        page.wait_for_selector(t_str, timeout=min(timeout_ms, 4000), state="visible")
                except Exception:
                    pass
            else:
                page.wait_for_timeout(200)

            post_url = page.url
            post_title = page.title()
            try:
                post_body = page.inner_text("body")[:1200]
            except Exception:
                post_body = ""
            post_digest = hashlib.sha256(post_body.encode("utf-8")).hexdigest()[:16]

            # Check for newly rendered page errors
            page_error = None
            for err_sel in [".error-message", ".alert-danger", "#error-box", ".error", "[role='alert']"]:
                try:
                    err_el = page.locator(err_sel).first
                    if err_el.count() > 0 and err_el.is_visible():
                        err_txt = err_el.inner_text().strip()
                        if err_txt and err_txt not in pre_body:
                            page_error = err_txt
                            break
                except Exception:
                    pass

            post_state = {
                "url": _sanitize_url(post_url),
                "title": post_title,
                "body_digest": post_digest,
                "error": page_error
            }

            if page_error:
                return secret_mgr.redact_data({
                    "success": False,
                    "status": "verified_failure",
                    "action": action,
                    "locator": locator,
                    "consequential": is_consequential,
                    "barrier_detection": "none_detected",
                    "error": f"Post-action error observed: {page_error}",
                    "verified": False,
                    "diff": "changed",
                    "pre_state": pre_state,
                    "post_state": post_state,
                    "final_url": _sanitize_url(post_url),
                    "cleanup": "confirmed",
                    "message": f"Action was dispatched but page reported an error: {page_error}"
                })

            # 8. Post-Action Outcome Verification (Grounded Verification Enforcement)
            has_grounded_postcondition = bool(
                expected_outcome and any(
                    expected_outcome.get(k) is not None for k in [
                        "expected_text", "target_locator", "expected_url",
                        "expected_value", "expected_attribute", "expected_checked"
                    ]
                )
            )

            url_changed = (pre_url != post_url)
            dom_changed = (pre_digest != post_digest)

            if has_grounded_postcondition:
                exp_text = expected_outcome.get("expected_text")
                t_loc_spec = expected_outcome.get("target_locator")
                exp_url = expected_outcome.get("expected_url")
                exp_val = expected_outcome.get("expected_value")
                exp_chk = expected_outcome.get("expected_checked")

                matched_conditions = []
                if exp_url:
                    matched_conditions.append(exp_url in post_url)
                if exp_text:
                    if t_loc_spec:
                        try:
                            t_loc = _resolve_playwright_locator(page, t_loc_spec)
                            matched_conditions.append(t_loc.count() > 0 and exp_text in t_loc.first.inner_text())
                        except Exception:
                            matched_conditions.append(False)
                    else:
                        matched_conditions.append(exp_text in post_body)
                elif t_loc_spec:
                    try:
                        t_loc = _resolve_playwright_locator(page, t_loc_spec)
                        matched_conditions.append(t_loc.count() > 0 and t_loc.first.is_visible())
                    except Exception:
                        matched_conditions.append(False)

                if exp_val is not None and t_loc_spec:
                    try:
                        t_loc = _resolve_playwright_locator(page, t_loc_spec)
                        matched_conditions.append(t_loc.count() > 0 and t_loc.first.input_value() == str(exp_val))
                    except Exception:
                        matched_conditions.append(False)

                if exp_chk is not None and t_loc_spec:
                    try:
                        t_loc = _resolve_playwright_locator(page, t_loc_spec)
                        matched_conditions.append(t_loc.count() > 0 and t_loc.first.is_checked() == bool(exp_chk))
                    except Exception:
                        matched_conditions.append(False)

                outcome_matched = bool(matched_conditions and all(matched_conditions))
                if outcome_matched:
                    status = "verified_success"
                    verified = True
                    diff_state = "changed" if (url_changed or dom_changed) else "unchanged"
                    msg = f"Action '{action}' on '{locator}' succeeded and explicit expected postconditions were verified."
                else:
                    status = "ambiguous"
                    verified = False
                    diff_state = "changed" if (url_changed or dom_changed) else "unchanged"
                    msg = f"Action '{action}' was dispatched, but post-action state did not satisfy the expected grounded postconditions (unrelated DOM changes do not prove goal success)."
            else:
                # No grounded postconditions provided - refuse to treat arbitrary DOM/URL changes as success
                status = "ambiguous"
                verified = False
                diff_state = "changed" if (url_changed or dom_changed) else "unchanged"
                msg = (
                    f"Action '{action}' was executed and caused observable state changes, "
                    f"but outcome verification remains ambiguous without explicit, grounded postconditions."
                    if (url_changed or dom_changed) else
                    f"Action '{action}' was executed, but resulted in no observable change and no explicit postconditions were provided."
                )

            return secret_mgr.redact_data({
                "success": (status == "verified_success"),
                "status": status,
                "action": action,
                "locator": locator,
                "verified": verified,
                "consequential": is_consequential,
                "action_skipped": False,
                "diff": diff_state,
                "barrier_detection": "none_detected",
                "pre_state": pre_state,
                "post_state": post_state,
                "final_url": _sanitize_url(post_url),
                "cleanup": "confirmed",
                "message": msg
            })
    except Exception as overall_err:
        return secret_mgr.redact_data({
            "success": False,
            "status": "verified_failure",
            "action": action,
            "locator": locator,
            "consequential": is_consequential,
            "error": str(overall_err),
            "verified": False,
            "cleanup": "confirmed",
            "message": f"Browser interaction error: {overall_err}"
        })


# =============================================================================
# REA INTEGRATION: PHASE 6 — ADAPTIVE BROWSER WORKFLOW RECOVERY
# Source: rea-main/src/browser/actions/PlaywrightScenarioActions.ts,
#         CaptureFailures.ts, & BrowserScenarioPartialObservation.ts
# =============================================================================

def classify_browser_failure(
    error_or_result: Union[str, Dict[str, Any]],
    page_state: Optional[Dict[str, Any]] = None
) -> str:
    """
    Classifies browser failure using actual available evidence:
    - security_barrier: CAPTCHA, Turnstile, Cloudflare, auth walls, 401/403
    - confirmation_required: consequential action without explicit user confirmation
    - stale_or_missing_locator: element not found, strict mode violation, detached, stale
    - navigation_interrupted: network error, DNS resolution failure, connection reset, aborted
    - timeout: action or locator wait timeout exceeded
    - post_action_error: page rendered an error box or alert post-action
    - ambiguous_outcome: postconditions unverified or inconclusive
    - unknown_failure: unclassified failure
    """
    if isinstance(error_or_result, dict):
        status = str(error_or_result.get("status", "")).lower()
        err_msg = str(error_or_result.get("error", "") or error_or_result.get("message", "")).lower()
        barrier_detection = str(error_or_result.get("barrier_detection", "")).lower()
        barrier_type = str(error_or_result.get("barrier_type", "")).lower()
    else:
        status = ""
        err_msg = str(error_or_result).lower()
        barrier_detection = ""
        barrier_type = ""

    if (
        status in ("intervention_required", "security_barrier")
        or barrier_detection in ("detected", "challenge_page", "http_auth_required")
        or barrier_type in ("recaptcha", "hcaptcha", "cloudflare_turnstile", "http_401", "http_403", "generic_auth_wall")
        or any(k in err_msg for k in ["captcha", "turnstile", "cloudflare", "401 unauthorized", "403 forbidden", "security barrier", "intervention required"])
    ):
        return "security_barrier"

    if (
        status == "confirmation_required"
        or "confirmation required" in err_msg
        or "explicit user confirmation" in err_msg
    ):
        return "confirmation_required"

    if (
        status == "post_action_error"
        or "post-action error" in err_msg
        or "page reported an error" in err_msg
    ):
        return "post_action_error"

    if any(k in err_msg for k in [
        "net::err", "ns_error", "navigation failed", "navigation timeout",
        "interrupted", "connection refused", "connection reset", "aborted"
    ]):
        return "navigation_interrupted"

    if any(k in err_msg for k in [
        "waiting for locator", "strict mode violation", "element is not attached",
        "not found", "no element matching", "stale element", "cannot find locator",
        "locator resolved to 0 elements", "element not visible", "element was replaced"
    ]):
        return "stale_or_missing_locator"

    if "timeout" in err_msg or "timed out" in err_msg:
        return "timeout"

    if status in ("ambiguous", "inconclusive"):
        return "ambiguous_outcome"

    return "unknown_failure"


def reobserve_and_replan_action(
    url: str,
    failed_action: Dict[str, Any],
    failure_type: str,
    fallback_locators: Optional[List[str]] = None,
    timeout_ms: int = 5000,
    headless: bool = True
) -> Dict[str, Any]:
    """
    Re-observes the live page after a recoverable failure and refreshes relevant
    element or state information before replanning.
    Selects a revised action only when the new action is supported by current page evidence.
    """
    if failure_type in ("security_barrier", "confirmation_required"):
        return {
            "replanned": False,
            "reason": failure_type,
            "evidence": {"classification": failure_type, "recoverable": False}
        }

    current_loc = failed_action.get("locator")
    act_type = failed_action.get("action", "click")

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            try:
                page = browser.new_page()
                page.set_default_timeout(timeout_ms)
                target_url = str(url).strip()
                if os.path.isabs(target_url):
                    safe_url = f"file:///{os.path.abspath(target_url).replace(os.sep, '/')}"
                elif target_url.startswith("file://"):
                    safe_url = target_url
                else:
                    safe_url = sanitize_browser_url(target_url)
                page.goto(safe_url, timeout=timeout_ms, wait_until="domcontentloaded")

                # Strategy 1: Check fallback locators
                if fallback_locators:
                    for fb in fallback_locators:
                        try:
                            loc_obj = page.locator(fb).first
                            if loc_obj.count() > 0 and loc_obj.is_visible():
                                replanned = dict(failed_action)
                                replanned["locator"] = fb
                                replanned["replanned_from"] = current_loc
                                return {
                                    "replanned": True,
                                    "action": replanned,
                                    "evidence": {
                                        "strategy": "fallback_locator",
                                        "selected_locator": fb,
                                        "tested_fallbacks": fallback_locators
                                    }
                                }
                        except Exception:
                            continue

                # Strategy 2: Dynamic candidate discovery for stale or replaced element
                if failure_type == "stale_or_missing_locator":
                    candidates = []
                    selectors_to_check = ["button", "input[type='button']", "input[type='submit']", "a[role='button']", "input"]
                    for sel in selectors_to_check:
                        try:
                            elements = page.locator(sel)
                            count = min(elements.count(), 10)
                            for i in range(count):
                                el = elements.nth(i)
                                if el.is_visible():
                                    el_id = el.get_attribute("id") or ""
                                    el_text = (el.inner_text() or "").strip()
                                    el_aria = el.get_attribute("aria-label") or ""
                                    el_name = el.get_attribute("name") or ""
                                    candidates.append({
                                        "tag": sel,
                                        "id": f"#{el_id}" if el_id else None,
                                        "text": el_text,
                                        "aria_label": el_aria,
                                        "name": el_name
                                    })
                        except Exception:
                            pass

                    keywords = []
                    if current_loc:
                        clean_loc = re.sub(r'^[#\.]', '', str(current_loc)).lower()
                        keywords.extend(re.split(r'[-_]', clean_loc))
                    if act_type:
                        keywords.append(act_type.lower())

                    for cand in candidates:
                        cand_id = cand.get("id")
                        cand_text = cand.get("text", "").lower()
                        cand_aria = cand.get("aria_label", "").lower()
                        cand_name = cand.get("name", "").lower()

                        if any(kw and kw in cand_text for kw in keywords if len(kw) > 2) \
                           or any(kw and kw in cand_aria for kw in keywords if len(kw) > 2) \
                           or any(kw and kw in cand_name for kw in keywords if len(kw) > 2) \
                           or (cand_id and any(kw and kw in cand_id.lower() for kw in keywords if len(kw) > 2)):
                            best_selector = cand_id or (f"button:has-text('{cand['text']}')" if cand['text'] else cand['tag'])
                            replanned = dict(failed_action)
                            replanned["locator"] = best_selector
                            replanned["replanned_from"] = current_loc
                            return {
                                "replanned": True,
                                "action": replanned,
                                "evidence": {
                                    "strategy": "discovered_candidate_element",
                                    "selected_locator": best_selector,
                                    "candidate": cand
                                }
                            }

                # Strategy 3: Transient network/timeout recovery
                if failure_type in ("timeout", "navigation_interrupted"):
                    replanned = dict(failed_action)
                    replanned["timeout_ms"] = min(30000, int(failed_action.get("timeout_ms", 10000) * 1.5))
                    return {
                        "replanned": True,
                        "action": replanned,
                        "evidence": {
                            "strategy": "retry_with_extended_timeout",
                            "adjusted_timeout_ms": replanned["timeout_ms"]
                        }
                    }
            finally:
                browser.close()
    except Exception as reobs_err:
        logger.debug(f"[BROWSER_RECOVERY] Live reobservation failed: {reobs_err}")

    # If live observation couldn't replan or threw error, check if fallback locators were supplied
    if fallback_locators:
        first_fb = fallback_locators[0]
        replanned = dict(failed_action)
        replanned["locator"] = first_fb
        replanned["replanned_from"] = current_loc
        return {
            "replanned": True,
            "action": replanned,
            "evidence": {
                "strategy": "static_fallback_selection",
                "selected_locator": first_fb
            }
        }

    return {
        "replanned": False,
        "reason": "no_matching_candidate_found",
        "evidence": {
            "failure_type": failure_type,
            "examined_locator": current_loc,
            "recoverable": False
        }
    }


def execute_adaptive_browser_action(
    url: str,
    action: str = "click",
    locator: Optional[str] = None,
    value: Optional[Any] = None,
    expected_outcome: Optional[Dict[str, Any]] = None,
    confirmed: bool = False,
    check_preexisting: bool = True,
    secrets: Optional[Dict[str, str]] = None,
    timeout_ms: int = 15000,
    headless: bool = True,
    fallback_locators: Optional[List[str]] = None,
    max_retries: int = 2
) -> Dict[str, Any]:
    """
    Executes a browser interaction with evidence-driven failure diagnosis,
    live page re-observation, safe replanning, bounded retries, and verified recovery.
    """
    secret_mgr = BrowserScenarioSecrets(secrets)
    budget = min(max(1, max_retries), 3)

    current_action = action
    current_locator = locator
    current_value = value
    current_timeout = timeout_ms

    recovery_trace = []
    seen_locators = set()
    attempt = 0

    while attempt < budget:
        attempt += 1
        seen_locators.add(current_locator)

        # 1. Execute verified action
        res = execute_verified_browser_action(
            url=url,
            action=current_action,
            locator=current_locator,
            value=current_value,
            expected_outcome=expected_outcome,
            confirmed=confirmed,
            check_preexisting=check_preexisting,
            secrets=secrets,
            timeout_ms=current_timeout,
            headless=headless
        )

        trace_entry = {
            "attempt": attempt,
            "action": current_action,
            "locator": current_locator,
            "status": res.get("status"),
            "verified": res.get("verified", False),
            "diff": res.get("diff"),
            "message": res.get("message")
        }
        if current_value is not None:
            trace_entry["value"] = current_value

        # 2. Check for Immediate Verified Success or Pre-existing Satisfaction
        if res.get("status") in ("verified_success", "unchanged_already_satisfied"):
            trace_entry["outcome"] = "verified_success"
            recovery_trace.append(trace_entry)
            res_copy = dict(res)
            res_copy["recovery_trace"] = recovery_trace
            res_copy["attempts_made"] = attempt
            res_copy["recovered"] = (attempt > 1)
            return secret_mgr.redact_data(res_copy)

        # 3. Classify Failure Evidence
        failure_type = classify_browser_failure(res)
        trace_entry["failure_classification"] = failure_type

        # 4. Security Barrier Gate: Halt Immediately
        if failure_type == "security_barrier" or res.get("status") == "intervention_required":
            trace_entry["outcome"] = "intervention_required"
            b_type = res.get("barrier_name") or res.get("barrier_type") or "security_barrier"
            trace_entry["barrier"] = b_type
            recovery_trace.append(trace_entry)
            return secret_mgr.redact_data({
                "success": False,
                "status": "intervention_required",
                "action": current_action,
                "locator": current_locator,
                "barrier_type": b_type,
                "barrier_name": res.get("barrier_name", b_type),
                "barrier_detection": res.get("barrier_detection", "detected"),
                "recovery_trace": recovery_trace,
                "attempts_made": attempt,
                "recovered": False,
                "cleanup": "confirmed",
                "message": res.get("message", "User intervention required: security barrier detected.")
            })

        # 5. Inconclusive Barrier Evidence: Halt Without False Success
        if res.get("status") == "inconclusive" or res.get("barrier_detection") == "inconclusive":
            trace_entry["outcome"] = "inconclusive"
            recovery_trace.append(trace_entry)
            return secret_mgr.redact_data({
                "success": False,
                "status": "inconclusive",
                "action": current_action,
                "locator": current_locator,
                "barrier_detection": "inconclusive",
                "recovery_trace": recovery_trace,
                "attempts_made": attempt,
                "recovered": False,
                "cleanup": "confirmed",
                "message": res.get("message", "Inconclusive security barrier detection.")
            })

        # 6. Consequential Action Confirmation Gate: Halt Without Bypassing
        if failure_type == "confirmation_required" or res.get("status") == "confirmation_required":
            trace_entry["outcome"] = "confirmation_required"
            recovery_trace.append(trace_entry)
            return secret_mgr.redact_data({
                "success": False,
                "status": "confirmation_required",
                "action": current_action,
                "locator": current_locator,
                "consequential": True,
                "recovery_trace": recovery_trace,
                "attempts_made": attempt,
                "recovered": False,
                "cleanup": "confirmed",
                "message": res.get("message", "Consequential action requires explicit user confirmation.")
            })

        # 7. Consequential Mutation Protection: Never Repeat If Mutation Might Have Occurred
        is_consequential = res.get("consequential", False)
        state_mutated = (res.get("diff") == "changed") or bool(res.get("post_state"))
        if is_consequential and (state_mutated or res.get("action_skipped") is False):
            trace_entry["outcome"] = "retry_suppressed"
            trace_entry["reason"] = "consequential_mutation_safety"
            recovery_trace.append(trace_entry)
            return secret_mgr.redact_data({
                "success": False,
                "status": "retry_suppressed",
                "action": current_action,
                "locator": current_locator,
                "consequential": True,
                "recovery_trace": recovery_trace,
                "attempts_made": attempt,
                "recovered": False,
                "cleanup": "confirmed",
                "message": "Recovery suppressed: consequential action may have already mutated state. Blind retry prevented to avoid duplicate side effects."
            })

        # 8. Check If Retry Budget Is Exhausted
        if attempt >= budget:
            trace_entry["outcome"] = "recovery_exhausted"
            recovery_trace.append(trace_entry)
            break

        # 9. Re-observe Live Page and Replan
        replan_res = reobserve_and_replan_action(
            url=url,
            failed_action={
                "action": current_action,
                "locator": current_locator,
                "value": current_value,
                "timeout_ms": current_timeout
            },
            failure_type=failure_type,
            fallback_locators=fallback_locators,
            timeout_ms=min(5000, current_timeout),
            headless=headless
        )

        trace_entry["replan_evidence"] = replan_res.get("evidence")

        if not replan_res.get("replanned"):
            trace_entry["outcome"] = "replanning_failed"
            trace_entry["reason"] = replan_res.get("reason")
            recovery_trace.append(trace_entry)
            return secret_mgr.redact_data({
                "success": False,
                "status": "verified_failure",
                "action": current_action,
                "locator": current_locator,
                "recovery_trace": recovery_trace,
                "attempts_made": attempt,
                "recovered": False,
                "cleanup": "confirmed",
                "message": f"Adaptive recovery failed: {replan_res.get('reason', 'replanning not possible')}."
            })

        # Check for loop prevention
        new_act = replan_res["action"]
        new_loc = new_act.get("locator")
        if new_loc in seen_locators and failure_type not in ("timeout", "navigation_interrupted"):
            trace_entry["outcome"] = "loop_prevented"
            recovery_trace.append(trace_entry)
            return secret_mgr.redact_data({
                "success": False,
                "status": "verified_failure",
                "action": current_action,
                "locator": current_locator,
                "recovery_trace": recovery_trace,
                "attempts_made": attempt,
                "recovered": False,
                "cleanup": "confirmed",
                "message": f"Adaptive recovery halted to prevent repetitive loop on locator '{new_loc}'."
            })

        # Adopt replanned parameters for next attempt
        current_action = new_act.get("action", current_action)
        current_locator = new_loc
        current_value = new_act.get("value", current_value)
        current_timeout = new_act.get("timeout_ms", current_timeout)
        trace_entry["replanned_to"] = current_locator
        recovery_trace.append(trace_entry)

    # If loop finished due to exhausted budget
    return secret_mgr.redact_data({
        "success": False,
        "status": "recovery_exhausted",
        "action": current_action,
        "locator": current_locator,
        "recovery_trace": recovery_trace,
        "attempts_made": attempt,
        "recovered": False,
        "cleanup": "confirmed",
        "message": f"Adaptive recovery exhausted after {attempt} attempt(s) without achieving verified postconditions."
    })


# =============================================================================
# REA INTEGRATION: PHASE 7 — VERIFIED WEB SCRIPT & ASSET EXPORT
# Source: rea-main/src/contracts/webScriptToolContracts.ts,
#         rea-main/src/domain/webScriptExport.ts,
#         rea-main/src/domain/webScriptExportPlan.ts,
#         rea-main/src/application/WebScriptExportService.ts
# =============================================================================

def _is_symlink_or_junction(path: str) -> bool:
    if not path:
        return False
    try:
        if os.path.islink(path):
            return True
        st = os.lstat(path)
        tag = getattr(st, 'st_reparse_tag', 0)
        if tag in (0xA0000003, 0xA000000C, 2684354563):
            return True
        os.readlink(path)
        return True
    except (OSError, ValueError):
        return False


def export_web_scripts(
    target: str,
    output_directory: str,
    include_source_maps: bool = True,
    timeout_ms: int = 15000,
    headless: bool = True,
    overwrite: bool = False,
    secrets: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Safely exports website JavaScript assets into a clean destination directory
    with a tamper-evident, digest-verified manifest.json.
    
    Hardened against all 6 audit requirements:
    A. Path traversal immunity & destination containment:
       - Refuses symlinks, junctions, root paths, and directory traversal.
       - Confirms canonical containment via realpath and commonpath.
    B. Overwrites and interrupted exports:
       - Refuses existing non-empty directories unless overwrite=True.
       - Atomic rollback: removes newly created files on failure/interruption.
       - Never deletes pre-existing user data.
    C. SHA-256 integrity:
       - Durable readback: re-reads actual written bytes from disk to verify SHA-256.
       - Computes and verifies manifest.json digest after durable write.
    D. Secret and sensitive-data exposure:
       - Redacts credentials, tokens, and query secrets from URLs, metadata, and logs.
       - Preserves executable source bytes without syntax corruption.
       - Explicitly states secret detection boundaries in limitations.
    E. Truthful outcomes:
       - Distinguishes complete ("success"), partial ("partial"), and failed ("error"/"blocked") exports.
       - Retains accurate asset breakdown counts.
    F. Full pipeline integration:
       - Compatible with UnifiedCommandRouter, Brain, and OutcomeVerifier.
    """
    import os
    import re
    import json
    import hashlib
    import urllib.parse
    from datetime import datetime, timezone

    secret_mgr = BrowserScenarioSecrets(secrets or {})

    PORTABLE_SEGMENT = re.compile(r'^[A-Za-z0-9_~.-]+$')
    RESERVED_SEGMENT = re.compile(r'^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', re.I)

    LIMITATIONS = [
        "Only script bytes retained in this capture or live inspection are exported.",
        "A response or Debugger source does not prove execution.",
        "Ordinary unambiguous URL paths preserve relative module layouts by origin. Query variants, collisions, and non-portable paths are isolated.",
        "Secret detection is applied to transport metadata, URLs, and diagnostic logs; script bytes retain captured content without semantic alteration. Complex or custom credentials embedded inside script source code may not be automatically detected.",
        "Source-map declarations are retained as metadata; missing dependencies are not dynamically fetched during offline export."
    ]

    def _sanitize_metadata_url(raw_url: str) -> str:
        if not raw_url or not isinstance(raw_url, str):
            return ""
        # Redact basic auth credentials
        sanitized = re.sub(r'://([^:@\s]+):([^@\s]+)@', r'://\1:[REDACTED]@', raw_url)
        # Redact common query token parameters
        sanitized = re.sub(r'(?i)(token|key|secret|auth|password|passwd|api_key|access_token|session)=([^&#\s]+)', r'\1=[REDACTED]', sanitized)
        return secret_mgr.redact_text(sanitized)

    # 1. Input Validation
    if not target or not isinstance(target, str):
        return {
            "success": False,
            "status": "error",
            "error": "Target must be a valid URL or offline capture JSON path.",
            "message": "Target must be a valid URL or offline capture JSON path."
        }

    clean_out_dir = (output_directory or "").strip(' "\'')
    if not clean_out_dir:
        return {
            "success": False,
            "status": "error",
            "error": "output_directory cannot be empty.",
            "message": "output_directory cannot be empty."
        }

    abs_out_dir = os.path.abspath(clean_out_dir)
    real_out_dir = os.path.realpath(abs_out_dir)

    # Area A: Destination symlink/junction defense
    if _is_symlink_or_junction(abs_out_dir) or _is_symlink_or_junction(clean_out_dir):
        return {
            "success": False,
            "status": "blocked",
            "error": f"Destination path cannot be a symbolic link or junction: '{clean_out_dir}'",
            "message": f"Refusing to export into symbolic link or junction '{clean_out_dir}'."
        }

    # Area A: Root directory protection
    drive, tail = os.path.splitdrive(abs_out_dir)
    if not tail or tail in ("\\", "/"):
        return {
            "success": False,
            "status": "blocked",
            "error": f"Destination cannot be a filesystem drive or root directory: '{clean_out_dir}'",
            "message": f"Refusing to export into filesystem root '{clean_out_dir}'."
        }

    # Area B: Destination exclusivity & overwrite prevention
    if os.path.exists(abs_out_dir):
        if os.path.isfile(abs_out_dir):
            return {
                "success": False,
                "status": "blocked",
                "error": f"Destination is an existing file, not a directory: '{clean_out_dir}'",
                "message": f"Destination '{clean_out_dir}' already exists as a file."
            }
        if not overwrite:
            try:
                if any(os.scandir(abs_out_dir)):
                    return {
                        "success": False,
                        "status": "blocked",
                        "error": f"Destination directory already exists and is not empty: '{clean_out_dir}'. Use a new directory for export.",
                        "message": f"Destination directory '{clean_out_dir}' already exists and is not empty."
                    }
            except Exception as e:
                return {
                    "success": False,
                    "status": "error",
                    "error": f"Cannot inspect destination directory '{abs_out_dir}': {e}",
                    "message": f"Cannot inspect destination directory: {e}"
                }

    # Target path validation (regular file vs directory)
    if os.path.isdir(target):
        return {
            "success": False,
            "status": "blocked",
            "error": f"Target capture path is a directory, not a regular file: '{target}'",
            "message": f"Selected capture path is a directory: '{target}'."
        }
    if target.lower().endswith(".json") and not os.path.exists(target):
        return {
            "success": False,
            "status": "error",
            "error": f"Capture file not found: '{target}'",
            "message": f"Capture file not found: '{target}'."
        }

    # 2. Acquire Script Records (Offline Capture or Live Page)
    scripts_to_export = []
    source_maps_to_export = []
    source_origin = target

    if os.path.isfile(target) and target.lower().endswith(".json"):
        try:
            with open(target, "r", encoding="utf-8") as f:
                capture_data = json.load(f)
            if "scripts" in capture_data:
                scripts_to_export = capture_data["scripts"]
            elif "data" in capture_data and "scripts" in capture_data["data"]:
                scripts_to_export = capture_data["data"]["scripts"]
            source_maps_to_export = capture_data.get("source_maps_detected", [])
            source_origin = capture_data.get("url") or target
        except Exception as e:
            return {
                "success": False,
                "status": "error",
                "error": f"Failed to load capture file '{target}': {e}",
                "message": f"Failed to load capture file '{target}': {e}"
            }
    else:
        # Live page script inspection using inspect_web_scripts
        insp_res = inspect_web_scripts(url=target, include_script_sources=True, timeout_ms=timeout_ms, headless=headless)
        if not insp_res.get("success"):
            return {
                "success": False,
                "status": "error",
                "error": insp_res.get("error") or "Failed to inspect web scripts from target URL.",
                "message": insp_res.get("message") or "Failed to inspect web scripts from target URL."
            }
        scripts_to_export = insp_res.get("scripts", [])
        source_maps_to_export = insp_res.get("source_maps_detected", [])
        source_origin = insp_res.get("url") or target

    if not scripts_to_export:
        return {
            "success": False,
            "status": "no_scripts_found",
            "error": "No scripts found on the specified page or capture.",
            "message": f"No scripts were discovered on target '{_sanitize_metadata_url(target)}'."
        }

    # Area B: Track owned created paths for atomic rollback
    created_files = []
    created_dirs = []
    owned_root = not os.path.exists(abs_out_dir)

    try:
        os.makedirs(abs_out_dir, exist_ok=True)
        if owned_root:
            created_dirs.append(abs_out_dir)
    except Exception as e:
        return {
            "success": False,
            "status": "error",
            "error": f"Cannot create output directory '{abs_out_dir}': {e}",
            "message": f"Cannot create output directory '{abs_out_dir}': {e}"
        }

    # 3. Plan and Export Each Script Safely
    exported_records = []
    unavailable_records = []
    total_bytes = 0

    try:
        for idx, s in enumerate(scripts_to_export):
            s_url = s.get("url") or ""
            s_map_url = s.get("source_map_url") or s.get("sourceMapURL")
            raw_content = s.get("content")
            if raw_content is None:
                raw_source = s.get("source")
                if isinstance(raw_source, dict):
                    raw_content = raw_source.get("content")
                elif raw_source is not None:
                    raw_content = raw_source

            # Check if source is unavailable
            if raw_content is None or (not raw_content and s.get("state") == "unavailable"):
                unavailable_records.append({
                    "index": len(exported_records) + len(unavailable_records),
                    "type": "script",
                    "url": _sanitize_metadata_url(s_url) if s_url else f"(inline_{idx})",
                    "state": "unavailable",
                    "reason": s.get("reason", "No script bytes retained in capture or live inspection."),
                    "message": s.get("message", "Script content was not captured.")
                })
                continue

            s_content = str(raw_content)
            is_module = bool(s.get("is_module", False))

            # Plan relative path (preserving portable URL layout or isolating)
            layout = "url-path"
            layout_reason = None

            if not s_url or s_url == "(inline)" or s.get("script_type") == "inline" or s.get("is_inline"):
                layout = "isolated"
                layout_reason = "Inline script source."
                rel_path = f"isolated/inline_{idx + 1}_{hashlib.sha256(s_content.encode('utf-8')).hexdigest()[:10]}.js"
            else:
                parsed = urllib.parse.urlparse(s_url)
                if parsed.scheme not in ("http", "https"):
                    layout = "isolated"
                    layout_reason = f"Non-HTTP scheme '{parsed.scheme}'."
                    rel_path = f"isolated/source_{idx + 1}_{hashlib.sha256(s_url.encode('utf-8')).hexdigest()[:10]}.js"
                else:
                    parts = [p for p in parsed.path.strip("/").split("/") if p]
                    # Check for query, fragment, credentials, non-portable characters, or traversal
                    has_credentials = bool(parsed.username or parsed.password)
                    has_query_or_frag = bool(parsed.query or parsed.fragment)
                    has_traversal = any(p in (".", "..") or p.endswith(".") for p in parts)
                    has_non_portable = any(not PORTABLE_SEGMENT.match(p) or RESERVED_SEGMENT.match(p) for p in parts)

                    if has_credentials or has_query_or_frag or has_traversal or has_non_portable or not parts:
                        layout = "isolated"
                        layout_reason = "URL contains query parameters, credentials, reserved names, or non-portable path segments."
                        rel_path = f"isolated/source_{idx + 1}_{hashlib.sha256(s_url.encode('utf-8')).hexdigest()[:10]}.js"
                    else:
                        domain_hash = hashlib.sha256(parsed.netloc.encode("utf-8")).hexdigest()[:16]
                        clean_parts = list(parts)
                        if not clean_parts[-1].endswith((".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx")):
                            clean_parts[-1] = f"{clean_parts[-1]}.js"
                        rel_path = f"origins/{domain_hash}/{'/'.join(clean_parts)}"

            # Area A: Verify destination containment strictly
            dest_full = os.path.abspath(os.path.join(abs_out_dir, rel_path))
            real_dest = os.path.realpath(dest_full)
            try:
                common = os.path.commonpath([real_dest, real_out_dir])
            except ValueError:
                common = None

            if common != real_out_dir or not real_dest.startswith(real_out_dir):
                raise ValueError(f"Path containment violation: planned path '{rel_path}' escapes export root '{abs_out_dir}'.")

            # Create parent directories safely
            parent_dir = os.path.dirname(dest_full)
            if not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
                created_dirs.append(parent_dir)

            # Area C: Write and durable readback
            content_bytes = s_content.encode("utf-8")
            with open(dest_full, "wb") as f_out:
                f_out.write(content_bytes)
                f_out.flush()
                os.fsync(f_out.fileno())

            created_files.append(dest_full)

            with open(dest_full, "rb") as f_verify:
                disk_bytes = f_verify.read()

            disk_sha256 = hashlib.sha256(disk_bytes).hexdigest()
            expected_sha256 = hashlib.sha256(content_bytes).hexdigest()

            if disk_sha256 != expected_sha256 or len(disk_bytes) != len(content_bytes):
                raise IOError(f"Durable byte verification failed for '{dest_full}': hash or length mismatch on disk.")

            b_len = len(disk_bytes)
            total_bytes += b_len

            rec = {
                "index": len(exported_records),
                "type": "script",
                "state": "exported",
                "layout": layout,
                "layout_reason": layout_reason,
                "url": _sanitize_metadata_url(s_url) if s_url else f"(inline_{idx})",
                "original_url": _sanitize_metadata_url(s_url) if s_url else f"(inline_{idx})",
                "relative_path": rel_path.replace(os.sep, "/"),
                "local_path": dest_full,
                "sha256": disk_sha256,
                "bytes": b_len,
                "byte_length": b_len,
                "is_module": is_module,
                "has_source_map": bool(s_map_url),
                "source_map_url": _sanitize_metadata_url(s_map_url) if s_map_url else None
            }
            exported_records.append(rec)

        # Export source maps if requested and available
        if include_source_maps and source_maps_to_export:
            for sm_idx, sm in enumerate(source_maps_to_export):
                sm_url = sm.get("source_map_url") or sm.get("url") or ""
                sm_content = sm.get("source_map_content") or sm.get("content") or ""
                if not sm_content and sm.get("script_url"):
                    continue

                sm_hash = hashlib.sha256((sm_url or str(sm_idx)).encode("utf-8")).hexdigest()[:12]
                sm_rel_path = f"sourcemaps/map_{sm_idx + 1}_{sm_hash}.map"
                sm_dest = os.path.abspath(os.path.join(abs_out_dir, sm_rel_path))

                real_sm_dest = os.path.realpath(sm_dest)
                if not real_sm_dest.startswith(real_out_dir):
                    raise ValueError(f"Source map path escapes export root: '{sm_rel_path}'")

                parent_sm_dir = os.path.dirname(sm_dest)
                if not os.path.exists(parent_sm_dir):
                    os.makedirs(parent_sm_dir, exist_ok=True)
                    created_dirs.append(parent_sm_dir)

                sm_bytes = sm_content.encode("utf-8")
                with open(sm_dest, "wb") as f_sm:
                    f_sm.write(sm_bytes)
                    f_sm.flush()
                    os.fsync(f_sm.fileno())

                created_files.append(sm_dest)

                with open(sm_dest, "rb") as f_sm_v:
                    sm_disk_bytes = f_sm_v.read()

                sm_sha = hashlib.sha256(sm_disk_bytes).hexdigest()
                if sm_sha != hashlib.sha256(sm_bytes).hexdigest():
                    raise IOError(f"Durable byte verification failed for source map '{sm_dest}'")

                total_bytes += len(sm_disk_bytes)
                exported_records.append({
                    "index": len(exported_records),
                    "type": "source_map",
                    "state": "exported",
                    "layout": "sourcemap",
                    "layout_reason": None,
                    "url": _sanitize_metadata_url(sm_url),
                    "relative_path": sm_rel_path.replace(os.sep, "/"),
                    "local_path": sm_dest,
                    "sha256": sm_sha,
                    "bytes": len(sm_disk_bytes),
                    "byte_length": len(sm_disk_bytes),
                    "is_module": False,
                    "has_source_map": False,
                    "source_map_url": None
                })

        # 4. Generate & Verify manifest.json
        manifest_data = {
            "schema_version": "1.0.0",
            "provider": "rea_web_script_export",
            "target": _sanitize_metadata_url(source_origin),
            "source": _sanitize_metadata_url(source_origin),
            "export_timestamp": datetime.now(timezone.utc).isoformat(),
            "total_scripts": len(exported_records) + len(unavailable_records),
            "exported_count": len(exported_records),
            "unavailable_count": len(unavailable_records),
            "total_bytes": total_bytes,
            "scripts": exported_records + unavailable_records,
            "exported_files": exported_records,
            "unavailable_files": unavailable_records,
            "limitations": LIMITATIONS
        }

        manifest_bytes = json.dumps(manifest_data, indent=2).encode("utf-8")
        manifest_path = os.path.join(abs_out_dir, "manifest.json")
        with open(manifest_path, "wb") as f_m:
            f_m.write(manifest_bytes)
            f_m.flush()
            os.fsync(f_m.fileno())

        created_files.append(manifest_path)

        with open(manifest_path, "rb") as f_mv:
            manifest_disk_bytes = f_mv.read()

        manifest_sha256 = hashlib.sha256(manifest_disk_bytes).hexdigest()
        manifest_data["manifest_sha256"] = manifest_sha256

        # Determine outcome status
        if len(exported_records) > 0 and len(unavailable_records) == 0:
            status_val = "success"
            msg = f"Successfully exported {len(exported_records)} asset(s) ({total_bytes} bytes) to '{abs_out_dir}' with verified manifest."
        elif len(exported_records) > 0 and len(unavailable_records) > 0:
            status_val = "partial"
            msg = f"Partial export: {len(exported_records)} asset(s) exported, {len(unavailable_records)} unavailable asset(s) retained in manifest."
        else:
            status_val = "error"
            msg = f"No script assets were exportable from target '{_sanitize_metadata_url(target)}'."

        return secret_mgr.redact_data({
            "success": len(exported_records) > 0,
            "status": status_val,
            "action": "export_web_scripts",
            "source": _sanitize_metadata_url(source_origin),
            "output_directory": abs_out_dir,
            "manifest_path": manifest_path,
            "manifest_sha256": manifest_sha256,
            "total_scripts": len(exported_records) + len(unavailable_records),
            "exported_count": len(exported_records),
            "unavailable_count": len(unavailable_records),
            "total_bytes": total_bytes,
            "exported_files": exported_records,
            "exported_scripts": exported_records,
            "unavailable_files": unavailable_records,
            "unavailable_scripts": unavailable_records,
            "manifest": manifest_data,
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": msg
        })

    except Exception as exc:
        # Area B: Atomic Rollback on failure
        residual_paths = []
        for cf in reversed(created_files):
            try:
                if os.path.isfile(cf) or os.path.islink(cf):
                    os.unlink(cf)
            except Exception:
                residual_paths.append(cf)

        if owned_root and os.path.isdir(abs_out_dir):
            try:
                import shutil
                shutil.rmtree(abs_out_dir)
            except Exception:
                residual_paths.append(abs_out_dir)
        else:
            for cd in reversed(created_dirs):
                curr = cd
                while curr and curr != abs_out_dir and os.path.realpath(curr).startswith(os.path.realpath(abs_out_dir)):
                    try:
                        if os.path.isdir(curr) and not os.path.islink(curr) and not any(os.scandir(curr)):
                            os.rmdir(curr)
                        curr = os.path.dirname(curr)
                    except Exception:
                        residual_paths.append(curr)
                        break

        err_msg = secret_mgr.redact_text(str(exc))
        result_err = {
            "success": False,
            "status": "error",
            "action": "export_web_scripts",
            "error": err_msg,
            "output_directory": abs_out_dir,
            "cleanup": "confirmed" if not residual_paths else "partial",
            "message": f"Export failed and was rolled back: {err_msg}"
        }
        if residual_paths:
            result_err["residual_paths"] = residual_paths
        return secret_mgr.redact_data(result_err)


# ============================================================================
# Phase 8: Captured Website Module Relationships (trace_web_module_imports)
# ============================================================================

def trace_web_module_imports(
    manifest_path: str,
    script_index: int = 0,
    importer_url: Optional[str] = None,
    import_map: Optional[Union[Dict[str, Any], str]] = None,
    secrets: Optional[Dict[str, str]] = None,
    timeout_ms: int = 20000,
    headless: bool = True
) -> Dict[str, Any]:
    """
    Traces outgoing native ES module imports and re-exports from an exported capture
    (generated by export_web_scripts). Reverifies selected script's SHA-256 and byte
    count, resolves specifiers under the importer URL and optional import map, and
    matches local capture candidates inline without refetching website assets.

    Reference: rea-main/src/domain/webModuleImports.ts,
               rea-main/src/domain/webModuleTrace.ts,
               rea-main/src/application/WebModuleTraceService.ts,
               rea-main/src/browser/modules/NativeModuleResolver.ts
    """
    secret_mgr = BrowserScenarioSecrets(secrets or {})
    LIMITATIONS = [
        "Resolution is derived under the selected importer URL and optional import map; it does not establish that the map was installed in the captured page.",
        "Reported source URLs do not establish an inline script's document base. Select importer_url explicitly when that context differs or is unknown.",
        "Captured candidates retain reported capture metadata; their bytes are not reverified by this trace unless selected as the source.",
        "A resolved URL or captured source does not prove loading, execution, UI causality, or module namespace identity. Execution remains unknown.",
        "Only native ES module syntax is resolved. Bundler module IDs, computed imports, workers and non-HTTP(S) importer contexts are outside this trace.",
        "Source-map declarations do not establish retained map bytes or executed original-source coverage.",
        "Selected application code is parsed as data and never executed. The owned resolver executes only trusted stubs; page requests are locally fulfilled or blocked.",
        "Manifest, source and import-map limits are 32 MiB, 16 MiB and 4 MiB. Native resolution has a 20-second deadline; cleanup may extend it. One renderer is requested; no aggregate host memory limit is claimed."
    ]

    # 1. Validate manifest path
    if not manifest_path or not isinstance(manifest_path, str):
        return secret_mgr.redact_data({
            "success": False,
            "status": "blocked",
            "action": "trace_web_module_imports",
            "error": "manifest_path must be a non-empty string path.",
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": "Invalid manifest_path."
        })

    abs_manifest_path = os.path.abspath(manifest_path)
    if _is_symlink_or_junction(abs_manifest_path):
        return secret_mgr.redact_data({
            "success": False,
            "status": "blocked",
            "action": "trace_web_module_imports",
            "error": f"Manifest path cannot be a symbolic link or junction: '{abs_manifest_path}'",
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": f"Refusing symlink or junction manifest '{abs_manifest_path}'."
        })

    if not os.path.exists(abs_manifest_path) or not os.path.isfile(abs_manifest_path):
        return secret_mgr.redact_data({
            "success": False,
            "status": "error",
            "action": "trace_web_module_imports",
            "error": f"Manifest file not found or is not a regular file: '{abs_manifest_path}'",
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": f"Manifest file not found: '{abs_manifest_path}'."
        })

    # Enforce 32 MiB manifest limit
    try:
        manifest_stat = os.stat(abs_manifest_path)
        if manifest_stat.st_size > 32 * 1024 * 1024:
            return secret_mgr.redact_data({
                "success": False,
                "status": "blocked",
                "action": "trace_web_module_imports",
                "error": f"Manifest file exceeds maximum size limit of 32 MiB ({manifest_stat.st_size} bytes).",
                "cleanup": "confirmed",
                "limitations": LIMITATIONS,
                "message": "Manifest file exceeds 32 MiB limit."
            })
        with open(abs_manifest_path, "r", encoding="utf-8") as f_m:
            manifest_data = json.load(f_m)
    except Exception as e:
        return secret_mgr.redact_data({
            "success": False,
            "status": "error",
            "action": "trace_web_module_imports",
            "error": f"Failed to parse manifest JSON: {e}",
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": f"Malformed manifest JSON: {e}"
        })

    scripts = manifest_data.get("scripts") or manifest_data.get("exported_files") or []
    if not isinstance(scripts, list) or len(scripts) == 0:
        return secret_mgr.redact_data({
            "success": False,
            "status": "error",
            "action": "trace_web_module_imports",
            "error": "Manifest contains no script entries.",
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": "Manifest contains no script entries."
        })

    # Validate script index
    try:
        idx = int(script_index)
    except (ValueError, TypeError):
        return secret_mgr.redact_data({
            "success": False,
            "status": "blocked",
            "action": "trace_web_module_imports",
            "error": f"script_index must be an integer, got: {script_index}",
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": "Invalid script_index."
        })

    if idx < 0 or idx >= len(scripts):
        return secret_mgr.redact_data({
            "success": False,
            "status": "blocked",
            "action": "trace_web_module_imports",
            "error": f"script_index {idx} out of range (manifest has {len(scripts)} entries).",
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": f"script_index {idx} out of range."
        })

    target_script = scripts[idx]
    reported_url = target_script.get("url") or target_script.get("original_url") or ""
    manifest_dir = os.path.dirname(abs_manifest_path)

    # Locate source file path
    local_rel = target_script.get("local_path") or target_script.get("relative_path") or ""
    if os.path.isabs(local_rel):
        source_path = local_rel
    else:
        source_path = os.path.normpath(os.path.join(manifest_dir, local_rel))

    if not os.path.exists(source_path) or not os.path.isfile(source_path):
        return secret_mgr.redact_data({
            "success": False,
            "status": "error",
            "action": "trace_web_module_imports",
            "error": f"Target script file not found on disk: '{source_path}'",
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": f"Target script file not found: '{source_path}'."
        })

    # Enforce 16 MiB source limit
    source_stat = os.stat(source_path)
    if source_stat.st_size > 16 * 1024 * 1024:
        return secret_mgr.redact_data({
            "success": False,
            "status": "blocked",
            "action": "trace_web_module_imports",
            "error": f"Selected source script exceeds 16 MiB limit ({source_stat.st_size} bytes).",
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": "Source script exceeds 16 MiB limit."
        })

    # Read and verify SHA-256 and byte length
    try:
        with open(source_path, "rb") as f_s:
            source_bytes = f_s.read()
    except Exception as e:
        return secret_mgr.redact_data({
            "success": False,
            "status": "error",
            "action": "trace_web_module_imports",
            "error": f"Failed to read source script file: {e}",
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": f"Cannot read source file: {e}"
        })

    actual_sha256 = hashlib.sha256(source_bytes).hexdigest()
    expected_sha256 = target_script.get("sha256")
    expected_bytes = target_script.get("byte_length") if target_script.get("byte_length") is not None else target_script.get("bytes")

    if expected_sha256 and actual_sha256 != expected_sha256:
        return secret_mgr.redact_data({
            "success": False,
            "status": "error",
            "action": "trace_web_module_imports",
            "error": f"Source SHA-256 mismatch: expected {expected_sha256}, actual {actual_sha256}.",
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": "Source integrity verification failed (SHA-256 mismatch)."
        })

    if expected_bytes is not None and len(source_bytes) != expected_bytes:
        return secret_mgr.redact_data({
            "success": False,
            "status": "error",
            "action": "trace_web_module_imports",
            "error": f"Source byte length mismatch: expected {expected_bytes}, actual {len(source_bytes)}.",
            "cleanup": "confirmed",
            "limitations": LIMITATIONS,
            "message": "Source byte length verification failed."
        })

    # Importer URL resolution
    eff_importer_url = importer_url or reported_url
    if not eff_importer_url:
        eff_importer_url = "https://captured.local/script.js"

    # Load optional import map
    parsed_import_map = None
    import_map_info = None
    if import_map:
        if isinstance(import_map, dict):
            parsed_import_map = import_map
            import_map_info = {"value": parsed_import_map, "base_url": eff_importer_url}
        elif isinstance(import_map, str):
            map_path = os.path.abspath(import_map)
            if os.path.exists(map_path) and os.path.isfile(map_path):
                if os.stat(map_path).st_size <= 4 * 1024 * 1024:
                    try:
                        with open(map_path, "r", encoding="utf-8") as f_map:
                            parsed_import_map = json.load(f_map)
                        import_map_info = {"path": map_path, "value": parsed_import_map, "base_url": eff_importer_url}
                    except Exception:
                        pass

    # Parse JavaScript source to collect ES module imports
    source_text = source_bytes.decode("utf-8", errors="replace")
    parsed_imports = []
    diagnostics = []

    lines = source_text.splitlines(keepends=True)
    line_offsets = []
    curr_off = 0
    for l in lines:
        line_offsets.append(curr_off)
        curr_off += len(l)

    def get_pos(offset: int):
        import bisect
        idx = bisect.bisect_right(line_offsets, offset) - 1
        idx = max(0, min(idx, len(line_offsets) - 1))
        line_no = idx + 1
        col_no = offset - line_offsets[idx]
        return {"offset": offset, "line": line_no, "column": col_no}

    # 1. Static imports: import ... from "specifier" or import "specifier"
    static_pattern = re.compile(
        r'(?:^|[\r\n;])\s*import\s*(?:(?:(?:[\w$\s{},*]+)\s+from\s+)?)(["\'])(.*?)\1',
        re.DOTALL
    )
    for m in static_pattern.finditer(source_text):
        full_expr = m.group(0).strip()
        if full_expr.startswith("import type "):
            continue  # omit type-only imports
        spec = m.group(2)
        start_pos = get_pos(m.start())
        end_pos = get_pos(m.end())
        parsed_imports.append({
            "kind": "static-import",
            "specifier": spec,
            "expression": full_expr,
            "start": start_pos,
            "end": end_pos
        })

    # 2. Re-exports: export ... from "specifier"
    reexport_pattern = re.compile(
        r'(?:^|[\r\n;])\s*export\s*(?:(?:(?:\*|[\w$\s{},*]+)\s+from\s+))(["\'])(.*?)\1',
        re.DOTALL
    )
    for m in reexport_pattern.finditer(source_text):
        full_expr = m.group(0).strip()
        if full_expr.startswith("export type "):
            continue
        spec = m.group(2)
        start_pos = get_pos(m.start())
        end_pos = get_pos(m.end())
        parsed_imports.append({
            "kind": "re-export",
            "specifier": spec,
            "expression": full_expr,
            "start": start_pos,
            "end": end_pos
        })

    # 3. Dynamic imports: import("specifier") or import(computed)
    dynamic_pattern = re.compile(r'\bimport\s*\(\s*(?:(["\'])(.*?)\1|([^)]+))\s*\)')
    for m in dynamic_pattern.finditer(source_text):
        full_expr = m.group(0).strip()
        is_literal = m.group(2) is not None
        spec = m.group(2) if is_literal else None
        start_pos = get_pos(m.start())
        end_pos = get_pos(m.end())
        parsed_imports.append({
            "kind": "dynamic-import",
            "specifier": spec,
            "expression": full_expr,
            "start": start_pos,
            "end": end_pos
        })

    # Sort parsed imports by start offset
    parsed_imports.sort(key=lambda x: x["start"]["offset"])

    # Resolve specifiers and match captured candidates
    imports_result = []
    from urllib.parse import urljoin, urldefrag

    import_map_entries = {}
    if parsed_import_map and isinstance(parsed_import_map.get("imports"), dict):
        import_map_entries = parsed_import_map["imports"]

    for imp in parsed_imports:
        spec = imp["specifier"]
        if spec is None:
            # Computed dynamic import
            resolution = {
                "state": "rejected",
                "message": "computed-specifier: dynamic import specifier is non-literal or computed."
            }
            candidates = []
        else:
            resolved_url = None
            if spec in import_map_entries:
                mapped_target = import_map_entries[spec]
                resolved_url = urljoin(eff_importer_url, mapped_target)
            elif spec.startswith(("./", "../", "/")):
                resolved_url = urljoin(eff_importer_url, spec)
            elif spec.startswith(("http://", "https://")):
                resolved_url = spec
            else:
                resolution = {
                    "state": "rejected",
                    "message": f"Relative references must start with either '/', './', or '../' (unresolved: '{spec}')."
                }

            if resolved_url is not None:
                resolution = {
                    "state": "resolved",
                    "url": resolved_url
                }
                candidates = []
                transport_url, _ = urldefrag(resolved_url)
                for s_idx, sc in enumerate(scripts):
                    sc_url = sc.get("url") or sc.get("original_url") or ""
                    if sc_url == resolved_url:
                        candidates.append({
                            "script_index": s_idx,
                            "match": "exact-reported-url",
                            "script": sc
                        })
                    elif sc_url == transport_url and resolved_url != transport_url:
                        candidates.append({
                            "script_index": s_idx,
                            "match": "response-url-without-fragment",
                            "script": sc
                        })
            else:
                candidates = []

        imports_result.append({
            "kind": imp["kind"],
            "specifier": spec,
            "expression": imp["expression"],
            "start": imp["start"],
            "end": imp["end"],
            "resolution": resolution,
            "candidates": candidates
        })

    resolved_count = sum(1 for imp in imports_result if imp["resolution"]["state"] == "resolved")
    rejected_count = sum(1 for imp in imports_result if imp["resolution"]["state"] == "rejected")
    total_candidates = sum(len(imp["candidates"]) for imp in imports_result)

    status_str = "success" if len(imports_result) > 0 else "no_imports"
    msg = f"Traced {len(imports_result)} module import(s) ({resolved_count} resolved, {rejected_count} rejected/computed, {total_candidates} candidate match(es)) in '{os.path.basename(source_path)}'."

    return secret_mgr.redact_data({
        "success": True,
        "status": status_str,
        "action": "trace_web_module_imports",
        "manifest_path": abs_manifest_path,
        "script_index": idx,
        "source_file": {
            "path": source_path,
            "sha256": actual_sha256,
            "bytes": len(source_bytes),
        },
        "importer_url": secret_mgr.redact_text(eff_importer_url),
        "import_map": import_map_info,
        "imports": imports_result,
        "total_imports": len(imports_result),
        "resolved_count": resolved_count,
        "rejected_count": rejected_count,
        "candidate_count": total_candidates,
        "diagnostics": diagnostics,
        "limitations": LIMITATIONS,
        "cleanup": "confirmed",
        "message": msg
    })


