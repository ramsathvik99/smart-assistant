!/usr/bin/env python3
"""Test script to verify intent routing fixes"""

from core.unified_command_router import unified_router

def test_routing():
    tests = [
        ("open whatsapp", "OPEN_APPLICATION"),
        ("open notepad", "OPEN_APPLICATION"),
        ("create folder ai", "FILE_OPERATIONS"),
        ("create a calculator in python", "CODE_GENERATION"),
        ("who is the president of usa", "RAG_SEARCH"),
        ("tell me about the new chatgpt version astra", "RAG_SEARCH"),
        ("what is the time", "TIME_QUERY"),
        ("what is today's date", "DATE_QUERY"),
        ("hello", "GENERAL_CONVERSATION"),
    ]
    
    print("=" * 60)
    print("ROUTING TEST RESULTS")
    print("=" * 60)
    
    for command, expected_intent in tests:
        result = unified_router.execute_single_action(command)
        actual_intent = result.get("intent", "UNKNOWN")
        response = result.get("response", "")
        
        status = "PASS" if actual_intent == expected_intent else "FAIL"
        print(f"{status} | Command: '{command}'")
        print(f"       | Expected: {expected_intent}, Got: {actual_intent}")
        if len(response) > 50:
            print(f"       | Response: {response[:50]}...")
        else:
            print(f"       | Response: {response}")
        print("-" * 60)

if __name__ == "__main__":
    test_routing()