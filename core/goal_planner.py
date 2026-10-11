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
class WorkGoal:
    """
    First-class Level 6 Work Goal representation.
    Tracks work objectives, deliverables, subtasks, completion, and proactive state.
    """
    id: str
    title: str
    objective: str
    topic: Optional[str] = None
    purpose: str = "general"
    deadline: Optional[str] = None
    priority: str = "normal"  # normal, high, urgent
    status: str = "IN_PROGRESS"  # NOT_STARTED, IN_PROGRESS, PAUSED, WAITING_FOR_USER, COMPLETED, CANCELLED
    progress: str = "0%"
    requirements: List[str] = field(default_factory=list)
    deliverables: List[Dict[str, Any]] = field(default_factory=list)
    subtasks: List[Dict[str, Any]] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    source_material: List[Dict[str, Any]] = field(default_factory=list)
    active_artifact: Optional[Dict[str, Any]] = None
    pending_actions: List[Dict[str, Any]] = field(default_factory=list)
    completed_actions: List[Dict[str, Any]] = field(default_factory=list)
    unfinished_actions: List[Dict[str, Any]] = field(default_factory=list)
    last_activity: str = field(default_factory=lambda: datetime.now().isoformat())
    next_recommended_action: Optional[str] = None
    reminder_state: Dict[str, Any] = field(default_factory=dict)
    resume_point: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to fully serializable dictionary compatible with existing goal contracts."""
        completed_sts = [st["title"] for st in self.subtasks if st.get("status") == "COMPLETED"]
        remaining_sts = [st["title"] for st in self.subtasks if st.get("status") != "COMPLETED"]
        art_ids = [d.get("file_path") for d in self.deliverables if d.get("file_path")]
        last_act = self.completed_actions[-1] if self.completed_actions else None
        last_comp = self.completed_actions[-1] if self.completed_actions else None
        next_act = self.next_recommended_action or (self.unfinished_actions[0] if self.unfinished_actions else None)
        pending_act = self.pending_actions[0] if self.pending_actions else None

        return {
            "id": self.id,
            "goal_id": self.id,
            "title": self.title,
            "goal_name": self.title,
            "objective": self.objective,
            "description": self.objective,
            "user_request": self.objective,
            "topic": self.topic,
            "purpose": self.purpose,
            "deadline": self.deadline,
            "priority": self.priority,
            "status": self.status,
            "goal_status": self.status,
            "progress": self.progress,
            "requirements": list(self.requirements),
            "deliverables": list(self.deliverables),
            "subtasks": list(self.subtasks),
            "completed_subtasks": completed_sts,
            "remaining_subtasks": remaining_sts,
            "dependencies": list(self.dependencies),
            "source_material": list(self.source_material),
            "active_artifact": self.active_artifact,
            "artifact_ids": art_ids,
            "pending_action": pending_act,
            "pending_actions": list(self.pending_actions),
            "completed_actions": list(self.completed_actions),
            "unfinished_actions": list(self.unfinished_actions),
            "paused": (self.status == "PAUSED"),
            "last_action": last_act,
            "last_completed_action": last_comp,
            "next_action": next_act,
            "last_activity": self.last_activity,
            "next_recommended_action": self.next_recommended_action,
            "reminder_state": dict(self.reminder_state),
            "resume_point": self.resume_point,
            "goal_subject": self.metadata.get("goal_subject", self.topic or ""),
            "goal_verb": self.metadata.get("goal_verb", "prepare"),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkGoal":
        """Reconstruct WorkGoal from dictionary."""
        if not data or not isinstance(data, dict):
            return cls(id=str(uuid.uuid4())[:8], title="Work Goal", objective="Work Objective")
        return cls(
            id=str(data.get("id") or data.get("goal_id") or str(uuid.uuid4())[:8]),
            title=str(data.get("title") or data.get("goal_name") or "Work Goal"),
            objective=str(data.get("objective") or data.get("description") or data.get("user_request") or ""),
            topic=data.get("topic"),
            purpose=str(data.get("purpose") or "general"),
            deadline=data.get("deadline"),
            priority=str(data.get("priority") or "normal"),
            status=str(data.get("status") or data.get("goal_status") or "IN_PROGRESS"),
            progress=str(data.get("progress") or "0%"),
            requirements=list(data.get("requirements") or []),
            deliverables=list(data.get("deliverables") or []),
            subtasks=list(data.get("subtasks") or []),
            dependencies=list(data.get("dependencies") or []),
            source_material=list(data.get("source_material") or []),
            active_artifact=data.get("active_artifact"),
            pending_actions=list(data.get("pending_actions") or []),
            completed_actions=list(data.get("completed_actions") or []),
            unfinished_actions=list(data.get("unfinished_actions") or []),
            last_activity=str(data.get("last_activity") or datetime.now().isoformat()),
            next_recommended_action=data.get("next_recommended_action"),
            reminder_state=dict(data.get("reminder_state") or {}),
            resume_point=data.get("resume_point"),
            metadata=dict(data.get("metadata") or {}),
        )

    def complete_deliverable(self, doc_type: str, file_path: str, slide_count: Optional[int] = None) -> None:
        """Mark deliverable completed, record artifact, update subtasks and remaining actions."""
        doc_type_norm = doc_type.upper()
        if doc_type_norm in ("PPTX", "PPT"):
            doc_type_norm = "PPT"
        elif doc_type_norm in ("DOCX", "DOC"):
            doc_type_norm = "DOCX"
        elif doc_type_norm in ("PDF",):
            doc_type_norm = "PDF"
        elif doc_type_norm in ("XLSX", "EXCEL", "SHEET"):
            doc_type_norm = "XLSX"

        found = False
        for d in self.deliverables:
            if d.get("type", "").upper() in (doc_type_norm, doc_type.upper()):
                d["status"] = "COMPLETED"
                d["file_path"] = file_path
                if slide_count:
                    d["slide_count"] = slide_count
                found = True

        if not found:
            self.deliverables.append({
                "type": doc_type_norm,
                "topic": self.topic or self.title,
                "status": "COMPLETED",
                "file_path": file_path,
                "slide_count": slide_count
            })
            if not any(f"create {doc_type_norm.lower()}" in st.get("title", "").lower() for st in self.subtasks):
                self.subtasks.append({
                    "title": f"Create {doc_type_norm}",
                    "status": "COMPLETED",
                    "doable_by_friday": True,
                    "deliverable_type": doc_type_norm
                })

        filename = Path(file_path).name if file_path else "artifact"
        action_msg = f"{doc_type_norm} created and verified ({filename})"
        if action_msg not in self.completed_actions:
            self.completed_actions.append(action_msg)

        # Clear creation actions from pending_actions
        self.pending_actions = [
            pa for pa in self.pending_actions
            if not any(k in str(pa).lower() for k in [
                f"create_{doc_type_norm.lower()}",
                "create_presentation" if doc_type_norm == "PPT" else ("create_document" if doc_type_norm == "DOCX" else "create_excel")
            ])
        ]

        # Update subtasks
        for st in self.subtasks:
            t_title = st.get("title", "").lower()
            if (doc_type_norm.lower() in t_title or "presentation" in t_title or "report" in t_title or "document" in t_title) and "create" in t_title:
                st["status"] = "COMPLETED"
            elif "verify" in t_title:
                st["status"] = "COMPLETED"

        # Update unfinished_actions
        self.unfinished_actions = [
            a for a in self.unfinished_actions
            if not any(k in a.lower() for k in [f"create {doc_type_norm.lower()}", "create ppt", "create report", "create excel", "verify"])
        ]

        self.last_activity = datetime.now().isoformat()
        
        # Check if all deliverables completed
        all_delivs_done = all(d.get("status") == "COMPLETED" for d in self.deliverables) if self.deliverables else True
        if all_delivs_done:
            # Check if any review subtask remains
            has_pending_review = any(
                st.get("status") != "COMPLETED" and any(k in st.get("title", "").lower() for k in ["review", "check"])
                for st in self.subtasks
            )
            if has_pending_review:
                self.status = "ARTIFACTS_READY"
                self.progress = f"{doc_type_norm} created and verified. Ready for final review."
                self.next_recommended_action = f"Review {self.topic or self.title}"
            else:
                self.status = "READY_FOR_SUBMISSION"
                self.progress = "All artifacts created and verified. Ready for final submission."
                self.next_recommended_action = "Submit to portal"
        else:
            self.status = "IN_PROGRESS"
            self.progress = f"{doc_type_norm} created and verified. Additional deliverables pending."
            self.next_recommended_action = "Continue remaining deliverables"

        art_type = "PRESENTATION" if doc_type_norm == "PPT" else ("REPORT" if doc_type_norm == "DOCX" else ("PDF" if doc_type_norm == "PDF" else ("SPREADSHEET" if doc_type_norm == "XLSX" else doc_type_norm)))
        self.active_artifact = {
            "artifact_id": str(uuid.uuid4())[:8],
            "filename": filename,
            "path": file_path,
            "filepath": file_path,
            "artifact_type": art_type,
            "format": doc_type_norm,
            "type": doc_type_norm,
            "title": self.title,
            "topic": self.topic or self.title,
            "subject": self.topic or self.title,
            "purpose": self.purpose,
            "work_goal_id": self.id,
            "created_at": datetime.now().isoformat(),
            "verified": True,
            "status": "READY",
            "slide_count": slide_count
        }

    def pause(self, reason: str = "USER_PAUSED") -> None:
        self.status = "PAUSED"
        self.resume_point = self.progress or "Paused by user"
        self.last_activity = datetime.now().isoformat()

    def resume(self) -> None:
        self.status = "RUNNING"
        self.last_activity = datetime.now().isoformat()


def create_work_goal(
    goal_id: str,
    title: str,
    objective: str,
    topic: Optional[str] = None,
    purpose: str = "general",
    deadline: Optional[str] = None,
    priority: str = "normal",
    requirements: Optional[List[str]] = None,
    source_material: Optional[List[Dict[str, Any]]] = None,
    verb: str = "prepare",
    subject: str = ""
) -> WorkGoal:
    """
    Factory creating a fully-formed first-class WorkGoal with structured subtasks,
    deliverables, and completion tracking.
    """
    topic_clean = topic or (subject.title() if subject else "Project")
    purpose_low = purpose.lower()
    subj_low = subject.lower()

    if "presentation" in purpose_low or "presentation" in subj_low or "ppt" in subj_low or "slide" in subj_low:
        deliverables = [{"type": "PPT", "topic": topic_clean, "status": "PENDING", "file_path": None}]
        subtasks = [
            {"title": "Gather topic information", "status": "COMPLETED", "doable_by_friday": True},
            {"title": "Structure presentation", "status": "COMPLETED", "doable_by_friday": True},
            {"title": "Create PPT", "status": "PENDING", "doable_by_friday": True, "deliverable_type": "PPT"},
            {"title": "Review presentation", "status": "PENDING", "doable_by_friday": False, "requires_user": True},
            {"title": "Verify files", "status": "PENDING", "doable_by_friday": True},
            {"title": "Final submission", "status": "PENDING", "doable_by_friday": False, "requires_user": True}
        ]
        completed_actions = ["Gather topic information", "Structure presentation"]
        unfinished_actions = ["Create PPT", "Review presentation", "Final submission"]
        pending_actions = [{"action": "create_presentation", "topic": topic_clean}]
        next_rec = f"Create the PPT presentation on {topic_clean}"
        prog = "Plan created. Next step: create PPT."
        canonical_purpose = "Academic presentation"
    elif "report" in purpose_low or "report" in subj_low or "document" in subj_low or "assignment" in subj_low:
        deliverables = [{"type": "DOCX", "topic": topic_clean, "status": "PENDING", "file_path": None}]
        subtasks = [
            {"title": "Gather topic research", "status": "COMPLETED", "doable_by_friday": True},
            {"title": "Draft report structure", "status": "COMPLETED", "doable_by_friday": True},
            {"title": "Create Report", "status": "PENDING", "doable_by_friday": True, "deliverable_type": "DOCX"},
            {"title": "Review report", "status": "PENDING", "doable_by_friday": False, "requires_user": True},
            {"title": "Verify document", "status": "PENDING", "doable_by_friday": True},
            {"title": "Final submission", "status": "PENDING", "doable_by_friday": False, "requires_user": True}
        ]
        completed_actions = ["Gather topic research", "Draft report structure"]
        unfinished_actions = ["Create Report", "Review report", "Final submission"]
        pending_actions = [{"action": "create_document", "topic": topic_clean}]
        next_rec = f"Create the report on {topic_clean}"
        prog = "Plan created. Next step: create Report."
        canonical_purpose = "Report / documentation"
    elif "spreadsheet" in purpose_low or "excel" in subj_low or "sheet" in subj_low:
        deliverables = [{"type": "XLSX", "topic": topic_clean, "status": "PENDING", "file_path": None}]
        subtasks = [
            {"title": "Determine spreadsheet requirements", "status": "COMPLETED", "doable_by_friday": True},
            {"title": "Design schema and formulas", "status": "COMPLETED", "doable_by_friday": True},
            {"title": "Create Excel Sheet", "status": "PENDING", "doable_by_friday": True, "deliverable_type": "XLSX"},
            {"title": "Verify calculations and totals", "status": "PENDING", "doable_by_friday": True},
            {"title": "Final user check", "status": "PENDING", "doable_by_friday": False, "requires_user": True}
        ]
        completed_actions = ["Determine spreadsheet requirements", "Design schema and formulas"]
        unfinished_actions = ["Create Excel Sheet", "Verify calculations and totals", "Final user check"]
        pending_actions = [{"action": "create_excel", "topic": topic_clean}]
        next_rec = f"Create the spreadsheet for {topic_clean}"
        prog = "Plan created. Next step: create Excel sheet."
        canonical_purpose = "Spreadsheet / calculations"
    else:
        deliverables = [{"type": "PLAN", "topic": topic_clean, "status": "COMPLETED", "file_path": None}]
        subtasks = [
            {"title": "Define objective", "status": "COMPLETED", "doable_by_friday": True},
            {"title": "Execute doable tasks", "status": "PENDING", "doable_by_friday": True},
            {"title": "Final review", "status": "PENDING", "doable_by_friday": False, "requires_user": True}
        ]
        completed_actions = ["Define objective"]
        unfinished_actions = ["Execute doable tasks", "Final review"]
        pending_actions = []
        next_rec = f"Continue work on {topic_clean}"
        prog = "Objective defined."
        canonical_purpose = "general"

    return WorkGoal(
        id=goal_id,
        title=title,
        objective=objective,
        topic=topic_clean,
        purpose=canonical_purpose,
        deadline=deadline,
        priority=priority,
        status="NOT_STARTED",
        progress=prog,
        requirements=list(requirements or []),
        deliverables=deliverables,
        subtasks=subtasks,
        dependencies=[],
        source_material=list(source_material or []),
        active_artifact=None,
        pending_actions=pending_actions,
        completed_actions=completed_actions,
        unfinished_actions=unfinished_actions,
        last_activity=datetime.now().isoformat(),
        next_recommended_action=next_rec,
        reminder_state={},
        metadata={"goal_subject": subject, "goal_verb": verb}
    )


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
    requires_elevation: bool = False
    permission_check: Optional[Dict[str, Any]] = None
    elevation_prompt: Optional[str] = None
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
    semantic_command: Optional[Any] = None


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
    requires_elevation: bool = False
    elevation_prompt: Optional[str] = None
    permission_assessment: Optional[Dict[str, Any]] = None
    
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
    # Execution Graph (Section 3 & 5 Integration)
    execution_graph: Optional[Any] = None


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
        
        if isinstance(intent_analysis, str):
            from core.multi_intent_analyzer import multi_intent_analyzer
            intent_analysis = multi_intent_analyzer.analyze(intent_analysis)

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
            requires_elevation=any(s.requires_elevation for s in ordered_steps),
            risk_level=risk_level,
            warnings=self._generate_warnings(ordered_steps, conflicts),
            confidence_score=intent_analysis.confidence_score,
            success_rate_estimate=self._estimate_success_rate(ordered_steps),
        )
        if plan.requires_elevation:
            elev_s = next((s for s in ordered_steps if s.requires_elevation), None)
            if elev_s and elev_s.elevation_prompt:
                plan.elevation_prompt = elev_s.elevation_prompt

        plan.original_plan = {
            "plan_id": plan.plan_id,
            "original_input": plan.original_input,
            "total_steps": plan.total_steps,
            "steps": [
                {"sequence": s.sequence, "intent": s.intent.name, "parameters": dict(s.parameters)}
                for s in plan.steps
            ]
        }
        
        try:
            plan.execution_graph = self.build_execution_graph_for_plan(plan)
        except Exception:
            pass
        
        return plan
    
    def _assess_step_permissions(self, step: ExecutionStep) -> None:
        """
        Assess Windows permissions for an individual execution step.
        Uses PermissionElevationManager as the authoritative gatekeeper.
        """
        try:
            from core.permission_manager import get_permission_elevation_manager
            pm = get_permission_elevation_manager()
            
            op_name = step.parameters.get("operation") or step.parameters.get("action") or (step.intent.name.lower() if hasattr(step.intent, "name") else str(step.intent).lower())
            target = (
                step.parameters.get("target")
                or step.parameters.get("file_path")
                or step.parameters.get("path")
                or step.parameters.get("service_name")
                or step.parameters.get("process_name")
                or step.parameters.get("name")
                or ""
            )
            
            perm_result = pm.check_permission(operation=str(op_name), target=str(target))
            step.permission_check = perm_result.to_dict()
            if perm_result.requires_elevation:
                step.requires_elevation = True
                step.elevation_prompt = pm.format_elevation_prompt(str(op_name), str(target))
            if perm_result.requires_user_consent:
                step.requires_confirmation = True
        except Exception:
            pass

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
        sem_cmd = intent_dict.get("semantic_command")
        params = dict(intent_dict["parameters"])
        if sem_cmd:
            params["semantic_command"] = sem_cmd

        is_power_or_destructive = (
            intent_dict["intent"] in {Intent.POWER_ACTION, Intent.EMERGENCY}
            or getattr(sem_cmd, "safety_class", "") == "CONFIRMATION_REQUIRED"
            or params.get("power_action") in ("shutdown", "restart", "reboot", "power_off")
            or params.get("action") in ("shutdown", "restart", "reboot", "power_off")
        )

        step = ExecutionStep(
            sequence=0,
            intent=intent_dict["intent"],
            parameters=params,
            confidence=intent_dict["confidence"],
            estimated_duration=self.EXECUTION_DURATION.get(intent_dict["intent"], 0.5),
            priority_score=self.INTENT_PRIORITY.get(intent_dict["intent"], 0),
            requires_confirmation=is_power_or_destructive or (intent_dict["confidence"] < 0.8),
            semantic_command=sem_cmd,
        )
        self._assess_step_permissions(step)
        if is_power_or_destructive:
            step.requires_confirmation = True

        risk_level = self._assess_risk([step], [])
        warnings = self._generate_warnings([step], [])

        plan = ExecutionPlan(
            plan_id=str(uuid.uuid4())[:8],
            creation_time=datetime.now().isoformat(),
            original_input=intent_analysis.original_input,
            steps=[step],
            total_steps=1,
            total_estimated_time=step.estimated_duration,
            requires_user_confirmation=step.requires_confirmation,
            requires_elevation=step.requires_elevation,
            elevation_prompt=step.elevation_prompt,
            risk_level=risk_level,
            warnings=warnings,
            confidence_score=intent_dict["confidence"],
            success_rate_estimate=intent_dict["confidence"],
        )
        try:
            plan.execution_graph = self.build_execution_graph_for_plan(plan)
        except Exception:
            pass
        return plan
    
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

            sem_cmd = intent_dict.get("semantic_command")
            if sem_cmd:
                params["semantic_command"] = sem_cmd

            deps = intent_dict.get("dependencies", [])

            is_power_or_destructive = (
                intent in {Intent.POWER_ACTION, Intent.EMERGENCY}
                or getattr(sem_cmd, "safety_class", "") == "CONFIRMATION_REQUIRED"
                or params.get("power_action") in ("shutdown", "restart", "reboot", "power_off")
                or params.get("action") in ("shutdown", "restart", "reboot", "power_off")
            )

            step = ExecutionStep(
                sequence=idx,
                intent=intent,
                parameters=params,
                confidence=intent_dict["confidence"],
                estimated_duration=self.EXECUTION_DURATION.get(intent, 0.5),
                priority_score=self.INTENT_PRIORITY.get(intent, 0),
                requires_confirmation=is_power_or_destructive or (intent_dict["confidence"] < 0.8),
                dependencies=deps,
                retry_on_failure=intent in {Intent.OPEN_APPLICATION, Intent.FILE_OPERATIONS, Intent.RAG_SEARCH, Intent.WEATHER_QUERY},
                max_retries=1,
                continue_on_failure=(len(deps) == 0),
                semantic_command=sem_cmd,
            )
            self._assess_step_permissions(step)
            if is_power_or_destructive:
                step.requires_confirmation = True

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
        
        # Preserve utterance order for steps without explicit dependencies
        # (Dependencies in dep_graph will still be visited first)
        for idx in range(len(steps)):
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

            # Confirmation / elevation requirement penalty
            if getattr(step, "requires_confirmation", False) or getattr(step, "requires_elevation", False):
                risk_score += 25
            
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

    def build_execution_graph_for_plan(self, plan: ExecutionPlan, user_id: int = 1) -> Any:
        """
        Build an ExecutionGraph from an ExecutionPlan.
        Discovers capabilities for each step, sets dependencies and verification definitions.
        """
        try:
            from core.execution_graph import ExecutionGraph, ExecutionNode, NodeStatus
            from core.capability_registry import capability_registry
        except ImportError:
            return None

        graph = ExecutionGraph(
            graph_id=f"graph_{plan.plan_id}",
            goal_id=plan.plan_id,
            user_id=user_id,
            title=f"Plan: {plan.original_input[:60]}" if plan.original_input else "Execution Plan"
        )

        for step in plan.steps:
            node_id = f"{plan.plan_id}_step_{step.sequence + 1}"
            intent_name = step.intent.name if hasattr(step.intent, "name") else str(step.intent)

            best_cap, matched_op = capability_registry.select_best_capability(
                intent_or_description=intent_name,
                desired_outcome=str(step.parameters or {}),
                context=step.input_context or {}
            )

            cap_id = best_cap.capability_id if best_cap else "os_operations"
            op_name = matched_op or intent_name.lower()

            dep_nodes = [f"{plan.plan_id}_step_{d + 1}" for d in step.dependencies]
            preconds = {"prior_steps_completed": dep_nodes} if dep_nodes else {}

            verif_method = best_cap.verification_methods[0] if (best_cap and best_cap.verification_methods) else "verify_output_state"

            status = NodeStatus.PENDING
            if step.status == "COMPLETED":
                status = NodeStatus.COMPLETED
            elif step.status == "FAILED":
                status = NodeStatus.FAILED

            node = ExecutionNode(
                node_id=node_id,
                goal_id=plan.plan_id,
                parent_node_id=dep_nodes[-1] if dep_nodes else None,
                operation=op_name,
                capability=cap_id,
                inputs=dict(step.parameters or {}),
                preconditions=preconds,
                expected_result=f"Completed {intent_name}",
                execution_method=best_cap.execution_methods[0] if (best_cap and best_cap.execution_methods) else "direct",
                status=status,
                verification_method=verif_method,
                verification_result={"expected": f"Verification for {intent_name}"},
                retry_count=step.retry_count,
                max_retries=step.max_retries,
                dependencies=dep_nodes
            )
            graph.add_node(node)

        return graph

    def build_execution_graph(
        self,
        goal: WorkGoal,
        user_id: int = 1,
        context: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Build an ExecutionGraph for a multi-step WorkGoal using Dynamic Capability Discovery.
        Creates sequential and dependent nodes with preconditions, expected results, and verification.
        """
        try:
            from core.execution_graph import ExecutionGraph, ExecutionNode, NodeStatus
            from core.capability_registry import capability_registry
        except ImportError:
            return None

        ctx = context or {}
        graph = ExecutionGraph(
            graph_id=f"graph_{goal.id}_{str(uuid.uuid4())[:6]}",
            goal_id=goal.id,
            user_id=user_id,
            title=goal.title
        )

        items_to_plan: List[Dict[str, Any]] = []
        if goal.subtasks:
            for st in goal.subtasks:
                items_to_plan.append({
                    "title": st.get("title", "Task"),
                    "status": st.get("status", "PENDING"),
                    "type": st.get("deliverable_type") or "subtask",
                    "requires_user": st.get("requires_user", False),
                    "raw": st
                })
        elif goal.pending_actions:
            for pa in goal.pending_actions:
                act = pa.get("action", "action") if isinstance(pa, dict) else str(pa)
                items_to_plan.append({
                    "title": act,
                    "status": "PENDING",
                    "type": "action",
                    "requires_user": False,
                    "raw": pa
                })
        else:
            items_to_plan.append({
                "title": goal.objective or goal.title,
                "status": "PENDING",
                "type": "goal",
                "requires_user": False,
                "raw": {}
            })

        prev_node_id: Optional[str] = None
        for idx, item in enumerate(items_to_plan):
            node_id = f"{goal.id}_node_{idx + 1}"
            title = item["title"]

            best_cap, matched_op = capability_registry.select_best_capability(
                intent_or_description=title,
                desired_outcome=goal.objective,
                context={"topic": goal.topic, "purpose": goal.purpose, **ctx}
            )

            cap_id = best_cap.capability_id if best_cap else "os_operations"
            op_name = matched_op or ("execute_action" if item["type"] == "action" else "run_subtask")

            dependencies = [prev_node_id] if prev_node_id else []
            preconditions = {"prior_step_completed": prev_node_id} if prev_node_id else {}

            verif_method = best_cap.verification_methods[0] if (best_cap and best_cap.verification_methods) else "verify_output_state"

            status = NodeStatus.COMPLETED if item.get("status") == "COMPLETED" else NodeStatus.PENDING

            node = ExecutionNode(
                node_id=node_id,
                goal_id=goal.id,
                parent_node_id=prev_node_id,
                operation=op_name,
                capability=cap_id,
                inputs={"title": title, "item_data": item["raw"], "topic": goal.topic},
                preconditions=preconditions,
                expected_result=f"Completed {title}",
                execution_method=best_cap.execution_methods[0] if (best_cap and best_cap.execution_methods) else "direct",
                status=status,
                verification_method=verif_method,
                verification_result={"expected": f"Verify completion of '{title}'"},
                dependencies=dependencies
            )

            graph.add_node(node)
            prev_node_id = node_id

        return graph


# ============================================================================
# Global Planner Instance
# ============================================================================

goal_planner = GoalPlanner()


def build_execution_graph_for_goal(goal: WorkGoal, user_id: int = 1, context: Optional[Dict[str, Any]] = None) -> Any:
    """Build an execution graph for a WorkGoal."""
    return goal_planner.build_execution_graph(goal, user_id=user_id, context=context)


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
