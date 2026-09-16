"""
⚠️ DEPRECATED MODULE — DO NOT USE

This module has been superseded by core/unified_command_router.py

The Execution Dispatcher was replaced with the Unified Command Router which
implements deterministic single-execution-path routing with 17 strict intents.

All command routing now happens through:
  core.unified_command_router.route_and_execute()

See: core/ROUTING_AUTHORITY.md

This file is kept for reference only. It is not imported or used in the active codebase.
"""

# LEGACY CODE BELOW - NOT USED
# ============================================================================

import logging
import time
import json
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger(__name__)


class IntentType(Enum):
    """Core intent types for execution dispatcher"""
    # Application & System Control
    OPEN_APPLICATION = "OPEN_APPLICATION"
    CLOSE_APPLICATION = "CLOSE_APPLICATION"
    SYSTEM_CONTROL = "SYSTEM_CONTROL"
    
    # Music Control
    PLAY_MUSIC = "PLAY_MUSIC"
    STOP_MUSIC = "STOP_MUSIC"
    PAUSE_MUSIC = "PAUSE_MUSIC"
    RESUME_MUSIC = "RESUME_MUSIC"
    
    # Email & Messaging
    EMAIL_SEND = "EMAIL_SEND"
    EMAIL_READ = "EMAIL_READ"
    EMAIL_CHECK = "EMAIL_CHECK"
    
    # Weather & Information
    WEATHER = "WEATHER"
    TIME_QUERY = "TIME_QUERY"
    DATE_QUERY = "DATE_QUERY"
    
    # Browser & Web
    BROWSER = "BROWSER"
    BROWSER_SEARCH = "BROWSER_SEARCH"
    
    # Conversation & Knowledge
    CHAT = "CHAT"
    GENERAL_KNOWLEDGE = "GENERAL_KNOWLEDGE"
    
    # System Actions
    POWER_ACTION = "POWER_ACTION"
    DEVICE_CONTROL = "DEVICE_CONTROL"
    FILE_OPERATIONS = "FILE_OPERATIONS"


class ExecutionStatus(Enum):
    """Execution status indicators"""
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    PENDING_CONFIRMATION = "pending_confirmation"
    FALLBACK_TO_LLM = "fallback_to_llm"


@dataclass
class ExecutionLog:
    """Comprehensive execution log record"""
    timestamp: str
    command_input: str
    detected_intent: str
    confidence_score: float
    confidence_threshold: float
    selected_module: str
    executed_function: str
    execution_status: str
    result: str
    execution_time_ms: float
    extra_metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ExecutionRequest:
    """Structured execution request"""
    intent: IntentType
    confidence: float
    input_text: str
    entities: Dict[str, Any]
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class MultiActionRequest:
    """Multi-intent execution request"""
    intents: List[ExecutionRequest]
    require_confirmation: bool = True
    execution_mode: str = "sequential"  # sequential or parallel
    
    def __len__(self):
        return len(self.intents)


class IntentToModuleRouter:
    """Maps intents to execution modules"""
    
    # Intent -> Module mapping with default handlers
    INTENT_MAPPING = {
        IntentType.OPEN_APPLICATION: ("launcher_engine", "open_application"),
        IntentType.CLOSE_APPLICATION: ("launcher_engine", "close_application"),
        IntentType.SYSTEM_CONTROL: ("system_controller", "execute_system_action"),
        
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
        
        IntentType.POWER_ACTION: ("system_controller", "power_action"),
        IntentType.DEVICE_CONTROL: ("system_controller", "device_control"),
        IntentType.FILE_OPERATIONS: ("file_engine", "execute_operation"),
        
        # Chat/LLM as fallback only
        IntentType.CHAT: ("llm_pipeline", "chat"),
        IntentType.GENERAL_KNOWLEDGE: ("llm_pipeline", "answer"),
    }
    
    @classmethod
    def get_module(cls, intent: IntentType) -> Tuple[str, str]:
        """Get module and handler function for intent"""
        return cls.INTENT_MAPPING.get(intent, ("llm_pipeline", "chat"))
    
    @classmethod
    def is_executable_intent(cls, intent: IntentType) -> bool:
        """Check if intent is executable (not chat/general_knowledge)"""
        chat_intents = {IntentType.CHAT, IntentType.GENERAL_KNOWLEDGE}
        return intent not in chat_intents


class ExecutionDispatcher:
    """
    Main Execution Dispatcher - routes intents to modules with confidence-based filtering.
    
    CRITICAL RULES:
    1. LLM pipeline is LAST FALLBACK ONLY
    2. If confidence > threshold for executable intent, NEVER send to chat
    3. Multi-intent commands return structured request for sequential/parallel execution
    4. All executions are comprehensively logged
    """
    
    def __init__(self, confidence_threshold: float = 0.65):
        """
        Initialize dispatcher
        
        Args:
            confidence_threshold: Min confidence to execute without LLM fallback (0.0-1.0)
        """
        self.confidence_threshold = confidence_threshold
        self.router = IntentToModuleRouter()
        self.execution_logs: List[ExecutionLog] = []
        self.module_handlers: Dict[str, Any] = {}
        
        logger.info(f"[DISPATCHER INIT] Confidence threshold: {self.confidence_threshold}")
    
    def register_module_handler(self, module_name: str, handler: Any):
        """Register module handler for execution"""
        self.module_handlers[module_name] = handler
        logger.info(f"[DISPATCHER] Registered module: {module_name}")
    
    def dispatch(self, request: ExecutionRequest) -> Dict[str, Any]:
        """
        Dispatch single intent request to appropriate module
        
        Args:
            request: ExecutionRequest with intent, confidence, entities
            
        Returns:
            Execution result dict with status, response, metadata
        """
        start_time = time.time()
        
        logger.info(
            f"[DISPATCHER DISPATCH] Intent: {request.intent.value} | "
            f"Confidence: {request.confidence:.2f} | "
            f"Input: {request.input_text}"
        )
        
        try:
            # CRITICAL: Check confidence threshold for executable intents
            if self._should_fallback_to_llm(request):
                return self._route_to_llm_fallback(request, start_time)
            
            # Route to appropriate module
            module_name, handler_name = self.router.get_module(request.intent)
            
            # Execute the handler
            result = self._execute_module(
                module_name, handler_name, request, start_time
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[DISPATCHER ERROR] {e}")
            return self._create_error_response(request, str(e), start_time)
    
    def dispatch_multi(self, multi_request: MultiActionRequest) -> Dict[str, Any]:
        """
        Dispatch multi-intent request
        
        Args:
            multi_request: MultiActionRequest with multiple intents
            
        Returns:
            Structured multi-action response
        """
        logger.info(
            f"[DISPATCHER MULTI] Processing {len(multi_request)} intents | "
            f"Mode: {multi_request.execution_mode}"
        )
        
        if multi_request.require_confirmation:
            return self._create_multi_action_confirmation(multi_request)
        
        if multi_request.execution_mode == "sequential":
            return self._execute_sequential(multi_request)
        elif multi_request.execution_mode == "parallel":
            return self._execute_parallel(multi_request)
    
    def _should_fallback_to_llm(self, request: ExecutionRequest) -> bool:
        """
        Determine if command should fallback to LLM
        
        CRITICAL RULE: Only fallback if:
        1. Intent is CHAT or GENERAL_KNOWLEDGE, OR
        2. Confidence is below threshold AND intent is not explicitly executable
        """
        # Always execute chat/general_knowledge intents through LLM
        chat_intents = {IntentType.CHAT, IntentType.GENERAL_KNOWLEDGE}
        if request.intent in chat_intents:
            return True
        
        # Check confidence threshold for executable intents
        if request.confidence < self.confidence_threshold:
            logger.warning(
                f"[DISPATCHER FALLBACK] Confidence {request.confidence:.2f} < "
                f"threshold {self.confidence_threshold}. Intent: {request.intent.value}"
            )
            return True
        
        return False
    
    def _execute_module(
        self,
        module_name: str,
        handler_name: str,
        request: ExecutionRequest,
        start_time: float
    ) -> Dict[str, Any]:
        """Execute module handler"""
        
        module = self.module_handlers.get(module_name)
        
        if not module:
            logger.warning(f"[DISPATCHER] Module not registered: {module_name}")
            return self._route_to_llm_fallback(request, start_time)
        
        try:
            handler = getattr(module, handler_name, None)
            if not handler:
                logger.warning(
                    f"[DISPATCHER] Handler not found: {module_name}.{handler_name}"
                )
                return self._route_to_llm_fallback(request, start_time)
            
            # Call handler with entities
            result = handler(request.entities, request.input_text)
            
            # Log execution
            execution_time = (time.time() - start_time) * 1000
            self._log_execution(
                request, module_name, handler_name,
                ExecutionStatus.SUCCESS, result, execution_time
            )
            
            return {
                "status": ExecutionStatus.SUCCESS.value,
                "module": module_name,
                "handler": handler_name,
                "result": result,
                "execution_time_ms": execution_time
            }
            
        except Exception as e:
            logger.error(f"[DISPATCHER MODULE ERROR] {module_name}.{handler_name}: {e}")
            execution_time = (time.time() - start_time) * 1000
            self._log_execution(
                request, module_name, handler_name,
                ExecutionStatus.FAILED, str(e), execution_time
            )
            return self._route_to_llm_fallback(request, start_time)
    
    def _route_to_llm_fallback(
        self,
        request: ExecutionRequest,
        start_time: float
    ) -> Dict[str, Any]:
        """Route to LLM conversational pipeline as fallback"""
        
        logger.info(
            f"[DISPATCHER LLM FALLBACK] Intent: {request.intent.value} | "
            f"Confidence: {request.confidence:.2f}"
        )
        
        module_name = "llm_pipeline"
        handler_name = "chat"
        
        # Log fallback
        execution_time = (time.time() - start_time) * 1000
        self._log_execution(
            request, module_name, handler_name,
            ExecutionStatus.FALLBACK_TO_LLM, "Routed to LLM", execution_time
        )
        
        return {
            "status": ExecutionStatus.FALLBACK_TO_LLM.value,
            "module": module_name,
            "handler": handler_name,
            "reason": "Confidence below threshold or chat intent",
            "input": request.input_text,
            "execution_time_ms": execution_time
        }
    
    def _create_multi_action_confirmation(
        self,
        multi_request: MultiActionRequest
    ) -> Dict[str, Any]:
        """Create structured confirmation request for multi-intent command"""
        
        intents_list = []
        for req in multi_request.intents:
            module, handler = self.router.get_module(req.intent)
            intents_list.append({
                "intent": req.intent.value,
                "confidence": req.confidence,
                "module": module,
                "handler": handler,
                "entities": req.entities
            })
        
        return {
            "status": ExecutionStatus.PENDING_CONFIRMATION.value,
            "type": "multi_action_request",
            "execution_mode": multi_request.execution_mode,
            "intents": intents_list,
            "message": (
                f"I detected {len(multi_request.intents)} actions. "
                "Should I execute them sequentially? "
                f"Actions: {', '.join(r.intent.value for r in multi_request.intents)}"
            )
        }
    
    def _execute_sequential(self, multi_request: MultiActionRequest) -> Dict[str, Any]:
        """Execute multiple intents sequentially"""
        
        results = []
        for req in multi_request.intents:
            result = self.dispatch(req)
            results.append(result)
        
        return {
            "status": ExecutionStatus.SUCCESS.value,
            "type": "multi_action_sequential",
            "results": results,
            "total_intents": len(multi_request.intents)
        }
    
    def _execute_parallel(self, multi_request: MultiActionRequest) -> Dict[str, Any]:
        """Execute multiple intents in parallel"""
        
        import concurrent.futures
        
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                (executor.submit(self.dispatch, req), req)
                for req in multi_request.intents
            ]
            
            for future, req in futures:
                try:
                    result = future.result(timeout=10)
                    results.append(result)
                except concurrent.futures.TimeoutError:
                    logger.error(f"[DISPATCHER] Parallel execution timeout: {req.intent}")
                    results.append({
                        "status": ExecutionStatus.FAILED.value,
                        "intent": req.intent.value,
                        "error": "Execution timeout"
                    })
        
        return {
            "status": ExecutionStatus.SUCCESS.value,
            "type": "multi_action_parallel",
            "results": results,
            "total_intents": len(multi_request.intents)
        }
    
    def _log_execution(
        self,
        request: ExecutionRequest,
        module_name: str,
        handler_name: str,
        status: ExecutionStatus,
        result: Any,
        execution_time: float
    ):
        """Log command execution for reporting"""
        
        log_entry = ExecutionLog(
            timestamp=datetime.now().isoformat(),
            command_input=request.input_text,
            detected_intent=request.intent.value,
            confidence_score=request.confidence,
            confidence_threshold=self.confidence_threshold,
            selected_module=module_name,
            executed_function=handler_name,
            execution_status=status.value,
            result=str(result)[:200],  # Truncate long results
            execution_time_ms=execution_time,
            extra_metadata=request.metadata
        )
        
        self.execution_logs.append(log_entry)
        
        logger.info(
            f"[EXECUTION LOG] {log_entry.detected_intent} -> {log_entry.selected_module} | "
            f"Status: {log_entry.execution_status} | "
            f"Time: {log_entry.execution_time_ms:.1f}ms"
        )
    
    def _create_error_response(
        self,
        request: ExecutionRequest,
        error: str,
        start_time: float
    ) -> Dict[str, Any]:
        """Create standardized error response"""
        
        execution_time = (time.time() - start_time) * 1000
        self._log_execution(
            request, "dispatcher", "error",
            ExecutionStatus.FAILED, error, execution_time
        )
        
        return {
            "status": ExecutionStatus.FAILED.value,
            "error": error,
            "intent": request.intent.value,
            "execution_time_ms": execution_time
        }
    
    def get_execution_logs(self, limit: int = None) -> List[Dict[str, Any]]:
        """Get execution logs for reporting"""
        logs = self.execution_logs
        if limit:
            logs = logs[-limit:]
        return [log.to_dict() for log in logs]
    
    def clear_execution_logs(self):
        """Clear execution log history"""
        self.execution_logs.clear()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get execution statistics"""
        if not self.execution_logs:
            return {"total_executions": 0, "message": "No execution logs available"}
        
        total = len(self.execution_logs)
        successful = sum(
            1 for log in self.execution_logs
            if log.execution_status == ExecutionStatus.SUCCESS.value
        )
        failed = sum(
            1 for log in self.execution_logs
            if log.execution_status == ExecutionStatus.FAILED.value
        )
        llm_fallback = sum(
            1 for log in self.execution_logs
            if log.execution_status == ExecutionStatus.FALLBACK_TO_LLM.value
        )
        
        avg_time = sum(log.execution_time_ms for log in self.execution_logs) / total
        
        # Module breakdown
        module_counts = {}
        for log in self.execution_logs:
            module = log.selected_module
            module_counts[module] = module_counts.get(module, 0) + 1
        
        return {
            "total_executions": total,
            "successful": successful,
            "failed": failed,
            "llm_fallback": llm_fallback,
            "success_rate": f"{(successful / total * 100):.1f}%",
            "average_execution_time_ms": f"{avg_time:.1f}",
            "module_breakdown": module_counts
        }


# Global dispatcher instance
_dispatcher = None

def get_dispatcher(confidence_threshold: float = 0.65) -> ExecutionDispatcher:
    """Get or create global dispatcher instance"""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = ExecutionDispatcher(confidence_threshold)
    return _dispatcher

def reset_dispatcher():
    """Reset global dispatcher"""
    global _dispatcher
    _dispatcher = None
