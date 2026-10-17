"""
Multi-Signal Semantic Reference Resolver for Content Artifacts
Provides:
  1. Multi-signal resolution: Explicit topic, content-type, programming language,
     lineage, ordinal position, dialogue state, and recency.
  2. Strict Semantic Preference: Topic & Content-Type override pure recency.
  3. Ambiguity Detection: Concise clarification prompt when multiple candidates collide.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.artifact_graph import ContentArtifact, get_artifact_graph

logger = logging.getLogger("ArtifactResolver")


@dataclass
class ResolvedArtifact:
    """Outcome of resolving an artifact reference from user input."""
    artifact: Optional[ContentArtifact] = None
    confidence: float = 0.0
    matched_signals: List[str] = field(default_factory=list)
    rationale: str = ""
    is_ambiguous: bool = False
    clarification_prompt: Optional[str] = None
    candidate_artifacts: List[ContentArtifact] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return self.artifact is not None and not self.is_ambiguous


class ArtifactReferenceResolver:
    """
    Resolves natural language references to specific ContentArtifacts in the
    ArtifactContextGraph using 12 independent semantic signals.
    """

    def __init__(self):
        self.graph = get_artifact_graph()

    def resolve(
        self,
        user_input: str,
        user_id: int = 1,
        dialogue_state: Optional[Any] = None
    ) -> ResolvedArtifact:
        """
        Main resolution entry point.
        Evaluates user reference against all active artifacts in the graph.
        """
        all_artifacts = self.graph.list_artifacts(user_id=user_id, status="active")
        if not all_artifacts:
            return ResolvedArtifact(
                artifact=None,
                confidence=0.0,
                rationale="No active artifacts exist for this user.",
                is_ambiguous=False
            )

        clean_text = user_input.strip()
        low_text = clean_text.lower()

        # Step 1: Detect explicit filters from query
        req_type = self._detect_requested_type(low_text)
        req_topic = self._detect_requested_topic(low_text)
        req_lang = self._detect_requested_language(low_text)
        req_ordinal = self._detect_ordinal_index(low_text)
        req_lineage = self._detect_lineage_request(low_text)
        req_full_info = any(w in low_text for w in ("full information", "full concept", "entire information", "original information", "complete information", "all the information", "all information"))

        # Step 2: Handle Ordinal References directly if explicit (e.g. "the first code", "the second one")
        if req_ordinal is not None:
            filtered = [
                a for a in all_artifacts
                if (req_type is None or a.content_type == req_type)
            ]
            filtered.sort(key=lambda a: a.created_at)  # Chronological order
            if 0 <= req_ordinal < len(filtered):
                chosen = filtered[req_ordinal]
                return ResolvedArtifact(
                    artifact=chosen,
                    confidence=0.98,
                    matched_signals=["ordinal_reference", f"type:{chosen.content_type}"],
                    rationale=f"Resolved {req_ordinal + 1}{'st' if req_ordinal==0 else ('nd' if req_ordinal==1 else 'rd')} artifact in chronological order: '{chosen.topic}'."
                )

        # Step 3: Score each candidate artifact across multiple signals
        scored_candidates: List[Tuple[ContentArtifact, float, List[str]]] = []
        now = time.time()

        for art in all_artifacts:
            score = 0.0
            signals: List[str] = []

            # Signal 0: Pronoun / Demonstrative Reference to Active/Recent Artifact
            pronoun_words = ("it", "that", "this", "them", "these", "those", "everything", "all")
            has_pronoun = (
                any(p in low_text.split() for p in pronoun_words)
                or self._is_pure_pronoun(low_text)
                or any(ph in low_text for ph in (
                    "what you gathered", "what you found", "what you wrote", "what you inserted",
                    "information that you found", "information you found", "information you gathered",
                    "the above", "previous content", "last gathered content", "last content", "last code"
                ))
            )
            if has_pronoun:
                is_active = False
                if dialogue_state and hasattr(dialogue_state, "session_context"):
                    if dialogue_state.session_context.get("last_content_artifact_id") == art.artifact_id:
                        is_active = True
                if not is_active and all_artifacts:
                    max_time = max(a.created_at for a in all_artifacts)
                    recent_candidates = [a for a in all_artifacts if abs(a.created_at - max_time) < 0.001]
                    if len(recent_candidates) == 1 and art.artifact_id == recent_candidates[0].artifact_id:
                        is_active = True
                if is_active:
                    score += 12.0
                    signals.append("pronoun_reference_match")

            # Signal 1: Explicit Topic Match (Strongest Signal)
            topic_low = art.topic.lower()
            subtopic_low = (art.subtopic or "").lower()

            if req_topic and (req_topic in topic_low or topic_low in req_topic or req_topic in subtopic_low):
                score += 15.0
                signals.append(f"topic_match:{art.topic}")
            elif any(part in low_text for part in topic_low.split() if len(part) >= 3):
                # Partial topic word match (e.g. "dbms", "sql", "normalization")
                score += 8.0
                signals.append(f"partial_topic:{art.topic}")

            # Signal 2: Content Type Match (Overrides recency)
            if req_type:
                if art.content_type == req_type:
                    score += 10.0
                    signals.append(f"type_match:{req_type}")
                else:
                    # Heavy penalty for wrong content type when user explicitly specified
                    score -= 12.0
                    signals.append(f"type_mismatch:{art.content_type}!= {req_type}")

            # Signal 3: Full Information / Root Resolution
            if req_full_info:
                if art.parent_id is None and art.content_type in ("information", "explanation"):
                    score += 10.0
                    signals.append("root_information_match")
                elif art.content_type == "summary":
                    score -= 8.0

            # Signal 4: Programming Language Match
            if req_lang and art.programming_language:
                if req_lang == art.programming_language.lower():
                    score += 6.0
                    signals.append(f"lang_match:{req_lang}")

            # Signal 5: Lineage / Transformation Match
            if req_lineage:
                if req_lineage == "original":
                    if art.parent_id is None:
                        score += 16.0
                        signals.append("lineage:original_root")
                    else:
                        score -= 10.0
                elif req_lineage == "previous_version":
                    # Check if art is the immediate parent of any other artifact in the graph
                    is_parent = any(other.parent_id == art.artifact_id for other in all_artifacts)
                    if is_parent:
                        score += 15.0
                        signals.append("lineage:previous_version")
                elif req_lineage == "translated":
                    if art.content_type == "translation" or any(h.get("operation") == "translate" for h in art.transformation_history):
                        score += 16.0
                        signals.append("lineage:translated_version")
                elif req_lineage == "code_ancestor":
                    if art.content_type == "code":
                        score += 16.0
                        signals.append("lineage:code_ancestor")
            elif req_type == "summary":
                if art.content_type == "summary" or any(h.get("operation") == "summarize" for h in art.transformation_history):
                    score += 6.0
                    signals.append("summary_lineage_match")

            # Signal 6: Contextual / Session Active Artifact
            if dialogue_state and hasattr(dialogue_state, "session_context"):
                last_id = dialogue_state.session_context.get("last_content_artifact_id")
                if last_id == art.artifact_id:
                    score += 2.0
                    signals.append("active_session_focus")

                # If dialogue mentions a topic lock
                topic_lock = dialogue_state.session_context.get("last_artifact_topic")
                if topic_lock and topic_lock.lower() in topic_low:
                    score += 3.0
                    signals.append("dialogue_topic_lock")

            # Signal 7: Recency (Micro tie-breaker only if at least one semantic signal matched)
            if signals:
                age_sec = max(0.1, now - art.created_at)
                recency_bonus = max(0.0, 1.5 - (age_sec / 3600.0))
                score += recency_bonus

            scored_candidates.append((art, score, signals))

        # Sort descending by score
        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        if not scored_candidates or scored_candidates[0][1] <= 0.0 or not scored_candidates[0][2]:
            # Fallback: if user asked using pure pronoun ("write it here", "put that here")
            # and no explicit type was given, resolve to active artifact
            if self._is_pure_pronoun(low_text):
                last_id = None
                if dialogue_state and hasattr(dialogue_state, "session_context"):
                    last_id = dialogue_state.session_context.get("last_content_artifact_id")
                art = self.graph.get_artifact(last_id) if last_id else (max(all_artifacts, key=lambda a: a.created_at) if all_artifacts else None)
                if art:
                    return ResolvedArtifact(
                        artifact=art,
                        confidence=0.85,
                        matched_signals=["pronoun_recency_fallback"],
                        rationale=f"Resolved demonstrative pronoun to active artifact '{art.topic}'."
                    )

            # No signals matched and not a pure pronoun -> return no match
            return ResolvedArtifact(
                artifact=None,
                confidence=0.0,
                is_ambiguous=False,
                candidate_artifacts=[],
                rationale="No matching artifact found for the query."
            )

        top_art, top_score, top_signals = scored_candidates[0]

        # Step 4: Check for Ambiguity Collision
        if len(scored_candidates) > 1:
            second_art, second_score, second_signals = scored_candidates[1]
            time_diff = abs(top_art.created_at - second_art.created_at)
            score_diff = abs(top_score - second_score)

            # If two distinct artifacts have virtually identical scores and no explicit topic
            if not req_topic and top_art.topic != second_art.topic:
                if time_diff < 0.001 and score_diff < 0.001:
                    action_verb = "read" if any(w in low_text for w in ("read", "listen", "speak", "recite")) else "write"
                    clarification = (
                        f"Which one would you like me to {action_verb}: the {top_art.topic} ({top_art.content_type}) "
                        f"or the {second_art.topic} ({second_art.content_type})?"
                    )
                    return ResolvedArtifact(
                        artifact=None,
                        confidence=0.45,
                        matched_signals=top_signals,
                        is_ambiguous=True,
                        clarification_prompt=clarification,
                        candidate_artifacts=[top_art, second_art],
                        rationale="Multiple artifacts matched the criteria with equal confidence."
                    )

        confidence = min(0.99, max(0.75, 0.70 + (top_score / 30.0)))
        return ResolvedArtifact(
            artifact=top_art,
            confidence=confidence,
            matched_signals=top_signals,
            is_ambiguous=False,
            candidate_artifacts=[top_art],
            rationale=f"Resolved '{top_art.topic}' ({top_art.content_type}) based on {', '.join(top_signals)}."
        )

    def _detect_requested_type(self, text: str) -> Optional[str]:
        """Detect if user explicitly specified a content type."""
        if any(w in text for w in ("the code", "that code", "this code", "write code", "the script", "the implementation", "python code", "last code")) or re.search(r'\b(?:the\s+)?(?:[a-zA-Z0-9_\-]+\s+)?code\b', text):
            return "code"
        if any(w in text for w in ("the summary", "that summary", "write the summary", "put the summary", "short version", "last summary")) or re.search(r'\b(?:the\s+)?(?:[a-zA-Z0-9_\-]+\s+)?summary\b', text):
            return "summary"
        if any(w in text for w in ("the notes", "those notes", "the bullet points", "last notes")) or re.search(r'\b(?:the\s+)?(?:[a-zA-Z0-9_\-]+\s+)?notes\b', text):
            return "notes"
        if any(w in text for w in ("the explanation", "that explanation")) or re.search(r'\b(?:the\s+)?(?:[a-zA-Z0-9_\-]+\s+)?explanation\b', text):
            return "explanation"
        if any(w in text for w in ("all the information", "all information", "the information", "that information", "the concept", "the theory", "what you gathered", "what you found", "last gathered content", "previous content")) or re.search(r'\b(?:the\s+)?(?:[a-zA-Z0-9_\-]+\s+)?information\b', text):
            return "information"
        return None

    def _detect_requested_topic(self, text: str) -> Optional[str]:
        """Extract domain or topic keywords from user reference."""
        if "dbms" in text or "normalization" in text:
            return "normalization"
        if "binary search" in text:
            return "binary search"
        if "linked list" in text or "linkedlist" in text:
            return "linked list"
        if "gradient descent" in text:
            return "gradient descent"
        if "machine learning" in text:
            return "machine learning"
        if "tcp" in text:
            return "tcp"
        if "bubble sort" in text:
            return "bubble sort"
        if "merge sort" in text:
            return "merge sort"
        if "quick sort" in text:
            return "quick sort"
        # Dynamic extraction for phrases like "read the X information", "read the X code"
        m_topic = re.search(r'\b(?:read|write|insert|put)\s+(?:all\s+the\s+|all\s+|the\s+)([a-zA-Z0-9_\-]+(?:\s+[a-zA-Z0-9_\-]+)*?)\s+(?:information|concept|code|summary|notes|details)\b', text)
        if m_topic:
            extracted = m_topic.group(1).strip()
            if extracted and extracted not in ("all", "entire", "whole", "complete", "first", "second", "third", "last", "latest", "the"):
                return extracted
        # Dynamic extraction for phrases like "information about [the] X", "information that you found about [the] X", "code for [the] X"
        m_topic_prep = re.search(r'\b(?:information|concept|code|summary|notes|details|explanation)\s+(?:that\s+you\s+(?:found|gathered|have|got|researched)\s+|you\s+(?:found|gathered|have|got|researched)\s+)?(?:about|for|of|on)\s+(?:the\s+)?([a-zA-Z0-9_\-]+(?:\s+[a-zA-Z0-9_\-]+)*?)(?:\s+(?:you\s+(?:found|form|gathered)|here|in\s+\w+|at\s+\w+))?$', text)
        if m_topic_prep:
            extracted = m_topic_prep.group(1).strip()
            if extracted and extracted not in ("all", "entire", "whole", "complete", "first", "second", "third", "last", "latest", "the"):
                return extracted
        return None

    def _detect_requested_language(self, text: str) -> Optional[str]:
        """Extract explicit programming language from text."""
        for lang in ("python", "javascript", "cpp", "c++", "java", "sql", "rust", "go"):
            if re.search(rf'\b{re.escape(lang)}\b', text):
                return "python" if lang in ("python", "py") else ("cpp" if lang in ("cpp", "c++") else lang)
        return None

    def _detect_ordinal_index(self, text: str) -> Optional[int]:
        """Detect ordinal references like 'the first one', 'the second code'."""
        if re.search(r'\b(?:the\s+)?first\s+(?:one|artifact|code|notes?|summary|doc|document|result)\b|\b1st\s+(?:one|artifact|code)\b|\bthe\s+first\b(?![-_\s]*(?:largest|smallest|highest|lowest|element|number|max|min|half|quarter|row|column|order|degree))', text, re.I):
            return 0
        if re.search(r'\b(?:the\s+)?second\s+(?:one|artifact|code|notes?|summary|doc|document|result)\b|\b2nd\s+(?:one|artifact|code)\b|\bthe\s+second\b(?![-_\s]*(?:largest|smallest|highest|lowest|element|number|max|min|half|quarter|row|column|order|degree))', text, re.I):
            return 1
        if re.search(r'\b(?:the\s+)?third\s+(?:one|artifact|code|notes?|summary|doc|document|result)\b|\b3rd\s+(?:one|artifact|code)\b|\bthe\s+third\b(?![-_\s]*(?:largest|smallest|highest|lowest|element|number|max|min|half|quarter|row|column|order|degree))', text, re.I):
            return 2
        return None

    def _detect_lineage_request(self, text: str) -> Optional[str]:
        """Detect explicit lineage or ancestry references."""
        if any(w in text for w in ("the original", "original version", "the root", "from the beginning", "use the original", "use original")):
            return "original"
        if any(w in text for w in ("the previous version", "previous version", "prior version", "before this version", "before this", "use the previous version", "use previous version")):
            return "previous_version"
        if any(w in text for w in ("the translated version", "the translation", "use the translated version", "use translated version", "translated version")):
            return "translated"
        if any(w in text for w in ("go back to the code", "back to the code", "return to the code")):
            return "code_ancestor"
        return None

    def _is_pure_pronoun(self, text: str) -> bool:
        """Check if reference consists only of generic pronouns without descriptive nouns."""
        words = set(re.findall(r'\b[a-zA-Z]+\b', text))
        generic_words = {
            "write", "type", "put", "paste", "insert", "read", "speak", "recite",
            "it", "that", "this", "them", "these", "those", "here", "where", "my", "cursor", "is", "please",
            "all", "of", "everything", "whole", "thing", "aloud", "out", "to", "me", "the",
            "in", "into", "at", "on", "notepad", "vscode", "file", "editor", "window",
            "app", "there", "can", "you", "could", "will", "would", "friday", "assistant",
            "what", "gathered", "found", "wrote", "inserted", "above", "previous", "content",
            "last"
        }
        return words.issubset(generic_words)


# Singleton instance
_artifact_resolver_instance: Optional[ArtifactReferenceResolver] = None

def get_artifact_resolver() -> ArtifactReferenceResolver:
    """Get the singleton ArtifactReferenceResolver instance."""
    global _artifact_resolver_instance
    if _artifact_resolver_instance is None:
        _artifact_resolver_instance = ArtifactReferenceResolver()
    return _artifact_resolver_instance

get_artifact_reference_resolver = get_artifact_resolver

