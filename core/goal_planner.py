"""
Goal Planner for PHASE 6

Transforms multi-intent analysis into executable plans.
Orders intents by priority and dependencies, detects conflicts,
estimates execution time, and assesses risk.

Architecture:
- Input: IntentAnalysis from multi_intent_analyzer
- Process: Order, conflict detect, estimate, risk assess
- Output: ExecutionPlan ready for execution
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple, Optional, Set
from enum import Enum
from datetime import datetime
import uuid

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.unified_command_router import Intent
from core.multi_intent_analyzer import IntentAnalysis


# ============================================================================
# Data Structures
# ============================================================================

class StepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    CANCELLED = "CANCELLED"


@dataclass
class ExecutionStep:
    """Single step in execution plan"""
    sequence: int                      # 0, 1, 2, ... (execution order)
    intent: Intent
    parameters: Dict[str, Any]
    confidence: float
    
    # Execution characteristics
    can_run_in_parallel: bool = False
    dependencies: List[int] = field(default_factory=list)  # Indices of dependent steps
    requires_confirmation: bool = False
    estimated_duration: float = 0.5
    
    # Context
    input_context: Dict[str, Any] = field(default_factory=dict)
    output_context_keys: List[str] = field(default_factory=list)
    
    # Execution metadata & Phase 2 state
    status: str = "PENDING"
    retry_count: int = 0
    max_retries: int = 1
    verification_condition: Optional[str] = None
    observation: Optional[Dict[str, Any]] = None
    state_difference: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    retry_on_failure: bool = False
    continue_on_failure: bool = True
    timeout: float = 10.0
    priority_score: float = 0.0


@dataclass
class ExecutionPlan:
    """Complete execution plan for multi-intent command"""
    # Basic info
    plan_id: str
    creation_time: str
    original_input: str
    
    # Execution status
    goal_status: str = "PENDING"
    active_step_index: int = 0
    
    # Plan structure
    steps: List[ExecutionStep] = field(default_factory=list)
    total_steps: int = 0
    parallel_groups: List[List[int]] = field(default_factory=list)
    
    # Execution info
    total_estimated_time: float = 0.0
    can_be_interrupted: bool = True
    requires_user_confirmation: bool = False
    
    # Safety/Analysis
    risk_level: str = "low"  # "low", "medium", "high"
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    
    # Metadata
    confidence_score: float = 0.0
    success_rate_estimate: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Phase 3 Adaptive Execution State
    original_plan: Optional[Dict[str, Any]] = None
    adaptation_count: int = 0
    max_adaptations: int = 2
    adaptation_reason: Optional[str] = None
    adaptation_history: List[Dict[str, Any]] = field(default_factory=list)
    completed_steps: List[Dict[str, Any]] = field(default_factory=list)
    failed_steps: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Conflict:
    """Represents a conflict between intents"""
    conflict_type: str  # "contradictory", "circular_dependency", "incompatible"
    step_indices: List[int]
    severity: str  # "warning", "error"
    description: str
    recommendation: str


# ============================================================================
# Goal Planner
# ============================================================================

class GoalPlanner:
    """
    Transforms intent analysis into execution plans.
    
    Responsibilities:
    - Order intents by priority and dependencies
    - Detect conflicts
    - Estimate execution time
    - Assess risk
    - Handle context passing
    """
    
    # Priority scores by intent type (higher = execute first)
    INTENT_PRIORITY = {
        Intent.POWER_ACTION: 100,
        Intent.EMERGENCY: 99,
        Intent.DEVICE_CONTROL: 50,
        Intent.VISUAL_SURFACE: 45,
        Intent.OPEN_APPLICATION: 40,
        Intent.FILE_OPERATIONS: 30,
        Intent.EMAIL: 25,
        Intent.NOTES: 24,
        Intent.REMINDERS: 23,
        Intent.MUSIC: 22,
        Intent.CALCULATOR: 20,
        Intent.CODE_GENERATION: 15,
        Intent.TRANSLATION: 14,
        Intent.TIME_QUERY: 13,
        Intent.DATE_QUERY: 12,
        Intent.WEATHER_QUERY: 11,
        Intent.MEMORY_QUERY: 10,
        Intent.RAG_SEARCH: 5,
        Intent.GENERAL_CONVERSATION: 1,
    }
    
    # Execution duration estimates (in seconds)
    EXECUTION_DURATION = {
        Intent.VISUAL_SURFACE: 0.1,
        Intent.MUSIC: 0.5,
        Intent.EMAIL: 0.8,
        Intent.REMINDERS: 0.3,
        Intent.CALCULATOR: 0.1,
        Intent.WEATHER_QUERY: 0.5,
        Intent.TIME_QUERY: 0.05,
        Intent.DATE_QUERY: 0.05,
        Intent.OPEN_APPLICATION: 1.0,
        Intent.GENERAL_CONVERSATION: 1.0,
        Intent.RAG_SEARCH: 1.5,
        Intent.FILE_OPERATIONS: 0.7,
        Intent.NOTES: 0.4,
        Intent.TRANSLATION: 0.6,
        Intent.CODE_GENERATION: 2.0,
        Intent.DEVICE_CONTROL: 0.8,
        Intent.POWER_ACTION: 0.5,
        Intent.EMERGENCY: 0.2,
        Intent.MEMORY_QUERY: 0.3,
    }
    
    # Intent type classifications
    STATE_CHANGE = {
        Intent.EMAIL,
        Intent.NOTES,
        Intent.REMINDERS,
        Intent.FILE_OPERATIONS,
        Intent.POWER_ACTION,
        Intent.DEVICE_CONTROL,
    }
    
    QUERIES = {
        Intent.WEATHER_QUERY,
        Intent.CALCULATOR,
        Intent.TIME_QUERY,
        Intent.DATE_QUERY,
        Intent.MEMORY_QUERY,
        Intent.RAG_SEARCH,
        Intent.TRANSLATION,
        Intent.CODE_GENERATION,
    }
    
    DISPLAY = {
        Intent.MUSIC,
        Intent.OPEN_APPLICATION,
    }
    
    # Contradictory intent pairs
    CONTRADICTORY_PAIRS = [
        (Intent.MUSIC, Intent.MUSIC),  # play + stop
        (Intent.POWER_ACTION, Intent.MUSIC),  # shutdown + play
    ]
    
    def __init__(self):
        """Initialize goal planner"""
        print("[GOAL_PLANNER] Initialized successfully")
    
    def create_plan(self, intent_analysis: IntentAnalysis) -> ExecutionPlan:
        """
        Create execution plan from intent analysis.
        
        Args:
            intent_analysis: From MultiIntentAnalyzer
            
        Returns:
            ExecutionPlan ready for execution
        """
        
        # Single-intent optimization (backward compatible)
        if not intent_analysis.has_multiple_intents:
            return self._create_single_intent_plan(intent_analysis)
        
        # Multi-intent planning
        steps = self._create_execution_steps(intent_analysis)
        
        # Order by priority and dependencies
        ordered_steps = self._order_steps(steps, intent_analysis.dependencies)
        
        # Detect conflicts
        conflicts = self._detect_conflicts(ordered_steps)
        
        # Estimate execution time
        total_time = self._estimate_total_time(ordered_steps)
        
        # Assess risk
        risk_level = self._assess_risk(ordered_steps, conflicts)
        
        # Build execution plan
        plan = ExecutionPlan(
            plan_id=str(uuid.uuid4())[:8],
            creation_time=datetime.now().isoformat(),
            original_input=intent_analysis.original_input,
            steps=ordered_steps,
            total_steps=len(ordered_steps),
            total_estimated_time=total_time,
            requires_user_confirmation=any(s.requires_confirmation for s in ordered_steps),
            risk_level=risk_level,
            warnings=self._generate_warnings(ordered_steps, conflicts),
            confidence_score=intent_analysis.confidence_score,
            success_rate_estimate=self._estimate_success_rate(ordered_steps),
        )
        plan.original_plan = {
            "plan_id": plan.plan_id,
            "original_input": plan.original_input,
            "total_steps": plan.total_steps,
            "steps": [
                {"sequence": s.sequence, "intent": s.intent.name, "parameters": dict(s.parameters)}
                for s in plan.steps
            ]
        }
        
        return plan
    
    def _create_single_intent_plan(self, intent_analysis: IntentAnalysis) -> ExecutionPlan:
        """Create plan for single intent (backward compatible)"""
        if not intent_analysis.intents:
            return ExecutionPlan(
                plan_id=str(uuid.uuid4())[:8],
                creation_time=datetime.now().isoformat(),
                original_input=intent_analysis.original_input,
                risk_level="low"
            )
        
        intent_dict = intent_analysis.intents[0]
        
        step = ExecutionStep(
            sequence=0,
            intent=intent_dict["intent"],
            parameters=intent_dict["parameters"],
            confidence=intent_dict["confidence"],
            estimated_duration=self.EXECUTION_DURATION.get(intent_dict["intent"], 0.5),
            priority_score=self.INTENT_PRIORITY.get(intent_dict["intent"], 0),
        )
        
        return ExecutionPlan(
            plan_id=str(uuid.uuid4())[:8],
            creation_time=datetime.now().isoformat(),
            original_input=intent_analysis.original_input,
            steps=[step],
            total_steps=1,
            total_estimated_time=step.estimated_duration,
            risk_level="low",
            confidence_score=intent_dict["confidence"],
            success_rate_estimate=intent_dict["confidence"],
        )
    
    def _create_execution_steps(self, intent_analysis: IntentAnalysis) -> List[ExecutionStep]:
        """Create execution steps from intent analysis"""
        steps = []

        for idx, intent_dict in enumerate(intent_analysis.intents):
            intent = intent_dict["intent"]

            # Merge matched_text into parameters so the Brain can use it
            params = dict(intent_dict["parameters"])
            matched_text = intent_dict.get("matched_text", "").strip()
            if matched_text:
                params["raw_input"] = matched_text

            step = ExecutionStep(
                sequence=idx,
                intent=intent,
                parameters=params,
                confidence=intent_dict["confidence"],
                estimated_duration=self.EXECUTION_DURATION.get(intent, 0.5),
                priority_score=self.INTENT_PRIORITY.get(intent, 0),
                requires_confirmation=intent_dict["confidence"] < 0.8,
                dependencies=intent_dict.get("dependencies", []),
                retry_on_failure=intent in {Intent.OPEN_APPLICATION, Intent.FILE_OPERATIONS, Intent.RAG_SEARCH, Intent.WEATHER_QUERY},
                max_retries=1,
            )

            steps.append(step)

        return steps
    
    def _order_steps(
        self,
        steps: List[ExecutionStep],
        dependencies: Dict[int, int]
    ) -> List[ExecutionStep]:
        """
        Order steps by priority and dependencies using topological sort.
        
        Args:
            steps: Unordered execution steps
            dependencies: From intent_analysis
            
        Returns:
            Ordered list of ExecutionStep
        """
        
        # Build dependency graph
        dep_graph = {i: [] for i in range(len(steps))}
        for idx, dep_indices in dependencies.items():
            if isinstance(dep_indices, list):
                dep_graph[idx] = dep_indices
            else:
                dep_graph[idx] = [dep_indices]
        
        # Topological sort with priority fallback
        ordered_indices = self._topological_sort(dep_graph, steps)
        
        # Create ordered steps with updated sequence numbers
        ordered_steps = []
        for seq, idx in enumerate(ordered_indices):
            step = steps[idx]
            step.sequence = seq
            ordered_steps.append(step)
        
        return ordered_steps
    
    def _topological_sort(
        self,
        dep_graph: Dict[int, List[int]],
        steps: List[ExecutionStep]
    ) -> List[int]:
        """
        Topological sort with priority-based secondary ordering.
        
        Returns list of step indices in execution order.
        """
        
        visited = set()
        order = []
        
        def visit(node):
            if node in visited:
                return
            visited.add(node)
            
            # Visit dependencies first
            for dep in dep_graph.get(node, []):
                visit(dep)
            
            order.append(node)
        
        # Sort by priority score for secondary ordering
        priority_order = sorted(
            range(len(steps)),
            key=lambda i: -steps[i].priority_score
        )
        
        # Visit in priority order (ensures dependencies respected)
        for idx in priority_order:
            visit(idx)
        
        return order
    
    def _detect_conflicts(self, steps: List[ExecutionStep]) -> List[Conflict]:
        """Detect conflicts between intents"""
        conflicts = []
        
        # Check for contradictory intents
        for i, step_i in enumerate(steps):
            for j, step_j in enumerate(steps):
                if i >= j:
                    continue
                
                if self._are_contradictory(step_i.intent, step_j.intent):
                    conflicts.append(Conflict(
                        conflict_type="contradictory",
                        step_indices=[i, j],
                        severity="warning",
                        description=f"{step_i.intent.name} contradicts {step_j.intent.name}",
                        recommendation=f"Execute only {step_i.intent.name}"
                    ))
        
        # Check for circular dependencies
        if self._has_circular_dependency(steps):
            conflicts.append(Conflict(
                conflict_type="circular_dependency",
                step_indices=[],
                severity="error",
                description="Circular dependency detected",
                recommendation="Simplify command or reorder intents"
            ))
        
        return conflicts
    
    def _are_contradictory(self, intent_a: Intent, intent_b: Intent) -> bool:
        """Check if two intents are contradictory"""
        return (intent_a, intent_b) in self.CONTRADICTORY_PAIRS or \
               (intent_b, intent_a) in self.CONTRADICTORY_PAIRS
    
    def _has_circular_dependency(self, steps: List[ExecutionStep]) -> bool:
        """Detect circular dependencies"""
        visited = set()
        rec_stack = set()
        
        def has_cycle(idx):
            visited.add(idx)
            rec_stack.add(idx)
            
            for dep in steps[idx].dependencies:
                if dep not in visited:
                    if has_cycle(dep):
                        return True
                elif dep in rec_stack:
                    return True
            
            rec_stack.remove(idx)
            return False
        
        for i in range(len(steps)):
            if i not in visited:
                if has_cycle(i):
                    return True
        
        return False
    
    def _estimate_total_time(self, steps: List[ExecutionStep]) -> float:
        """Estimate total execution time for all steps"""
        total_time = 0.0
        
        for step in steps:
            base_duration = step.estimated_duration
            
            # Adjust for confidence
            if step.confidence >= 0.9:
                base_duration *= 0.9  # Faster for high confidence
            elif step.confidence < 0.75:
                base_duration *= 1.1  # Slower for low confidence
            
            # Adjust for dependencies
            if step.dependencies:
                base_duration *= 1.05
            
            # Add confirmation time
            if step.requires_confirmation:
                base_duration += 1.0  # User decision time
            
            total_time += base_duration
        
        return total_time
    
    def _assess_risk(self, steps: List[ExecutionStep], conflicts: List[Conflict]) -> str:
        """Assess overall risk level"""
        risk_score = 0.0
        
        # Conflict penalty
        for conflict in conflicts:
            if conflict.severity == "error":
                risk_score += 50
            else:
                risk_score += 20
        
        # Per-step risk
        for step in steps:
            # Confidence penalty
            if step.confidence < 0.7:
                risk_score += 30
            elif step.confidence < 0.8:
                risk_score += 15
            
            # Intent type penalty
            if step.intent in {Intent.POWER_ACTION, Intent.EMERGENCY}:
                risk_score += 50
            elif step.intent in {Intent.FILE_OPERATIONS, Intent.EMAIL}:
                risk_score += 20
            
            # Dependency complexity
            if len(step.dependencies) > 2:
                risk_score += 15
        
        # Determine risk level
        if risk_score > 80:
            return "high"
        elif risk_score > 40:
            return "medium"
        else:
            return "low"
    
    def _generate_warnings(
        self,
        steps: List[ExecutionStep],
        conflicts: List[Conflict]
    ) -> List[str]:
        """Generate user warnings"""
        warnings = []
        
        # Conflict warnings
        for conflict in conflicts:
            warnings.append(f"⚠️  {conflict.description}")
        
        # High-risk operation warnings
        for step in steps:
            if step.intent in {Intent.POWER_ACTION, Intent.EMERGENCY}:
                warnings.append(f"⚠️  Will execute {step.intent.name} - may be irreversible")
            elif step.intent == Intent.FILE_OPERATIONS:
                warnings.append(f"⚠️  File operation detected - data may be modified")
        
        # Low confidence warnings
        for step in steps:
            if step.confidence < 0.75:
                warnings.append(f"⚠️  Low confidence ({step.confidence:.0%}) for {step.intent.name}")
        
        return warnings
    
    def _estimate_success_rate(self, steps: List[ExecutionStep]) -> float:
        """Estimate probability of successful execution"""
        if not steps:
            return 0.0
        
        # Success rate is product of all step confidence scores
        success_rate = 1.0
        for step in steps:
            success_rate *= step.confidence
        
        return min(success_rate, 1.0)


# ============================================================================
# Global Planner Instance
# ============================================================================

goal_planner = GoalPlanner()


# ============================================================================
# Utility Functions
# ============================================================================

def plan_execution(intent_analysis: IntentAnalysis) -> ExecutionPlan:
    """
    Create execution plan from intent analysis.
    
    Usage:
        analysis = analyze_input("play music and set reminder")
        plan = plan_execution(analysis)
    """
    return goal_planner.create_plan(intent_analysis)


def explain_plan(execution_plan: ExecutionPlan) -> str:
    """Generate human-readable explanation of execution plan"""
    lines = [
        f"📋 Execution Plan ({execution_plan.plan_id})",
        f"⏱️  Total Time: {execution_plan.total_estimated_time:.1f}s",
        f"📊 Risk Level: {execution_plan.risk_level.upper()}",
        f"✅ Success Rate: {execution_plan.success_rate_estimate:.0%}",
        "",
    ]
    
    for step in execution_plan.steps:
        lines.append(f"Step {step.sequence + 1}: {step.intent.name}")
        lines.append(f"  └─ Duration: {step.estimated_duration:.1f}s, Confidence: {step.confidence:.0%}")
        if step.dependencies:
            lines.append(f"  └─ Depends on: Steps {[d+1 for d in step.dependencies]}")
    
    if execution_plan.warnings:
        lines.append("")
        lines.append("⚠️  Warnings:")
        for warning in execution_plan.warnings:
            lines.append(f"  └─ {warning}")
    
    return "\n".join(lines)


if __name__ == "__main__":
    # Test goal planner with multi-intent analysis
    from core.multi_intent_analyzer import analyze_input
    
    test_cases = [
        "play music",
        "play some Telugu songs and set a reminder to listen later",
        "find weather in Guntur and send the results to Sathvik",
    ]
    
    print("[GOAL_PLANNER] Test Cases\n")
    
    for test_input in test_cases:
        print(f"Input: {test_input}")
        analysis = analyze_input(test_input)
        plan = plan_execution(analysis)
        print(explain_plan(plan))
        print("\n" + "="*70 + "\n")
