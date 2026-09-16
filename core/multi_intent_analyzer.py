"""
Multi-Intent Analyzer for PHASE 6

Extends NOVA to detect and parse multiple intents from a single user input.
Handles intent detection, parameter extraction, dependency analysis, and 
confidence scoring while maintaining PHASE 5 backward compatibility.

Architecture:
- Detects multiple intents in single command
- Extracts parameters for each intent separately
- Identifies dependencies between intents
- Orders intents by priority and dependencies
- Returns structured analysis for Goal Planner
"""

import re
from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple, Optional
from enum import Enum
from datetime import datetime

import sys
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.unified_command_router import Intent, unified_router


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class IntentMatch:
    """Represents a single intent match from pattern detection"""
    intent: Intent
    matched_text: str
    confidence: float
    start_pos: int = 0
    end_pos: int = 0
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionIntent:
    """Intent ready for execution with all metadata"""
    sequence: int  # Execution order (0 = first)
    intent: Intent
    parameters: Dict[str, Any]
    confidence: float
    dependencies: List[int] = field(default_factory=list)  # Indices of dependencies
    context_from_previous: Dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False


@dataclass
class IntentAnalysis:
    """Complete analysis of user input for multiple intents"""
    intents: List[Dict[str, Any]]  # List of intent analysis dicts
    has_multiple_intents: bool
    total_intents: int
    primary_intent: Intent
    secondary_intents: List[Intent] = field(default_factory=list)
    dependencies: Dict[int, int] = field(default_factory=dict)  # intent_idx -> depends_on_idx
    execution_context: Dict[str, Any] = field(default_factory=dict)
    confidence_score: float = 0.0
    requires_sequential_execution: bool = False
    estimated_execution_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    original_input: str = ""
    timestamp: str = ""


# ============================================================================
# Multi-Intent Analyzer
# ============================================================================

class MultiIntentAnalyzer:
    """
    Analyzes user input to detect and parse multiple intents.
    
    Extends unified_command_router capabilities to handle:
    - Multiple intents in one command
    - Context-aware references
    - Dependent intents
    - Complex goals
    """
    
    # Multi-intent connectors
    INTENT_CONNECTORS = [
        (r'\band\b', 0.8),           # "play music and set reminder"
        (r'\bthen\b', 0.85),          # "play music then set reminder"
        (r'\balso\b', 0.7),           # "play music also set reminder"
        (r'\bafter\b', 0.9),          # "after playing music, set reminder"
        (r'\bbefore\b', 0.9),         # "before playing music, set reminder"
        (r'\bwhile\b', 0.85),         # "while playing music, set reminder"
        (r'\bplus\b', 0.75),          # "play music plus set reminder"
        (r'[,;]\s*(?=\w)', 0.6),      # "play music, set reminder" or "play music; set reminder"
    ]
    
    # Dependency patterns (intent_A depends on intent_B if pattern matches)
    DEPENDENCY_PATTERNS = {
        # EMAIL depends on WEATHER
        (Intent.EMAIL, Intent.WEATHER_QUERY): r'send.*weather|email.*weather|results to',
        
        # EMAIL depends on MUSIC
        (Intent.EMAIL, Intent.MUSIC): r'send.*song|email.*music',
        
        # EMAIL depends on REMINDERS
        (Intent.EMAIL, Intent.REMINDERS): r'send.*reminder|email.*reminder',
        
        # REMINDERS depends on MUSIC/WEATHER/EMAIL (contextual)
        (Intent.REMINDERS, Intent.MUSIC): r'remind.*music|remember.*song',
        (Intent.REMINDERS, Intent.WEATHER_QUERY): r'remind.*weather',
        (Intent.REMINDERS, Intent.EMAIL): r'remind.*email',
    }
    
    # Confidence thresholds
    MIN_CONFIDENCE = 0.7
    HIGH_CONFIDENCE = 0.9
    
    def __init__(self):
        """Initialize multi-intent analyzer"""
        self.router = unified_router
        self.primary_intent_cache = {}
        print("[MULTI_INTENT_ANALYZER] Initialized successfully")
    
    def analyze(self, user_input: str) -> IntentAnalysis:
        """
        Analyze user input for multiple intents.
        
        Args:
            user_input: User's command text
            
        Returns:
            IntentAnalysis with complete breakdown
        """
        if not user_input or not user_input.strip():
            return self._empty_analysis(user_input)
        
        # Check for multiple intents
        has_connectors = self._detect_connectors(user_input)
        
        if has_connectors:
            # Multi-intent analysis
            return self._analyze_multiple_intents(user_input)
        else:
            # Single-intent analysis (backward compatible)
            return self._analyze_single_intent(user_input)
    
    def _detect_connectors(self, user_input: str) -> bool:
        """Detect if input contains multi-intent connectors"""
        input_lower = user_input.lower()
        for pattern, _ in self.INTENT_CONNECTORS:
            if re.search(pattern, input_lower):
                return True
        return False
    
    def _analyze_single_intent(self, user_input: str) -> IntentAnalysis:
        """
        Analyze single intent (PHASE 5 backward compatible).
        
        Falls back to existing unified router.
        """
        intent, params = self.router.route_command(user_input)
        
        # Calculate confidence
        confidence = self._calculate_single_intent_confidence(intent, user_input)
        
        analysis = IntentAnalysis(
            intents=[{
                "intent": intent,
                "confidence": confidence,
                "parameters": params,
                "dependencies": [],
                "sequence_position": 0
            }],
            has_multiple_intents=False,
            total_intents=1,
            primary_intent=intent,
            secondary_intents=[],
            dependencies={},
            confidence_score=confidence,
            requires_sequential_execution=False,
            estimated_execution_time=0.5,
            original_input=user_input,
            timestamp=datetime.now().isoformat()
        )
        
        return analysis
    
    def _analyze_multiple_intents(self, user_input: str) -> IntentAnalysis:
        """Analyze input with multiple intents detected"""
        
        # Step 1: Split by connectors
        segments = self._split_by_connectors(user_input)
        
        if len(segments) == 1:
            # Fallback to single-intent if split failed
            return self._analyze_single_intent(user_input)
        
        # Step 2: Analyze each segment
        intent_matches = []
        for segment_text, segment_idx in segments:
            intent, params = self.router.route_command(segment_text)
            confidence = self._calculate_segment_confidence(intent, segment_text)
            
            # Only include matches with sufficient confidence
            if confidence >= self.MIN_CONFIDENCE:
                match = IntentMatch(
                    intent=intent,
                    matched_text=segment_text,
                    confidence=confidence,
                    context={"segment_index": segment_idx, "parameters": params}
                )
                intent_matches.append(match)
        
        if not intent_matches:
            # No valid intents found, treat as general conversation
            return self._analyze_single_intent(user_input)
        
        # Step 3: Detect dependencies
        dependencies = self._detect_dependencies(intent_matches, user_input)
        
        # Step 4: Order by priority
        ordered_intents = self._order_by_priority(intent_matches, dependencies)
        
        # Step 5: Build IntentAnalysis
        intents_list = []
        for seq_idx, (match, position) in enumerate(ordered_intents):
            intents_list.append({
                "intent": match.intent,
                "confidence": match.confidence,
                "parameters": match.context.get("parameters", {}),
                "dependencies": dependencies.get(seq_idx, []),
                "sequence_position": seq_idx,
                "matched_text": match.matched_text
            })
        
        # Calculate average confidence
        avg_confidence = sum(m.confidence for m, _ in ordered_intents) / len(ordered_intents)
        
        analysis = IntentAnalysis(
            intents=intents_list,
            has_multiple_intents=True,
            total_intents=len(intents_list),
            primary_intent=ordered_intents[0][0].intent,
            secondary_intents=[m.intent for m, _ in ordered_intents[1:]],
            dependencies=dependencies,
            execution_context={"segments": len(segments), "original_input": user_input},
            confidence_score=avg_confidence,
            requires_sequential_execution=len(ordered_intents) > 1,
            estimated_execution_time=0.5 + (len(ordered_intents) * 0.3),
            original_input=user_input,
            timestamp=datetime.now().isoformat()
        )
        
        return analysis
    
    def _split_by_connectors(self, user_input: str) -> List[Tuple[str, int]]:
        """
        Split user input by connector patterns.
        
        Returns list of (segment_text, segment_index) tuples
        """
        segments = []
        input_lower = user_input.lower()
        
        # Find all connector positions
        connector_positions = []
        for pattern, _ in self.INTENT_CONNECTORS:
            for match in re.finditer(pattern, input_lower):
                connector_positions.append((match.start(), match.end(), match.group()))
        
        if not connector_positions:
            return [(user_input, 0)]
        
        # Sort by position
        connector_positions.sort(key=lambda x: x[0])
        
        # Split by connectors
        last_end = 0
        segment_idx = 0
        
        for conn_start, conn_end, connector in connector_positions:
            # Add segment before connector
            segment = user_input[last_end:conn_start].strip()
            if segment:
                segments.append((segment, segment_idx))
                segment_idx += 1
            
            last_end = conn_end
        
        # Add final segment
        final_segment = user_input[last_end:].strip()
        if final_segment:
            segments.append((final_segment, segment_idx))
        
        return segments if segments else [(user_input, 0)]
    
    def _calculate_single_intent_confidence(self, intent: Intent, user_input: str) -> float:
        """Calculate confidence for single intent"""
        if intent == Intent.GENERAL_CONVERSATION:
            return 0.5
        
        # Check if intent patterns match
        patterns = self.router.patterns.get(intent, [])
        for pattern in patterns:
            if pattern.search(user_input.lower()):
                return 0.95
        
        return 0.7
    
    def _calculate_segment_confidence(self, intent: Intent, segment: str) -> float:
        """Calculate confidence for segment analysis"""
        if intent == Intent.GENERAL_CONVERSATION:
            return 0.4  # Lower confidence for fallback
        
        # Check keyword density
        segment_lower = segment.lower()
        patterns = self.router.patterns.get(intent, [])
        
        match_count = 0
        for pattern in patterns:
            if pattern.search(segment_lower):
                match_count += 1
        
        if match_count > 0:
            return min(0.95, 0.7 + (match_count * 0.1))
        
        return 0.5
    
    def _detect_dependencies(
        self,
        intent_matches: List[IntentMatch],
        user_input: str
    ) -> Dict[int, List[int]]:
        """
        Detect dependencies between intents.
        
        Returns dict: intent_index -> list of dependent intent indices
        """
        dependencies = {}
        input_lower = user_input.lower()
        
        for i, match_i in enumerate(intent_matches):
            for j, match_j in enumerate(intent_matches):
                if i == j:
                    continue
                
                # Check if match_i depends on match_j
                key = (match_i.intent, match_j.intent)
                if key in self.DEPENDENCY_PATTERNS:
                    pattern = self.DEPENDENCY_PATTERNS[key]
                    if re.search(pattern, input_lower):
                        if i not in dependencies:
                            dependencies[i] = []
                        dependencies[i].append(j)
        
        return dependencies
    
    def _order_by_priority(
        self,
        intent_matches: List[IntentMatch],
        dependencies: Dict[int, List[int]]
    ) -> List[Tuple[IntentMatch, int]]:
        """
        Order intents by priority and dependencies.
        
        Returns list of (IntentMatch, original_position) tuples
        """
        # Create ordering with original indices
        original_positions = {i: m for i, m in enumerate(intent_matches)}
        
        # Topological sort for dependencies
        ordered = []
        processed = set()
        
        def process_intent(idx):
            if idx in processed:
                return
            
            # Process dependencies first
            for dep_idx in dependencies.get(idx, []):
                process_intent(dep_idx)
            
            ordered.append((original_positions[idx], idx))
            processed.add(idx)
        
        # Process all intents
        for i in range(len(intent_matches)):
            process_intent(i)
        
        return ordered
    
    def _empty_analysis(self, user_input: str) -> IntentAnalysis:
        """Return empty analysis for invalid input"""
        return IntentAnalysis(
            intents=[],
            has_multiple_intents=False,
            total_intents=0,
            primary_intent=Intent.GENERAL_CONVERSATION,
            confidence_score=0.0,
            original_input=user_input,
            timestamp=datetime.now().isoformat()
        )


# ============================================================================
# Global Analyzer Instance
# ============================================================================

multi_intent_analyzer = MultiIntentAnalyzer()


# ============================================================================
# Utility Functions
# ============================================================================

def analyze_input(user_input: str) -> IntentAnalysis:
    """
    Convenience function to analyze user input.
    
    Usage:
        analysis = analyze_input("play music and set reminder")
    """
    return multi_intent_analyzer.analyze(user_input)


def has_multiple_intents(user_input: str) -> bool:
    """Check if input contains multiple intents"""
    analysis = analyze_input(user_input)
    return analysis.has_multiple_intents


def get_execution_order(user_input: str) -> List[ExecutionIntent]:
    """
    Get ordered list of intents ready for execution.
    
    Returns list of ExecutionIntent objects in execution order.
    """
    analysis = analyze_input(user_input)
    
    execution_intents = []
    for intent_dict in analysis.intents:
        exec_intent = ExecutionIntent(
            sequence=intent_dict["sequence_position"],
            intent=intent_dict["intent"],
            parameters=intent_dict["parameters"],
            confidence=intent_dict["confidence"],
            dependencies=intent_dict.get("dependencies", []),
            requires_confirmation=intent_dict["confidence"] < 0.8
        )
        execution_intents.append(exec_intent)
    
    return execution_intents


if __name__ == "__main__":
    # Test multi-intent analyzer
    
    test_cases = [
        # Single intents (backward compatible)
        "play music",
        "what is the time",
        "send email to sathvik",
        
        # Multi-intents
        "play some Telugu songs and set a reminder to listen later",
        "find weather in Guntur and send the results to Sathvik",
        "open Chrome and search for weather",
        
        # Context-aware (single intent with context)
        "what about tomorrow",
        
        # Edge cases
        "I like music and email",
        "play music and stop music",
    ]
    
    print("[MULTI_INTENT_ANALYZER] Test Cases\n")
    
    for test_input in test_cases:
        print(f"Input: {test_input}")
        analysis = analyze_input(test_input)
        print(f"  Multiple Intents: {analysis.has_multiple_intents}")
        print(f"  Total Intents: {analysis.total_intents}")
        print(f"  Primary Intent: {analysis.primary_intent.name}")
        print(f"  Confidence: {analysis.confidence_score:.2f}")
        if analysis.has_multiple_intents:
            print(f"  Secondary Intents: {[i.name for i in analysis.secondary_intents]}")
        print()
