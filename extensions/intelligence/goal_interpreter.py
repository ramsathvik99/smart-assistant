"""
Goal Interpreter Module
Interprets user goals and maps them to multi-step plans.
"""

import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

@dataclass
class Goal:
    """Represents a user goal with metadata"""
    name: str
    confidence: float
    context: Dict[str, Any]
    suggested_plan: List[str]

class GoalInterpreter:
    """Interprets user goals and creates execution plans"""
    
    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger("assistant.intelligence.goals")
        
        # Goal patterns and their associated plans
        self.goal_patterns = {
            "focus": {
                "keywords": ["focus", "concentrate", "study", "work"],
                "plan": ["close_distractions", "open_vscode", "play_focus_music"],
                "confidence": 0.9
            },
            "coding": {
                "keywords": ["coding", "program", "develop", "code", "prepare for coding"],
                "plan": ["open_vscode", "open_project", "play_music"],
                "confidence": 0.85
            },
            "learning": {
                "keywords": ["learn", "study", "tutorial", "help", "documentation"],
                "plan": ["open_browser", "search_tutorial"],
                "confidence": 0.8
            },
            "development": {
                "keywords": ["development", "start", "begin", "setup"],
                "plan": ["open_vscode", "open_terminal"],
                "confidence": 0.8
            },
            "project": {
                "keywords": ["project", "work", "task"],
                "plan": ["open_vscode", "open_project_folder"],
                "confidence": 0.75
            },
            "git": {
                "keywords": ["git", "repository", "version", "commit"],
                "plan": ["open_vscode", "open_git", "open_terminal"],
                "confidence": 0.85
            },
            "vscode": {
                "keywords": ["vscode", "code", "editor", "extensions", "settings"],
                "plan": ["open_vscode", "open_extensions"],
                "confidence": 0.9
            },
            "break": {
                "keywords": ["break", "rest", "relax", "pause"],
                "plan": ["play_music", "open_browser"],
                "confidence": 0.7
            },
            "entertainment": {
                "keywords": ["entertainment", "fun", "youtube", "videos"],
                "plan": ["open_browser", "search_query"],
                "confidence": 0.8
            }
        }
        
        # Context-aware goal adjustments
        self.context_adjustments = {
            "evening": {
                "coding": 0.7,  # Lower confidence in evening
                "entertainment": 0.95,  # Higher confidence in evening
                "break": 0.9
            },
            "morning": {
                "coding": 0.95,  # Higher confidence in morning
                "development": 0.9,
                "entertainment": 0.6
            },
            "work_hours": {
                "focus": 0.95,
                "coding": 0.9,
                "break": 0.5
            }
        }
    
    def interpret_goal(self, user_input: str, context: Dict[str, Any] | None = None) -> Optional[Goal]:
        """
        Interpret user input to identify goals and create plans.
        
        Args:
            user_input: The user's command
            context: Current context information
            
        Returns:
            Goal object if goal identified, None otherwise
        """
        user_input_lower = user_input.lower()
        
        # Find matching goals
        matched_goals = []
        
        for goal_name, goal_data in self.goal_patterns.items():
            confidence = self._calculate_goal_confidence(
                user_input_lower, goal_name, goal_data, context
            )
            
            if confidence > 0.5:  # Minimum confidence threshold
                matched_goals.append((goal_name, confidence, goal_data))
        
        if not matched_goals:
            return None
        
        # Sort by confidence and get the best match
        matched_goals.sort(key=lambda x: x[1], reverse=True)
        best_goal_name, confidence, goal_data = matched_goals[0]
        
        # Create goal object
        goal = Goal(
            name=best_goal_name,
            confidence=confidence,
            context=context or {},
            suggested_plan=goal_data["plan"].copy()
        )
        
        self.logger.info(f"Interpreted goal: {best_goal_name} (confidence: {confidence:.2f})")
        
        return goal
    
    def _calculate_goal_confidence(
        self, 
        user_input: str, 
        goal_name: str, 
        goal_data: Dict[str, Any], 
        context: Dict[str, Any] | None
    ) -> float:
        """Calculate confidence score for a goal match."""
        base_confidence = goal_data["confidence"]
        
        # Keyword matching
        keyword_matches = sum(1 for keyword in goal_data["keywords"] if keyword in user_input)
        keyword_score = min(keyword_matches / len(goal_data["keywords"]), 1.0)
        
        # Exact phrase matching (higher weight)
        exact_matches = sum(1 for keyword in goal_data["keywords"] if keyword in user_input.split())
        exact_score = min(exact_matches / max(len(goal_data["keywords"]), 1), 1.0)
        
        # Context adjustments
        context_multiplier = 1.0
        if context:
            time_context = context.get("time_context")
            if time_context in self.context_adjustments:
                goal_adjustments = self.context_adjustments[time_context]
                if goal_name in goal_adjustments:
                    context_multiplier = goal_adjustments[goal_name]
        
        # Combine scores
        final_confidence = base_confidence * (0.6 * keyword_score + 0.4 * exact_score) * context_multiplier
        
        return min(final_confidence, 1.0)
    
    def get_goal_suggestion(self, user_input: str, context: Dict[str, Any] | None = None) -> Optional[str]:
        """Get a suggestion based on interpreted goal."""
        goal = self.interpret_goal(user_input, context)
        
        if not goal:
            return None
        
        if goal.confidence > 0.8:
            return f"I understand you want to {goal.name}. Should I execute this plan: {', '.join(goal.suggested_plan)}?"
        elif goal.confidence > 0.6:
            return f"It looks like you want to {goal.name}. I can help with that."
        
        return None
    
    def create_execution_plan(self, goal: Goal) -> List[str]:
        """Create a detailed execution plan from a goal."""
        return goal.suggested_plan.copy()
    
    def get_available_goals(self) -> List[str]:
        """Get list of all available goal types."""
        return list(self.goal_patterns.keys())
    
    def add_custom_goal(self, name: str, keywords: List[str], plan: List[str], confidence: float = 0.7):
        """Add a custom goal pattern."""
        self.goal_patterns[name] = {
            "keywords": keywords,
            "plan": plan,
            "confidence": confidence
        }
        
        self.logger.info(f"Added custom goal: {name}")

# Global goal interpreter instance
_goal_interpreter = None

def get_goal_interpreter() -> GoalInterpreter:
    """Get the global goal interpreter instance."""
    global _goal_interpreter
    if _goal_interpreter is None:
        _goal_interpreter = GoalInterpreter()
    return _goal_interpreter

def reset_goal_interpreter():
    """Reset the global goal interpreter instance (for testing)."""
    global _goal_interpreter
    _goal_interpreter = None
