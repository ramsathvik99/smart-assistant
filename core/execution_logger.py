"""
Execution Logger - Comprehensive logging system for command execution
================================================================================
Tracks every command execution with detailed metrics for reporting and analysis.

Logged Information:
- Input command
- Detected intent
- Confidence score
- Selected module
- Executed function
- Result status
- Execution time
- Module-specific metadata
"""

import logging
import json
import csv
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
import threading

logger = logging.getLogger(__name__)


class CommandStatus(Enum):
    """Command execution status"""
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    ROUTED_TO_LLM = "routed_to_llm"
    ERROR = "error"


@dataclass
class CommandExecutionRecord:
    """Single command execution record"""
    timestamp: str
    command_id: str
    input_command: str
    detected_intent: str
    intent_confidence: float
    confidence_threshold: float
    selected_module: str
    handler_function: str
    execution_status: str
    result_message: str
    execution_time_ms: float
    result_data: Optional[Dict[str, Any]]
    is_multi_intent: bool = False
    sub_intent_count: int = 1
    entities_extracted: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        data = asdict(self)
        # Convert enums to strings
        for key, value in data.items():
            if isinstance(value, Enum):
                data[key] = value.value
        return data


class ExecutionLogger:
    """Comprehensive command execution logger"""
    
    def __init__(self, log_dir: str = "logs"):
        """Initialize logger"""
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        self.execution_records: List[CommandExecutionRecord] = []
        self.lock = threading.Lock()  # Thread-safe
        
        # CSV output path
        self.csv_path = self.log_dir / "execution_log.csv"
        self.json_path = self.log_dir / "execution_log.json"
        
        # Statistics tracking
        self.stats = {
            "total_commands": 0,
            "successful": 0,
            "failed": 0,
            "routed_to_llm": 0,
            "partial": 0,
            "errors": 0,
            "by_intent": {},
            "by_module": {},
            "by_status": {},
            "total_execution_time_ms": 0.0,
            "average_execution_time_ms": 0.0,
            "confidence_scores": []
        }
        
        logger.info(f"[EXECUTION LOGGER] Initialized with log directory: {self.log_dir}")
    
    def log_command(
        self,
        command_id: str,
        input_text: str,
        intent: str,
        confidence: float,
        confidence_threshold: float,
        module: str,
        handler: str,
        status: CommandStatus,
        result_message: str,
        execution_time_ms: float,
        result_data: Optional[Dict[str, Any]] = None,
        entities: Optional[Dict[str, Any]] = None,
        is_multi_intent: bool = False,
        sub_intent_count: int = 1,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Log command execution
        
        Args:
            command_id: Unique command identifier
            input_text: Original user input
            intent: Detected intent
            confidence: Confidence score
            confidence_threshold: Threshold used
            module: Execution module
            handler: Handler function
            status: Execution status
            result_message: Result message
            execution_time_ms: Execution time in milliseconds
            result_data: Result data dict
            entities: Extracted entities
            is_multi_intent: Whether multi-intent command
            sub_intent_count: Number of sub-intents
            metadata: Additional metadata
        """
        record = CommandExecutionRecord(
            timestamp=datetime.now().isoformat(),
            command_id=command_id,
            input_command=input_text,
            detected_intent=intent,
            intent_confidence=confidence,
            confidence_threshold=confidence_threshold,
            selected_module=module,
            handler_function=handler,
            execution_status=status.value,
            result_message=result_message,
            execution_time_ms=execution_time_ms,
            result_data=result_data,
            is_multi_intent=is_multi_intent,
            sub_intent_count=sub_intent_count,
            entities_extracted=entities,
            metadata=metadata
        )
        
        with self.lock:
            self.execution_records.append(record)
            self._update_statistics(record)
        
        logger.info(
            f"[EXECUTION LOG] ID: {command_id} | Intent: {intent} | "
            f"Status: {status.value} | Module: {module} | Time: {execution_time_ms:.1f}ms"
        )
    
    def _update_statistics(self, record: CommandExecutionRecord):
        """Update running statistics"""
        
        # Total commands
        self.stats["total_commands"] += 1
        
        # Status counts
        status = record.execution_status
        self.stats["by_status"][status] = self.stats["by_status"].get(status, 0) + 1
        
        if status == CommandStatus.SUCCESS.value:
            self.stats["successful"] += 1
        elif status == CommandStatus.FAILED.value:
            self.stats["failed"] += 1
        elif status == CommandStatus.ROUTED_TO_LLM.value:
            self.stats["routed_to_llm"] += 1
        elif status == CommandStatus.PARTIAL.value:
            self.stats["partial"] += 1
        elif status == CommandStatus.ERROR.value:
            self.stats["errors"] += 1
        
        # By intent
        intent = record.detected_intent
        if intent not in self.stats["by_intent"]:
            self.stats["by_intent"][intent] = {"count": 0, "success": 0, "failed": 0, "to_llm": 0}
        self.stats["by_intent"][intent]["count"] += 1
        if status == CommandStatus.SUCCESS.value:
            self.stats["by_intent"][intent]["success"] += 1
        elif status == CommandStatus.FAILED.value:
            self.stats["by_intent"][intent]["failed"] += 1
        elif status == CommandStatus.ROUTED_TO_LLM.value:
            self.stats["by_intent"][intent]["to_llm"] += 1
        
        # By module
        module = record.selected_module
        if module not in self.stats["by_module"]:
            self.stats["by_module"][module] = {"count": 0, "success": 0, "failed": 0}
        self.stats["by_module"][module]["count"] += 1
        if status == CommandStatus.SUCCESS.value:
            self.stats["by_module"][module]["success"] += 1
        elif status == CommandStatus.FAILED.value:
            self.stats["by_module"][module]["failed"] += 1
        
        # Timing
        self.stats["total_execution_time_ms"] += record.execution_time_ms
        self.stats["average_execution_time_ms"] = (
            self.stats["total_execution_time_ms"] / self.stats["total_commands"]
        )
        
        # Confidence tracking
        self.stats["confidence_scores"].append(record.intent_confidence)
    
    def save_to_csv(self):
        """Save logs to CSV file"""
        if not self.execution_records:
            logger.warning("[EXECUTION LOGGER] No records to save")
            return
        
        try:
            records_dict = [r.to_dict() for r in self.execution_records]
            
            if not records_dict:
                return
            
            # Get all keys from first record
            fieldnames = list(records_dict[0].keys())
            
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(records_dict)
            
            logger.info(f"[EXECUTION LOGGER] Saved {len(records_dict)} records to CSV: {self.csv_path}")
        
        except Exception as e:
            logger.error(f"[EXECUTION LOGGER] CSV save error: {e}")
    
    def save_to_json(self):
        """Save logs to JSON file"""
        if not self.execution_records:
            logger.warning("[EXECUTION LOGGER] No records to save")
            return
        
        try:
            records_dict = [r.to_dict() for r in self.execution_records]
            
            with open(self.json_path, 'w', encoding='utf-8') as f:
                json.dump(records_dict, f, indent=2, ensure_ascii=False)
            
            logger.info(f"[EXECUTION LOGGER] Saved {len(records_dict)} records to JSON: {self.json_path}")
        
        except Exception as e:
            logger.error(f"[EXECUTION LOGGER] JSON save error: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics summary"""
        return self.stats.copy()
    
    def get_records(self, limit: int = None, intent: str = None, status: str = None) -> List[Dict]:
        """Get execution records with optional filtering"""
        records = self.execution_records
        
        if intent:
            records = [r for r in records if r.detected_intent == intent]
        
        if status:
            records = [r for r in records if r.execution_status == status]
        
        if limit:
            records = records[-limit:]
        
        return [r.to_dict() for r in records]
    
    def generate_report(self) -> str:
        """Generate human-readable execution report"""
        report_lines = [
            "=" * 80,
            "ASSISTANT EXECUTION DISPATCHER - COMMAND EXECUTION REPORT",
            "=" * 80,
            f"Report Generated: {datetime.now().isoformat()}",
            f"Total Records: {len(self.execution_records)}",
            "",
            "OVERALL STATISTICS",
            "-" * 80,
            f"Total Commands Executed: {self.stats['total_commands']}",
            f"Successful: {self.stats['successful']} ({self.stats['successful']/max(1, self.stats['total_commands'])*100:.1f}%)",
            f"Failed: {self.stats['failed']} ({self.stats['failed']/max(1, self.stats['total_commands'])*100:.1f}%)",
            f"Routed to LLM: {self.stats['routed_to_llm']} ({self.stats['routed_to_llm']/max(1, self.stats['total_commands'])*100:.1f}%)",
            f"Partial Success: {self.stats['partial']}",
            f"Errors: {self.stats['errors']}",
            f"Average Execution Time: {self.stats['average_execution_time_ms']:.2f}ms",
            "",
            "INTENT BREAKDOWN",
            "-" * 80,
        ]
        
        for intent, stats in sorted(self.stats["by_intent"].items()):
            success_rate = stats["success"] / max(1, stats["count"]) * 100
            report_lines.append(
                f"{intent:30s} | Count: {stats['count']:3d} | "
                f"Success: {stats['success']:3d} ({success_rate:5.1f}%) | "
                f"Failed: {stats['failed']:3d} | To LLM: {stats['to_llm']:3d}"
            )
        
        report_lines.extend([
            "",
            "MODULE BREAKDOWN",
            "-" * 80,
        ])
        
        for module, stats in sorted(self.stats["by_module"].items()):
            success_rate = stats["success"] / max(1, stats["count"]) * 100
            report_lines.append(
                f"{module:30s} | Count: {stats['count']:3d} | "
                f"Success: {stats['success']:3d} ({success_rate:5.1f}%) | "
                f"Failed: {stats['failed']:3d}"
            )
        
        report_lines.extend([
            "",
            "EXECUTION STATUS DISTRIBUTION",
            "-" * 80,
        ])
        
        for status, count in sorted(self.stats["by_status"].items()):
            percentage = count / max(1, self.stats["total_commands"]) * 100
            report_lines.append(f"{status:20s}: {count:4d} ({percentage:5.1f}%)")
        
        report_lines.extend([
            "",
            "CONFIDENCE SCORE ANALYSIS",
            "-" * 80,
        ])
        
        if self.stats["confidence_scores"]:
            scores = self.stats["confidence_scores"]
            avg_confidence = sum(scores) / len(scores)
            min_confidence = min(scores)
            max_confidence = max(scores)
            
            report_lines.extend([
                f"Average Confidence: {avg_confidence:.3f}",
                f"Min Confidence: {min_confidence:.3f}",
                f"Max Confidence: {max_confidence:.3f}",
            ])
        
        report_lines.extend([
            "",
            "=" * 80,
        ])
        
        return "\n".join(report_lines)
    
    def clear_records(self):
        """Clear all records"""
        with self.lock:
            self.execution_records.clear()
            self.stats = {
                "total_commands": 0,
                "successful": 0,
                "failed": 0,
                "routed_to_llm": 0,
                "partial": 0,
                "errors": 0,
                "by_intent": {},
                "by_module": {},
                "by_status": {},
                "total_execution_time_ms": 0.0,
                "average_execution_time_ms": 0.0,
                "confidence_scores": []
            }


# Global logger instance
_execution_logger = None


def get_execution_logger(log_dir: str = "logs") -> ExecutionLogger:
    """Get or create global execution logger"""
    global _execution_logger
    if _execution_logger is None:
        _execution_logger = ExecutionLogger(log_dir)
    return _execution_logger


def log_command_execution(
    command_id: str,
    input_text: str,
    intent: str,
    confidence: float,
    confidence_threshold: float,
    module: str,
    handler: str,
    status: CommandStatus,
    result_message: str,
    execution_time_ms: float,
    result_data: Optional[Dict[str, Any]] = None,
    entities: Optional[Dict[str, Any]] = None,
    is_multi_intent: bool = False,
    sub_intent_count: int = 1,
    metadata: Optional[Dict[str, Any]] = None
):
    """Convenience function to log command execution"""
    logger_instance = get_execution_logger()
    logger_instance.log_command(
        command_id, input_text, intent, confidence, confidence_threshold,
        module, handler, status, result_message, execution_time_ms,
        result_data, entities, is_multi_intent, sub_intent_count, metadata
    )
