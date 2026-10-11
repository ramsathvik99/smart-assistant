"""
Environment Awareness Package
Provides continuous environment observation, rich state extraction,
application-specific adapters, and a unified state engine.

Public API:
    get_environment_coordinator()   → EnvironmentObserverCoordinator (main entry point)
    get_state_engine()              → EnvironmentStateEngine (direct state queries)
    EnvironmentState                → Snapshot data model
    StateTransition                 → Transition event data model
"""

from core.environment.models import EnvironmentState, StateTransition
from core.environment.state_engine import (
    EnvironmentStateEngine,
    get_state_engine,
    verify_and_synchronize_foreground_state,
)
from core.environment.continuous_observer import (
    ContinuousEnvironmentObserver,
    EnvironmentObserverCoordinator,
    get_environment_coordinator,
)

__all__ = [
    "EnvironmentState",
    "StateTransition",
    "EnvironmentStateEngine",
    "get_state_engine",
    "verify_and_synchronize_foreground_state",
    "ContinuousEnvironmentObserver",
    "EnvironmentObserverCoordinator",
    "get_environment_coordinator",
]
