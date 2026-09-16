"""
assistant_os/planner/planner.py
============================
NOVA OS - Planner: Core Orchestrator

Architecture:
    The Planner is the ONLY public entry point for the Brain to request
    a task plan. It orchestrates the three internal sub-components:

        GoalDecomposer      →  flat list of subtask instructions
        IntentClassifier    →  AgentType + RiskLevel per instruction
        DependencyResolver  →  validates and topologically sorts the DAG

    The Planner DOES NOT:
        ✗ Execute any tasks
        ✗ Call any tools
        ✗ Communicate with any agent
        ✗ Modify the Router
        ✗ Read or write to Memory or Database

    The Planner ONLY:
        ✓ Receives a BrainOutput
        ✓ Returns a TaskPlan
        ✓ Enforces max_tasks safety limit
        ✓ Sets requires_approval based on RiskLevel and PlannerConfig
        ✓ Logs all decisions for traceability

Integration with Brain:
    The Brain calls the Planner at the boundary between
    "understanding the goal" and "dispatching agent tasks".

    Example integration (Brain pseudocode):
        ┌──────────────────────────────────────────────────────┐
        │ from assistant_os.planner import Planner, BrainOutput     │
        │                                                      │
        │ brain_output = BrainOutput(                          │
        │     goal="Research AI trends and email me a summary",│
        │     raw_input=user_utterance,                        │
        │     session_id=session.id,                           │
        │     user_id=user.id,                                 │
        │     context=memory_manager.assemble_context(...),    │
        │ )                                                    │
        │                                                      │
        │ planner = Planner()                                  │
        │ task_plan = planner.create_plan(brain_output)        │
        │                                                      │
        │ # Brain then passes task_plan to Agent Manager.      │
        │ # The Planner's job is done.                         │
        └──────────────────────────────────────────────────────┘

SDD Reference: Sections 11 (Brain), 12 (Planner), 27 (Data Flow).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import List

_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from assistant_os.planner.dependency_resolver import DependencyResolver
from assistant_os.planner.goal_decomposer import GoalDecomposer
from assistant_os.planner.intent_classifier import IntentClassifier
from assistant_os.planner.models import (
    AgentType,
    BrainOutput,
    PlannerConfig,
    RiskLevel,
    TaskNode,
    TaskPlan,
)

logger = logging.getLogger("assistant_os.planner")


class Planner:
    """
    Converts a BrainOutput (high-level user goal) into a validated
    TaskPlan (DAG of TaskNodes) ready for Agent Manager dispatch.

    The Planner is stateless between plan calls. A single Planner
    instance may be reused across multiple Brain invocations.

    Constructor Args:
        config: PlannerConfig instance.  Uses defaults if not provided.

    Usage:
        planner = Planner()
        plan    = planner.create_plan(brain_output)
    """

    def __init__(self, config: PlannerConfig | None = None):
        self.config     = config or PlannerConfig()
        self.decomposer = GoalDecomposer(
            use_llm        = self.config.use_llm,
            min_confidence = self.config.min_confidence,
            max_tasks      = self.config.max_tasks,
        )
        self.classifier = IntentClassifier(use_llm=self.config.use_llm)
        self.resolver   = DependencyResolver()

        logger.info(
            f"[Planner] Initialized — use_llm={self.config.use_llm}, "
            f"max_tasks={self.config.max_tasks}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_plan(self, brain_output: BrainOutput) -> TaskPlan:
        """
        Entry point for the Brain.

        Converts a BrainOutput into a validated, topologically sorted
        TaskPlan ready for the Agent Manager.

        Args:
            brain_output: Structured intent from the Brain module.

        Returns:
            TaskPlan with sorted TaskNodes and execution_groups.
            Guaranteed to contain at least one TaskNode.

        Raises:
            ValueError: If the task graph is cyclic or has unknown deps.
        """
        goal       = brain_output.goal.strip()
        session_id = brain_output.session_id
        context    = brain_output.context

        logger.info(f"[Planner] Planning goal: {goal!r} (session={session_id})")

        # ── Step 1: Decompose goal into flat list of instructions ─────────
        instructions: List[str] = self.decomposer.decompose(goal, context)
        logger.info(f"[Planner] Decomposed into {len(instructions)} instruction(s).")

        # ── Step 2: Enforce max_tasks safety limit ────────────────────────
        if len(instructions) > self.config.max_tasks:
            logger.warning(
                f"[Planner] Decomposed {len(instructions)} tasks — "
                f"capping at {self.config.max_tasks}."
            )
            instructions = instructions[: self.config.max_tasks]

        # ── Step 3: Build TaskNodes from instructions ─────────────────────
        plan_id = None  # Will be set from TaskPlan after creation
        nodes   = self._build_nodes(instructions, session_id)

        # ── Step 4: Infer sequential dependencies ─────────────────────────
        #   By default, each task depends on the one before it.
        #   This is the conservative baseline — the Planner guarantees
        #   safe sequential execution. Parallelism is discovered in
        #   Step 5 when the DependencyResolver finds independent waves.
        self._chain_dependencies(nodes)

        # ── Step 5: Resolve DAG (validate + topological sort + parallelism)─
        sorted_nodes, execution_groups = self.resolver.resolve(nodes)

        # ── Step 6: Assemble the TaskPlan ────────────────────────────────
        plan = TaskPlan(
            session_id       = session_id,
            goal             = goal,
            tasks            = sorted_nodes,
            execution_groups = execution_groups,
        )

        # Stamp plan_id back onto each node
        for node in plan.tasks:
            node.plan_id = plan.plan_id

        logger.info(
            f"[Planner] Plan ready: {plan.plan_id} — "
            f"{plan.total_tasks} task(s), "
            f"{len(plan.execution_groups)} wave(s), "
            f"has_approvals={plan.has_approvals}"
        )
        return plan

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _build_nodes(
        self, instructions: List[str], session_id: str
    ) -> List[TaskNode]:
        """
        Create a TaskNode for each instruction string.

        For each instruction:
            - Classify to get AgentType and RiskLevel.
            - Determine if requires_approval (based on risk + config).
        """
        nodes: List[TaskNode] = []

        for idx, instruction in enumerate(instructions):
            agent_type, risk = self.classifier.classify(instruction)

            if agent_type == AgentType.UNKNOWN:
                # Default to CONVERSATION for unclassified tasks so
                # the Brain can ask the user rather than failing silently.
                agent_type = AgentType.CONVERSATION
                logger.debug(
                    f"[Planner] Step {idx}: Could not classify {instruction!r:.60} — "
                    f"defaulting to CONVERSATION."
                )

            requires_approval = self._needs_approval(risk)

            node = TaskNode(
                agent_type        = agent_type,
                instruction       = instruction,
                risk_level        = risk,
                requires_approval = requires_approval,
                rationale         = (
                    f"Classified as {agent_type.value} with {risk.value} risk "
                    f"from instruction: {instruction[:60]!r}"
                ),
                metadata          = {"session_id": session_id, "step_index": idx},
            )
            nodes.append(node)
            logger.debug(
                f"[Planner] Node {idx}: agent={agent_type.value}, "
                f"risk={risk.value}, approval={requires_approval}, "
                f"instruction={instruction[:60]!r}"
            )

        return nodes

    def _chain_dependencies(self, nodes: List[TaskNode]) -> None:
        """
        Build a sequential dependency chain (task N depends on task N-1).

        This is the default conservative strategy.  It ensures correct
        execution order and is always safe.

        If the LLM or a future DependencyInferencer provides richer
        dependency annotations, they can override this by populating
        node.dependencies before this method runs.

        Nodes that already have dependencies set are not overridden.
        """
        for idx, node in enumerate(nodes):
            if idx == 0:
                continue  # First task has no predecessor
            if not node.dependencies:  # Respect pre-set dependencies
                node.dependencies = [nodes[idx - 1].task_id]

    def _needs_approval(self, risk: RiskLevel) -> bool:
        """
        Determine if a task requires user approval before execution.

        Rules:
            CRITICAL → always requires approval
            HIGH     → always requires approval
            MEDIUM   → requires approval
            LOW      → auto-approved if PlannerConfig.auto_approve_low=True
        """
        if risk in (RiskLevel.CRITICAL, RiskLevel.HIGH):
            return True
        if risk == RiskLevel.MEDIUM:
            return True
        # LOW risk
        return not self.config.auto_approve_low
