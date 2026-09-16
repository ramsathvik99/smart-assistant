"""
⚠️ DEPRECATED MODULE — DO NOT USE

This module was a wrapper around the old dispatcher system.

All command routing now goes through:
  core.unified_command_router.route_and_execute()

See: core/ROUTING_AUTHORITY.md
"""

# LEGACY CODE BELOW - NOT USED
# ============================================================================

import logging
from typing import Dict, Any
from core.dispatcher_integration import DispatcherIntegration, process_command

logger = logging.getLogger(__name__)


class DispatcherWrapper:
    """
    Wrapper class providing unified interface for command execution.
    Replaces old routing with new Execution Dispatcher.
    """
    
    def __init__(self):
        self.dispatcher = DispatcherIntegration(confidence_threshold=0.65)
        logger.info("[DISPATCHER WRAPPER] Initialized with Execution Dispatcher")
    
    def execute_command(self, user_input: str) -> Dict[str, Any]:
        """
        Execute command using the new Execution Dispatcher
        
        Args:
            user_input: User input string
            
        Returns:
            Structured execution result
        """
        logger.info(f"[DISPATCHER WRAPPER] Processing: {user_input}")
        
        result = self.dispatcher.process_command(user_input)
        
        # Convert result to unified format
        return self._normalize_result(result)
    
    def _normalize_result(self, dispatcher_result: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize dispatcher result to unified format"""
        
        normalized = {
            "status": dispatcher_result.get("status", "error"),
            "intent": dispatcher_result.get("intent", "UNKNOWN"),
            "confidence": dispatcher_result.get("confidence", 0.0),
            "message": "",
            "response": "",
            "data": None,
        }
        
        # Extract message/response from result
        if dispatcher_result.get("result"):
            result_data = dispatcher_result["result"]
            if isinstance(result_data, dict):
                normalized["message"] = result_data.get("message", "")
                normalized["data"] = result_data.get("data")
            else:
                normalized["message"] = str(result_data)
        
        # For fallback/error results
        if dispatcher_result.get("message"):
            normalized["message"] = dispatcher_result["message"]
        
        # Keep track of module for debugging
        normalized["module"] = dispatcher_result.get("module", "unknown")
        normalized["handler"] = dispatcher_result.get("handler", "unknown")
        
        return normalized
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get execution statistics"""
        return self.dispatcher.get_statistics()
    
    def get_logs(self, limit: int = None):
        """Get execution logs"""
        return self.dispatcher.get_logs(limit)


# Global wrapper instance
_wrapper = None


def get_dispatcher_wrapper() -> DispatcherWrapper:
    """Get or create global dispatcher wrapper"""
    global _wrapper
    if _wrapper is None:
        _wrapper = DispatcherWrapper()
    return _wrapper


def execute_unified_command(user_input: str) -> Dict[str, Any]:
    """Execute command with unified interface"""
    wrapper = get_dispatcher_wrapper()
    return wrapper.execute_command(user_input)
