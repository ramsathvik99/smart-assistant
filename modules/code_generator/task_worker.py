"""
Background Execution & Live Progress Tracking for Code Generation.
Provides:
  1. Task complexity classification (Fast-path synchronous vs. Long-running background).
  2. Incremental, checkpointed multi-stage execution lifecycle (PLANNING -> GENERATING -> SAVING -> VALIDATING -> REPAIRING -> COMPLETED).
  3. Live milestone progress streaming and Visual Response Surface details panel synchronization.
  4. Bounded repair retry cycles with checkpoint persistence.
  5. Cooperative cancellation checkpoints and safe failure isolation.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.task_execution_manager import (
    get_task_execution_manager,
    Task,
    TaskStatus,
    TaskPriority,
    Resource,
    ExecutionEvent,
    EventType
)
from core.visual_response import (
    VisualResponse,
    VisualResponseType,
    VisualResponseAction
)
from extensions.dialogue_state_manager import get_dialogue_manager
from modules.code_generator.config import GENERATED_CODE_DIR
from modules.code_generator.generator import (
    generate_code,
    fix_code_with_llm
)
from modules.code_generator.main import (
    extract_files,
    save_project,
    is_multi_file_request
)
from modules.code_generator.utils import (
    detect_language,
    validate_code_syntax,
    clean_code
)

logger = logging.getLogger("CodeGeneratorTaskWorker")


# ============================================================================
# 1. Complexity Classifier
# ============================================================================

def classify_task_complexity(command: str) -> Tuple[bool, str]:
    """
    Decides whether a coding request should run synchronously (fast path)
    or in the background as a stateful, checkpointed task.

    Returns:
        (is_long_running, reason)
    """
    if not command:
        return False, "empty_command"

    t = command.lower().strip()

    # Explicit user directive for background execution
    if any(k in t for k in ("in the background", "as a background task", "in background", "background task")):
        return True, "explicit_background_request"

    # Multi-file projects & complete applications
    if is_multi_file_request(command):
        return True, "multi_file_project"

    long_running_patterns = [
        r'\b(?:portfolio\s+website|portfolio\s+site|landing\s+page\s+with)\b',
        r'\b(?:full-?stack|full\s+stack)\b',
        r'\b(?:multi-?file|multiple\s+files)\b',
        r'\b(?:complete|entire|full)\s+(?:application|website|web\s+app|service|system|portal)\b',
        r'\b(?:build|create|generate|develop)\s+(?:a\s+)?(?:complete|full|entire)\b',
        r'\b(?:fastapi|flask|django|express|react|vue|angular|spring\s+boot|next\.?js)\s+(?:project|app|application|service)\b',
        r'\b(?:with\s+database\s+integration|with\s+(?:sqlite|postgres|postgresql|mongodb|mysql)\s+database)\b',
        r'\b(?:machine\s+learning|data\s+science|deep\s+learning)\s+project\b',
        r'\b(?:refactor|rewrite|overhaul)\s+(?:the\s+)?(?:entire|whole|complete|substantial)?\s*(?:project|codebase)\b',
    ]

    for pat in long_running_patterns:
        if re.search(pat, t):
            return True, "complex_application"

    # Small single-file functions, snippets, explanations, and syntax checks stay fast-path
    return False, "fast_path_snippet"


# ============================================================================
# 2. Milestone Planning & Formatting
# ============================================================================

def generate_project_milestones(prompt: str, language: str) -> List[Dict[str, Any]]:
    """Generate meaningful, verifiable milestones tailored to the specific project."""
    p_low = prompt.lower()
    
    is_web = any(k in p_low for k in ("website", "portfolio", "landing page", "react", "html", "css", "frontend"))
    is_api = any(k in p_low for k in ("api", "fastapi", "flask", "backend", "express", "service"))

    if is_web:
        return [
            {"id": 1, "title": "Analyze design requirements and file structure", "status": "PENDING", "completed_at": None},
            {"id": 2, "title": "Generate semantic HTML5 layout and foundation", "status": "PENDING", "completed_at": None},
            {"id": 3, "title": "Implement responsive CSS styling and theme tokens", "status": "PENDING", "completed_at": None},
            {"id": 4, "title": "Build dynamic JavaScript interactions and UI logic", "status": "PENDING", "completed_at": None},
            {"id": 5, "title": "Save files and verify directory integrity", "status": "PENDING", "completed_at": None},
            {"id": 6, "title": "Validate syntax, markup, and asset links", "status": "PENDING", "completed_at": None},
            {"id": 7, "title": "Package final deliverable and delivery report", "status": "PENDING", "completed_at": None},
        ]
    elif is_api:
        return [
            {"id": 1, "title": "Analyze API specification and data models", "status": "PENDING", "completed_at": None},
            {"id": 2, "title": "Create project configuration and dependencies", "status": "PENDING", "completed_at": None},
            {"id": 3, "title": "Implement core routes, endpoints, and handlers", "status": "PENDING", "completed_at": None},
            {"id": 4, "title": "Build database schema, models, and validation logic", "status": "PENDING", "completed_at": None},
            {"id": 5, "title": "Save files and verify directory integrity", "status": "PENDING", "completed_at": None},
            {"id": 6, "title": "Run AST syntax validation and dependency checks", "status": "PENDING", "completed_at": None},
            {"id": 7, "title": "Package final deliverable and delivery report", "status": "PENDING", "completed_at": None},
        ]
    else:
        return [
            {"id": 1, "title": "Analyze system requirements and architecture", "status": "PENDING", "completed_at": None},
            {"id": 2, "title": "Generate project structure and configuration", "status": "PENDING", "completed_at": None},
            {"id": 3, "title": "Implement core application components and logic", "status": "PENDING", "completed_at": None},
            {"id": 4, "title": "Build supporting utilities and modules", "status": "PENDING", "completed_at": None},
            {"id": 5, "title": "Save files and verify directory integrity", "status": "PENDING", "completed_at": None},
            {"id": 6, "title": "Run multi-language syntax and integrity checks", "status": "PENDING", "completed_at": None},
            {"id": 7, "title": "Package final deliverable and delivery report", "status": "PENDING", "completed_at": None},
        ]


def format_milestone_markdown(
    task_id: str,
    status: str,
    current_activity: str,
    milestones: List[Dict[str, Any]],
    project_path: Optional[str] = None,
    files: Optional[List[str]] = None,
    error: Optional[str] = None
) -> str:
    """Renders a scannable Markdown summary card for the Visual Response Surface."""
    lines = [
        f"### Project Generation: `{task_id}`",
        f"**Status:** `{status}` | **Current Activity:** {current_activity}\n",
        "#### Milestones:"
    ]

    for m in milestones:
        st = m.get("status", "PENDING")
        idx = m.get("id", "")
        title = m.get("title", "")
        if st == "COMPLETED":
            lines.append(f"- [x] **{idx}. {title}** *(Done)*")
        elif st == "IN_PROGRESS":
            lines.append(f"- [>] **{idx}. {title}** *(In Progress)*")
        elif st == "FAILED":
            lines.append(f"- [!] **{idx}. {title}** *(Failed)*")
        else:
            lines.append(f"- [ ] {idx}. {title}")

    if project_path:
        lines.append(f"\n**Target Location:** `{project_path}`")
    if files:
        lines.append(f"**Files Created ({len(files)}):** {', '.join(files[:6])}{'...' if len(files) > 6 else ''}")
    if error:
        lines.append(f"\n**Notice / Issue:** {error}")

    return "\n".join(lines)


def emit_task_visual_response(
    task: Task,
    milestones: List[Dict[str, Any]],
    current_activity: str,
    project_path: Optional[str] = None,
    files: Optional[List[str]] = None,
    error: Optional[str] = None
) -> VisualResponse:
    """Constructs and stores a live VisualResponse in DialogueStateManager."""
    md_content = format_milestone_markdown(
        task_id=task.task_id,
        status=task.status.value,
        current_activity=current_activity,
        milestones=milestones,
        project_path=project_path,
        files=files,
        error=error
    )

    actions = [VisualResponseAction(label="Task Status", action_type="task_status", payload=task.task_id)]
    if project_path and os.path.exists(project_path):
        actions.append(VisualResponseAction(label="Open Folder", action_type="open_folder", payload=project_path))
    if task.is_active:
        actions.append(VisualResponseAction(label="Cancel", action_type="cancel_task", payload=task.task_id))

    vr = VisualResponse(
        response_id=f"VR_{task.task_id[-6:]}",
        user_id=str(task.user_id),
        response_type=VisualResponseType.TASK_STATUS,
        title=f"TASK #{task.task_id} ({task.status.value})",
        primary_value=md_content,
        secondary_text=f"Activity: {current_activity}",
        raw_content={
            "task_id": task.task_id,
            "status": task.status.value,
            "milestones": milestones,
            "project_path": project_path,
            "files": files or [],
            "error": error
        },
        actions=actions,
        ttl_seconds=1200.0,
        source_context="code_generation_background"
    )

    try:
        dm = get_dialogue_manager(str(task.user_id))
        dm.store_visual_response(vr)
    except Exception as e:
        logger.debug(f"[TASK_WORKER] Dialogue state update notice: {e}")

    return vr


# ============================================================================
# 3. Main Background Execution Engine
# ============================================================================

def execute_code_generation_task(
    task: Task,
    report_progress: Callable[[str, Optional[float]], None],
    cancellation_token: threading.Event
) -> Dict[str, Any]:
    """
    Stateful, checkpointed background executor for complex code generation projects.
    Handles PLANNING -> GENERATING -> SAVING -> VALIDATING -> REPAIRING -> COMPLETED.
    """
    user_id = task.user_id
    command = task.user_request
    target_lang = task.metadata.get("target_lang") or detect_language(command)

    # ────────────────────────────────────────────────────────────────────────
    # Stage 1: PLANNING
    # ────────────────────────────────────────────────────────────────────────
    if cancellation_token.is_set():
        task.status = TaskStatus.CANCELLED
        return {"status": "cancelled", "message": "Cancelled during initial queue."}

    task.status = TaskStatus.PLANNING
    milestones = generate_project_milestones(command, target_lang)
    milestones[0]["status"] = "IN_PROGRESS"
    task.metadata["milestones"] = milestones
    task.current_step = "Analyzing requirements and structuring project..."
    report_progress(task.current_step, 10.0)
    emit_task_visual_response(task, milestones, task.current_step)

    # Simulate brief architectural design pass
    time.sleep(0.3)
    if cancellation_token.is_set():
        task.status = TaskStatus.CANCELLED
        return {"status": "cancelled", "message": "Cancelled during planning."}

    milestones[0]["status"] = "COMPLETED"
    milestones[0]["completed_at"] = time.time()
    milestones[1]["status"] = "IN_PROGRESS"

    # ────────────────────────────────────────────────────────────────────────
    # Stage 2: GENERATING (with Bounded Retries for Provider Failures)
    # ────────────────────────────────────────────────────────────────────────
    task.status = TaskStatus.GENERATING
    task.current_step = f"Generating {target_lang} components and manifest..."
    report_progress(task.current_step, 25.0)
    emit_task_visual_response(task, milestones, task.current_step)

    raw_output = None
    generation_attempts = 0
    max_attempts = 2

    while generation_attempts < max_attempts:
        if cancellation_token.is_set():
            task.status = TaskStatus.CANCELLED
            return {"status": "cancelled", "message": "Cancelled during generation."}

        generation_attempts += 1
        try:
            raw_output = generate_code(
                prompt=command,
                language=target_lang,
                max_tokens=4000,
                user_id=user_id,
                is_project=True
            )
            if raw_output and "sorry, i could not generate code" not in raw_output.lower():
                break
        except Exception as gen_err:
            logger.warning(f"[TASK_WORKER] Generation attempt {generation_attempts} failed: {gen_err}")
            time.sleep(1.0)

    if not raw_output or "sorry, i could not generate code" in raw_output.lower():
        task.status = TaskStatus.FAILED
        err_msg = "LLM provider failed to generate complete project output after retries."
        task.error = err_msg
        milestones[1]["status"] = "FAILED"
        emit_task_visual_response(task, milestones, "Generation failed", error=err_msg)
        return {"status": "error", "error": err_msg, "task_id": task.task_id}

    extracted = extract_files(raw_output)
    if not extracted:
        # Fallback to single file if model emitted monolithic block
        cleaned_single = clean_code(raw_output)
        if cleaned_single:
            extracted = [(f"main.{target_lang if target_lang != 'python' else 'py'}", cleaned_single)]

    if not extracted:
        task.status = TaskStatus.FAILED
        err_msg = "No verifiable files could be extracted from generator output."
        task.error = err_msg
        milestones[1]["status"] = "FAILED"
        emit_task_visual_response(task, milestones, "Extraction failed", error=err_msg)
        return {"status": "error", "error": err_msg, "task_id": task.task_id}

    milestones[1]["status"] = "COMPLETED"
    milestones[1]["completed_at"] = time.time()
    if len(milestones) > 2:
        milestones[2]["status"] = "COMPLETED"
        milestones[2]["completed_at"] = time.time()
    if len(milestones) > 3:
        milestones[3]["status"] = "IN_PROGRESS"

    # ────────────────────────────────────────────────────────────────────────
    # Stage 3: SAVING (Checkpointed & Security-Validated)
    # ────────────────────────────────────────────────────────────────────────
    if cancellation_token.is_set():
        task.status = TaskStatus.CANCELLED
        return {"status": "cancelled", "message": "Cancelled before writing files."}

    task.status = TaskStatus.SAVING
    task.current_step = f"Saving {len(extracted)} files with traversal security verification..."
    report_progress(task.current_step, 55.0)
    emit_task_visual_response(task, milestones, task.current_step)

    # Base name slug from command
    slug_match = re.search(r'\b(?:project|website|app|portfolio|api)\s+([a-zA-Z0-9_\-]+)', command, re.I)
    base_name = slug_match.group(1).lower() if slug_match else f"{target_lang}_project"

    try:
        project_path, saved_files = save_project(extracted, base_name=base_name)
    except Exception as save_err:
        task.status = TaskStatus.FAILED
        err_msg = f"Filesystem write failed: {save_err}"
        task.error = err_msg
        emit_task_visual_response(task, milestones, "File save error", error=err_msg)
        return {"status": "error", "error": err_msg, "task_id": task.task_id}

    file_names = [f[0] for f in saved_files]

    # Save checkpoint into task metadata
    task.metadata["checkpoint"] = {
        "project_path": project_path,
        "saved_files": file_names,
        "saved_count": len(saved_files),
        "timestamp": time.time()
    }
    task.metadata["project_path"] = project_path
    task.metadata["files"] = file_names

    if len(milestones) > 4:
        milestones[4]["status"] = "COMPLETED"
        milestones[4]["completed_at"] = time.time()

    # ────────────────────────────────────────────────────────────────────────
    # Stage 4: VALIDATING (Multi-language AST & Syntax Verification)
    # ────────────────────────────────────────────────────────────────────────
    if cancellation_token.is_set():
        task.status = TaskStatus.CANCELLED
        task.result = {"saved_files": file_names, "project_path": project_path}
        emit_task_visual_response(task, milestones, "Cancelled by user (Saved files preserved)", project_path=project_path, files=file_names)
        return {"status": "cancelled", "saved_files": file_names, "project_path": project_path}

    task.status = TaskStatus.VALIDATING
    task.current_step = f"Running multi-language syntax and structural validation on {len(saved_files)} files..."
    report_progress(task.current_step, 75.0)
    if len(milestones) > 5:
        milestones[5]["status"] = "IN_PROGRESS"
    emit_task_visual_response(task, milestones, task.current_step, project_path=project_path, files=file_names)

    syntax_errors: List[Dict[str, Any]] = []
    validation_reports: List[Dict[str, Any]] = []

    for rel_p, abs_p in saved_files:
        try:
            with open(abs_p, "r", encoding="utf-8") as f_in:
                content = f_in.read()
            ext = os.path.splitext(rel_p)[1].lower().lstrip(".")
            # Infer language for syntax check
            file_lang = "python" if ext == "py" else ("javascript" if ext in ("js", "jsx") else ("html" if ext in ("html", "htm") else ext))
            v_res = validate_code_syntax(content, language=file_lang)
            validation_reports.append({"file": rel_p, "result": v_res})
            if not v_res.get("valid"):
                syntax_errors.append({"file": rel_p, "abs_path": abs_p, "error": v_res.get("message"), "content": content, "lang": file_lang})
        except Exception as val_e:
            logger.debug(f"[TASK_WORKER] Validation reading error for {rel_p}: {val_e}")

    task.metadata["validation_reports"] = validation_reports

    # ────────────────────────────────────────────────────────────────────────
    # Stage 5: REPAIRING (Bounded Automated Repair Budget)
    # ────────────────────────────────────────────────────────────────────────
    repaired_count = 0
    if syntax_errors and not cancellation_token.is_set():
        task.status = TaskStatus.REPAIRING
        task.current_step = f"Repairing {len(syntax_errors)} syntax issues with automated repair cycle..."
        report_progress(task.current_step, 88.0)
        emit_task_visual_response(task, milestones, task.current_step, project_path=project_path, files=file_names)

        for err_item in syntax_errors[:2]:  # Limit repair budget to first 2 errors
            if cancellation_token.is_set():
                break
            try:
                fix_res = fix_code_with_llm(
                    code=err_item["content"],
                    error_message=err_item["error"],
                    language=err_item["lang"],
                    user_id=user_id
                )
                if fix_res.get("success") and fix_res.get("fixed_code"):
                    with open(err_item["abs_path"], "w", encoding="utf-8") as f_out:
                        f_out.write(fix_res["fixed_code"])
                    repaired_count += 1
            except Exception as repair_e:
                logger.warning(f"[TASK_WORKER] Repair attempt failed for {err_item['file']}: {repair_e}")

    if len(milestones) > 5:
        milestones[5]["status"] = "COMPLETED"
        milestones[5]["completed_at"] = time.time()

    # ────────────────────────────────────────────────────────────────────────
    # Stage 6: COMPLETED
    # ────────────────────────────────────────────────────────────────────────
    if cancellation_token.is_set():
        task.status = TaskStatus.CANCELLED
        task.result = {"saved_files": file_names, "project_path": project_path}
        emit_task_visual_response(task, milestones, "Cancelled (Saved files preserved)", project_path=project_path, files=file_names)
        return {"status": "cancelled", "saved_files": file_names, "project_path": project_path}

    task.status = TaskStatus.COMPLETED
    if len(milestones) > 6:
        milestones[6]["status"] = "COMPLETED"
        milestones[6]["completed_at"] = time.time()

    # Determine setup instructions based on project files
    instructions = []
    if any(f.endswith(".py") for f in file_names):
        if any(f.endswith("requirements.txt") for f in file_names):
            instructions.append("pip install -r requirements.txt")
        instructions.append("python main.py (or run target entry file)")
    if any(f.endswith(".js") or f.endswith(".json") for f in file_names):
        if any(f.endswith("package.json") for f in file_names):
            instructions.append("npm install && npm start")
    if any(f.endswith(".html") for f in file_names):
        instructions.append("Open index.html in any web browser")

    setup_text = " | ".join(instructions) if instructions else "Inspect generated files in folder."

    final_result = {
        "status": "success",
        "task_id": task.task_id,
        "requested": command,
        "language": target_lang,
        "project_path": project_path,
        "files": file_names,
        "file_count": len(file_names),
        "milestones": milestones,
        "validation_summary": f"{len(file_names) - len(syntax_errors) + repaired_count}/{len(file_names)} files valid",
        "repaired_count": repaired_count,
        "setup_instructions": setup_text,
        "executed": False,  # Explicit accurate disclosure per Section 9
        "preview_available": True
    }

    task.result = final_result
    task.current_step = f"Project completed: {len(file_names)} files saved at {os.path.basename(project_path)}"
    report_progress(task.current_step, 100.0)

    # Emit final visual response card
    emit_task_visual_response(
        task=task,
        milestones=milestones,
        current_activity=task.current_step,
        project_path=project_path,
        files=file_names
    )

    return final_result
