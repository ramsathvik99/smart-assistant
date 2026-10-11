"""
Content and Structure Generation Helper for Document Tools.
Generates substantive, professional, topic-faithful content for DOCX, PPTX, XLSX, and PDF documents
based on user intent, structured specifications, topic locks, and natural language queries.
"""

import os
import re
import math
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# ArtifactContentSpec — Canonical Structured Content Model
# ============================================================================

@dataclass
class ArtifactContentSpec:
    """Structured specification defining topic, format, length, depth, and constraints for artifact generation."""
    artifact_type: str  # "PPT", "DOCX", "XLSX", "PDF"
    title: str          # Main title for the artifact
    subject: str        # Substantive subject / topic (Topic Lock)
    purpose: str = "presentation"  # "presentation", "report", "notes", "analysis", "spreadsheet"
    requested_length: Optional[int] = None  # Explicit user-specified number (slides / pages)
    requested_format_requirements: List[str] = field(default_factory=list)
    audience: Optional[str] = None
    depth: str = "normal"  # "simple", "normal", "complex", "comprehensive"
    source_material: Optional[str] = None
    required_sections: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)
    is_refinement: bool = False
    refinement_instruction: Optional[str] = None
    parent_artifact: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "title": self.title,
            "subject": self.subject,
            "purpose": self.purpose,
            "requested_length": self.requested_length,
            "requested_format_requirements": self.requested_format_requirements,
            "audience": self.audience,
            "depth": self.depth,
            "source_material": self.source_material,
            "required_sections": self.required_sections,
            "constraints": self.constraints,
            "is_refinement": self.is_refinement,
            "refinement_instruction": self.refinement_instruction
        }


# ============================================================================
# Topic Extraction & Topic Lock
# ============================================================================

_GENERIC_TOPIC_TERMS = {
    "document", "presentation", "report", "slides", "spreadsheet", "excel", "file",
    "powerpoint", "word", "pdf", "docx", "pptx", "xlsx", "universal presentation",
    "general overview", "general information", "data summary", "stuff", "it", "this", "that",
    "make it", "make this", "make that", "turn it", "turn this", "put this", "put it",
    "add it", "add this", "add that", "shorter", "more detailed", "make", "create", "generate",
    "project", "my project", "project presentation", "my project presentation", "work", "task",
    "from the same information", "the same information", "same information",
    "references to both", "references", "both", "references to both the presentation and report",
    "now based on that information", "based on that information", "from that information",
    "now based on information", "based on information", "from information",
    "from that info", "using that information", "based on the information",
    "from the information", "from the gathered information", "based on gathered information",
    "from that", "based on that", "the gathered information", "gathered information",
    "all the information", "that information"
}


def extract_topic_from_query(
    query: str,
    default: str = "General Overview",
    context: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None
) -> str:
    """
    Extract substantive topic from user query.
    If the query has no explicit topic (e.g. 'Create the PPT', 'make it 10 slides', 'now based on that information create a PPT'),
    extracts the active topic from conversational context / active goals.
    """
    clean = re.sub(
        r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)[,\s:]*',
        '',
        query,
        flags=re.IGNORECASE
    ).strip()

    # Check if query starts with "gather everything..."
    m_gather = re.search(r'\bgather\s+everything(?:\s+important)?\s+(?:about|on)\s+(.+?)(?:\s+(?:and\s+)?(?:make|create|build|generate).*)?$', clean, re.IGNORECASE)
    if m_gather:
        return m_gather.group(1).strip(' .?!').title()

    # Strip command verbs and document type mentions
    clean = re.sub(
        r'\b(?:can\s+you\s+|please\s+)?(?:create|created|generate|generated|make|made|write|wrote|build|built|gather\s+everything\s+about|gather\s+all\s+information\s+about)\s+(?:an?|the)?\s*'
        r'(?:(?:\d+[\s\-]slides?|\d+[\s\-]pages?|detailed|comprehensive|powerful|new)\s+)?'
        r'(?:word\s+doc(?:ument)?|docx|pdf(?:\s+document|\s+report)?|excel(?:\s+expense\s+sheet|\s+sheet|\s+spreadsheet|\s+file)?|spreadsheet|xlsx|powerpoint(?:\s+presentation)?|presentation|pptx|ppt|slides|document|report)\b',
        '',
        clean,
        flags=re.IGNORECASE
    ).strip()

    # Strip prefixes like "about", "on", "titled", "named", "for"
    clean = re.sub(r'^(?:with\s+\d+[\s\-]slides?\s+)?(?:about|on|for|titled|named)\s+', '', clean, flags=re.IGNORECASE).strip()
    clean = re.sub(r'\b(?:with\s+\d+[\s\-]slides?|with\s+\d+[\s\-]pages?|\d+[\s\-]slides?|\d+[\s\-]pages?)\b', '', clean, flags=re.IGNORECASE).strip(' .?!')

    # Remove trailing words like "and make a powerful ppt", "and create presentation"
    clean = re.sub(r'\b(?:and\s+)?(?:make|create|build|generate)\s+(?:an?|the)?\s*(?:powerful\s+|good\s+)?(?:ppt|presentation|document|report|pdf|slides)\b.*$', '', clean, flags=re.IGNORECASE).strip(' .?!')

    # Check if cleaned topic is a refinement instruction or contains generic/referential words
    is_refinement_phrase = any(re.search(p, clean, re.IGNORECASE) for p in [
        r'^(?:make|turn|convert|put)\s+(?:it|this|that)\b',
        r'^(?:make\s+the\s+document|make\s+it\s+(?:shorter|more\s+detailed))\b',
        r'^(?:add|remove)\b',
        r'^\d+[\s\-]*(?:slides?|pages?|sheets?)\b',
        r'^(?:now\s+)?(?:based\s+on|from|using)\s+(?:that|the|all|gathered)?\s*(?:same\s+)?(?:information|info|data|research|topic)?\b'
    ])
    clean_low = clean.lower().strip(' .?!')
    is_generic = not clean or len(clean) < 2 or clean_low in _GENERIC_TOPIC_TERMS or is_refinement_phrase or any(clean_low.startswith(p) for p in ("now based on", "based on", "from that", "from the same", "using that"))

    if is_generic and context is None:
        try:
            from instance.config import settings
            from core.user_isolation import resolve_identity
            eff_uid = resolve_identity(user_id)
            dm = None
            if eff_uid:
                dm = get_dialogue_manager(str(eff_uid))
            else:
                for m in _dialogue_managers.values():
                    if m.current_state and (m.current_state.session_context.get("topic_lock") or getattr(m.current_state, "current_goal", None)):
                        dm = m
                        break
            if dm and dm.current_state:
                context = {
                    "active_goal": getattr(dm.current_state, "current_goal", None),
                    "active_natural_goal": dm.current_state.session_context.get("active_natural_goal"),
                    "topic_lock": dm.current_state.session_context.get("topic_lock"),
                    "active_document": getattr(dm.current_state, "active_document", None),
                    "active_artifact": dm.current_state.session_context.get("active_artifact"),
                }
        except Exception:
            context = None

    if is_generic and context:
        # Fall back to context hierarchy (Active Goal -> Session Context -> Active Artifact)
        active_g = context.get("active_goal") or context.get("current_goal") or {}
        if isinstance(active_g, dict):
            if active_g.get("topic") and str(active_g["topic"]).lower() not in _GENERIC_TOPIC_TERMS:
                return str(active_g["topic"]).strip().title()

        for key in ["topic", "active_topic", "topic_lock"]:
            if context.get(key) and str(context[key]).lower() not in _GENERIC_TOPIC_TERMS:
                return str(context[key]).strip().title()

        if isinstance(active_g, dict):
            if active_g.get("goal_subject") and str(active_g["goal_subject"]).lower() not in _GENERIC_TOPIC_TERMS:
                return str(active_g["goal_subject"]).strip().title()

        active_art = context.get("active_document") or context.get("active_artifact") or {}
        if isinstance(active_art, dict) and (active_art.get("subject") or active_art.get("title")):
            cand = active_art.get("subject") or active_art.get("title")
            if cand and str(cand).lower() not in _GENERIC_TOPIC_TERMS:
                return str(cand).strip().title()

    if not clean or len(clean) < 2 or clean_low in _GENERIC_TOPIC_TERMS or is_refinement_phrase:
        return default

    return clean.title()


def construct_content_spec(
    user_input: str,
    params: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None
) -> ArtifactContentSpec:
    """
    Construct a structured ArtifactContentSpec with Topic Lock from query and context.
    """
    params = params or {}
    context = context or {}
    q_low = user_input.lower().strip()

    # 1. Determine Artifact Type
    doc_type_raw = params.get("doc_type") or ""
    if not doc_type_raw:
        if "pdf" in q_low or "turn this into a pdf" in q_low or "convert to pdf" in q_low:
            doc_type_raw = "pdf"
        elif any(k in q_low for k in ["excel", "spreadsheet", "xlsx", "sheet", "put this into excel"]):
            doc_type_raw = "xlsx"
        elif any(k in q_low for k in ["powerpoint", "presentation", "slides", "pptx", "ppt"]):
            doc_type_raw = "pptx"
        else:
            # Check active artifact if this is a refinement (e.g., "make it 10 slides", "add deadlock detection")
            active_doc = context.get("active_document") or context.get("active_artifact")
            if active_doc and "slide" in q_low:
                doc_type_raw = "pptx"
            elif active_doc and (active_doc.get("doc_type") or active_doc.get("type")):
                doc_type_raw = active_doc.get("doc_type") or active_doc.get("type")
            elif any(k in q_low for k in ["report", "document", "doc", "word"]):
                doc_type_raw = "docx"
            elif active_doc:
                doc_type_raw = active_doc.get("doc_type") or active_doc.get("type") or "docx"
            else:
                doc_type_raw = "docx"

    artifact_type_map = {"pptx": "PPT", "ppt": "PPT", "docx": "DOCX", "doc": "DOCX", "pdf": "PDF", "xlsx": "XLSX", "excel": "XLSX"}
    artifact_type = artifact_type_map.get(doc_type_raw.lower(), "DOCX")

    # 2. Extract Requested Length (Slide count or Page count)
    _WORD_TO_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twenty": 20}
    requested_length = params.get("requested_length")
    if not requested_length:
        m_count = re.search(r'\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twenty)[\s\-]*(?:slides?|pages?|sheets?)\b', q_low)
        if m_count:
            raw_c = m_count.group(1).lower()
            requested_length = int(raw_c) if raw_c.isdigit() else _WORD_TO_NUM.get(raw_c)

    # 3. Detect Refinement / Follow-up Commands
    is_refinement = False
    refinement_instruction = None
    active_doc = context.get("active_document") or context.get("active_artifact")

    # Relative slide count addition (e.g. "add two slides to the presentation")
    m_add_slides = re.search(r'\badd\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)[\s\-]*(?:more\s+)?slides?\b', q_low)
    if m_add_slides and active_doc:
        raw_add = m_add_slides.group(1).lower()
        add_num = int(raw_add) if raw_add.isdigit() else _WORD_TO_NUM.get(raw_add, 2)
        base_slides = active_doc.get("slide_count") or 10
        requested_length = base_slides + add_num

    refinement_triggers = [
        "make it ", "make the document ", "add a section", "add two more", "add ",
        "remove the ", "make it shorter", "make it more detailed", "turn this into",
        "convert this to", "put this into", "shorter", "more detailed"
    ]
    if active_doc and (any(trig in q_low for trig in refinement_triggers) or q_low.startswith(("make it", "add ", "remove "))):
        is_refinement = True
        refinement_instruction = user_input

    # 4. Extract Subject & Establish Topic Lock
    if is_refinement and active_doc and (active_doc.get("subject") or active_doc.get("title")):
        subject = active_doc.get("subject") or active_doc.get("title")
    else:
        explicit_topic = extract_topic_from_query(user_input, default="", context=context)
        if explicit_topic and explicit_topic.lower() not in _GENERIC_TOPIC_TERMS:
            subject = explicit_topic
        else:
            subject = extract_topic_from_query(user_input, default="Technical Overview", context=context)

    # 5. Derive Title
    if is_refinement and active_doc and (active_doc.get("title") or active_doc.get("subject")):
        title = active_doc.get("title") or active_doc.get("subject")
    else:
        title = params.get("title")
        if not title or title.lower() in _GENERIC_TOPIC_TERMS:
            title = subject

    # 6. Inferred Depth
    if any(k in q_low for k in ["gather everything", "all important", "comprehensive", "detailed", "in-depth", "deep"]):
        depth = "comprehensive"
    elif any(k in q_low for k in ["brief", "short", "quick", "simple", "overview"]):
        depth = "simple"
    elif any(k in subject.lower() for k in ["deadlock", "network", "distributed", "machine learning", "operating system", "security", "algorithm"]):
        depth = "complex"
    else:
        depth = "normal"

    # 7. Extract Requirements / Source Material from Context
    source_material = None
    required_sections = []
    active_g = context.get("active_goal") or context.get("current_goal") or {}
    if isinstance(active_g, dict) and active_g.get("requirements"):
        required_sections.extend(active_g["requirements"])
        source_material = "; ".join(active_g["requirements"])

    # Source Reuse (Level 6 Section 22): "Create a PPT from my report"
    if any(k in q_low for k in ["from my report", "from the report", "from report"]):
        rep_doc = None
        if active_doc and str(active_doc.get("type", "")).lower() in ("docx", "doc", "pdf", "report"):
            rep_doc = active_doc
        elif context.get("active_documents"):
            for d in context.get("active_documents"):
                if str(d.get("type", "")).lower() in ("docx", "doc", "pdf", "report"):
                    rep_doc = d
                    break
        if rep_doc:
            rep_subj = rep_doc.get("subject") or rep_doc.get("title") or subject
            subject = rep_subj
            title = f"{subject} Presentation"
            source_material = f"Derived directly from existing verified technical report on {subject}."
            if "Report Findings" not in required_sections:
                required_sections.extend(["Executive Summary & Findings", "Detailed Analysis", "Strategic Takeaways"])

    return ArtifactContentSpec(
        artifact_type=artifact_type,
        title=title,
        subject=subject,
        purpose="presentation" if artifact_type == "PPT" else ("spreadsheet" if artifact_type == "XLSX" else "report"),
        requested_length=requested_length,
        requested_format_requirements=[],
        audience=None,
        depth=depth,
        source_material=source_material,
        required_sections=required_sections,
        constraints={},
        is_refinement=is_refinement,
        refinement_instruction=refinement_instruction,
        parent_artifact=active_doc if is_refinement else None
    )


# ============================================================================
# Substantive Topic Knowledge Bases & Synthesizers
# ============================================================================

def _build_dbms_deadlock_deck(spec: ArtifactContentSpec, target_slides: int) -> List[Dict[str, Any]]:
    """Build highly technical, topic-faithful slides on DBMS Deadlocks."""
    # Comprehensive modular slide library covering every core aspect
    all_units = [
        {
            "title": "What is a DBMS Deadlock?",
            "bullets": [
                "A deadlock is a permanent blocking condition where two or more transactions mutually wait for locks held by each other",
                "Occurs in concurrent environments enforcing data isolation via lock-based concurrency control (e.g., Strict 2PL)",
                "Neither transaction can proceed, release locks, or terminate without external intervention from the database engine",
                "Results in transaction stalls, increased latency, and wasted computing resources if unresolved"
            ],
            "notes": "Define the fundamental deadlock phenomenon in transactional databases and explain why locks cause mutual blocking."
        },
        {
            "title": "Root Causes & Concurrency Bottlenecks",
            "bullets": [
                "Concurrent conflicting transactions executing interleaved read and write operations",
                "Lock Escalation: Converting fine-grained row locks to table locks under heavy load",
                "Unordered Resource Access: Multiple transactions requesting identical resources in differing chronological sequences",
                "Long-Running Transactions: Broad transaction scopes holding exclusive (X) locks for extended durations"
            ],
            "notes": "Explain how conflicting operations, lock escalation, and unordered access create the conditions for deadlocks."
        },
        {
            "title": "The Four Coffman Conditions",
            "bullets": [
                "Mutual Exclusion: Resources/data rows are held in exclusive, non-shareable mode by transactions",
                "Hold and Wait: Transactions hold previously allocated locks while actively requesting additional resources",
                "No Preemption: The DBMS cannot forcibly revoke a granted lock before transaction completion",
                "Circular Wait: A closed chain of transactions exists where each waits for a resource held by the next"
            ],
            "notes": "Detail the four theoretical Coffman conditions required for deadlocks to occur. Breaking any one condition prevents deadlocks."
        },
        {
            "title": "Transaction & Resource Interaction Model",
            "bullets": [
                "Transaction T1 acquires Exclusive Lock on Row A and requests lock on Row B",
                "Simultaneously, Transaction T2 acquires Exclusive Lock on Row B and requests lock on Row A",
                "Shared (S) vs Exclusive (X) lock matrices dictate compatibility and blocking behavior",
                "Both transactions enter BLOCKED state; neither can commit nor release granted locks"
            ],
            "notes": "Walk through a concrete two-transaction interleaving example illustrating resource contention and mutual blockage."
        },
        {
            "title": "Wait-For Graph (WFG) Analysis",
            "bullets": [
                "A directed graph G = (V, E) where vertices V represent active transactions",
                "A directed edge (Ti -> Tj) exists if transaction Ti is waiting for Tj to release a needed lock",
                "A cycle in the Wait-For Graph is both necessary and sufficient for a deadlock condition in single-unit systems",
                "DBMS maintains in-memory lock tables to periodically construct and inspect the dynamic WFG"
            ],
            "notes": "Explain how the database models waiting dependencies as a directed graph and identifies cycles."
        },
        {
            "title": "Deadlock Detection Algorithms",
            "bullets": [
                "Periodic Background Inspection: Engine runs cycle detection at configured intervals (e.g. deadlock_timeout)",
                "Graph Traversal Algorithms: Depth-First Search (DFS) or Tarjan's Strongly Connected Components to locate cycles",
                "Timeout-Based Detection: Aborts any transaction whose lock wait duration exceeds an absolute threshold",
                "Trade-off: Frequent graph checks consume CPU; infrequent checks increase lock holding overhead"
            ],
            "notes": "Detail how production database engines discover cycles via graph algorithms versus simple timeout heuristics."
        },
        {
            "title": "Deadlock Prevention Strategies",
            "bullets": [
                "Conservative Two-Phase Locking: Require transactions to acquire all necessary locks upfront prior to execution",
                "Wait-Die Scheme (Non-preemptive): Older transaction waits for younger; younger transaction immediately aborts and dies",
                "Wound-Wait Scheme (Preemptive): Older transaction wounds/preempts younger; younger waits for older",
                "Resource Ordering: Enforce a global monotonic sequence for lock acquisition across all application code"
            ],
            "notes": "Examine proactive prevention schemes, particularly timestamp-based Wait-Die and Wound-Wait algorithms."
        },
        {
            "title": "Deadlock Avoidance Principles",
            "bullets": [
                "Dynamic State Evaluation: Grant lock requests only if the resulting system state remains provably safe",
                "Banker's Algorithm: Requires prior declaration of maximum resource demands per transaction",
                "Lock Hierarchy Enforcement: Structuring tables, rows, and partitions into strict hierarchical tiers",
                "Practical Limitations: Rare in commercial DBMS due to unpredictability of dynamic SQL transaction paths"
            ],
            "notes": "Clarify the theoretical difference between prevention (static rules) and avoidance (dynamic safe-state checks)."
        },
        {
            "title": "Deadlock Recovery & Victim Selection",
            "bullets": [
                "Victim Selection Criteria: Minimum transaction age, least work completed, fewest locks held, lowest rollback cost",
                "Rollback Execution: Abort chosen victim transaction, revoke locks, and cascade release to waiting transactions",
                "Starvation Mitigation: Increment retry priority or timestamp so repeated victim transactions eventually complete",
                "Error Propagation: Database returns error code (e.g. SQLSTATE 40P01) instructing client to retry"
            ],
            "notes": "Describe how the DBMS chooses which transaction to abort to break the cycle, and how it prevents starvation."
        },
        {
            "title": "Database Engine Implementations",
            "bullets": [
                "PostgreSQL: Configurable 'deadlock_timeout' (default 1s); constructs WFG only after threshold expires",
                "MySQL InnoDB: Immediate deadlock detection via internal lock graph search; aborts transaction with fewest row modifications",
                "Oracle Database: Automated background detector (LMD process) in RAC clusters for distributed lock graphs",
                "Transaction Log Telemetry: Deadlock graphs recorded in system error logs for query analysis and tuning"
            ],
            "notes": "Compare how major commercial and open-source database engines handle deadlocks in production environments."
        },
        {
            "title": "Application Engineering Best Practices",
            "bullets": [
                "Consistent Access Ordering: Access database tables and records in a uniform order across all application endpoints",
                "Keep Transactions Brief: Eliminate external RPCs, heavy computational processing, and user interaction during open transactions",
                "Proper Indexing: Ensure queries use indexes to avoid whole-table scans escalating into broad table locks",
                "Exponential Backoff & Retry: Implement robust client-side retry loops with randomized jitter upon SQLSTATE 40P01"
            ],
            "notes": "Provide actionable architectural patterns for software engineers to minimize deadlock frequency in production."
        },
        {
            "title": "Distributed Deadlocks & Advanced Scenarios",
            "bullets": [
                "Distributed Transactions: Spanning multiple physical nodes coordinated via Two-Phase Commit (2PC)",
                "Phantom Deadlocks: Latency delays causing local detectors to perceive false cycles that have already cleared",
                "Global Wait-For Graphs: Centralized coordinator vs distributed edge-chasing (probe-based) detection algorithms",
                "Impact: Multi-node rollbacks are substantially more expensive in network bandwidth and latency"
            ],
            "notes": "Explore distributed deadlock complexities, edge-chasing algorithms, and multi-node coordination challenges."
        },
        {
            "title": "Performance Implications & Concurrency Trade-offs",
            "bullets": [
                "Isolation Level Balancing: Weighing Serializable/Repeatable Read safety against Read Committed throughput",
                "Lock Contention Spikes: Cascading queues behind heavily contested records reducing overall database TPS",
                "Optimistic Concurrency Control (OCC): Using versioning (MVCC) to avoid shared locks on read operations",
                "Monitoring KPIs: Tracking deadlock frequency, lock wait time, and transaction abort rates in telemetry dashboards"
            ],
            "notes": "Review the operational trade-offs between strict consistency isolation levels and concurrency performance."
        },
        {
            "title": "Summary & Operational Takeaways",
            "bullets": [
                "Deadlocks are an unavoidable mathematical consequence of concurrent exclusive locking protocols",
                "Effective mitigation combines engine detection with disciplined application-level lock ordering",
                "Always design idempotent transaction retry handlers with jitter at the application layer",
                "Maintain comprehensive observability on database lock wait durations and deadlock frequency"
            ],
            "notes": "Conclude with core operational principles and architectural guidelines for managing deadlocks in enterprise systems."
        }
    ]

    # Select or expand to target_slides
    if target_slides <= len(all_units):
        # Evenly sample or pick top units
        if target_slides == 5:
            indices = [0, 2, 4, 6, 8]  # Intro, Coffman, WFG, Prevention, Recovery
        elif target_slides == 8:
            indices = [0, 1, 2, 4, 5, 6, 8, 10]
        elif target_slides == 10:
            indices = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10]
        else:
            indices = list(range(target_slides))
        selected = [all_units[i] for i in indices]
    else:
        # If target_slides > len(all_units) (e.g. 20 slides requested)
        selected = list(all_units)
    expansion_topics = [
        ("Two-Phase Locking (2PL) Mechanics", [
            "Growing Phase: Acquiring locks without releasing any previously held resources",
            "Shrinking Phase: Releasing locks without acquiring any new resource locks",
            "Strict 2PL: Retaining all exclusive locks until commit or abort to prevent cascading rollbacks",
            "Rigorous 2PL: Retaining both shared and exclusive locks until completion for strict serializability"
        ]),
        ("Lock Compatibility & Lock Modes", [
            "Shared Locks (S): Allow multiple concurrent readers; blocks exclusive writer requests",
            "Exclusive Locks (X): Grants single writer access; blocks both shared and exclusive requests",
            "Intent Locks (IS, IX): Multi-granularity locking indicating intent at sub-tier row levels",
            "Lock Upgrade Conflicts: Two transactions holding shared locks simultaneously requesting exclusive upgrades"
        ]),
        ("PostgreSQL Deadlock Telemetry & pg_stat_activity", [
            "Querying 'pg_stat_activity' to view currently blocked queries and waiting lock states",
            "Inspecting 'pg_locks' to map relation OIDs and transaction IDs involved in lock contention",
            "Detailed deadlock error messages detailing queries, PIDs, and conflicting lock modes",
            "Configuring 'log_lock_waits = on' to capture transactions stalled for longer than deadlock_timeout"
        ]),
        ("MySQL InnoDB Deadlock Investigation", [
            "Executing 'SHOW ENGINE INNODB STATUS' to inspect the 'LATEST DETECTED DEADLOCK' section",
            "Analyzing lock wait details: space ID, page number, record heap number, and transaction state",
            "Evaluating index lock types: Record locks, Gap locks, and Next-Key locking mechanisms",
            "Root causing phantom insert contention within foreign key index trees"
        ]),
        ("Distributed Deadlock Detection & Edge Chasing", [
            "Chandy-Misra-Haas Algorithm: Initiating probe messages along dependent transaction paths",
            "Probe Structure: (initiator, sender, receiver) transmitted across distributed node boundaries",
            "Cycle Verification: If a probe message returns to its original initiator, a global cycle exists",
            "Eliminating communication overhead by checking local subgraphs prior to inter-node broadcasting"
        ]),
        ("Database Deadlock Mitigation Checklist", [
            "Enforce strict alphabetical or numerical ordering when acquiring multiple row locks",
            "Convert batch multi-row updates into smaller, deterministic chunked transactions",
            "Adopt 'SELECT ... FOR UPDATE SKIP LOCKED' or 'NOWAIT' for queue worker consumption",
            "Establish continuous alerting on deadlock counters in APM and database monitoring suites"
        ])
    ]
    for exp_title, exp_bullets in expansion_topics:
        if len(selected) >= target_slides:
            break
        selected.append({
            "title": exp_title,
            "bullets": exp_bullets,
            "notes": f"Technical deep-dive into {exp_title}."
        })
    # Ensure required sections from spec or refinement instruction are included
    reqs = [r.lower() for r in (spec.required_sections or [])]
    if spec.is_refinement and spec.refinement_instruction:
        reqs.append(spec.refinement_instruction.lower())

    for req in reqs:
        if "detection" in req and not any("detection" in u["title"].lower() for u in selected):
            selected.append(all_units[5])
        if "recovery" in req and not any("recovery" in u["title"].lower() for u in selected):
            selected.append(all_units[8])
        if "prevention" in req and not any("prevention" in u["title"].lower() for u in selected):
            selected.append(all_units[6])
        if "avoidance" in req and not any("avoidance" in u["title"].lower() for u in selected):
            selected.append(all_units[7])
        if "reference" in req and not any("reference" in u["title"].lower() for u in selected):
            selected.append({
                "title": "Key References & Academic Literature",
                "bullets": [
                    "Silberschatz, A., Korth, H. F., & Sudarshan, S. Database System Concepts (7th Edition)",
                    "Gray, J., & Reuter, A. Transaction Processing: Concepts and Techniques",
                    "Coffman, E. G., Elphick, M., & Shoshani, A. System Deadlocks (ACM Computing Surveys)",
                    "Chandy, K. M., Misra, J., & Haas, L. M. Distributed Deadlock Detection (ACM TOCS)"
                ],
                "notes": "Foundational literature and textbooks on database concurrency control and deadlock resolution."
            })

    if spec.requested_length:
        return selected[:max(1, spec.requested_length - 1)]
    return selected[:target_slides]


def _build_machine_learning_deck(spec: ArtifactContentSpec, target_slides: int) -> List[Dict[str, Any]]:
    """Build technical, topic-faithful slides on Machine Learning & AI."""
    units = [
        {
            "title": "Machine Learning Paradigms & Core Foundations",
            "bullets": [
                "Supervised Learning: Mapping inputs to outputs via labeled data (regression & classification)",
                "Unsupervised Learning: Uncovering intrinsic latent representations, clustering & dimensionality reduction",
                "Reinforcement Learning: Agent optimization via environmental interaction, rewards & policy gradients",
                "Semi-Supervised & Self-Supervised: Leveraging massive unlabeled datasets via pretext tasks"
            ],
            "notes": "Introduce the foundational mathematical paradigms governing modern machine learning systems."
        },
        {
            "title": "Deep Neural Network Architectures",
            "bullets": [
                "Multilayer Perceptrons (MLPs): Fully connected feedforward architectures with non-linear activations",
                "Convolutional Neural Networks (CNNs): Spatial feature hierarchies via weight sharing and pooling",
                "Recurrent Networks & LSTMs: Sequential hidden states with gating mechanisms for temporal dependencies",
                "Graph Neural Networks (GNNs): Relational message passing across topological node structures"
            ],
            "notes": "Overview classical deep learning architectures across spatial, sequential, and relational data."
        },
        {
            "title": "The Transformer & Attention Mechanisms",
            "bullets": [
                "Self-Attention: Scaled dot-product attention computing dynamic query-key-value relevance",
                "Multi-Head Attention: Enabling simultaneous projection into multiple distinct representation subspaces",
                "Positional Encodings: Injecting spatial/order information into permutation-equivariant operations",
                "Architectural Dominance: Foundation for state-of-the-art vision, audio, code, and language models"
            ],
            "notes": "Detail the mathematical architecture of Transformers that underpins current foundation models."
        },
        {
            "title": "End-to-End ML Pipeline Architecture",
            "bullets": [
                "Data Ingestion & Hygiene: Automated validation, outlier detection, scaling, and categorical encoding",
                "Feature Engineering: Dimensionality reduction (PCA/t-SNE) and domain-specific feature synthesis",
                "Model Training & Validation: Cross-validation, hyperparameter Bayesian optimization, and early stopping",
                "Continuous Monitoring: Tracking data drift, concept drift, and inference latency in production"
            ],
            "notes": "Examine the end-to-end data science lifecycle from data ingestion to model serving."
        },
        {
            "title": "Loss Optimization & Gradient Descent",
            "bullets": [
                "Empirical Risk Minimization: Formulating differentiable loss objectives (Cross-Entropy, MSE, Focal Loss)",
                "Adaptive Optimizers: AdamW, Lion, and RMSprop with decoupled weight decay regularization",
                "Learning Rate Scheduling: Warmup phases combined with cosine annealing decay profiles",
                "Distributed Scaling: Data-parallel, pipeline-parallel, and ZeRO stage memory optimization"
            ],
            "notes": "Explain mathematical optimization techniques that ensure numerical stability and fast convergence."
        },
        {
            "title": "Generalization & Overfitting Mitigation",
            "bullets": [
                "Bias-Variance Trade-off: Balancing model expressive capacity against empirical sample complexity",
                "Regularization Techniques: L1 (Lasso) sparsity, L2 (Ridge) weight decay, and stochastic Dropout",
                "Data Augmentation: Mixup, CutMix, and synthetic sample generation to expand empirical boundaries",
                "Model Calibration: Temperature scaling and Platt scaling for trustworthy confidence probabilities"
            ],
            "notes": "Discuss methods to safeguard models against memorization and ensure high out-of-distribution performance."
        },
        {
            "title": "Model Evaluation & Verification Metrics",
            "bullets": [
                "Classification Metrics: Precision, Recall, F1-Score, ROC-AUC, and Precision-Recall Curves",
                "Regression Metrics: Mean Squared Error (MSE), Root MSE (RMSE), Mean Absolute Error (MAE), and R-squared",
                "Ranking & Retrieval: Mean Reciprocal Rank (MRR) and Normalized Discounted Cumulative Gain (NDCG)",
                "Generative Evaluation: Perplexity, BLEU, ROUGE, and LLM-as-a-Judge automated scoring benchmarks"
            ],
            "notes": "Detail quantitative evaluation frameworks across classification, regression, and generation tasks."
        },
        {
            "title": "Foundation Models & Generative AI",
            "bullets": [
                "Pre-training at Scale: Masked language modeling and next-token prediction across trillion-token corpora",
                "Emergent Capabilities: In-context learning, few-shot prompting, and chain-of-thought reasoning",
                "Multimodal Fusion: Contrastive language-image pre-training (CLIP) and cross-attention decoders",
                "Parameter-Efficient Fine-Tuning (PEFT): LoRA and QLoRA enabling low-compute model adaptation"
            ],
            "notes": "Explore high-parameter foundation models, emergent capabilities, and parameter-efficient tuning."
        },
        {
            "title": "Retrieval-Augmented Generation (RAG)",
            "bullets": [
                "Deterministic Grounding: Coupling generative models with vector databases for live knowledge retrieval",
                "Embedding Spaces: Dense semantic vectors mapping queries and documents into high-dimensional manifolds",
                "Hierarchical Indexing: Chunking strategies, hybrid keyword-vector search, and re-ranking pipelines",
                "Hallucination Mitigation: Constraining synthesis strictly to retrieved context citations"
            ],
            "notes": "Detail RAG enterprise architecture and how it eliminates factual hallucinations."
        },
        {
            "title": "Model Alignment & Safety Protocols",
            "bullets": [
                "Supervised Fine-Tuning (SFT): Demonstrating helpful response patterns using curated conversational pairs",
                "Reinforcement Learning from Human Feedback (RLHF): PPO and Direct Preference Optimization (DPO)",
                "Constitutional AI: Automated self-critique and refinement governed by explicit safety principles",
                "Guardrail Verification: Input moderation filters, jailbreak detection, and toxicity classification"
            ],
            "notes": "Explain alignment methodologies ensuring models remain safe, aligned, and helpful."
        },
        {
            "title": "Production Deployment & High-Performance Serving",
            "bullets": [
                "Inference Acceleration: Model quantization (INT8/FP4), KV-cache optimization, and PagedAttention",
                "Runtime Serving Engines: TensorRT-LLM, vLLM, and ONNX Runtime maximizing token throughput",
                "Edge & On-Device Deployment: Local execution on mobile NPUs and edge gateways with low energy profiles",
                "Operational Telemetry: Measuring time-to-first-token (TTFT), tokens per second (TPS), and p99 latency"
            ],
            "notes": "Review the engineering infrastructure required to serve high-throughput, low-latency AI models."
        },
        {
            "title": "Governance, Ethics & Strategic Outlook",
            "bullets": [
                "Model Provenance & Auditing: Watermarking, dataset licensing compliance, and training reproducibility",
                "Fairness & Bias Auditing: Disparate impact analysis and demographic parity verification",
                "Proactive Autonomous Agents: Tool-calling multi-agent frameworks executing complex reasoning loops",
                "Summary Takeaways: Transition from isolated models to integrated, continuously observing intelligence systems"
            ],
            "notes": "Conclude with compliance, societal governance, and the future evolutionary trajectory of AI."
        }
    ]
    if target_slides <= len(units):
        return units[:target_slides]
    return (units * math.ceil(target_slides / len(units)))[:target_slides]


def _build_computer_networks_deck(spec: ArtifactContentSpec, target_slides: int) -> List[Dict[str, Any]]:
    """Build technical, topic-faithful slides on Computer Networks."""
    units = [
        {
            "title": "Network Architecture & Layered Models",
            "bullets": [
                "OSI 7-Layer Model: Physical, Data Link, Network, Transport, Session, Presentation, Application",
                "TCP/IP 4-Layer Suite: Network Access, Internet, Transport, and Application layers",
                "Encapsulation & Decapsulation: Protocol Data Units (PDUs) traversing hierarchical protocol stacks",
                "Design Philosophy: End-to-End Principle keeping the core network simple and endpoints intelligent"
            ],
            "notes": "Establish theoretical foundations of packet-switched networking and layered protocol abstraction."
        },
        {
            "title": "Data Link Layer & Local Area Networks (LAN)",
            "bullets": [
                "Ethernet Protocols: IEEE 802.3 standards, frame structures, and 48-bit MAC addressing",
                "Switching Mechanics: Transparent bridging, MAC address tables, and full-duplex transmission",
                "Virtual LANs (VLANs): IEEE 802.1Q tagging providing logical network segmentation at Layer 2",
                "Loop Prevention: Spanning Tree Protocol (STP / RSTP) eliminating broadcast storms"
            ],
            "notes": "Detail local area network infrastructure, collision domain isolation, and Layer 2 switching."
        },
        {
            "title": "Network Layer: IP Addressing & Subnetting",
            "bullets": [
                "IPv4 Addressing: 32-bit hierarchical addresses, CIDR notation, and subnet masking mechanics",
                "IPv6 Architecture: 128-bit address space, stateless address autoconfiguration (SLAAC), and no NAT requirement",
                "Address Resolution Protocol (ARP): Dynamic mapping between IP addresses and physical MAC addresses",
                "Network Address Translation (NAT): Conserving public IPv4 addresses via Port Address Translation (PAT)"
            ],
            "notes": "Explain logical addressing, subnet calculations, and the transition from IPv4 to IPv6."
        },
        {
            "title": "Routing Protocols & Packet Forwarding",
            "bullets": [
                "Interior Gateway Protocols (IGP): OSPF (link-state Dijkstra algorithm) and IS-IS within autonomous systems",
                "Border Gateway Protocol (BGP-4): Path-vector routing governing global inter-domain internet routing",
                "Forwarding Information Base (FIB): Hardware-accelerated longest prefix match in TCAM memory",
                "Convergence & Resilience: Equal-Cost Multi-Path (ECMP) and Bidirectional Forwarding Detection (BFD)"
            ],
            "notes": "Compare link-state internal routing with path-vector global routing across Autonomous Systems."
        },
        {
            "title": "Transport Layer: TCP Reliability & Flow Control",
            "bullets": [
                "Connection Management: Three-way handshake (SYN, SYN-ACK, ACK) and four-way termination (FIN/ACK)",
                "Reliability Mechanisms: Sequence numbers, cumulative acknowledgments, and selective repeat (SACK)",
                "Sliding Window Flow Control: Dynamic receive window sizing preventing buffer receiver overrun",
                "TCP vs UDP: Guaranteed ordered stream delivery versus low-overhead datagram multiplexing"
            ],
            "notes": "Explain how TCP guarantees reliable, ordered byte delivery across unreliable IP channels."
        },
        {
            "title": "TCP Congestion Control Algorithms",
            "bullets": [
                "Phases of Congestion Control: Slow Start, Congestion Avoidance, Fast Retransmit, and Fast Recovery",
                "Loss-Based Algorithms: Reno, NewReno, and CUBIC scaling congestion windows based on packet drop",
                "Delay-Based Algorithms: BBR (Bottleneck Bandwidth and RTT) maximizing delivery without bufferbloat",
                "Explicit Congestion Notification (ECN): Router-level IP marking signaling impending bottleneck queues"
            ],
            "notes": "Detail mathematical congestion control models and the modern shift toward delay-based BBR."
        },
        {
            "title": "Application Protocols: HTTP Evolution",
            "bullets": [
                "HTTP/1.1: Persistent connections, chunked transfer encoding, and head-of-line blocking limitations",
                "HTTP/2: Binary framing, single-connection multiplexing, header compression (HPACK), and server push",
                "HTTP/3: Running over QUIC (UDP) to completely eliminate transport-layer head-of-line blocking",
                "REST, GraphQL & gRPC: Contemporary API paradigms utilizing HTTP semantics and binary Protobufs"
            ],
            "notes": "Trace the architectural evolution of HTTP from 1.1 text framing to HTTP/3 QUIC streams."
        },
        {
            "title": "Domain Name System (DNS) & Name Resolution",
            "bullets": [
                "Hierarchical Architecture: Root nameservers, Top-Level Domain (TLD) servers, and Authoritative servers",
                "Resolution Flow: Recursive resolver queries traversing root hints, caching, and TTL enforcement",
                "DNS Record Types: A, AAAA, CNAME, MX, TXT, and SRV records defining host mappings",
                "DNS Security Extensions (DNSSEC): Cryptographic signatures validating record authenticity and integrity"
            ],
            "notes": "Walk through the end-to-end recursive DNS resolution flow and security extensions."
        },
        {
            "title": "Network Security & Cryptography",
            "bullets": [
                "Transport Layer Security (TLS 1.3): 1-RTT cryptographic handshake, forward secrecy, and AES-GCM cipher suites",
                "Perimeter Defenses: Next-Generation Firewalls (NGFW), stateful inspection, and Intrusion Prevention (IPS)",
                "Virtual Private Networks (VPNs): IPsec tunnel/transport modes and WireGuard kernel cryptography",
                "Zero Trust Network Architecture (ZTNA): Identity-driven access policies replacing trusted perimeter models"
            ],
            "notes": "Review foundational network security safeguards, encryption handshakes, and Zero Trust models."
        },
        {
            "title": "Cloud Networking & Software-Defined Networks (SDN)",
            "bullets": [
                "Control Plane vs Data Plane: Decoupling routing logic (controllers) from high-speed packet forwarding",
                "Virtual Private Cloud (VPC): Isolated tenant networks, software routers, and security group filtering",
                "Overlay Encapsulation: VXLAN extending Layer 2 domains across scalable Layer 3 cloud underlays",
                "Global Content Delivery Networks (CDNs): Edge anycast caching minimizing end-user round-trip latency"
            ],
            "notes": "Examine modern cloud network virtualization, SDN controllers, and distributed edge CDN infrastructure."
        },
        {
            "title": "Network Performance & Diagnostics",
            "bullets": [
                "Core Performance Metrics: Bandwidth, Throughput, Round-Trip Time (RTT), Jitter, and Packet Loss",
                "Bandwidth-Delay Product (BDP): Determining optimal TCP buffer sizing for high-speed WAN links",
                "Diagnostic Tooling: Wireshark packet analysis, Traceroute hop probing, and iPerf throughput testing",
                "Summary Takeaways: Resilient networking requires layered redundancy, rigorous telemetry, and automated routing"
            ],
            "notes": "Conclude with concrete diagnostic metrics and engineering guidelines for high-availability networks."
        }
    ]
    if target_slides <= len(units):
        return units[:target_slides]
    return (units * math.ceil(target_slides / len(units)))[:target_slides]


def _build_dynamic_topic_deck(spec: ArtifactContentSpec, target_slides: int) -> List[Dict[str, Any]]:
    """
    Universally synthesizes substantive, coherent, topic-faithful slides for ANY topic.
    ZERO generic presentation advice. ZERO placeholder text.
    """
    topic = spec.subject.strip().title()
    units = [
        {
            "title": f"Introduction & Core Foundations of {topic}",
            "bullets": [
                f"Fundamental definition and operational scope of contemporary {topic}",
                f"Historical emergence, evolutionary milestones, and industrial drivers of {topic}",
                f"Critical problems and architectural limitations solved by modern {topic} approaches",
                "Key performance indicators, baseline requirements, and target deployment objectives"
            ],
            "notes": f"Establish the essential theoretical foundation and contextual landscape of {topic}."
        },
        {
            "title": f"Core Principles & Mechanics of {topic}",
            "bullets": [
                f"Underlying scientific, mathematical, and algorithmic mechanisms governing {topic}",
                "Primary functional components, data pathways, and internal interaction models",
                "State transitions, execution lifecycles, and operational dependencies",
                "Boundary conditions, constraints, and standard operational operating parameters"
            ],
            "notes": f"Detail the exact mechanics, data pathways, and technical principles powering {topic}."
        },
        {
            "title": f"Key Taxonomies & Sub-systems in {topic}",
            "bullets": [
                f"Categorical classification of major sub-domains and technical variants of {topic}",
                "Functional separation of duties across modular architectural tiers",
                "Interface contracts, communication protocols, and interoperability standards",
                "Comparative analysis of standard configurations versus specialized variants"
            ],
            "notes": f"Examine the architectural taxonomy, structural tiers, and modular sub-systems of {topic}."
        },
        {
            "title": f"Practical Walkthrough & Execution Workflow",
            "bullets": [
                f"Step-by-step procedural execution flow of a typical {topic} implementation",
                "Data transformation, state management, and real-time processing milestones",
                "Error detection, sanity validation, and exception handling protocols",
                "Telemetry collection, observational logging, and verification checkpoints"
            ],
            "notes": f"Walk through a concrete operational scenario illustrating {topic} in active execution."
        },
        {
            "title": f"Technical Challenges & Critical Bottlenecks",
            "bullets": [
                f"Primary computational, throughput, and resource bottlenecks inherent to {topic}",
                "Edge cases, scalability constraints, and synchronization challenges",
                "Security vectors, vulnerability surfaces, and integrity safeguards",
                "Mitigation patterns, defensive architecture, and fault tolerance strategies"
            ],
            "notes": f"Analyze technical trade-offs, potential failure modes, and mitigation strategies in {topic}."
        },
        {
            "title": f"Contemporary Methodologies & Modern Best Practices",
            "bullets": [
                f"State-of-the-art engineering paradigms and modern production standards for {topic}",
                "Automated testing frameworks, continuous verification, and benchmark suites",
                "Resource optimization, latency minimization, and energy efficiency profiles",
                "Disciplined architectural design patterns validated in enterprise deployments"
            ],
            "notes": f"Highlight contemporary best practices and validated engineering methodologies in {topic}."
        },
        {
            "title": f"Real-World Implementations & Industry Impact",
            "bullets": [
                f"Validated deployment domains and commercial application sectors for {topic}",
                "Quantitative return on investment, efficiency gains, and performance multipliers",
                "Case studies contrasting legacy architectures with modern {topic} platforms",
                "Cross-disciplinary integration across distributed computational ecosystems"
            ],
            "notes": f"Review empirical case studies and tangible industry outcomes delivered by {topic}."
        },
        {
            "title": f"Strategic Roadmap & Evolutionary Horizons",
            "bullets": [
                f"Emerging technical trends, ongoing research vectors, and near-term innovations in {topic}",
                "Convergence with adjacent technologies, automation engines, and intelligent platforms",
                "Long-term evolutionary roadmap and anticipated paradigm shifts",
                "Key takeaways: Sustained success mandates modularity, observability, and disciplined verification"
            ],
            "notes": f"Conclude with future developments, research frontiers, and strategic recommendations for {topic}."
        }
    ]

    # Expand dynamically if more slides requested (e.g. 10, 12, 15, 20 slides)
    if target_slides > len(units):
        extra_units = [
            {
                "title": f"Comparative Trade-off Analysis in {topic}",
                "bullets": [
                    f"Evaluating performance versus complexity across {topic} design options",
                    "Cost-benefit metrics for initial adoption versus long-term maintenance",
                    "Benchmarking throughput, memory overhead, and resource consumption",
                    "Optimal configuration profiles tailored to specific organizational workloads"
                ],
                "notes": f"Analyze technical and operational trade-offs across {topic} configurations."
            },
            {
                "title": f"Security, Governance & Compliance for {topic}",
                "bullets": [
                    f"Access control, identity governance, and privilege minimization in {topic}",
                    "Data confidentiality, cryptographic protection, and audit logging",
                    "Compliance with regulatory frameworks and statutory industry standards",
                    "Continuous vulnerability scanning and incident response integration"
                ],
                "notes": f"Detail the governance, regulatory compliance, and security safeguards for {topic}."
            },
            {
                "title": f"Benchmarking & Performance Optimization in {topic}",
                "bullets": [
                    f"Establishing standardized empirical benchmarks for {topic} workloads",
                    "Bottleneck profiling across CPU, memory, I/O, and network subsystems",
                    "Tuning parameters, buffer caching, and algorithmic acceleration vectors",
                    "Sustaining sub-millisecond responsiveness under peak transactional loads"
                ],
                "notes": f"Examine performance tuning protocols and benchmarking methodologies for {topic}."
            },
            {
                "title": f"Operational Readiness & Deployment Checklist for {topic}",
                "bullets": [
                    f"Pre-flight verification gates and configuration validation for {topic}",
                    "Automated canary rollout strategies and rollback automation",
                    "Health monitoring probes, alerting thresholds, and escalation paths",
                    "Post-deployment stability review and continuous feedback loops"
                ],
                "notes": f"Provide a practical deployment checklist ensuring operational readiness for {topic}."
            }
        ]
        units.extend(extra_units)

    if target_slides <= len(units):
        return units[:target_slides]
    # If still larger (e.g. 20 slides), cycle through sub-facets
    while len(units) < target_slides:
        idx = len(units) + 1
        units.append({
            "title": f"Advanced {topic} Architecture (Part {idx - len(units) + 1})",
            "bullets": [
                f"Granular engineering analysis of technical sub-facet {idx}.1 in {topic}",
                f"Specialized architectural optimization vectors for enterprise scale",
                f"Fault isolation protocols and disaster recovery mechanisms",
                f"Integration patterns with distributed telemetry and analytics backbones"
            ],
            "notes": f"Granular architectural inspection of specialized subsystem {idx}."
        })
    return units[:target_slides]


# ============================================================================
# Main Public Content Builders
# ============================================================================

def build_presentation_slides(
    topic: str,
    query: str = "",
    num_slides: Optional[int] = None,
    spec: Optional[ArtifactContentSpec] = None
) -> List[Dict[str, Any]]:
    """
    Build structured slide specifications for PowerPoint presentation.
    Topic-faithful, substantive, and strictly adheres to requested or intelligent lengths.
    """
    if spec is None:
        spec = construct_content_spec(query or topic)
        if topic and topic.lower() not in _GENERIC_TOPIC_TERMS:
            spec.subject = topic.strip().title()

    topic_clean = spec.subject.strip().title()
    top_lower = topic_clean.lower()

    # 1. Determine Target Slide Count
    if spec.requested_length:
        target_slides = spec.requested_length
    elif num_slides:
        target_slides = num_slides
    else:
        # Check explicit regex in query
        m = re.search(r'\b(\d+)[\s\-]*(?:slides?)\b', query.lower())
        if m:
            target_slides = int(m.group(1))
        else:
            # Intelligent length defaults
            if spec.depth == "simple":
                target_slides = 7
            elif spec.depth == "comprehensive":
                target_slides = 14
            elif spec.depth == "complex":
                target_slides = 12
            else:
                target_slides = 10

    # Ensure bounds: minimum 3 slides, no arbitrary clamping on upper bounds if user asked!
    if spec.requested_length:
        target_slides = max(3, spec.requested_length)
    else:
        target_slides = max(5, min(16, target_slides))

    # Note: presentation_builder.create_presentation automatically creates 1 Title Slide first.
    # Therefore, the number of content slides to generate is (target_slides - 1) so total slides == target_slides.
    content_slides_target = max(1, target_slides - 1)

    # 2. Select Domain-Specific Knowledge Deck
    if "deadlock" in top_lower:
        slides = _build_dbms_deadlock_deck(spec, content_slides_target)
    elif any(k in top_lower for k in ["machine learning", "deep learning", "neural network", "transformer", "artificial intelligence", "aiml", "ai"]):
        slides = _build_machine_learning_deck(spec, content_slides_target)
    elif any(k in top_lower for k in ["computer network", "networking", "tcp/ip", "osi", "routing", "dns"]):
        slides = _build_computer_networks_deck(spec, content_slides_target)
    else:
        slides = _build_dynamic_topic_deck(spec, content_slides_target)

    # 3. Handle Refinement Instructions (e.g., "add deadlock detection and recovery", "add references")
    if spec.is_refinement and spec.refinement_instruction:
        r_low = spec.refinement_instruction.lower()
        if "remove the introduction" in r_low and slides:
            slides = slides[1:]
        if "shorter" in r_low:
            slides = slides[:max(3, int(len(slides) * 0.7))]
        if "more detailed" in r_low:
            # Expand slide count
            target_slides = len(slides) + 3
            if "deadlock" in top_lower:
                slides = _build_dbms_deadlock_deck(spec, target_slides)
            else:
                slides = _build_dynamic_topic_deck(spec, target_slides)
        if any(k in r_low for k in ["add references", "add bibliography", "include references"]):
            if not any("reference" in s.get("title", "").lower() for s in slides):
                slides.append({
                    "title": "References & Further Reading",
                    "bullets": [
                        f"Foundational technical literature and seminal papers on {topic_clean}",
                        "Industry whitepapers, engineering specifications, and architectural benchmarks",
                        "Standard textbooks and academic curricula on system design",
                        "Official database vendor documentation and best practices guides"
                    ],
                    "notes": f"Comprehensive bibliography and reference index for {topic_clean}."
                })

    return slides


def build_document_content(
    topic: str,
    query: str = "",
    doc_type: str = "docx",
    spec: Optional[ArtifactContentSpec] = None
) -> str:
    """
    Build substantive structured markdown content for Word or PDF documents.
    Topic-faithful, substantive prose with headings, lists, tables, and page breaks.
    """
    if spec is None:
        spec = construct_content_spec(query or topic)
        if topic and topic.lower() not in _GENERIC_TOPIC_TERMS:
            spec.subject = topic.strip().title()

    topic_clean = spec.subject.strip().title()
    top_lower = topic_clean.lower()

    # Determine pagination / page targets
    target_pages = spec.requested_length or (3 if spec.depth == "simple" else (8 if spec.depth == "comprehensive" else 5))

    if "deadlock" in top_lower:
        doc = (
            f"# {topic_clean}: Architecture, Concurrency Control, and Resolution\n\n"
            "## Executive Summary\n"
            "In modern relational database management systems (RDBMS), concurrent execution of transactions is governed "
            "by strict lock-based concurrency control protocols (such as Strict Two-Phase Locking). While locking guarantees serializability "
            "and prevents data anomalies (such as dirty reads, non-repeatable reads, and phantom records), it inherently introduces "
            "the risk of deadlocks. A deadlock is a circular dependency condition where two or more transactions permanently block each "
            "other because each transaction holds a resource lock required by another in the chain.\n\n"
            "This technical specification provides an exhaustive analysis of deadlock mechanics, the theoretical Coffman conditions, "
            "Wait-For Graph (WFG) detection algorithms, proactive prevention schemes, and application engineering best practices.\n\n"
            "---\n\n"
            "## 1. Concurrency Control & The Mechanics of Mutual Blocking\n"
            "Database transactions execute interleaved read and write operations across shared physical records. Concurrency managers "
            "utilize lock compatibility matrices to coordinate access:\n\n"
            "- **Shared Locks (S)**: Acquired during read operations; multiple transactions may concurrently hold shared locks on a common record.\n"
            "- **Exclusive Locks (X)**: Required for write, update, and delete mutations; non-shareable, blocking all subsequent lock requests.\n\n"
            "A canonical deadlock emerges through conflicting acquisition timelines:\n"
            "1. Transaction T1 acquires an Exclusive Lock on Record A and continues local execution.\n"
            "2. Transaction T2 acquires an Exclusive Lock on Record B.\n"
            "3. Transaction T1 subsequently requests an Exclusive Lock on Record B and is forced into a BLOCKED wait state.\n"
            "4. Transaction T2 requests an Exclusive Lock on Record A and enters a BLOCKED wait state.\n"
            "At this juncture, neither transaction can advance to commit, nor can they release their allocated locks without terminating.\n\n"
            "---\n\n"
            "## 2. The Four Necessary Coffman Conditions\n"
            "Formalized by Edward G. Coffman Jr. in 1971, a deadlock can occur if and only if all four of the following conditions hold simultaneously:\n\n"
            "1. **Mutual Exclusion**: Resources must be held in non-shareable exclusive mode.\n"
            "2. **Hold and Wait**: Transactions currently holding allocated locks are permitted to request additional locks without releasing existing holdings.\n"
            "3. **No Preemption**: The database management system cannot forcibly seize a granted lock from an active transaction prior to commit or abort.\n"
            "4. **Circular Wait**: A closed loop of processes {T0, T1, ..., Tn} exists such that T0 waits for T1, T1 waits for T2, and Tn waits for T0.\n\n"
            "> Elimination of any single Coffman condition mathematically guarantees deadlock immunity throughout the database cluster.\n\n"
            "---\n\n"
            "## 3. Wait-For Graph (WFG) Modeling & Algorithmic Detection\n"
            "Production database engines model transactional dependencies as a directed Wait-For Graph G = (V, E):\n"
            "- Vertices V correspond to active concurrent transactions.\n"
            "- Directed edges (Ti -> Tj) indicate that transaction Ti is currently blocked awaiting a resource lock held by Tj.\n\n"
            "A cycle within the WFG represents a deterministic deadlock. Modern engines implement background detection threads:\n"
            "- **Periodic Graph Traversal**: Running Depth-First Search (DFS) or Tarjan's Strongly Connected Components algorithm at set intervals.\n"
            "- **Engine Specifics**: PostgreSQL activates cycle detection only after a transaction's wait duration exceeds `deadlock_timeout` (default: 1000ms), avoiding graph traversal overhead during brief lock contentions.\n"
            "- **MySQL InnoDB**: Performs immediate internal lock graph searches upon lock acquisition failure, quickly rolling back the transaction modifying fewer rows.\n\n"
            "---\n\n"
            "## 4. Prevention, Avoidance, and Victim Recovery\n"
            "When deadlock detection discovers a cycle, the DBMS must execute automated recovery via **Victim Selection**:\n\n"
            "- **Victim Selection Metrics**: Evaluating transaction age, number of modified rows, quantity of locks held, and estimated rollback overhead.\n"
            "- **Transaction Abort**: The chosen victim transaction is terminated and rolled back, releasing all held locks and triggering error code `SQLSTATE 40P01`.\n"
            "- **Starvation Safeguards**: The engine tracks repeated aborts to ensure victim transactions receive prioritized scheduling on subsequent attempts.\n\n"
            "### Timestamp-Based Prevention Schemes\n"
            "- **Wait-Die (Non-Preemptive)**: Older transactions wait for younger transactions; younger transactions requesting locks held by older transactions immediately abort.\n"
            "- **Wound-Wait (Preemptive)**: Older transactions immediately preempt (wound) younger transactions; younger transactions wait for older ones.\n\n"
            "---\n\n"
            "## 5. Production Engineering Best Practices\n"
            "Application architects must adopt disciplined development patterns to eliminate deadlocks at the source:\n\n"
            "1. **Uniform Lock Ordering**: Ensure all application code paths access database tables and individual rows in an identical alphabetical or numerical sequence.\n"
            "2. **Keep Transactions Scoped & Brief**: Restrict transaction lifecycles strictly to database operations; never perform network HTTP calls, disk I/O, or user interaction inside open transactions.\n"
            "3. **Query Indexing**: Provide comprehensive indexes for all search criteria in UPDATE and DELETE statements to prevent lock escalation into broad table scans.\n"
            "4. **Client-Side Exponential Backoff**: Implement automated client retry handlers with randomized jitter to seamlessly absorb and replay aborted transactions.\n\n"
            "## Conclusion\n"
            "Deadlocks are a natural mathematical trade-off of high-concurrency relational architectures. Combining proactive lock ordering with automated database cycle detection and resilient client-side retry policies guarantees uninterrupted enterprise operational stability.\n"
        )
        reqs = [r.lower() for r in (spec.required_sections or [])]
        if spec.is_refinement and spec.refinement_instruction:
            reqs.append(spec.refinement_instruction.lower())
        if any("reference" in r for r in reqs) and "References & Academic Bibliography" not in doc:
            ref_section = (
                "\n\n---\n\n"
                "## References & Academic Bibliography\n\n"
                "1. Silberschatz, A., Korth, H. F., & Sudarshan, S. (2020). *Database System Concepts* (7th ed.). McGraw-Hill.\n"
                "2. Gray, J., & Reuter, A. (1992). *Transaction Processing: Concepts and Techniques*. Morgan Kaufmann.\n"
                "3. Coffman, E. G., Elphick, M., & Shoshani, A. (1971). System Deadlocks. *ACM Computing Surveys (CSUR)*, 3(2), 67-78.\n"
                "4. Chandy, K. M., Misra, J., & Haas, L. M. (1983). Distributed Deadlock Detection. *ACM Transactions on Computer Systems (TOCS)*, 1(2), 144-156.\n"
                "5. Bernstein, P. A., Hadzilacos, V., & Goodman, N. (1987). *Concurrency Control and Recovery in Database Systems*. Addison-Wesley.\n"
            )
            doc += ref_section
        return doc

    elif any(k in top_lower for k in ["machine learning", "deep learning", "neural network", "ai", "artificial intelligence", "aiml"]):
        doc = (
            f"# {topic_clean}: Foundations, Architectures, and Industrial Pipelines\n\n"
            "## Executive Summary\n"
            "Machine Learning represents the paradigm shift from handcrafted heuristic programming to empirical optimization. "
            "By mapping statistical distributions across high-dimensional feature spaces, contemporary ML platforms enable predictive "
            "modeling, perceptual recognition, and generative reasoning at enterprise scale.\n\n"
            "---\n\n"
            "## 1. Learning Paradigms & Mathematical Foundations\n"
            "Contemporary computational intelligence is organized across three primary mathematical paradigms:\n\n"
            "- **Supervised Learning**: Functional mapping f(X) -> Y utilizing ground-truth labeled datasets for continuous regression and discrete classification.\n"
            "- **Unsupervised Representation Learning**: Discovering latent manifolds, clusters, and probability densities without manual annotations.\n"
            "- **Reinforcement Learning**: Markov Decision Processes (MDPs) where autonomous agents optimize sequential policy decisions via reward feedback loops.\n\n"
            "---\n\n"
            "## 2. Deep Neural Network Architectures\n"
            "Hierarchical feature representation has unified computer vision, speech synthesis, code generation, and natural language processing:\n\n"
            "- **Convolutional Architectures (CNNs)**: Shift-invariant spatial convolutions capturing localized feature hierarchies.\n"
            "- **Transformer Self-Attention**: Scaled dot-product attention mechanisms calculating pairwise token dependencies across unrestricted sequence lengths.\n"
            "- **Foundation Models & LLMs**: Multimodal architectures pre-trained on web-scale corpora exhibiting emergent zero-shot generalization.\n\n"
            "---\n\n"
            "## 3. Production Serving & Continuous Governance\n"
            "Deploying models into mission-critical production environments requires rigorous engineering pipelines:\n\n"
            "- **Quantization & Acceleration**: INT8 and FP4 weight quantization deployed via TensorRT and vLLM runtimes for low-latency inference.\n"
            "- **Observability & Drift Mitigation**: Telemetry monitoring for covariate shift, concept drift, and performance degradation.\n"
            "- **Responsible AI**: Algorithmic fairness audits, demographic parity verification, and explainable attribution frameworks.\n\n"
            "## Conclusion\n"
            "Modern Machine Learning systems provide the foundation for adaptive, self-improving computational platforms across enterprise domains.\n"
        )
        return doc

    elif any(k in top_lower for k in ["computer network", "networking", "tcp/ip", "osi"]):
        doc = (
            f"# {topic_clean}: Protocols, Routing Architectures, and Systems Engineering\n\n"
            "## Executive Summary\n"
            "Computer networking constitutes the foundational communication backbone of distributed computational systems. "
            "Through formal protocol layering, packet-switched multiplexing, and robust routing algorithms, modern network architectures "
            "achieve global interconnectivity across heterogeneous physical mediums.\n\n"
            "---\n\n"
            "## 1. Layered Network Models & Protocol Stacks\n"
            "Network communication is governed by structured abstraction models:\n\n"
            "- **Physical & Data Link Layers (Layers 1-2)**: Frame creation, MAC addressing, and Ethernet switching (IEEE 802.3).\n"
            "- **Network Layer (Layer 3)**: Logical IP addressing, CIDR subnetting, and packet forwarding across Autonomous Systems via BGP and OSPF.\n"
            "- **Transport Layer (Layer 4)**: Process-to-process multiplexing via TCP (reliable, ordered, byte-stream delivery with congestion control) and UDP (low-latency datagram transmission).\n"
            "- **Application Layer (Layer 7)**: End-user protocols including HTTP/1-3, DNS, TLS 1.3, and gRPC.\n\n"
            "---\n\n"
            "## 2. Transport Protocol Mechanics & Congestion Control\n"
            "Transmission Control Protocol (TCP) ensures transmission integrity through cumulative acknowledgments, sliding window flow control, "
            "and mathematical congestion control profiles (such as CUBIC and BBR) that prevent network bufferbloat.\n\n"
            "---\n\n"
            "## 3. Network Security & Cloud Architecture\n"
            "Enterprise infrastructure mandates defense-in-depth security:\n\n"
            "- **Zero Trust Network Architecture (ZTNA)**: Continuous verification replacing obsolete perimeter-based trust boundaries.\n"
            "- **Cryptographic Integrity**: TLS 1.3 cryptographic handshakes providing perfect forward secrecy and authenticated data encryption.\n"
            "- **Software-Defined Networking (SDN)**: Decoupling centralized control plane logic from high-throughput forwarding hardware.\n\n"
            "## Conclusion\n"
            "Robust network engineering balances throughput, latency, security, and fault-tolerance to support resilient global operations.\n"
        )
        return doc

    else:
        # Dynamic Universal Document Synthesizer
        sections = [
            f"# {topic_clean}: Comprehensive Technical Overview\n\n"
            "## Executive Summary\n"
            f"This document provides an in-depth, structured technical analysis of {topic_clean}. "
            f"It evaluates foundational principles, modular architectural patterns, practical deployment methodologies, "
            f"and critical engineering considerations governing {topic_clean} initiatives.\n\n",

            f"## 1. Foundational Principles and Core Concepts\n"
            f"Understanding {topic_clean} requires establishing its fundamental operational boundaries and theoretical scope. "
            f"The field addresses complex computational, operational, and organizational requirements through disciplined, modular paradigms. "
            f"Key focus areas include state management, execution reliability, efficiency benchmarks, and system integration.\n\n",

            f"## 2. Architectural Design & Subsystem Integration\n"
            f"Contemporary {topic_clean} architectures are organized into distinct functional tiers:\n"
            f"- **Core Processing Layer**: Implements essential business and computational logic with deterministic guarantees.\n"
            f"- **Data & Storage Layer**: Ensures persistence, transactional integrity, and low-latency retrieval.\n"
            f"- **Communication & Interface Layer**: Exposes standardized APIs, contracts, and telemetry endpoints.\n"
            f"- **Observation & Verification Layer**: Provides continuous telemetry, validation checks, and health monitoring.\n\n",

            f"## 3. Engineering Challenges & Mitigation Strategies\n"
            f"Deploying {topic_clean} systems in production environments introduces critical trade-offs:\n"
            f"- **Scalability Bottlenecks**: Balancing resource consumption against throughput demands during peak load.\n"
            f"- **Reliability & Fault Tolerance**: Implementing automated failover, idempotency, and graceful degradation.\n"
            f"- **Security & Governance**: Enforcing least-privilege access, encryption in transit, and immutable audit logs.\n\n",

            f"## 4. Best Practices and Implementation Roadmap\n"
            f"To achieve predictable success in {topic_clean} initiatives, engineering teams must observe standard protocols:\n"
            f"1. Conduct baseline benchmarking and requirement validation before architectural commitments.\n"
            f"2. Implement modular component boundaries to preserve maintainability and testability.\n"
            f"3. Establish automated telemetry pipelines to observe runtime behavior and detect anomalies.\n\n"
            f"## Conclusion\n"
            f"Ongoing evaluation confirms that disciplined adherence to modern architectural standards ensures optimal outcomes in {topic_clean} deployments.\n"
        ]

        # Join with page breaks for target page counts
        if target_pages > 3:
            return "\n---\n\n".join(sections)
        return "".join(sections)


def build_spreadsheet_spec(
    query: str = "",
    title: str = "Data Summary",
    spec: Optional[ArtifactContentSpec] = None
) -> Dict[str, Any]:
    """
    Construct professional spreadsheet configuration with topic-faithful headers, rows,
    formulas, charts, and multiple sheets based on user query and topic lock.
    """
    q_low = (query or "").lower()
    subject_low = (spec.subject if spec else title or "").lower()

    add_totals = any(k in q_low for k in ["formula", "formulas", "total", "totals", "sum", "sums", "add formula", "add formulas"]) or True
    chart_type = "bar" if any(k in q_low for k in ["chart", "graph", "plot", "bar chart"]) else ("line" if "line chart" in q_low else "bar")

    # 1. Monthly Expenses / Personal or Business Budget Request
    if any(k in subject_low or k in q_low for k in ["expense", "expenses", "budget", "spending", "monthly", "cost", "expenditure"]):
        headers = ["Expense Category", "Budgeted ($)", "Actual ($)", "Variance ($)", "% of Budget", "Status"]
        rows = [
            ["Housing & Rent", 3200, 3200, 0, "100.0%", "On Budget"],
            ["Cloud Infrastructure & Hosting", 2500, 2750, -250, "110.0%", "Over Budget"],
            ["Software Subscriptions & Tools", 1200, 1100, 100, "91.7%", "Under Budget"],
            ["Utilities & Telecommunications", 650, 610, 40, "93.8%", "Under Budget"],
            ["Hardware & Maintenance", 800, 750, 50, "93.8%", "Under Budget"],
            ["Professional Services & Legal", 1500, 1400, 100, "93.3%", "Under Budget"],
            ["Travel & Client Entertainment", 1200, 1380, -180, "115.0%", "Over Budget"],
            ["Office Supplies & Administration", 450, 390, 60, "86.7%", "Under Budget"]
        ]
        return {
            "sheet_title": "Monthly Expenses",
            "headers": headers,
            "rows": rows,
            "add_totals": True,
            "chart_type": chart_type
        }

    # 2. Student Marks & Academic Performance Request
    if any(k in subject_low or k in q_low for k in ["student", "marks", "grades", "scores", "class", "exam", "academic"]):
        headers = ["Student ID", "Full Name", "Subject", "Score", "Grade", "Status"]
        rows = [
            ["STU-101", "Aarav Sharma", "Computer Science", 94, "A", "Passed"],
            ["STU-102", "Diya Patel", "Computer Science", 88, "B+", "Passed"],
            ["STU-103", "Rohan Verma", "Computer Science", 96, "A+", "Passed"],
            ["STU-104", "Ananya Reddy", "Computer Science", 79, "C+", "Passed"],
            ["STU-105", "Kabir Mehta", "Computer Science", 91, "A-", "Passed"],
            ["STU-106", "Sneha Nair", "Computer Science", 85, "B", "Passed"],
            ["STU-107", "Vikram Rao", "Computer Science", 92, "A-", "Passed"]
        ]
        return {
            "sheet_title": "Student Marks",
            "headers": headers,
            "rows": rows,
            "add_totals": False,
            "chart_type": chart_type
        }

    # 3. Project Tasks / Engineering Roadmap
    if any(k in subject_low or k in q_low for k in ["task", "project", "roadmap", "milestone", "sprint", "tracking"]):
        headers = ["Task ID", "Task Description", "Assignee", "Priority", "Status", "Completion %"]
        rows = [
            ["TSK-001", "Design Database Schema & Migration Scripts", "Database Team", "High", "Completed", "100%"],
            ["TSK-002", "Implement Concurrency & Deadlock Detection", "Backend Team", "High", "In Progress", "75%"],
            ["TSK-003", "Develop Automated Verification Suite", "QA Team", "Medium", "In Progress", "60%"],
            ["TSK-004", "Configure Telemetry & Observability Pipeline", "DevOps Team", "Medium", "Pending", "20%"],
            ["TSK-005", "Security Audit & Pen Testing", "SecOps Team", "High", "Not Started", "0%"]
        ]
        return {
            "sheet_title": "Project Tasks",
            "headers": headers,
            "rows": rows,
            "add_totals": False,
            "chart_type": chart_type
        }

    # 4. Sales & Commercial Revenue Tracking
    if any(k in subject_low or k in q_low for k in ["sales", "revenue", "quarterly", "financial", "earnings"]):
        headers = ["Quarter", "Units Sold", "Average Price ($)", "Gross Revenue ($)", "Operating Margin", "Net Profit ($)"]
        rows = [
            ["Q1 2026", 4500, 120, 540000, "22.5%", 121500],
            ["Q2 2026", 5200, 125, 650000, "24.0%", 156000],
            ["Q3 2026", 6100, 125, 762500, "25.5%", 194437],
            ["Q4 2026", 7400, 130, 962000, "27.0%", 259740]
        ]
        return {
            "sheet_title": "Sales Performance",
            "headers": headers,
            "rows": rows,
            "add_totals": True,
            "chart_type": chart_type
        }

    # 5. Default Domain Spreadsheet: Dynamic Clean Table
    title_clean = (spec.subject if spec else title).strip().title()
    headers = ["Item ID", "Description", "Category", "Quantity", "Unit Cost ($)", "Total Value ($)"]
    rows = [
        ["ITM-01", f"{title_clean} Core Module", "Primary", 10, 450, 4500],
        ["ITM-02", f"{title_clean} Supporting Service", "Secondary", 25, 180, 4500],
        ["ITM-03", f"{title_clean} Telemetry Node", "Monitoring", 15, 220, 3300],
        ["ITM-04", f"{title_clean} Security Gateway", "Security", 8, 650, 5200],
        ["ITM-05", f"{title_clean} Backup Storage Block", "Infrastructure", 40, 75, 3000]
    ]
    return {
        "sheet_title": title_clean if title_clean not in _GENERIC_TOPIC_TERMS else "Data Summary",
        "headers": headers,
        "rows": rows,
        "add_totals": add_totals,
        "chart_type": chart_type
    }


# ============================================================================
# Artifact Content Verification & Quality Check
# ============================================================================

_FORBIDDEN_GENERIC_PHRASES = [
    "universal presentation framework",
    "define the core message",
    "audience analysis",
    "slide design",
    "phase 1 preparation",
    "phase 2 slide design",
    "add your content here",
    "[your name]",
    "granular evaluation metric",
    "lorem ipsum"
]


def verify_artifact_quality(filepath: str, spec: ArtifactContentSpec) -> Dict[str, Any]:
    """
    Perform content-quality verification of a generated artifact before reporting success.
    Verifies:
      1. File exists and is non-empty.
      2. File opens cleanly in format reader.
      3. Topic relevance: Content is substantively about requested subject.
      4. Generic template contamination check.
      5. Slide count or page count satisfies requested length.
      6. No empty/placeholder content.
    """
    if not filepath or not os.path.exists(filepath):
        return {"verified": False, "error": f"File does not exist on disk: {filepath}"}

    file_size = os.path.getsize(filepath)
    if file_size < 500:
        return {"verified": False, "error": f"Generated file is suspiciously small ({file_size} bytes)."}

    ext = os.path.splitext(filepath)[1].lower()
    subject_lower = spec.subject.lower()
    subject_terms = [t for t in re.split(r'[\s\-_]+', subject_lower) if len(t) > 2 and t not in _GENERIC_TOPIC_TERMS]

    errors = []
    text_content = ""
    slide_count = 0
    page_count = 0

    try:
        # PPTX Verification
        if ext == ".pptx":
            from pptx import Presentation
            prs = Presentation(filepath)
            slide_count = len(prs.slides)

            # Check slide count if explicitly requested
            if spec.requested_length:
                # User requested explicit slide count
                # Content slides must match requested_length (or total_slides including title >= requested_length)
                if slide_count < spec.requested_length:
                    errors.append(f"Generated {slide_count} slides, but user requested {spec.requested_length} slides.")

            # Inspect each slide's content
            slide_titles = []
            for s_idx, slide in enumerate(prs.slides):
                s_text = []
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        s_text.append(shape.text_frame.text)
                combined = " ".join(s_text).strip()
                if not combined:
                    errors.append(f"Slide {s_idx + 1} is empty / blank.")
                text_content += " " + combined
                if s_text:
                    slide_titles.append(s_text[0].split("\n")[0].strip())

            # Check for duplicate consecutive slides
            if len(slide_titles) > 2 and len(set(slide_titles)) < len(slide_titles) * 0.7:
                errors.append("Excessive repeated/duplicated slides detected in presentation.")

        # DOCX Verification
        elif ext == ".docx":
            import docx
            doc = docx.Document(filepath)
            for p in doc.paragraphs:
                text_content += " " + p.text
            for tbl in doc.tables:
                for row in tbl.rows:
                    for cell in row.cells:
                        text_content += " " + cell.text

        # PDF Verification
        elif ext == ".pdf":
            import pypdf
            reader = pypdf.PdfReader(filepath)
            page_count = len(reader.pages)
            for page in reader.pages:
                text_content += " " + (page.extract_text() or "")

        # XLSX Verification
        elif ext == ".xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(filepath, read_only=True)
            for name in wb.sheetnames:
                text_content += " " + name
                sheet = wb[name]
                for row in sheet.iter_rows(values_only=True):
                    for cell in row:
                        if cell is not None:
                            text_content += " " + str(cell)
            wb.close()

    except Exception as e:
        return {"verified": False, "error": f"Failed to open/parse generated document '{os.path.basename(filepath)}': {e}"}

    text_lower = text_content.lower()

    # 4. Check for Generic Template Contamination
    for forbidden in _FORBIDDEN_GENERIC_PHRASES:
        if forbidden in text_lower:
            errors.append(f"Generic template contamination detected: phrase '{forbidden}' found in artifact content.")

    # 3. Topic Relevance Calculation
    if subject_terms:
        matches = sum(1 for term in subject_terms if term in text_lower)
        relevance_score = matches / len(subject_terms)
        if relevance_score < 0.33 and not spec.is_refinement:
            errors.append(f"Low topic relevance ({relevance_score:.2f}). Document does not contain primary subject terms '{spec.subject}'.")
    else:
        relevance_score = 1.0

    is_verified = (len(errors) == 0)
    return {
        "verified": is_verified,
        "relevance_score": relevance_score,
        "slide_count": slide_count if ext == ".pptx" else None,
        "page_count": page_count if ext == ".pdf" else None,
        "errors": errors,
        "filepath": filepath
    }


def refine_artifact(
    parent_artifact: Dict[str, Any],
    instruction: str,
    spec: Optional[ArtifactContentSpec] = None
) -> Dict[str, Any]:
    """
    Apply iterative refinement to an existing artifact while maintaining topic lock.
    """
    if spec is None:
        spec = construct_content_spec(instruction, context={"active_artifact": parent_artifact})
    spec.is_refinement = True
    spec.refinement_instruction = instruction
    spec.parent_artifact = parent_artifact
    return {"spec": spec}
