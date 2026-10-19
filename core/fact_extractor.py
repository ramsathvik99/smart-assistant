"""
Deterministic Automatic Fact Extraction Engine for Friday / Smart Assistant.

Extracts candidate memories from ordinary natural conversation in categories:
- Identity and background
- Education and employment
- Interests and preferences
- Goals and plans
- Active projects and technical decisions
- Recurring routines and constraints
- Important commitments and deadlines (with temporal expiration)
- Explicit corrections to previously stored facts

Distinguishes confirmed facts from tentative thoughts, and ignores ephemeral commands,
small talk, questions, and sensitive secrets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any


@dataclass
class ExtractedFact:
    """A structured factual candidate extracted from conversation."""
    key: str
    value: str
    category: str  # identity, education, employment, preferences, goals, projects, routines, commitments, corrections, general
    confidence: float = 0.95
    status: str = "confirmed"  # confirmed, tentative, superseded
    expiration_date: Optional[datetime] = None
    source_ref: str = ""
    supersedes_key: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "category": self.category,
            "confidence": self.confidence,
            "status": self.status,
            "expiration_date": self.expiration_date.isoformat() if self.expiration_date else None,
            "source_ref": self.source_ref,
            "supersedes_key": self.supersedes_key,
        }


# Emotional states, temporary adjectives, and common non-name words after "I'm / I am"
_NON_NAME_WORDS = {
    "tired", "bored", "happy", "sad", "here", "back", "fine", "ok", "okay",
    "ready", "done", "busy", "sorry", "good", "great", "interested", "sure",
    "trying", "thinking", "asking", "looking", "working", "going", "wondering",
    "using", "testing", "planning", "hoping", "afraid", "curious", "excited",
    "not", "just", "also", "still", "always", "now", "listening", "speaking",
    "reading", "writing", "coding", "debugging", "learning", "running", "feeling"
}

_STOP_WORDS_END = {".", "!", "?", ",", ";"}


def _clean_str(val: str) -> str:
    """Trim and clean trailing punctuation."""
    if not val:
        return ""
    v = val.strip()
    while v and v[-1] in _STOP_WORDS_END:
        v = v[:-1].strip()
    return v


def _is_sensitive_secret(text: str) -> bool:
    """Detect passwords, PINs, tokens, and credentials that must not be stored."""
    t = text.lower()
    patterns = [
        r'\b(?:my\s+)?(?:secret\s+)?(?:pin|password|passcode|passphrase|token|api[_\s]key|credit[_\s]card|cvv|credentials?)\b',
        r'\b(?:pin|password|secret)\s+is\s+[a-zA-Z0-9_\-@#$%^&*!]+',
    ]
    for p in patterns:
        if re.search(p, t):
            return True
    return False


def _is_ephemeral_or_smalltalk(text: str) -> bool:
    """Filter out pure small talk and system commands that contain no personal facts."""
    t = text.lower().strip().rstrip(".!?")
    # Exact smalltalk phrases
    smalltalk = {
        "hello", "hi", "hey", "hey friday", "hello friday", "hi friday", "good morning",
        "good afternoon", "good evening", "good night", "how are you", "how are you doing",
        "how do you feel", "how's it going", "how is it going", "thanks", "thank you",
        "thanks a lot", "bye", "goodbye", "see you", "see ya", "ok", "okay", "cool",
        "great", "nice", "awesome", "perfect", "sounds good", "yes", "no", "yep", "nope",
        "sure", "alright", "all right", "never mind", "nevermind", "stop", "cancel", "clear"
    }
    if t in smalltalk:
        return True

    # Pure operational desktop commands
    if re.match(r'^(?:open|launch|close|quit|play|pause|resume|turn\s+on|turn\s+off|delete|remove|create\s+folder|screenshot|capture)\s+[a-zA-Z0-9_\s\.\-]+$', t):
        return True

    return False


def extract_candidate_facts(text: str) -> List[ExtractedFact]:
    """
    Deterministically extract candidate facts from ordinary conversational text.
    Handles compound sentences, multiple facts in a single utterance,
    and returns high-confidence ExtractedFact objects.
    """
    if not text or not str(text).strip():
        return []

    raw_text = text.strip()
    text_clean = raw_text.rstrip(".!?")
    text_lower = text_clean.lower()

    # Guard: sensitive secrets
    if _is_sensitive_secret(raw_text):
        return []

    # Guard: pure smalltalk or operational command without personal context
    if _is_ephemeral_or_smalltalk(raw_text):
        return []

    # Guard: questions that do NOT contain declarative personal context
    # E.g. "What time is it?" -> False.
    # But "Since I'm at SRM AP, what courses should I take?" -> Has declarative personal fact!
    if raw_text.endswith("?"):
        has_intro_declarative = any(p in text_lower for p in (
            "since i'm", "since i am", "as a student", "given that i", "now that i"
        ))
        if not has_intro_declarative:
            # If purely an interrogative without declarative clause, return empty
            if any(text_lower.startswith(q) for q in (
                "what", "who", "which", "where", "when", "why", "how", "can you",
                "could you", "do you", "is it", "are there", "tell me what", "tell me how"
            )):
                return []

    facts: List[ExtractedFact] = []
    seen_keys: set = set()

    def add_fact(fact: ExtractedFact):
        if not fact.key or not fact.value:
            return
        # Avoid duplicate keys within same extraction pass unless different category
        dedup_id = f"{fact.category}:{fact.key}"
        if dedup_id not in seen_keys:
            seen_keys.add(dedup_id)
            facts.append(fact)

    # ──────────────────────────────────────────────────────────────────────────
    # 1. COMPOUND PATTERNS: e.g. "I'm Ram, a final-year SRM AP student, and I'm in the placement cell."
    # ──────────────────────────────────────────────────────────────────────────

    # A. Preferred Name & Identity
    # Match: "I'm Ram", "I am Ram", "My name is Ram", "Call me Ram"
    m_name = re.search(
        r'\b(?:i\'m|i\s+am|my\s+name\s+is|call\s+me)\s+([A-Z][a-zA-Z]+)(?:,\s*|\s+(?:and|a|an|the|who|from|at|in|with|studying|working)\b|\.|$|!)',
        raw_text
    )
    if not m_name:
        m_name = re.search(
            r'^(?:i\'m|i\s+am)\s+([a-zA-Z]+)(?:,\s*|\s+(?:and|a|an|the|who|from|at|in|with|studying|working)\b|\.|$|!)',
            raw_text,
            re.IGNORECASE
        )
    if m_name:
        candidate_name = _clean_str(m_name.group(1))
        if candidate_name.lower() not in _NON_NAME_WORDS and len(candidate_name) >= 2:
            norm_name = candidate_name.capitalize()
            add_fact(ExtractedFact(
                key="name",
                value=norm_name,
                category="identity",
                confidence=0.98,
                status="confirmed",
                source_ref=raw_text
            ))
            add_fact(ExtractedFact(
                key="preferred_name",
                value=norm_name,
                category="identity",
                confidence=0.98,
                status="confirmed",
                source_ref=raw_text
            ))

    # Explicit: "My name is X"
    m_my_name = re.search(r'\bmy\s+name\s+is\s+([a-zA-Z\s]+?)(?:,\s*|\s+and\b|\.|$)', raw_text, re.IGNORECASE)
    if m_my_name:
        n_val = _clean_str(m_my_name.group(1))
        words = n_val.split()
        if 1 <= len(words) <= 3 and not any(w.lower() in _NON_NAME_WORDS for w in words):
            clean_name = " ".join(w.capitalize() for w in words)
            add_fact(ExtractedFact(
                key="name",
                value=clean_name,
                category="identity",
                confidence=0.99,
                status="confirmed",
                source_ref=raw_text
            ))

    # B. Education & Student Status: Year and Degree
    # e.g., "final-year ... student", "in third year", "studying CSE"
    m_yr = re.search(
        r'\b((?:final|first|second|third|fourth|1st|2nd|3rd|4th)(?:-|\s+)?year)\s+(?:[a-zA-Z0-9\s–\-]+?\s+)?student\b',
        raw_text,
        re.IGNORECASE
    )
    if m_yr:
        raw_yr = m_yr.group(1).lower().replace(" ", "-")
        std_yr = f"{raw_yr} student"
        add_fact(ExtractedFact(
            key="education",
            value=std_yr,
            category="education",
            confidence=0.95,
            status="confirmed",
            source_ref=raw_text
        ))
        add_fact(ExtractedFact(
            key="student_status",
            value=std_yr,
            category="education",
            confidence=0.95,
            status="confirmed",
            source_ref=raw_text
        ))
    elif re.search(r'\b(?:i\'m\s+a|i\s+am\s+a)\s+student\b', raw_text, re.IGNORECASE):
        add_fact(ExtractedFact(
            key="education",
            value="student",
            category="education",
            confidence=0.90,
            status="confirmed",
            source_ref=raw_text
        ))

    # Academic Year update: "I'm in third year", "I'm now in final year"
    m_year_now = re.search(
        r'\b(?:i\'m|i\s+am)\s+(?:now\s+)?in\s+(?:my\s+)?(final|first|second|third|fourth|1st|2nd|3rd|4th)\s+year\b',
        raw_text,
        re.IGNORECASE
    )
    if m_year_now:
        y_name = m_year_now.group(1).lower()
        full_yr_val = f"{y_name}-year student"
        add_fact(ExtractedFact(
            key="education",
            value=full_yr_val,
            category="education",
            confidence=0.95,
            status="confirmed",
            source_ref=raw_text
        ))
        add_fact(ExtractedFact(
            key="student_status",
            value=full_yr_val,
            category="education",
            confidence=0.95,
            status="confirmed",
            source_ref=raw_text
        ))

    # C. Institution / University / College
    # e.g., "SRM AP student", "student at SRM University–AP", "studying at SRM AP", "My university is SRM AP"
    m_univ_explicit = re.search(
        r'\b(?:my\s+)?(?:university|college|institution|campus|school)\s+(?:is|was|=)\s+([a-zA-Z0-9\s–\-]+?)(?:,\s*|\s+(?:and|where|but)\b|\.|$)',
        raw_text,
        re.IGNORECASE
    )
    if m_univ_explicit:
        u_val = _clean_str(m_univ_explicit.group(1))
        if len(u_val.split()) <= 6:
            add_fact(ExtractedFact(
                key="institution",
                value=u_val,
                category="education",
                confidence=0.98,
                status="confirmed",
                source_ref=raw_text
            ))
            add_fact(ExtractedFact(
                key="university",
                value=u_val,
                category="education",
                confidence=0.98,
                status="confirmed",
                source_ref=raw_text
            ))

    # Recognizer for known or standard university expressions in conversational clauses
    # e.g. "SRM AP", "SRM University-AP", "SRM University–AP", "IIT Madras", "Stanford"
    m_srm = re.search(r'\b(SRM\s*(?:University\s*[-–]\s*AP|University\s+AP|University|AP))\b', raw_text, re.IGNORECASE)
    if m_srm:
        srm_raw = m_srm.group(1).strip()
        # Canonicalize to the official institution name
        inst_name = "SRM University–AP" if "ap" in srm_raw.lower() else "SRM University"
        add_fact(ExtractedFact(
            key="institution",
            value=inst_name,
            category="education",
            confidence=0.95,
            status="confirmed",
            source_ref=raw_text
        ))
        add_fact(ExtractedFact(
            key="university",
            value=inst_name,
            category="education",
            confidence=0.95,
            status="confirmed",
            source_ref=raw_text
        ))
    else:
        m_at_inst = re.search(
            r'\b(?:at|attending|studying\s+at)\s+((?:IIT|NIT|BITS|IIIT|IIM|MIT|Stanford|Harvard|Oxford|Cambridge)(?:\s+[A-Z][a-zA-Z0-9]+)?|[A-Z][a-zA-Z0-9\s–\-]+?(?:University|College|Institute|Campus|Academy))\b',
            raw_text
        )
        if m_at_inst:
            inst_val = _clean_str(m_at_inst.group(1))
            add_fact(ExtractedFact(
                key="institution",
                value=inst_val,
                category="education",
                confidence=0.95,
                status="confirmed",
                source_ref=raw_text
            ))
            add_fact(ExtractedFact(
                key="university",
                value=inst_val,
                category="education",
                confidence=0.95,
                status="confirmed",
                source_ref=raw_text
            ))

    # Major / Department: e.g. "studying CSE", "CSE student"
    _INST_ACRONYMS = {"AP", "SRM", "IIT", "NIT", "BITS", "MIT", "VIT", "IIIT", "DU", "JNU", "VTU", "ANNA"}
    m_major = re.search(
        r'\b(?:studying\s+|majoring\s+in\s+)([A-Z]{2,4}|computer\s+science(?:[a-zA-Z\s]+)?|data\s+science|mechanical|electrical|electronics|civil|biotech)\b',
        raw_text,
        re.IGNORECASE
    )
    if not m_major:
        m_major = re.search(
            r'\b([A-Z]{2,4}|computer\s+science|data\s+science)\s+student\b',
            raw_text,
            re.IGNORECASE
        )
    if m_major:
        raw_maj = m_major.group(1).strip()
        if raw_maj.upper() not in _INST_ACRONYMS:
            maj_val = raw_maj.upper() if len(raw_maj) <= 4 else raw_maj.title()
            add_fact(ExtractedFact(
                key="major",
                value=maj_val,
                category="education",
                confidence=0.95,
                status="confirmed",
                source_ref=raw_text
            ))

    # D. Activities, Organizations, and Roles
    # e.g., "I'm in the placement cell", "member of the placement cell", "president of X"
    m_cell = re.search(
        r'\b(?:i\'m\s+|i\s+am\s+)?(?:in|part\s+of|a\s+member\s+of)\s+the\s+([a-zA-Z0-9_\s]+?\s+(?:cell|team|club|society|committee|council|board|department))\b',
        raw_text,
        re.IGNORECASE
    )
    if m_cell:
        cell_name = _clean_str(m_cell.group(1)).lower()
        role_val = f"member of the {cell_name}"
        add_fact(ExtractedFact(
            key="activity",
            value=role_val,
            category="employment",
            confidence=0.95,
            status="confirmed",
            source_ref=raw_text
        ))
        add_fact(ExtractedFact(
            key="role",
            value=role_val,
            category="employment",
            confidence=0.95,
            status="confirmed",
            source_ref=raw_text
        ))

    # E. Preferences
    # e.g., "I usually prefer short explanations", "I prefer concise answers"
    m_pref_expl = re.search(
        r'\bi\s+(?:usually\s+)?prefer\s+([a-zA-Z0-9_\s]+?)\s+(?:explanations?|answers?|responses?|replies)\b',
        raw_text,
        re.IGNORECASE
    )
    if m_pref_expl:
        pref_style = _clean_str(m_pref_expl.group(1)).lower()
        if "concise" in pref_style or "short" in pref_style or "brief" in pref_style:
            pref_style = "concise"
        add_fact(ExtractedFact(
            key="response_style",
            value=pref_style,
            category="preferences",
            confidence=0.95,
            status="confirmed",
            source_ref=raw_text
        ))
        add_fact(ExtractedFact(
            key="explanation_preference",
            value=pref_style,
            category="preferences",
            confidence=0.95,
            status="confirmed",
            source_ref=raw_text
        ))
    elif re.search(r'\bi\s+(?:usually\s+)?prefer\s+([a-zA-Z0-9_\s]+?)(?:,\s*|\s+(?:and|because|when)\b|\.|$)', raw_text, re.IGNORECASE):
        m_gen_pref = re.search(r'\bi\s+(?:usually\s+)?prefer\s+([a-zA-Z0-9_\s]+?)(?:,\s*|\s+(?:and|because|when)\b|\.|$)', raw_text, re.IGNORECASE)
        val_pref = _clean_str(m_gen_pref.group(1))
        if 1 <= len(val_pref.split()) <= 4:
            add_fact(ExtractedFact(
                key="preference",
                value=val_pref,
                category="preferences",
                confidence=0.90,
                status="confirmed",
                source_ref=raw_text
            ))

    # F. Goals & Plans (with Tentative vs Confirmed Distinction)
    # e.g. "I'm currently applying for internships", "I might apply for an internship"
    m_tentative = re.search(
        r'\bi\s+(?:might|may|could\s+possibly|am\s+thinking\s+of|am\s+thinking\s+about)\s+([a-zA-Z0-9_\s]+?)(?:,\s*|\.|$)',
        raw_text,
        re.IGNORECASE
    )
    if m_tentative:
        plan_val = _clean_str(m_tentative.group(1))
        if 1 <= len(plan_val.split()) <= 8:
            add_fact(ExtractedFact(
                key="tentative_plan",
                value=plan_val,
                category="goals",
                confidence=0.75,
                status="tentative",
                source_ref=raw_text
            ))
    else:
        m_goal = re.search(
            r'\bi\'m\s+(?:currently\s+)?applying\s+for\s+([a-zA-Z0-9_\s]+?)(?:,\s*|\s+(?:and|at)\b|\.|$)',
            raw_text,
            re.IGNORECASE
        )
        if m_goal:
            appl_val = f"applying for {_clean_str(m_goal.group(1))}"
            add_fact(ExtractedFact(
                key="goal",
                value=appl_val,
                category="goals",
                confidence=0.95,
                status="confirmed",
                source_ref=raw_text
            ))
            add_fact(ExtractedFact(
                key="career_goal",
                value=appl_val,
                category="goals",
                confidence=0.95,
                status="confirmed",
                source_ref=raw_text
            ))

    # G. Project Decisions & Technical Stack
    # e.g. "We decided to use PostgreSQL for this project", "The backend for this project is Python"
    m_proj_dec = re.search(
        r'\b(?:we\s+decided\s+to\s+use|we\'re\s+using|we\s+are\s+using|using)\s+([a-zA-Z0-9_\s]+?)\s+(?:for\s+this\s+project|as\s+(?:the\s+)?database|as\s+(?:the\s+)?backend|as\s+(?:the\s+)?frontend)\b',
        raw_text,
        re.IGNORECASE
    )
    if m_proj_dec:
        tech_val = _clean_str(m_proj_dec.group(1))
        t_low = text_lower
        key_name = "database" if any(w in t_low for w in ["database", "postgres", "db", "sql", "mongo"]) else ("backend" if "backend" in t_low else "project_technology")
        add_fact(ExtractedFact(
            key=key_name,
            value=tech_val,
            category="projects",
            confidence=0.95,
            status="confirmed",
            source_ref=raw_text
        ))
    else:
        m_db_explicit = re.search(
            r'\b(?:the\s+)?database\s+(?:for\s+this\s+project\s+)?(?:is|was|=)\s+([a-zA-Z0-9_\s]+)',
            raw_text,
            re.IGNORECASE
        )
        if m_db_explicit:
            db_val = _clean_str(m_db_explicit.group(1))
            if 1 <= len(db_val.split()) <= 3:
                add_fact(ExtractedFact(
                    key="database",
                    value=db_val,
                    category="projects",
                    confidence=0.98,
                    status="confirmed",
                    source_ref=raw_text
                ))

    # H. Explicit Corrections
    # e.g. "Actually, I changed my mind. Use the existing router.", "Actually, my university is SRM AP"
    m_corr = re.search(
        r'\bactually,?\s+(?:i\s+changed\s+my\s+mind\.?\s+)?(?:use|switch\s+to)\s+(?:the\s+)?([a-zA-Z0-9_\s]+)',
        raw_text,
        re.IGNORECASE
    )
    if m_corr:
        corr_val = f"use {_clean_str(m_corr.group(1))}"
        add_fact(ExtractedFact(
            key="decision",
            value=corr_val,
            category="corrections",
            confidence=0.98,
            status="confirmed",
            source_ref=raw_text
        ))

    # I. Temporary Events & Deadlines (with Expiration Dates)
    # e.g. "My interview is tomorrow", "The deadline is Friday"
    m_interview = re.search(
        r'\bmy\s+((?:[a-zA-Z0-9_\s]+?\s+)?(?:interview|exam|presentation|meeting|test|deadline))\s+is\s+(tomorrow|today|on\s+[a-zA-Z]+|\d{1,2}(?:st|nd|rd|th)?\s+[a-zA-Z]+)\b',
        raw_text,
        re.IGNORECASE
    )
    if m_interview:
        ev_type = _clean_str(m_interview.group(1)).lower()
        ev_when = _clean_str(m_interview.group(2)).lower()
        now = datetime.now()
        if "tomorrow" in ev_when:
            exp_date = now + timedelta(days=2)
        elif "today" in ev_when:
            exp_date = now + timedelta(days=1)
        else:
            exp_date = now + timedelta(days=7)

        ev_val = f"{ev_type} {ev_when}"
        add_fact(ExtractedFact(
            key="commitment",
            value=ev_val,
            category="commitments",
            confidence=0.95,
            status="confirmed",
            expiration_date=exp_date,
            source_ref=raw_text
        ))

    # J. Location / City: "I live in X", "I am from X"
    m_city = re.search(r'\b(?:i\s+live\s+in|i\s+am\s+from|i\'m\s+from)\s+([A-Z][a-zA-Z\s]+?)(?:,\s*|\s+(?:and|where)\b|\.|$)', raw_text)
    if m_city:
        city_val = _clean_str(m_city.group(1))
        if len(city_val.split()) <= 3 and city_val.lower() not in _NON_NAME_WORDS:
            add_fact(ExtractedFact(
                key="city",
                value=city_val,
                category="identity",
                confidence=0.95,
                status="confirmed",
                source_ref=raw_text
            ))

    # K. Favorites: "my favorite X is Y"
    m_fav = re.search(r'\bmy\s+favou?rite\s+(\w+)\s+is\s+([a-zA-Z0-9\s]+?)(?:,\s*|\s+and\b|\.|$)', raw_text, re.IGNORECASE)
    if m_fav:
        f_item = _clean_str(m_fav.group(1)).lower()
        f_val = _clean_str(m_fav.group(2))
        if 1 <= len(f_val.split()) <= 5:
            add_fact(ExtractedFact(
                key=f"favorite_{f_item}",
                value=f_val,
                category="preferences",
                confidence=0.98,
                status="confirmed",
                source_ref=raw_text
            ))

    return facts
