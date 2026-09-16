"""
assistant_os/browser_manager/tests/test_browser_manager.py
======================================================
NOVA OS - Browser Automation Manager: Unit Tests

Coverage:
    - Navigation forward calls to BrowserEngine.
    - Mocked pyautogui click and fill events.
    - Page text extraction utilizing BeautifulSoup mock calls.
    - Screenshot file writing via mocked pyautogui image capture.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from assistant_os.browser_manager.browser_manager import BrowserAutomationManager


class TestBrowserAutomationManager(unittest.TestCase):

    @patch("assistant_os.browser_manager.browser_manager.BrowserEngine")
    def setUp(self, mock_be_class):
        self.mock_be = MagicMock()
        mock_be_class.return_value = self.mock_be
        self.manager = BrowserAutomationManager()

    def test_navigate(self):
        self.mock_be.open_page.return_value = "Opening google."
        res = self.manager.navigate("google", "https://google.com")
        self.assertEqual(res, "Opening google.")
        self.mock_be.open_page.assert_called_once_with("google", "https://google.com")

    @patch("pyautogui.click")
    def test_click(self, mock_click):
        res = self.manager.click(100, 200)
        self.assertIn("Clicked at (100, 200)", res)
        mock_click.assert_called_once_with(100, 200)

    @patch("pyautogui.write")
    def test_fill(self, mock_write):
        res = self.manager.fill("Hello World")
        self.assertIn("filled successfully", res)
        mock_write.assert_called_once_with("Hello World", interval=0.01)

    @patch("assistant_os.browser_manager.browser_manager.requests.get")
    def test_extract(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><head><title>Test Page</title></head><body><p>Clean text extract</p></body></html>"
        mock_get.return_value = mock_resp

        res = self.manager.extract("https://example.com")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["title"], "Test Page")
        self.assertIn("Clean text extract", res["text"])

    @patch("pyautogui.screenshot")
    def test_screenshot(self, mock_ss):
        mock_img = MagicMock()
        mock_ss.return_value = mock_img

        res = self.manager.screenshot("dummy/path/file.png")
        self.assertIn("Screenshot saved to dummy/path/file.png.", res)
        mock_img.save.assert_called_once_with("dummy/path/file.png")


if __name__ == "__main__":
    unittest.main(verbosity=2)
