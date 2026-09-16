# extensions/rag_system/validator.py

class RAGValidator:
    def validate(self, intent, data):
        """
        Validates that the retrieved data is sufficient for the intent.
        Returns True if valid, False otherwise.
        """
        if not data:
            return False
            
        if "error" in data:
            print(f"[RAG VALIDATOR] Error in data: {data['error']}")
            return False
            
        if intent == "calendar_query":
            # Check if holiday info exists or specific data was found
            return "holidays" in data and len(data["holidays"]) > 0 or "today" in str(data)
            
        if intent == "memory_storage":
            # Storage is valid if the fact was saved successfully
            return "saved_fact" in data or "status" in data and data.get("status") == "success"
            
        if intent in ["memory_management", "memory_retrieval"]:
            # Check if memory was actually found
            if "status" in data and ("No specific memory" in str(data["status"]) or "No memories stored" in str(data["status"])):
                return False
            if "memory_value" in data and not data["memory_value"]:
                return False
            if "all_memory" in data:
                return True  # We have memory to reason over
            return True

            
        if intent in ["real_time_info", "dynamic_fact_query"]:
            # Check if search returned something useful (AI Overview, Answer Box, Knowledge Graph, or Organic Results)
            has_ai_overview = "ai_overview" in data and bool(data["ai_overview"])
            has_answer = "answer_box" in data and bool(data["answer_box"])
            has_kg = "knowledge_graph" in data and bool(data["knowledge_graph"])
            has_organic = "organic_results" in data and any(isinstance(s, str) and bool(s.strip()) for s in data["organic_results"])
            has_items = "organic_items" in data and len(data["organic_items"]) > 0
            
            if not (has_ai_overview or has_answer or has_kg or has_organic or has_items):
                print("[RAG VALIDATOR] Web search returned empty/unusable content.")
                return False
            return True
            
        if intent == "location_query":
            # Check if city or region was found
            return "city" in data or "region" in data
            
        return True # Default to True for non-factual or chat intents
