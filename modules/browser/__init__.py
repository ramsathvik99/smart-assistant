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
    build_flight_search_url,
    sanitize_browser_url,
    inspect_web_page,
    BrowserScenarioSecrets,
    execute_browser_scenario,
    compare_png_screenshots,
    inspect_web_network_capture,
    inspect_web_event_listeners,
    observe_web_execution,
    inspect_web_scripts,
    trace_web_source_location,
    correlate_browser_error_stack,
    diagnose_web_execution,
    execute_verified_browser_action,
    classify_browser_failure,
    reobserve_and_replan_action,
    execute_adaptive_browser_action,
    export_web_scripts,
    trace_web_module_imports
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
    'build_flight_search_url',
    'sanitize_browser_url',
    'inspect_web_page',
    'BrowserScenarioSecrets',
    'execute_browser_scenario',
    'compare_png_screenshots',
    'inspect_web_network_capture',
    'inspect_web_event_listeners',
    'observe_web_execution',
    'inspect_web_scripts',
    'trace_web_source_location',
    'correlate_browser_error_stack',
    'diagnose_web_execution',
    'execute_verified_browser_action',
    'classify_browser_failure',
    'reobserve_and_replan_action',
    'execute_adaptive_browser_action',
    'export_web_scripts',
    'trace_web_module_imports'
]


