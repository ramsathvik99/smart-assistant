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

    # Explicit: "My name is X" / "My full name is X"
    m_my_name = re.search(r'\bmy\s+(?:full\s+)?name\s+is\s+([a-zA-Z\s]+?)(?:,\s*|\s+and\b|\.|$)', raw_text, re.IGNORECASE)
    if m_my_name:
        n_val = _clean_str(m_my_name.group(1))
        words = n_val.split()
        if 1 <= len(words) <= 4 and not any(w.lower() in _NON_NAME_WORDS for w in words):
            clean_name = " ".join(w.capitalize() for w in words)
            add_fact(ExtractedFact(
                key="name",
                value=clean_name,
                category="identity",
                confidence=0.99,
                status="confirmed",
                source_ref=raw_text
            ))
            add_fact(ExtractedFact(
                key="preferred_name",
                value=clean_name,
                category="identity",
                confidence=0.99,
                status="confirmed",
                source_ref=raw_text
            ))
            add_fact(ExtractedFact(
                key="full_name",
                value=clean_name,
                category="identity",
                confidence=0.99,
                status="confirmed",
                source_ref=raw_text
            ))

    # 10th School / Schooling: e.g. "I studied my 10th at Ongole Sai Baba Central School", "My 10th school is ..."
    m_10th = re.search(
        r'\b(?:i\s+(?:studied|did|completed|attended|went\s+to)\s+(?:my\s+)?(?:10th(?:\s+grade)?|tenth(?:\s+grade)?|schooling)|my\s+(?:10th|tenth)\s+(?:school\s+)?(?:was|is|=))\s+(?:at|in|from)?\s*([a-zA-Z0-9\s–\-]+?)(?:,\s*|\s+(?:and|where|but)\b|\.|$)',
        raw_text,
        re.IGNORECASE
    )
    if m_10th:
        s_val = _clean_str(m_10th.group(1))
        if s_val:
            add_fact(ExtractedFact(
                key="10th",
                value=s_val,
                category="education",
                confidence=0.98,
                status="confirmed",
                source_ref=raw_text
            ))
            add_fact(ExtractedFact(
                key="tenth",
                value=s_val,
                category="education",
                confidence=0.98,
                status="confirmed",
                source_ref=raw_text
            ))
            add_fact(ExtractedFact(
                key="tenth_school",
                value=s_val,
                category="education",
                confidence=0.98,
                status="confirmed",
                source_ref=raw_text
            ))
            add_fact(ExtractedFact(
                key="school",
                value=s_val,
                category="education",
                confidence=0.98,
                status="confirmed",
                source_ref=raw_text
            ))

    # Intermediate / Junior College: e.g. "I completed intermediate at Narayana Junior College in Nellore"
    m_inter = re.search(
        r'\b(?:i\s+(?:studied|did|completed|attended|went\s+to)\s+(?:my\s+)?(?:intermediate|inter|\+2|plus\s+two|junior\s+college)|my\s+(?:intermediate|inter)\s+(?:college\s+)?(?:was|is|=))\s+(?:at|in|from)?\s*([a-zA-Z0-9\s–\-]+?)(?:,\s*|\s+(?:and|where|but)\b|\.|$)',
        raw_text,
        re.IGNORECASE
    )
    if m_inter:
        i_val = _clean_str(m_inter.group(1))
        if i_val:
            add_fact(ExtractedFact(
                key="intermediate",
                value=i_val,
                category="education",
                confidence=0.98,
                status="confirmed",
                source_ref=raw_text
            ))
            add_fact(ExtractedFact(
                key="intermediate_college",
                value=i_val,
                category="education",
                confidence=0.98,
                status="confirmed",
                source_ref=raw_text
            ))
            add_fact(ExtractedFact(
                key="junior_college",
                value=i_val,
                category="education",
                confidence=0.98,
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

    # C. Institution / University / College (only if not an intermediate or 10th school statement)
    # e.g., "SRM AP student", "student at SRM University–AP", "studying at SRM AP", "My university is SRM AP"
    if not re.search(r'\b(?:intermediate|junior\s+college|inter\b|10th|tenth|schooling)\b', raw_text, re.IGNORECASE):
        m_univ_explicit = re.search(
            r'\b(?:my\s+)?(?:university|institution|campus)\s+(?:is|was|=)\s+([a-zA-Z0-9\s–\-]+?)(?:,\s*|\s+(?:and|where|but)\b|\.|$)',
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
    else:
        m_srm = re.search(r'\b(SRM\s*(?:University\s*[-–]\s*AP|University\s+AP|University|AP))\b', raw_text, re.IGNORECASE)
        if m_srm:
            srm_raw = m_srm.group(1).strip()
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
        # Embed a concrete ISO date for relative timings ("today"/"tomorrow") so
        # the milestone detector can date the event after the fact. Absolute
        # timings ("on April 15") are left as-is and parsed by month name.
        if "tomorrow" in ev_when:
            ev_val = f"{ev_type} {ev_when} ({(now + timedelta(days=1)).strftime('%Y-%m-%d')})"
        elif "today" in ev_when:
            ev_val = f"{ev_type} {ev_when} ({now.strftime('%Y-%m-%d')})"
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
    m_city = re.search(r'\b(?:i\s+live\s+in|i\s+am\s+from|i\'m\s+from)\s+([A-Z][a-zA-Z\s]+?)(?:,\s*|\s+(?:and|where)\b|\.|$)', raw_text, re.IGNORECASE)
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

    # J2. Age: "I am 21 years old", "I'm 21", "my age is 21", "I am 21-year-old"
    m_age = re.search(
        r'\b(?:i\s+am|i\'m|my\s+age\s+is)\s+(?:a\s+)?(\d{1,3})[- ]?(?:years?\s+old|yrs?\s+old|yo\b|year[- ]old\b)?',
        raw_text,
        re.IGNORECASE
    )
    if not m_age:
        m_age = re.search(
            r'\bage\s+(?:is\s+)?(\d{1,3})\b',
            raw_text,
            re.IGNORECASE
        )
    if m_age:
        age_val = m_age.group(1).strip()
        age_int = int(age_val)
        if 5 <= age_int <= 120:
            add_fact(ExtractedFact(
                key="age",
                value=age_val,
                category="identity",
                confidence=0.98,
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

    # ─────────────────────────────────────────────────────────────────────────
    # L. Birthday / Date-of-birth
    # e.g. "My birthday is April 14", "My DOB is 14 April 2005", "I was born on 1996-07-22"
    # ─────────────────────────────────────────────────────────────────────────
    m_dob = re.search(
        r'\b(?:my\s+(?:birthday|birth\s*day|date\s+of\s+birth|dob|birth\s+date)\s+is|'
        r'i\s+was\s+born\s+(?:on|in))\s+'
        r'([A-Za-z0-9,\s\-/]+?)(?:\.|,|$)',
        raw_text,
        re.IGNORECASE
    )
    if m_dob:
        dob_raw = _clean_str(m_dob.group(1))
        if dob_raw:
            add_fact(ExtractedFact(
                key="birthday",
                value=dob_raw,
                category="identity",
                confidence=0.99,
                status="confirmed",
                source_ref=raw_text
            ))
            add_fact(ExtractedFact(
                key="date_of_birth",
                value=dob_raw,
                category="identity",
                confidence=0.99,
                status="confirmed",
                source_ref=raw_text
            ))

    # ─────────────────────────────────────────────────────────────────────────
    # M. Graduation confirmed (lifecycle transition)
    # e.g. "I graduated last month", "I have graduated", "I graduated from SRM AP"
    # ─────────────────────────────────────────────────────────────────────────
    m_graduated = re.search(
        r'\bi\s+(?:have\s+)?(?:graduated|completed\s+my\s+degree|finished\s+my\s+(?:degree|graduation))'
        r'(?:\s+(?:from|at|in)\s+([a-zA-Z0-9\s–\-]+?))?(?:\.|,|\s+and\b|$)',
        raw_text,
        re.IGNORECASE
    )
    if m_graduated:
        inst_val = _clean_str(m_graduated.group(1)) if m_graduated.group(1) else "confirmed"
        add_fact(ExtractedFact(
            key="graduation_status",
            value="graduated",
            category="education",
            confidence=0.97,
            status="confirmed",
            source_ref=raw_text,
            supersedes_key="student_status"
        ))
        if inst_val and inst_val != "confirmed":
            add_fact(ExtractedFact(
                key="graduated_from",
                value=inst_val,
                category="education",
                confidence=0.97,
                status="confirmed",
                source_ref=raw_text
            ))

    # ─────────────────────────────────────────────────────────────────────────
    # N. Employment confirmed (lifecycle transition)
    # e.g. "I got a job at Google", "I got an offer from Microsoft", "I joined Amazon"
    # ─────────────────────────────────────────────────────────────────────────
    m_job_got = re.search(
        r'\bi\s+(?:got\s+(?:a\s+)?(?:job|offer|position)\s+(?:at|from|with)|'
        r'joined|am\s+now\s+working\s+at|started\s+working\s+at|am\s+employed\s+(?:at|by))\s+'
        r'([a-zA-Z0-9\s–\-]+?)(?:\.|,|\s+and\b|\s+as\b|$)',
        raw_text,
        re.IGNORECASE
    )
    if m_job_got:
        company_val = _clean_str(m_job_got.group(1))
        if company_val and len(company_val.split()) <= 5:
            add_fact(ExtractedFact(
                key="employer",
                value=company_val,
                category="employment",
                confidence=0.97,
                status="confirmed",
                source_ref=raw_text,
                supersedes_key="goal"
            ))
            add_fact(ExtractedFact(
                key="employment_status",
                value="employed",
                category="employment",
                confidence=0.97,
                status="confirmed",
                source_ref=raw_text
            ))

    # "I am still looking for a job / I am still in a job search"
    m_job_search = re.search(
        r'\bi\s+am\s+still\s+(?:looking\s+for\s+a\s+job|job\s+searching|in\s+a\s+job\s+search|applying)',
        raw_text,
        re.IGNORECASE
    )
    if m_job_search:
        add_fact(ExtractedFact(
            key="employment_status",
            value="job_searching",
            category="employment",
            confidence=0.95,
            status="confirmed",
            source_ref=raw_text
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # O. Travel / Trip dates
    # e.g. "I'm traveling to Paris on December 10", "My flight is on Dec 15"
    # ─────────────────────────────────────────────────────────────────────────
    m_travel = re.search(
        r'\b(?:i\'m\s+(?:traveling|flying|going)\s+to\s+(?:[a-zA-Z\s]+?)\s+on|'
        r'my\s+(?:flight|trip|travel|departure)\s+is\s+(?:on\s+)?)\s*'
        r'([A-Za-z0-9,\s]+?)(?:\.|,|$)',
        raw_text,
        re.IGNORECASE
    )
    if m_travel:
        travel_date_raw = _clean_str(m_travel.group(1))
        if travel_date_raw:
            add_fact(ExtractedFact(
                key="travel_date",
                value=travel_date_raw,
                category="commitments",
                confidence=0.90,
                status="confirmed",
                expiration_date=datetime.now() + timedelta(days=60),
                source_ref=raw_text
            ))

    # ─────────────────────────────────────────────────────────────────────────
    # P. Subscription / Payment renewal
    # e.g. "My Netflix subscription renews on January 5"
    # ─────────────────────────────────────────────────────────────────────────
    m_subscription = re.search(
        r'\bmy\s+([a-zA-Z0-9\s]+?)\s+(?:subscription|membership|renewal|bill)\s+'
        r'(?:renews?|is\s+due|expires?)\s+(?:on\s+)?([A-Za-z0-9,\s]+?)(?:\.|,|$)',
        raw_text,
        re.IGNORECASE
    )
    if m_subscription:
        sub_name = _clean_str(m_subscription.group(1))
        sub_date = _clean_str(m_subscription.group(2))
        if sub_name and sub_date:
            key_name = f"subscription_{sub_name.lower().replace(' ', '_')}_renewal"
            add_fact(ExtractedFact(
                key=key_name,
                value=sub_date,
                category="commitments",
                confidence=0.90,
                status="confirmed",
                source_ref=raw_text
            ))

    # ─────────────────────────────────────────────────────────────────────────
    # Q. Certification / document expiry
    # e.g. "My AWS certification expires in March 2025"
    # ─────────────────────────────────────────────────────────────────────────
    m_cert = re.search(
        r'\bmy\s+([a-zA-Z0-9\s]+?)\s+(?:certification|certificate|license|passport|visa)\s+'
        r'(?:expires?|is\s+valid\s+until|valid\s+till)\s+(?:in\s+|on\s+)?([A-Za-z0-9,\s]+?)(?:\.|,|$)',
        raw_text,
        re.IGNORECASE
    )
    if m_cert:
        cert_name = _clean_str(m_cert.group(1))
        cert_date = _clean_str(m_cert.group(2))
        if cert_name and cert_date:
            key_name = f"certification_{cert_name.lower().replace(' ', '_')}_expiry"
            add_fact(ExtractedFact(
                key=key_name,
                value=cert_date,
                category="commitments",
                confidence=0.90,
                status="confirmed",
                source_ref=raw_text
            ))

    # ─────────────────────────────────────────────────────────────────────────
    # R. "I no longer want X reminders" — explicit opt-out preference
    # ─────────────────────────────────────────────────────────────────────────
    m_no_remind = re.search(
        r'\bi\s+(?:no\s+longer\s+want|don\'t\s+want|do\s+not\s+want)\s+'
        r'([a-zA-Z0-9\s]+?)\s+reminders?\b',
        raw_text,
        re.IGNORECASE
    )
    if m_no_remind:
        remind_topic = _clean_str(m_no_remind.group(1)).lower().replace(" ", "_")
        if remind_topic:
            add_fact(ExtractedFact(
                key=f"opt_out_{remind_topic}_reminders",
                value="true",
                category="preferences",
                confidence=0.98,
                status="confirmed",
                source_ref=raw_text
            ))

    # ─────────────────────────────────────────────────────────────────────────
    # S. "I plan to X" — explicit future plan (status=planned)
    # e.g. "I plan to take an exam next year", "I plan to join Google in July"
    # ─────────────────────────────────────────────────────────────────────────
    m_plan = re.search(
        r'\bi\s+plan\s+to\s+([a-zA-Z0-9\s]+?)(?:\s+(?:next|in|on|by|before|after)\s+[a-zA-Z0-9,\s]+)?(?:\.|,|$)',
        raw_text,
        re.IGNORECASE
    )
    if m_plan and not m_tentative:  # avoid duplicate with tentative pattern above
        plan_desc = _clean_str(m_plan.group(1))
        if 1 <= len(plan_desc.split()) <= 8:
            add_fact(ExtractedFact(
                key="planned_event",
                value=plan_desc,
                category="goals",
                confidence=0.88,
                status="tentative",  # Plans are not confirmed until executed
                source_ref=raw_text
            ))

    # ─────────────────────────────────────────────────────────────────────────
    # T. Interview outcome response (post follow-up, outcome unknown -> known)
    # These are answers to a "How did your interview go?" follow-up. Each outcome
    # records a distinct consequence: an offer updates employment, a rejection
    # closes the event, a postponement moves the date (or stays tentative if the
    # new date is unknown), "attended" records participation without inventing a
    # result, and "went well" records the user's own impression only. The stale
    # 'commitment' fact is superseded so the dated commitment stops driving the
    # milestone engine and follow-ups do not repeat once the outcome is known.
    #
    # Gate: an offer is recognized even without the word "interview" ("I got the
    # offer from Google"), because a bare offer announcement must still confirm
    # employment. Rejection / postponement / attended / not-attended only run when
    # "interview" appears in the text, so e.g. "the flight was postponed" or "I was
    # rejected by the university" (admissions, not a job) are never misread as an
    # interview outcome.
    #
    # The offer rule requires explicit hiring context: the offer noun tied to a
    # company or to the interview ("offer from Google", "offer for the interview"),
    # the fixed compounds "job offer" / "offer letter", or a hiring verb. A bare
    # "offer"/"placement" carrying an unrelated complement ("an offer on the house",
    # "the placement drive", "a hackathon offer") is NOT a job outcome and must
    # never mark the user employed.
    # ──────────────────────────────────────────────────────────────────────────
    _offer_only = re.search(
        r'\b(?:'
        r'job\s+offer\b'
        r'|offer\s+letter\b'
        r'|(?:got|received|landed|accepted|signed|bagged)\b[^.]*?'
        r'\boffer\b\s*(?:(?:from|at|with)\b|for\s+(?:the\s+)?interview\b)'
        r'|(?:got|was|were|been|am)\s+hired\b'
        r')',
        raw_text, re.IGNORECASE
    )
    if _offer_only or "interview" in text_lower:
        outcome = None
        company = None

        # Postponement carries an optional new day ("to Monday", "to May 5").
        m_postpone = re.search(
            r'\b(?:postponed|rescheduled|moved|pushed)(?:\s+(?:the\s+)?interview)?\s+'
            r'(?:to|until|by)\s+(?:next\s+)?([a-zA-Z0-9,\s]{1,30})',
            raw_text, re.IGNORECASE
        )
        if m_postpone:
            outcome = "postponed"
            company = _clean_str(m_postpone.group(1))
        else:
            # "not attended" must be evaluated BEFORE the positive "attended"
            # pattern, otherwise "I have not attended" matches "attended" as a
            # substring and is misclassified as a completed interview.
            m_not_attended = re.search(
                r'\b(?:have|had)?\s*not\s+(?:yet\s+)?attended\b|'
                r'\bhaven\'?t\s+(?:attended|yet\s+attended)\b|'
                r'\bdidn\'?t\s+attend\b|\bdid\s+not\s+attend\b',
                raw_text, re.IGNORECASE
            )
            if m_not_attended:
                outcome = "not_attended"

            if not outcome:
                # Offer: require the success verb and an offer/placement noun in the
                # same clause. Company is captured only when it immediately follows
                # "from"/"at" (e.g. "got the offer from Google"), so trailing
                # clauses like "for the interview" are never misread as a company.
                if _offer_only:
                    outcome = "offer_received"
                    m_company = re.search(
                        r'\b(?:from|at)\s+([A-Z][A-Za-z0-9.&–\-]{1,30})',
                        raw_text
                    )
                    if m_company:
                        company = _clean_str(m_company.group(1)).strip()

            if not outcome and re.search(r'\b(?:was|were|they|i\s+am)\s+not\s+(?:selected|chosen|shortlisted)\b|\brejected\b|\bgot\s+rejected\b|\bdidn\'?t\s+(?:get\s+)?(?:selected|crack|clear)\b', raw_text, re.IGNORECASE):
                outcome = "rejected"

            if not outcome and re.search(
                r'\b(?:i\s+)?(?:attended|completed|gave|took|finished)\s+(?:the\s+|my\s+)?interview\b|'
                r'\binterview\s+(?:went\s+well|was\s+(?:good|great|excellent|smooth|positive))\b',
                raw_text, re.IGNORECASE
            ):
                # "attended" records participation only. "went well" is the
                # user's impression and must NOT invent an offer or result.
                outcome = "attended"

        if outcome:
            # 1. Record the interview outcome (no expiration: the result is durable).
            add_fact(ExtractedFact(
                key="interview_outcome",
                value=outcome,
                category="commitments",
                confidence=0.96,
                status="confirmed",
                source_ref=raw_text
            ))

            # 2. An offer confirms employment and supersedes the job-search goal.
            #    A rejection or postponement must NOT imply the user got a job.
            if outcome == "offer_received":
                add_fact(ExtractedFact(
                    key="employment_status",
                    value="employed",
                    category="employment",
                    confidence=0.95,
                    status="confirmed",
                    source_ref=raw_text,
                    supersedes_key="employment_status"  # replaces job_searching if present
                ))
                if company:
                    add_fact(ExtractedFact(
                        key="employer",
                        value=company,
                        category="employment",
                        confidence=0.95,
                        status="confirmed",
                        source_ref=raw_text,
                        supersedes_key="goal"
                    ))

            # 3. Close the dated commitment: a final outcome (offer/rejected/attended)
            #    supersedes the 'commitment' fact so the milestone engine stops
            #    generating INTERVIEW/INTERVIEW_FOLLOWUP for it. Postponement keeps
            #    the commitment active; not-attended leaves it pending.
            if outcome in ("offer_received", "rejected", "attended"):
                add_fact(ExtractedFact(
                    key="commitment",
                    value=f"interview {outcome}",
                    category="commitments",
                    confidence=0.96,
                    status="confirmed",
                    source_ref=raw_text
                ))

    return facts
