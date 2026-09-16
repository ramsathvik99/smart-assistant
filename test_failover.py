#!/usr/bin/env python3
"""Test script to verify multi-key/multi-provider failover"""

from extensions.llm_engine import LLMEngine
from instance.config import settings as CONFIG

def test_failover():
    """Test the multi-key/multi-provider failover functionality"""
    
    print("=" * 60)
    print("PROVIDER/KEY INVENTORY")
    print("=" * 60)
    
    print(f"OpenAI keys: {len(CONFIG.get('OPENAI_API_KEYS', []))} configured")
    print(f"Groq keys: {len(CONFIG.get('GROQ_API_KEYS', []))} configured")
    print(f"Gemini keys: {len(CONFIG.get('GEMINI_API_KEYS', []))} configured")
    print(f"DeepSeek keys: {len(CONFIG.get('DEEPSEEK_API_KEYS', []))} configured")
    print(f"HuggingFace keys: {len(CONFIG.get('HF_API_KEYS', []))} configured")
    
    print("\n" + "=" * 60)
    print("FAILOVER TEST")
    print("=" * 60)
    
    engine = LLMEngine()
    
    # Test with a simple prompt
    test_prompt = "What is 2 + 2?"
    
    print(f"\nTest prompt: '{test_prompt}'")
    print("Testing provider/key failover...")
    
    response = engine.get_completion(test_prompt, max_tokens=50)
    
    if response:
        print(f"SUCCESS: Got response from failover chain")
        print(f"Response: {response}")
    else:
        print("FAIL: All providers/keys failed")
    
    print("\n" + "=" * 60)
    print("INTENT PRESERVATION TEST")
    print("=" * 60)
    
    # Test that knowledge questions don't fall back to code generation
    from core.unified_command_router import unified_router
    
    knowledge_tests = [
        "who is the president of usa",
        "tell me about quantum computing",
        "explain black holes"
    ]
    
    for test in knowledge_tests:
        result = unified_router.execute_single_action(test)
        intent = result.get("intent", "UNKNOWN")
        response = result.get("response", "")
        
        print(f"\nTest: '{test}'")
        print(f"Intent: {intent}")
        
        if response:
            print(f"Contains 'code file': {'code file' in response.lower()}")
            print(f"Contains 'generated': {'generated' in response.lower()}")
            
            if intent in ["RAG_SEARCH", "GENERAL_CONVERSATION"] and "code file" not in response.lower():
                print("PASS: Intent preserved correctly")
            else:
                print("FAIL: Intent preservation issue detected")
        else:
            print("Response: None (all providers failed)")
            if intent in ["RAG_SEARCH", "GENERAL_CONVERSATION"]:
                print("PASS: Intent preserved correctly (but no response due to provider failure)")
            else:
                print("FAIL: Intent preservation issue detected")

if __name__ == "__main__":
    test_failover()