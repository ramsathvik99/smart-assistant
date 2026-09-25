"""
Browser Module for Nova Smart Assistant.
Provides controlled web navigation, page text extraction, and screenshot capture.
"""

from .browser_controller import (
    open_url,
    extract_page_text,
    take_page_screenshot,
    search_web
)

__all__ = [
    'open_url',
    'extract_page_text',
    'take_page_screenshot',
    'search_web'
]
