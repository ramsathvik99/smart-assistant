"""
Runtime Behavioral Regression Repair Tests
Verifies real production routing and contextual execution fixes:
1. System telemetry routing (CPU, RAM, GPU, combined, GPU memory)
2. Browser link extraction and table extraction with natural addressing prefixes
3. Browser link & table follow-up context (link counts, ordinal link display/open, table rows)
4. Flight search artifact reference resolution ("open the flight search")
5. Ambiguous flight search clarification ("Mumbai Express")
6. RAG boundary protection (strictly preserving deterministic routing)
7. PPT artifact reference resolution ("Friday analyse that PPT")
8. Truthful local execution when LLMs are unavailable
"""

import os
import pytest
from core.unified_command_router import UnifiedCommandRouter, Intent
from extensions.context_manager import get_manager, ContextType
from extensions.dialogue_state_manager import get_dialogue_manager
from modules.system_controller import (
    get_cpu_metrics,
    get_ram_metrics,
    get_gpu_telemetry,
    get_system_telemetry_summary
)


@pytest.fixture
def router():
    r = UnifiedCommandRouter()
    r._semantic_enabled = False  # Ensure deterministic routing works without LLM
    return r


@pytest.fixture
def clean_context():
    cm = get_manager()
    cm.user_artifacts.clear()
    cm.active_context = {
        "type": ContextType.NONE,
        "name": None,
        "metadata": {},
        "timestamp": 0,
        "awaiting_confirmation": False,
        "last_app": None,
        "last_browser": None,
        "last_action": None,
        "awaiting_input": False,
        "awaiting_type": None
    }
    dm = get_dialogue_manager("1")
    dm.current_state.session_context.clear()
    return cm, dm


# ── 1. SYSTEM TELEMETRY NATURAL-LANGUAGE ROUTING ────────────────────────────

def test_cpu_telemetry_natural_routing(router):
    cpu_queries = [
        "can I check my CPU",
        "check my cpu",
        "what is my cpu usage",
        "how much cpu am I using",
        "check cpu",
        "what's my cpu"
    ]
    for q in cpu_queries:
        intent, params = router.route_command(q)
        assert intent == Intent.DEVICE_CONTROL, f"Failed on query: {q}"
        assert params.get("action") in ("cpu_metrics", "system_telemetry_summary")
        res = router.execute_single_action(q, user_id=1)
        assert res.get("status") == "success"
        assert "overall_percent" in res or "cpu_total_percent" in res or "cpu" in res


def test_gpu_and_gpu_memory_telemetry_routing(router):
    gpu_queries = [
        "check gpu",
        "how much gpu am I using",
        "how much gpu memory am I using",
        "GPU memory am I using",
        "check my GPU",
        "gpu usage",
        "gpu telemetry"
    ]
    for q in gpu_queries:
        intent, params = router.route_command(q)
        assert intent == Intent.DEVICE_CONTROL, f"Failed on query: {q}"
        assert params.get("action") == "gpu_telemetry"
        res = router.execute_single_action(q, user_id=1)
        assert res.get("status") == "success"
        assert "message" in res


def test_ram_telemetry_routing(router):
    ram_queries = [
        "check ram",
        "how much ram is free",
        "check my RAM",
        "what is my ram usage"
    ]
    for q in ram_queries:
        intent, params = router.route_command(q)
        assert intent == Intent.DEVICE_CONTROL, f"Failed on query: {q}"
        assert params.get("action") == "ram_metrics"
        res = router.execute_single_action(q, user_id=1)
        assert res.get("status") == "success"
        assert "total_gb" in res or "percent" in res


def test_combined_system_telemetry_routing(router):
    combined_queries = [
        "check my CPU RAM and GPU usage",
        "check cpu ram and gpu",
        "show system usage",
        "check system usage"
    ]
    for q in combined_queries:
        intent, params = router.route_command(q)
        assert intent == Intent.DEVICE_CONTROL, f"Failed on query: {q}"
        assert params.get("action") == "system_telemetry_summary"
        res = router.execute_single_action(q, user_id=1)
        assert res.get("status") == "success"
        assert "cpu" in res and "ram" in res and "gpu" in res
        assert "System telemetry:" in res.get("message", "")


# ── 2. BROWSER LINK EXTRACTION & FOLLOW-UP CONTEXT ──────────────────────────

def test_browser_link_extraction_with_addressing_prefix(router, clean_context, monkeypatch):
    cm, dm = clean_context
    fake_links = [
        {"text": "Python Software Foundation", "url": "https://python.org"},
        {"text": "Documentation", "url": "https://docs.python.org"},
        {"text": "PyPI Package Index", "url": "https://pypi.org"},
        {"text": "Community", "url": "https://python.org/community"},
    ]

    import modules.browser.browser_controller as bc
    monkeypatch.setattr(bc, "extract_page_links", lambda url, max_links=20: {
        "success": True, "status": "success", "url": url, "count": len(fake_links), "links": fake_links, "message": f"Found {len(fake_links)} hyperlinks."
    })

    # Test link extraction with "Friday" addressing prefix
    query = "Friday extract all the available links from this page"
    intent, params = router.route_command(query)
    assert intent == Intent.OPEN_APPLICATION
    assert params.get("action") == "extract_links"

    res = router.execute_single_action(query, user_id=1)
    assert res.get("status") == "success"
    assert res.get("count") == 4
    assert len(res.get("links")) == 4

    # Verify context persistence
    assert dm.current_state.session_context.get("last_extracted_links") == fake_links
    assert cm.active_context.get("last_extracted_links") == fake_links

    # 1. Follow-up: "how many links did you find?"
    q_count = "how many links did you find?"
    intent2, params2 = router.route_command(q_count)
    assert intent2 == Intent.OPEN_APPLICATION
    assert params2.get("action") == "count_links"
    res_count = router.execute_single_action(q_count, user_id=1)
    assert res_count.get("status") == "success"
    assert res_count.get("count") == 4
    assert "4" in res_count.get("response")

    # 2. Follow-up: "show me the third link"
    q_third = "show me the third link"
    intent3, params3 = router.route_command(q_third)
    assert intent3 == Intent.OPEN_APPLICATION
    assert params3.get("action") == "get_link"
    res_third = router.execute_single_action(q_third, user_id=1)
    assert res_third.get("status") == "success"
    assert res_third.get("link", {}).get("url") == "https://pypi.org"

    # 3. Follow-up: "open the third one"
    opened_urls = []
    monkeypatch.setattr(bc, "open_url", lambda url: opened_urls.append(url) or {"success": True, "url": url})
    q_open = "open the third one"
    intent4, params4 = router.route_command(q_open)
    assert intent4 == Intent.OPEN_APPLICATION
    assert params4.get("action") == "open_link"
    res_open = router.execute_single_action(q_open, user_id=1)
    assert res_open.get("status") == "success"
    assert "https://pypi.org" in opened_urls


# ── 3. BROWSER TABLE EXTRACTION & FOLLOW-UP CONTEXT ─────────────────────────

def test_browser_table_extraction_and_rows(router, clean_context, monkeypatch):
    cm, dm = clean_context
    sample_rows = [
        ["ID", "Name", "Role", "Department"],
        ["101", "Alice", "Lead Architect", "Engineering"],
        ["102", "Bob", "Systems Engineer", "Infrastructure"],
        ["103", "Charlie", "Security Analyst", "InfoSec"],
        ["104", "Diana", "Data Scientist", "AI Research"],
        ["105", "Evan", "DevOps Engineer", "Platform Operations"],
        ["106", "Fiona", "Product Specialist", "Operations"]
    ]

    import modules.browser.browser_controller as bc
    monkeypatch.setattr(bc, "extract_page_tables", lambda url: {
        "success": True, "status": "success", "url": url, "table_count": 1, "tables": [sample_rows], "message": "Extracted 1 table."
    })

    query = "extract the table from this page"
    intent, params = router.route_command(query)
    assert intent == Intent.OPEN_APPLICATION
    assert params.get("action") == "extract_tables"

    res = router.execute_single_action(query, user_id=1)
    assert res.get("status") == "success"
    assert res.get("table_count") == 1

    # Follow-up: "show me the first five rows"
    q_five = "show me the first five rows"
    intent2, params2 = router.route_command(q_five)
    assert intent2 == Intent.OPEN_APPLICATION
    assert params2.get("action") == "get_table_rows"
    res_five = router.execute_single_action(q_five, user_id=1)
    assert res_five.get("status") == "success"
    assert len(res_five.get("rows")) == 5
    assert "Alice" in res_five.get("response")

    # Follow-up: "what is the value in the third row?"
    q_third_row = "what is the value in the third row?"
    intent3, params3 = router.route_command(q_third_row)
    assert intent3 == Intent.OPEN_APPLICATION
    assert params3.get("action") == "get_table_row"
    res_third_row = router.execute_single_action(q_third_row, user_id=1)
    assert res_third_row.get("status") == "success"
    assert "Bob" in res_third_row.get("response") or "Systems Engineer" in res_third_row.get("response")


# ── 4. FLIGHT SEARCH REFERENCE & CLARIFICATION ──────────────────────────────

def test_flight_search_and_reference_opening(router, clean_context, monkeypatch):
    cm, dm = clean_context
    opened_urls = []
    import modules.browser.browser_controller as bc
    monkeypatch.setattr(bc, "open_url", lambda url: opened_urls.append(url) or {"success": True, "url": url})
    monkeypatch.setattr(bc, "build_flight_search_url", lambda origin, destination, departure_date=None, **kwargs: {
        "success": True,
        "status": "success",
        "url": f"https://www.google.com/travel/flights?q=flights+from+{origin}+to+{destination}",
        "message": f"Flight search for {origin} to {destination} opened."
    })

    # Step 1: Perform flight search
    q_search = "find flights from Hyderabad to Delhi tomorrow"
    intent, params = router.route_command(q_search)
    assert intent == Intent.OPEN_APPLICATION
    assert params.get("action") == "search_flights"

    res_search = router.execute_single_action(q_search, user_id=1)
    assert res_search.get("status") == "success"
    assert "google.com/travel/flights" in res_search.get("url")

    # Step 2: Open that flight search
    q_open = "open the flight search"
    intent2, params2 = router.route_command(q_open)
    assert intent2 == Intent.OPEN_APPLICATION
    assert params2.get("action") == "open"

    res_open = router.execute_single_action(q_open, user_id=1)
    assert res_open.get("status") == "success"
    assert "google.com/travel/flights" in res_open.get("url")
    assert any("google.com/travel/flights" in u for u in opened_urls)


def test_ambiguous_flight_clarification(router):
    q_ambiguous = "then what about flights from Hyderabad to Mumbai Express"
    intent, params = router.route_command(q_ambiguous)
    assert intent == Intent.OPEN_APPLICATION
    assert params.get("action") == "search_flights"

    res = router.execute_single_action(q_ambiguous, user_id=1)
    assert res.get("status") == "clarification_needed"
    assert "Air India Express" in res.get("response") or "Mumbai" in res.get("response")


# ── 5. RAG BOUNDARY PROTECTION ──────────────────────────────────────────────

def test_rag_boundary_preservation(router):
    local_commands = [
        "check my CPU",
        "check my GPU",
        "check my RAM",
        "check CPU RAM and GPU",
        "what wallpaper am I using",
        "extract links from this page",
        "extract the table from this page",
        "open that flight search",
        "profile this file",
        "diagnose this traceback"
    ]
    for cmd in local_commands:
        intent, params = router.route_command(cmd)
        assert intent != Intent.RAG_SEARCH, f"Local command '{cmd}' was hijacked by RAG_SEARCH!"
        assert intent != Intent.GENERAL_CONVERSATION, f"Local command '{cmd}' became general conversation!"


# ── 6. ARTIFACT CONTEXT PRESERVATION (PPT) ──────────────────────────────────

def test_preserve_ppt_artifact_followup(router, clean_context, tmp_path):
    cm, dm = clean_context
    sample_ppt = tmp_path / "Machine_Learning_Overview.pptx"
    sample_ppt.write_bytes(b"PK\x03\x04test_pptx_content")

    # Register PPT artifact
    cm.add_user_artifact(1, {
        "path": str(sample_ppt),
        "filepath": str(sample_ppt),
        "filename": "Machine_Learning_Overview.pptx",
        "type": "pptx",
        "source_action": "presentation_creation"
    })

    # Follow up: "Friday analyse that PPT"
    query = "Friday analyse that PPT"
    intent, params = router.route_command(query)
    assert intent == Intent.FILE_OPERATIONS
    assert params.get("action") == "profile_file"

    res = router.execute_single_action(query, user_id=1)
    assert res.get("status") == "success"
    assert res.get("category") == "presentation"
    assert "Machine_Learning_Overview.pptx" in res.get("response")
