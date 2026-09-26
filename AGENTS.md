# PERMANENT REGRESSION PROTECTION RULE & ARCHITECTURE FREEZE

This project is in a mature integration and hardening stage.
All previously implemented and verified functionality is **FROZEN BEHAVIOR**.

---

## 1. Core Principles

1. **DO NOT** assume existing architecture is wrong.
2. **DO NOT** broadly refactor shared systems.
3. **DO NOT** rewrite `UnifiedCommandRouter`.
4. **DO NOT** rewrite `GoalPlanner`.
5. **DO NOT** replace `DialogueStateManager` or `ContextManager`.
6. **DO NOT** replace the existing execution pipeline.
7. **DO NOT** create duplicate subsystems.
8. **DO NOT** modify working audio/STT/VAD/TTS/barge-in behavior.
9. **DO NOT** modify working visual-response behavior.
10. **DO NOT** modify working document generation (`modules/document_tools`).
11. **DO NOT** modify PostgreSQL schema unless absolutely required and explicitly proven necessary.
12. **DO NOT** modify authentication / user isolation.
13. **DO NOT** modify previously-fixed intent priorities unless a new failure proves that priority is the direct cause.
14. **DO NOT** change unrelated modules while fixing one module.
15. **DO NOT** perform cleanup or refactoring together with a feature fix.

---

## 2. Before Modifying Code: Production Path Tracing

Trace the exact failing command through the canonical production path:
```
INPUT
  ↓
INTENT
  ↓
ROUTER
  ↓
PLANNER
  ↓
MODULE
  ↓
EXECUTION
  ↓
VERIFICATION
  ↓
CONTEXT
  ↓
RESPONSE
```
Find the exact failure point.

---

## 3. Modification & Isolation Protocol

- Change **only** the responsible component.
- Preserve all existing behavior outside that component.
- Run relevant existing regression tests.
- Run new feature tests.
- Run collision tests around the changed intent/module.

---

## 4. Strict Regression Stop Rule

If an existing test that previously passed now fails:
- **STOP** implementing the new feature immediately.
- Do not continue adding changes on top of the regression.
- Determine exactly why the new change caused the old failure.
- Restore previous behavior, then implement the new behavior in a more isolated way.
- **NEVER** "fix" a regression by weakening or deleting an old test.
- **NEVER** mark a feature as working because a helper function works; it must work through the real production path.
- If a required change cannot be implemented without risking an existing capability, **STOP and report the conflict** instead of making a broad change.

---

## 5. Mandatory Reporting Format

Every final report must include:
- **Files changed**
- **Functions changed**
- **Root cause**
- **New behavior**
- **Regression tests executed**
- **Previously working capabilities verified**
- **Any remaining limitations**

**Goal:** `NEW CAPABILITY + ZERO REGRESSION` (not `NEW CAPABILITY + REWRITE EXISTING SYSTEMS`).

## 6. Protected Capability Baseline

The following capabilities are considered protected baseline functionality.

Any future change MUST preserve them unless the current task explicitly
targets that capability and the production-path investigation proves that
the capability itself is the root cause.

### Core Interaction
- Continuous microphone listening
- Persistent audio stream
- VAD speech detection
- STT
- TTS
- True barge-in/interruption
- No mandatory wake word
- Assistant-name recognition/usage

### Intelligence & Execution
- Intent resolution
- UnifiedCommandRouter
- Multi-intent handling
- GoalPlanner
- DialogueStateManager
- ContextManager
- Observe → Act → Observe → Verify
- Adaptive execution
- Goal lifecycle
- Goal cancellation
- Goal completion
- Contextual follow-up
- Cross-session goal/context behavior

### Proactive Systems
- EnvironmentObserver
- State-difference detection
- ProactiveObserver
- Goal-aware proactive reasoning
- Proactive event relevance/correlation
- Cancellation precedence
- User isolation

### Modules
- Document generation
- PDF generation
- DOCX generation
- PPTX generation
- XLSX generation
- File management
- Browser
- Music/media
- Calendar
- Reminders
- Tasks
- Notes
- Email
- System controller
- Device management
- Android/mobile control
- Smart home
- Window management
- Clipboard
- Location
- Learning/personalization
- Undo
- Code generation

### UI / Presentation
- PyQt6 assistant UI
- Floating launcher
- Dashboard
- Visual Response Surface
- Visual-response cache
- "show that again"
- Outside-click dismissal
- Account-specific assistant name

### Platform / Data
- Authentication
- Per-user isolation
- PostgreSQL persistence
- Existing database schema
- Existing memory system
- Existing task persistence
- Existing reminder persistence

### Regression Requirement

For any future change, the developer/agent must verify the relevant
protected capabilities after modification.

If a protected capability regresses:

STOP.

Do not continue implementing the new feature until the regression is
understood and resolved.

Do not remove, weaken, skip, or rewrite the regression test to make it pass.

A feature is NOT considered complete merely because its local function
works. It must work through the real production path without breaking
the protected baseline.