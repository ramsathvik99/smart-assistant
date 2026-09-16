"""
⚠️ DEPRECATED MODULE — DO NOT USE

This module has been superseded by core/unified_command_router.py

See: core/ROUTING_AUTHORITY.md

Do NOT use this module. All command routing now goes through:
  core.unified_command_router.route_and_execute()
"""

# LEGACY CODE BELOW - NOT USED
# ============================================================================

import logging
from typing import Dict, Any, Optional
from core.execution_dispatcher import (
    ExecutionDispatcher, ExecutionRequest, MultiActionRequest, IntentType
)
from core.intent_resolver import resolve_intent, detect_multi_intent
from core.module_adapters import execute_module

logger = logging.getLogger(__name__)


class DispatcherIntegration:
    """Main integration layer for command execution"""
    
    def __init__(self, confidence_threshold: float = 0.65):
        """Initialize dispatcher integration"""
        self.dispatcher = ExecutionDispatcher(confidence_threshold)
        self.confidence_threshold = confidence_threshold
        
        logger.info(
            f"[DISPATCHER INTEGRATION] Initialized with confidence threshold: {confidence_threshold}"
        )
    
    def process_command(self, user_input: str) -> Dict[str, Any]:
        """
        Main entry point for processing user commands
        
        Args:
            user_input: Raw user input string
            
        Returns:
            Structured response with execution result
        """
        logger.info(f"[DISPATCH PIPELINE] Processing: '{user_input}'")
        
        try:
            # STEP 1: Detect multi-intent
            multi_request = detect_multi_intent(user_input)
            if multi_request:
                return self._process_multi_intent(multi_request, user_input)
            
            # STEP 2: Resolve single intent
            request, confidence = resolve_intent(user_input)
            
            if not request:
                return self._error_response("Could not parse command")
            
            logger.info(
                f"[DISPATCH PIPELINE] Resolved intent: {request.intent.value} | "
                f"Confidence: {confidence:.2f}"
            )
            
            # STEP 3: Dispatch to appropriate module
            response = self._execute_request(request)
            
            return response
        
        except Exception as e:
            logger.error(f"[DISPATCH PIPELINE] Error: {e}")
            return self._error_response(f"Processing error: {str(e)}")
    
    def _process_multi_intent(
        self,
        multi_request: MultiActionRequest,
        raw_input: str
    ) -> Dict[str, Any]:
        """Process multi-intent command"""
        
        logger.info(
            f"[DISPATCH PIPELINE MULTI] Processing {len(multi_request)} intents"
        )
        
        # For now, execute sequentially without confirmation
        # In production, could request user confirmation for certain combinations
        
        results = []
        all_success = True
        
        for i, request in enumerate(multi_request.intents):
            logger.info(
                f"[DISPATCH PIPELINE MULTI] Executing intent {i+1}/{len(multi_request)}: "
                f"{request.intent.value}"
            )
            
            result = self._execute_request(request)
            results.append(result)
            
            if not result.get("success", False):
                all_success = False
        
        return {
            "status": "success" if all_success else "partial_success",
            "multi_action": True,
            "total_intents": len(multi_request.intents),
            "results": results,
            "execution_mode": multi_request.execution_mode
        }
    
    def _execute_request(self, request: ExecutionRequest) -> Dict[str, Any]:
        """Execute single intent request"""
        
        # Check if should fallback to LLM
        if self._should_fallback_to_llm(request):
            logger.info(
                f"[DISPATCH PIPELINE] Routing to LLM fallback | "
                f"Intent: {request.intent.value} | "
                f"Confidence: {request.confidence:.2f}"
            )
            return self._execute_llm_fallback(request)
        
        # Get module and handler
        module_name, handler_name = self._get_module_for_intent(request.intent)
        
        logger.info(
            f"[DISPATCH PIPELINE] Routing to module | "
            f"Module: {module_name} | Handler: {handler_name}"
        )
        
        # Execute module
        try:
            result = execute_module(
                module_name,
                handler_name,
                request.entities,
                request.input_text
            )
            
            return {
                "status": "success" if result.get("success") else "failed",
                "intent": request.intent.value,
                "confidence": request.confidence,
                "module": module_name,
                "handler": handler_name,
                "result": result
            }
        
        except Exception as e:
            logger.error(f"[DISPATCH PIPELINE] Module execution error: {e}")
            return self._execute_llm_fallback(request)
    
    def _should_fallback_to_llm(self, request: ExecutionRequest) -> bool:
        """Determine if command should go to LLM"""
        
        # CRITICAL: Chat/General Knowledge always go to LLM
        if request.intent in {IntentType.CHAT, IntentType.GENERAL_KNOWLEDGE}:
            return True
        
        # Check confidence threshold
        if request.confidence < self.confidence_threshold:
            logger.warning(
                f"[DISPATCH DECISION] Low confidence {request.confidence:.2f} < "
                f"{self.confidence_threshold} for {request.intent.value}"
            )
            return True
        
        return False
    
    def _get_module_for_intent(self, intent: IntentType) -> tuple:
        """Get module and handler for intent"""
        
        mapping = {
            IntentType.OPEN_APPLICATION: ("launcher_engine", "open_application"),
            IntentType.CLOSE_APPLICATION: ("launcher_engine", "close_application"),
            IntentType.PLAY_MUSIC: ("music_engine", "play"),
            IntentType.STOP_MUSIC: ("music_engine", "stop"),
            IntentType.PAUSE_MUSIC: ("music_engine", "pause"),
            IntentType.RESUME_MUSIC: ("music_engine", "resume"),
            IntentType.EMAIL_SEND: ("email_controller", "send_email"),
            IntentType.EMAIL_READ: ("email_controller", "read_email"),
            IntentType.EMAIL_CHECK: ("email_controller", "check_inbox"),
            IntentType.WEATHER: ("weather_service", "get_weather"),
            IntentType.TIME_QUERY: ("system_service", "get_current_time"),
            IntentType.DATE_QUERY: ("system_service", "get_current_date"),
            IntentType.BROWSER: ("browser_engine", "open_page"),
            IntentType.BROWSER_SEARCH: ("browser_engine", "search"),
            IntentType.SYSTEM_CONTROL: ("system_controller", "execute"),
            IntentType.DEVICE_CONTROL: ("system_controller", "device_control"),
            IntentType.FILE_OPERATIONS: ("file_engine", "execute"),
            IntentType.POWER_ACTION: ("system_controller", "power_action"),
            IntentType.CHAT: ("llm_pipeline", "chat"),
            IntentType.GENERAL_KNOWLEDGE: ("llm_pipeline", "answer"),
        }
        
        return mapping.get(intent, ("llm_pipeline", "chat"))
    
    def _execute_llm_fallback(self, request: ExecutionRequest) -> Dict[str, Any]:
        """Execute LLM conversational fallback"""
        
        try:
            result = execute_module(
                "llm_pipeline",
                "chat",
                request.entities,
                request.input_text
            )
            
            return {
                "status": "success" if result.get("success") else "failed",
                "intent": request.intent.value,
                "confidence": request.confidence,
                "module": "llm_pipeline",
                "handler": "chat",
                "fallback": True,
                "result": result
            }
        
        except Exception as e:
            logger.error(f"[DISPATCH PIPELINE] LLM fallback error: {e}")
            return self._error_response("Fallback to LLM failed")
    
    def _error_response(self, message: str) -> Dict[str, Any]:
        """Create error response"""
        return {
            "status": "error",
            "message": message,
            "intent": "ERROR",
            "confidence": 0.0
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get execution statistics"""
        return self.dispatcher.get_statistics()
    
    def get_logs(self, limit: int = None) -> list:
        """Get execution logs"""
        return self.dispatcher.get_execution_logs(limit)
    
    def clear_logs(self):
        """Clear execution logs"""
        self.dispatcher.clear_execution_logs()


# Global integration instance
_integration = None


def get_dispatcher_integration(confidence_threshold: float = 0.65) -> DispatcherIntegration:
    """Get or create global dispatcher integration instance"""
    global _integration
    if _integration is None:
        _integration = DispatcherIntegration(confidence_threshold)
    return _integration


def reset_dispatcher_integration():
    """Reset global dispatcher integration"""
    global _integration
    _integration = None


def process_command(user_input: str) -> Dict[str, Any]:
    """Process user command through dispatcher"""
    integration = get_dispatcher_integration()
    return integration.process_command(user_input)


# Convenience function to replace RAGSystem for direct testing
def quick_dispatch(user_input: str) -> str:
    """Quick dispatch for testing - returns just the message"""
    result = process_command(user_input)
    
    if result.get("result"):
        message = result["result"].get("message", "")
        if message:
            return message
    
    return result.get("message", "No response")
