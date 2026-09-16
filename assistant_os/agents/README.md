# NOVA OS Agent Framework Documentation

This package defines the execution contract, base classes, and registries that all future NOVA OS agents must inherit from.

## Core Architecture

The Agent Framework enforces a strict boundary between agent scheduling (owned by the `AgentManager` module) and task execution (owned by concrete implementations of `BaseAgent`).

```
[AgentManager] 
      │ 
      │ (instantiates subclass via AgentClassRegistry)
      ▼
  BaseAgent.run(AgentTask)
      │
      ├───► _pre_run() (hook)
      ├───► execute() (implemented by subclass)
      └───► _post_run() (hook)
      │
      ▼
[AgentResult] (returned back to AgentManager)
```

---

## Base Classes & Models

### 1. `BaseAgent`
An abstract base class that manages:
- Verification of incoming `AgentTask` constraints.
- Automated subclass registration in `AgentClassRegistry` on module loading.
- Execution metrics (capturing duration and exceptions).
- Access to injected tool handlers (under `self.tools`).

### 2. `AgentClassRegistry`
A class-level mapping (`AgentType` -> `BaseAgent` class). Enables dynamic instantiation of specialized agents at runtime.

### 3. `AgentTask`
Dataclass capturing everything an agent needs to perform a single execution: the instructions, the memory-assembled `ContextPackage`, the list of allowed tools, and execution metadata (like timeout constraints).

### 4. `AgentResult`
Dataclass representing the execution outcome, containing the final `content` matched to an `AgentOutputType` (e.g. TEXT, CODE, TABLE, STRUCTURED, etc.), diagnostic fields (`error`, `duration_ms`), and optional metadata (sources or token usage).

---

## Example Usage: Implementing a New Agent

To implement an agent, subclass `BaseAgent` and set the static `AGENT_MANIFEST`:

```python
from nova_os.agents import BaseAgent, AgentTask, AgentResult, AgentOutputType
from nova_os.agent_manager.models import AgentManifest
from nova_os.planner.models import AgentType

class ExampleAutomationAgent(BaseAgent):
    
    # Static declaration required for auto-registration
    AGENT_MANIFEST = AgentManifest(
        agent_type=AgentType.AUTOMATION,
        display_name="Automation Agent",
        description="Controls OS windows and application states.",
        capabilities=["launch_app", "close_app"],
        intent_patterns=["open", "launch", "close"],
        max_concurrent=1
    )

    def execute(self, task: AgentTask) -> AgentResult:
        # Check task instructions
        instruction = task.instruction
        
        # Access tool if available
        if "launch" in instruction and self._has_tool("launch_app"):
            app_name = instruction.split("launch")[-1].strip()
            self._call_tool("launch_app", app_name)
            return self._success(task, f"Launched {app_name}", AgentOutputType.TEXT)
            
        return self._failure(task, "Action not supported or missing tool.")
```
