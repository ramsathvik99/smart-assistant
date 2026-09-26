"""
Browser Module for Nova Smart Assistant.
Provides controlled web navigation, page text extraction, and screenshot capture.
"""

from .browser_controller import (
    open_url,
    extract_page_text,
    take_page_screenshot,
    search_web,
    click_element,
    type_into_element,
    scroll_page,
    press_key,
    fill_form_fields,
    extract_page_links,
    extract_page_tables,
    build_flight_search_url
)

__all__ = [
    'open_url',
    'extract_page_text',
    'take_page_screenshot',
    'search_web',
    'click_element',
    'type_into_element',
    'scroll_page',
    'press_key',
    'fill_form_fields',
    'extract_page_links',
    'extract_page_tables',
    'build_flight_search_url'
]
