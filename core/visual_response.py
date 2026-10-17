"""
Smart Assistant — Visual Response Surface & Ephemeral Information Panel
Core data model, detection rules, and formatting for visual presentations.

Enables the assistant to provide visual presentation when information
is substantially easier to consume visually (codes, IP addresses, paths, lists, etc.)
or when explicitly requested by the user ("show me the pairing code", "show that again").

Follows strict user isolation, contextual freshness, and never regenerates
or recomputes on "show that again".
"""

import re
import time
import uuid
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Union, Tuple, Set, Callable


class VisualResponseType(str, Enum):
    """Supported types for structured visual presentation."""
    TEXT = "TEXT"
    KNOWLEDGE = "KNOWLEDGE"
    CODE = "CODE"
    PAIRING_CODE = "PAIRING_CODE"
    VERIFICATION_CODE = "VERIFICATION_CODE"
    IP_ADDRESS = "IP_ADDRESS"
    URL = "URL"
    FILE_PATH = "FILE_PATH"
    LIST = "LIST"
    TABLE = "TABLE"
    STATUS = "STATUS"
    ERROR = "ERROR"
    SEARCH_RESULT = "SEARCH_RESULT"
    SEARCH_RESULTS = "SEARCH_RESULTS"
    DEVICE_INFO = "DEVICE_INFO"
    TASK_STATUS = "TASK_STATUS"
    DOCUMENT_INFO = "DOCUMENT_INFO"
    GENERIC_RESULT = "GENERIC_RESULT"
    CALENDAR_EVENT = "CALENDAR_EVENT"
    EMAIL_INFO = "EMAIL_INFO"
    PROCEDURE_STEPS = "PROCEDURE_STEPS"
    TECHNICAL_DETAILS = "TECHNICAL_DETAILS"


@dataclass
class VisualResponseAction:
    """Action button on the visual response panel."""
    label: str          # e.g., "Copy", "Open"
    action_type: str    # "copy", "open_url", "open_file"
    payload: str        # The text to copy or target to open

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VisualResponseAction':
        return cls(
            label=data.get("label", ""),
            action_type=data.get("action_type", ""),
            payload=data.get("payload", "")
        )


@dataclass
class VisualResponse:
    """
    Structured model for an ephemeral visual response.
    Maintained per user in DialogueStateManager with short-lived freshness.
    """
    response_id: str
    user_id: str
    response_type: VisualResponseType
    title: str
    primary_value: str
    secondary_text: Optional[str] = None
    raw_content: Any = None
    actions: List[VisualResponseAction] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: time.time())
    ttl_seconds: float = 300.0  # Default 5-minute freshness
    source_context: str = ""
    related_goal_id: Optional[str] = None
    related_task_id: Optional[str] = None
    is_sensitive: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self, current_time: Optional[float] = None) -> bool:
        """Check if visual response has passed its freshness TTL."""
        now = current_time if current_time is not None else time.time()
        return (now - self.created_at) > self.ttl_seconds

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["response_type"] = self.response_type.value if hasattr(self.response_type, "value") else str(self.response_type)
        d["actions"] = [a.to_dict() if hasattr(a, "to_dict") else a for a in self.actions]
        return d

    @classmethod
    def from_dict(cls, data: Union['VisualResponse', Dict[str, Any]]) -> 'VisualResponse':
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            return cls(
                response_id=str(uuid.uuid4())[:8],
                user_id="default",
                response_type=VisualResponseType.GENERIC_RESULT,
                title="RESULT",
                primary_value=str(data)
            )
        raw_type = data.get("response_type", VisualResponseType.GENERIC_RESULT)
        if isinstance(raw_type, str):
            try:
                resp_type = VisualResponseType(raw_type)
            except ValueError:
                resp_type = VisualResponseType.GENERIC_RESULT
        else:
            resp_type = raw_type

        actions = [
            VisualResponseAction.from_dict(a) if isinstance(a, dict) else a
            for a in data.get("actions", [])
        ]

        return cls(
            response_id=data.get("response_id", str(uuid.uuid4())[:8]),
            user_id=str(data.get("user_id", "default")),
            response_type=resp_type,
            title=data.get("title", "RESULT"),
            primary_value=data.get("primary_value", ""),
            secondary_text=data.get("secondary_text"),
            raw_content=data.get("raw_content"),
            actions=actions,
            created_at=float(data.get("created_at", time.time())),
            ttl_seconds=float(data.get("ttl_seconds", 300.0)),
            source_context=data.get("source_context", ""),
            related_goal_id=data.get("related_goal_id"),
            related_task_id=data.get("related_task_id"),
            is_sensitive=bool(data.get("is_sensitive", False)),
            metadata=data.get("metadata", {})
        )

    @classmethod
    def for_text(
        cls,
        text: str,
        title: str = "DETAILS",
        description: str = "",
        user_id: str = "default",
        **kwargs
    ) -> 'VisualResponse':
        clean_text = str(text or "").strip()
        r_type = kwargs.pop("response_type", VisualResponseType.KNOWLEDGE)
        return cls(
            response_id=str(uuid.uuid4())[:8],
            user_id=str(user_id),
            response_type=r_type,
            title=title.upper(),
            primary_value=clean_text,
            secondary_text=description or "Information display.",
            raw_content={"text": clean_text},
            actions=[VisualResponseAction(label="Copy", action_type="copy", payload=clean_text)],
            created_at=time.time(),
            ttl_seconds=600.0,
            source_context="text_details",
            **kwargs
        )

    @classmethod
    def for_file_path(
        cls,
        path: str,
        title: str = "FILE PATH",
        description: str = "",
        user_id: str = "default",
        **kwargs
    ) -> 'VisualResponse':
        clean_path = str(path or "").strip()
        return cls(
            response_id=str(uuid.uuid4())[:8],
            user_id=str(user_id),
            response_type=VisualResponseType.FILE_PATH,
            title=title.upper(),
            primary_value=clean_path,
            secondary_text=description or "File system path.",
            raw_content={"path": clean_path},
            actions=[
                VisualResponseAction(label="Open", action_type="open_file", payload=clean_path),
                VisualResponseAction(label="Copy", action_type="copy", payload=clean_path)
            ],
            created_at=time.time(),
            ttl_seconds=600.0,
            source_context="file_details",
            **kwargs
        )

    @classmethod
    def for_code(
        cls,
        code: str,
        title: str = "CODE",
        language: str = "",
        user_id: str = "default",
        **kwargs
    ) -> 'VisualResponse':
        clean_code = str(code or "").strip()
        return cls(
            response_id=str(uuid.uuid4())[:8],
            user_id=str(user_id),
            response_type=VisualResponseType.CODE,
            title=title.upper(),
            primary_value=clean_code,
            secondary_text=f"Language: {language}" if language else "Technical code snippet.",
            raw_content={"code": clean_code, "language": language},
            actions=[VisualResponseAction(label="Copy", action_type="copy", payload=clean_code)],
            created_at=time.time(),
            ttl_seconds=600.0,
            source_context="code_snippet",
            **kwargs
        )

    @classmethod
    def for_steps(
        cls,
        steps: Union[List[str], str],
        title: str = "PROCEDURE STEPS",
        user_id: str = "default",
        **kwargs
    ) -> 'VisualResponse':
        if isinstance(steps, list):
            formatted_steps = "\n".join(f"{i+1}. {s}" if not re.match(r'^\d+\.', s.strip()) else s for i, s in enumerate(steps))
        else:
            formatted_steps = str(steps).strip()
        return cls(
            response_id=str(uuid.uuid4())[:8],
            user_id=str(user_id),
            response_type=VisualResponseType.PROCEDURE_STEPS,
            title=title.upper(),
            primary_value=formatted_steps,
            secondary_text="Step-by-step procedure.",
            raw_content={"steps": steps},
            actions=[VisualResponseAction(label="Copy", action_type="copy", payload=formatted_steps)],
            created_at=time.time(),
            ttl_seconds=600.0,
            source_context="procedure_steps",
            **kwargs
        )

    @classmethod
    def for_calendar_event(
        cls,
        event: Dict[str, Any],
        title: str = "CALENDAR EVENT",
        user_id: str = "default",
        **kwargs
    ) -> 'VisualResponse':
        ev_title = event.get("title") or event.get("summary") or event.get("event_name") or "Calendar Event"
        ev_date = event.get("date") or event.get("start_date") or event.get("event_date") or ""
        ev_time = event.get("time") or event.get("start_time") or ""
        ev_end_time = event.get("end_time") or ""
        ev_loc = event.get("location") or "No location specified"
        ev_desc = event.get("description") or event.get("notes") or ""
        ev_attendees = event.get("attendees") or event.get("participants") or []
        if isinstance(ev_attendees, list):
            attendees_str = ", ".join(str(a) for a in ev_attendees) if ev_attendees else ""
        else:
            attendees_str = str(ev_attendees)

        time_display = f"{ev_date} at {ev_time}" if (ev_date and ev_time) else (ev_date or ev_time or "Scheduled")
        if ev_end_time:
            time_display += f" – {ev_end_time}"

        lines = [f"### 📅 {ev_title}"]
        lines.append(f"• **When:** {time_display}")
        if ev_loc and ev_loc != "No location specified":
            lines.append(f"• **Where:** {ev_loc}")
        if attendees_str:
            lines.append(f"• **Attendees:** {attendees_str}")
        if ev_desc:
            lines.append(f"• **Details:** {ev_desc}")

        primary_val = "\n".join(lines)
        return cls(
            response_id=str(uuid.uuid4())[:8],
            user_id=str(user_id),
            response_type=VisualResponseType.CALENDAR_EVENT,
            title=title.upper() if title != "CALENDAR EVENT" else f"EVENT: {ev_title.upper()[:25]}",
            primary_value=primary_val,
            secondary_text=f"Calendar: {time_display}",
            raw_content=event,
            actions=[VisualResponseAction(label="Copy", action_type="copy", payload=primary_val)],
            created_at=time.time(),
            ttl_seconds=600.0,
            source_context="calendar_event_details",
            **kwargs
        )

    @classmethod
    def for_email(
        cls,
        email_data: Dict[str, Any],
        title: str = "EMAIL DETAILS",
        user_id: str = "default",
        **kwargs
    ) -> 'VisualResponse':
        subj = email_data.get("subject") or "No Subject"
        sender = email_data.get("sender") or email_data.get("from") or "Unknown Sender"
        date_str = email_data.get("date") or email_data.get("time") or ""
        body = email_data.get("body") or email_data.get("snippet") or email_data.get("preview") or ""
        lines = [f"### ✉️ {subj}"]
        lines.append(f"• **From:** {sender}")
        if date_str:
            lines.append(f"• **Date:** {date_str}")
        if body:
            lines.append(f"• **Content:**\n{body[:350]}")
        primary_val = "\n".join(lines)
        return cls(
            response_id=str(uuid.uuid4())[:8],
            user_id=str(user_id),
            response_type=VisualResponseType.EMAIL_INFO,
            title=title.upper(),
            primary_value=primary_val,
            secondary_text=f"From: {sender}",
            raw_content=email_data,
            actions=[VisualResponseAction(label="Copy", action_type="copy", payload=primary_val)],
            created_at=time.time(),
            ttl_seconds=600.0,
            source_context="email_details",
            **kwargs
        )


# ─────────────────────────────────────────────────────────────────────────────
# SENSITIVE DATA DETECTION & FILTERING
# ─────────────────────────────────────────────────────────────────────────────
_SENSITIVE_KEYWORDS = [
    "password", "secret", "private_key", "api_key", "token", "auth_token",
    "access_token", "bearer", "credential", "private key", "apikey"
]

def contains_sensitive_data(text_or_dict: Union[str, Dict[str, Any]]) -> bool:
    """Detect if content contains private credentials or security secrets."""
    if isinstance(text_or_dict, dict):
        text = " ".join(f"{k} {v}" for k, v in text_or_dict.items())
    else:
        text = str(text_or_dict)
    text_low = text.lower()
    for kw in _SENSITIVE_KEYWORDS:
        if kw in text_low:
            # Exclude false positives like "pairing_code" or "token" when it's device_auth internal
            if (
                "pairing code" in text_low 
                or "pairing_code" in text_low 
                or "mobile device" in text_low
                or "pairing_started" in text_low 
                or "pairing_code_active" in text_low
            ):
                continue
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# EXPLICIT "SHOW ME" & VISUAL PRESENTATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────
_EXPLICIT_SHOW_PATTERNS = [
    r'\b(?:show\s+me\s+the\s+details|show\s+me\s+details|show\s+the\s+details|open\s+the\s+details(?:\s+box)?|open\s+details(?:\s+box)?|details\s+box)\b',
    r'\b(?:show\s+all\s+(?:the\s+)?information|show\s+all\s+info|show\s+the\s+information|show\s+info)\b',
    r'\b(?:display\s+(?:the\s+)?complete\s+explanation|display\s+(?:the\s+)?explanation|complete\s+explanation)\b',
    r'\b(?:show\s+(?:the\s+)?full\s+steps|show\s+the\s+steps|full\s+steps|step\s+by\s+step\s+details)\b',
    r'\b(?:put\s+(?:that|it|this)\s+on\s+(?:the\s+)?screen|on\s+(?:the\s+)?screen|on\s+my\s+screen|visually|on\s+display)\b',
    r'\b(?:i\s+didn\'?t\s+understand\s+everything[;,]?\s*show\s+me|didn\'?t\s+understand\s+everything\s+show\s+me)\b',
    r'\b(?:show\s+(?:the\s+)?technical\s+details|technical\s+details|expand\s+that(?:\s+information)?|expand\s+details)\b',
    r'\b(?:can\s+you\s+)?show\s+what\s+you\s+(?:just\s+)?(?:explained|said|told\s+me)\b',
    r'\b(?:show\s+that\s+again|show\s+that|show\s+it\s+again|show\s+it|display\s+that\s+again|display\s+that|bring\s+that\s+back|bring\s+it\s+back)\b',
    r'\b(?:display\s+(?:the\s+)?result|show\s+(?:the\s+)?result|visualize\s+this|visualize\s+that|visualize\b|what\s+does\s+this\s+look\s+like\??)\b',
    r'\b(?:show\s+me\s+the\s+information|show\s+me\s+the\s+info)\b',
    r'\b(?:let\s+me\s+see\s+(?:it|that|the|this))\b',
    r'\b(?:show\s+visual\s+response|visual\s+surface|visual\s+response)\b',
    r'\b(?:open\s+(?:the\s+)?dashboard|show\s+(?:the\s+)?dashboard|show\s+(?:the\s+)?assistant\s+panel|open\s+system\s+monitor)\b',
    r'\b(?:show|display)\s+(?:my\s+|the\s+)?(?:cpu(?:\s+usage)?|system\s+stat(?:istic)?s?|calendar|files|route|graph|chart|calculation|table|pairing\s+code|code)\b',
    r'\b(?:show\s+me\s+something\s+visual|make\s+it\s+visual)\b',
    # Multilingual: Telugu
    r'(?:వివరాలు\s+చూపించు|వివరాలను\s+చూపించు|స్క్రీన్‌పై\s+చూపించు|పూర్తి\s+వివరణ\s+చూపించు|మొత్తం\s+సమాచారం\s+చూపించు|వివరాల\s+పెట్టె)',
    # Multilingual: Hindi
    r'(?:विवरण\s+दिखाएं|विवरण\s+दिखाओ|पूरी\s+जानकारी\s+दिखाओ|स्क्रीन\s+पर\s+दिखाओ|पूरा\s+विवरण\s+दिखाओ|डिटेल्स\s+दिखाओ)',
    # Multilingual: Tamil
    r'(?:விவரங்களை\s+காட்டு|முழு\s+விளக்கத்தை\s+காட்டு|திரையில்\s+காட்டு)',
    # Multilingual: Spanish
    r'(?:muestra\s+los\s+detalles|mostrar\s+detalles|abrir\s+la\s+caja\s+de\s+detalles|muestra\s+toda\s+la\s+informaci[oó]n|pon\s+eso\s+en\s+la\s+pantalla)',
]

def is_explicit_visual_request(user_input: str) -> bool:
    """Return True if user explicitly asked to see/display/show something visually."""
    if not user_input or not isinstance(user_input, str):
        return False
    text = user_input.strip().lower()

    # Conversational questions or greetings with assistant name are never explicit visual requests
    if re.search(r'\bshow\s+(?:friday|trevon|nova|jarvis|assistant)\b', text) and not any(k in text for k in ["detail", "result", "cpu", "graph", "table", "chart", "screen", "code"]):
        return False

    for pat in _EXPLICIT_SHOW_PATTERNS:
        if re.search(pat, text):
            return True
    return False


def is_complex_or_information_dense(
    text: str,
    result: Any = None,
    intent: Any = None
) -> Tuple[bool, str, VisualResponseType]:
    """
    Evaluates whether response content is especially important, complex, technical,
    information-dense, multi-step, or difficult to retain from speech alone.

    Returns (is_complex, reason, suggested_response_type).
    """
    if not text and not result:
        return False, "", VisualResponseType.GENERIC_RESULT

    raw_str = ""
    if isinstance(text, str):
        raw_str = text.strip()
    elif isinstance(result, dict):
        raw_str = str(result.get("response") or result.get("message") or result.get("primary_value") or "").strip()
    elif result:
        raw_str = str(result).strip()

    if not raw_str:
        return False, "", VisualResponseType.GENERIC_RESULT

    # Hard exclusions for trivial / casual output
    if raw_str.lower() in ("done.", "done", "got it.", "all set.", "hello", "hi", "hey"):
        return False, "", VisualResponseType.GENERIC_RESULT

    # 1. Multi-step procedures or numbered/bulleted action steps (>= 3 steps)
    numbered_steps = re.findall(r'(?:^|\n)\s*(?:\d+[\.\)]|step\s*\d+[:\.\-])\s+[^\n]+', raw_str, flags=re.IGNORECASE)
    if len(numbered_steps) >= 3:
        return True, "multi_step_procedure", VisualResponseType.PROCEDURE_STEPS

    bullet_steps = re.findall(r'(?:^|\n)\s*[\*\-\•]\s+[^\n]+', raw_str)
    if len(bullet_steps) >= 4:
        return True, "structured_bullet_list", VisualResponseType.LIST

    # 2. Programming Code, Shell Commands, Scripts, or Config Blocks
    if "```" in raw_str:
        return True, "code_block", VisualResponseType.CODE

    command_patterns = [
        r'\b(?:sudo|systemctl|docker|kubectl|git|pip|npm|npx|apt-get|brew|curl|wget)\s+[a-zA-Z0-9_\-\.\/]+',
        r'\b(?:reg\s+add|netsh|powershell|cmd\.exe|chmod|chown)\s+',
        r'(?:SELECT\s+.+\s+FROM\s+.+|INSERT\s+INTO\s+|UPDATE\s+.+\s+SET\s+)',
        r'(?:def\s+[a-zA-Z_]\w*\(|class\s+[a-zA-Z_]\w*\(|function\s+[a-zA-Z_]\w*\(|import\s+[a-zA-Z_]\w*)',
    ]
    for cp in command_patterns:
        if re.search(cp, raw_str, re.IGNORECASE):
            return True, "technical_command_or_code", VisualResponseType.CODE

    # 3. Mathematical formulas / complex equations / configuration syntax
    if re.search(r'[\w]+\s*=\s*[\w\+\-\*\/\^\(\)\.\s]{6,}', raw_str) and any(m in raw_str.lower() for m in ["formula", "equation", "calculate", "algorithm", "integral", "derivative", "sqrt"]):
        return True, "mathematical_formula", VisualResponseType.TECHNICAL_DETAILS

    # 4. High Information Density (Multiple exact dates, times, amounts, or structured metrics)
    date_matches = re.findall(r'\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?|\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b', raw_str, re.IGNORECASE)
    currency_matches = re.findall(r'[\$€£₹]\s*\d+(?:,\d{3})*(?:\.\d{2})?', raw_str)
    if len(date_matches) >= 3 or (len(date_matches) >= 2 and len(currency_matches) >= 1):
        return True, "dense_dates_or_amounts", VisualResponseType.LIST

    # 5. Long, information-dense technical explanation
    words = raw_str.split()
    tech_terms = [
        "architecture", "protocol", "latency", "concurrency", "asynchronous",
        "microservice", "infrastructure", "kubernetes", "docker", "encryption",
        "authentication", "authorization", "database", "postgresql", "index",
        "algorithm", "bandwidth", "throughput", "parameter", "configuration",
        "compiler", "dependency", "deployment", "repository", "pipeline"
    ]
    tech_count = sum(1 for term in tech_terms if term in raw_str.lower())
    if (len(words) >= 30 and tech_count >= 3) or (len(words) >= 50 and tech_count >= 2) or (len(words) >= 60 and tech_count >= 1):
        return True, "complex_technical_explanation", VisualResponseType.TECHNICAL_DETAILS

    return False, "", VisualResponseType.GENERIC_RESULT


def should_show_visual_surface(
    intent: Any = None,
    response_type: Any = None,
    user_request: Optional[str] = None,
    result: Any = None,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """Authoritative centralized policy: determine if visual popup/surface should appear.

    Default policy:
        Voice response + Normal chat feed + NO popup.
    The detailed visual surface opens when:
    1. User explicitly asks to see something ("show me details", "show that", "display result", "visualize this", etc.)
    2. Proactive display: response is complex, technical, multi-step, code, or information-dense
    3. Visual information is inherently useful ("show CPU usage", pairing code, verification code)
    4. Large structured output (TABLE, graph, chart, system dashboard)
    5. Explicit UI/dashboard requests ("open dashboard", "show assistant panel", "system monitor")

    The visual surface must NEVER appear for:
    - Ordinary conversation: "hello", "how are you?", "what is your name?", "what are you doing?"
    - Simple confirmations: "Done.", "Opening YouTube.", "Volume increased.", "Got it.", "All set."
    - Simple actions: "open YouTube", "open Chrome", "increase volume", "mute", "pause", "play"
    """
    req_raw = str(user_request or "").strip()
    req_low = req_raw.lower()

    # Normalize intent and response_type strings
    intent_str = str(intent.name if hasattr(intent, "name") else (intent or "")).upper()
    resp_type_str = str(response_type.value if hasattr(response_type, "value") else (response_type or "")).upper()

    # Extract response text if available
    resp_text = ""
    if isinstance(result, str):
        resp_text = result.strip().lower()
    elif isinstance(result, dict):
        resp_text = str(result.get("response") or result.get("message") or result.get("primary_value") or "").strip().lower()

    # Clean user request for matching
    cleaned_req = req_low
    if req_low:
        cleaned_req = re.sub(r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|trevon|nova|jarvis|assistant|computer)[,\s:]*', '', req_low).strip()
        cleaned_req = re.sub(r'^(?:can\s+you\s+|could\s+you\s+|please\s+)+', '', cleaned_req).strip()
        cleaned_req = cleaned_req.rstrip("?.!")

    # ── 1. HARD EXCLUSIONS (Must never pop up unless explicit visual request) ──

    # Simple confirmations / short status
    CONFIRMATIONS = {"done.", "done", "got it.", "got it", "all set.", "all set", "opening youtube.", "volume increased.", "volume decreased.", "muted.", "unmuted.", "paused.", "playing."}
    if resp_text in CONFIRMATIONS:
        return False
    if any(resp_text.startswith(c) for c in ["opening ", "launching ", "closing ", "muting ", "unmuting ", "volume set to ", "brightness set to "]):
        if not is_explicit_visual_request(req_raw):
            return False

    # Ordinary conversation / greetings
    CONV_STARTS = (
        "hello", "hi", "hey", "how are you", "what is your name", "who are you",
        "what are you doing", "what do you want to do", "what's up", "good morning",
        "good afternoon", "good evening", "thank you", "thanks", "how do you feel",
        "how're you", "how are you doing", "how are you feeling"
    )
    if cleaned_req in CONV_STARTS or any(cleaned_req.startswith(c) for c in CONV_STARTS):
        return False

    if intent_str in ("GENERAL_CONVERSATION", "CONVERSATION", "GREETING", "CASUAL_CHAT") and not is_explicit_visual_request(req_raw):
        is_comp, _, _ = is_complex_or_information_dense(resp_text, result, intent)
        if not is_comp:
            return False

    # Recommendations
    if intent_str in ("RECOMMENDATION", "RECOMMEND") and not is_explicit_visual_request(req_raw):
        is_comp, _, _ = is_complex_or_information_dense(resp_text, result, intent)
        if not is_comp:
            return False
    if cleaned_req.startswith(("what should i", "what can i", "recommend ", "suggest ", "what do you recommend", "what do you suggest", "what should we")):
        if not is_explicit_visual_request(req_raw):
            is_comp, _, _ = is_complex_or_information_dense(resp_text, result, intent)
            if not is_comp:
                return False

    # Simple actions
    SIMPLE_ACTIONS = ("open youtube", "open chrome", "open edge", "open spotify", "open calculator", "increase volume", "decrease volume", "mute", "unmute", "pause", "play", "skip", "stop", "volume up", "volume down")
    if any(cleaned_req == a or req_low == a for a in SIMPLE_ACTIONS) and not is_explicit_visual_request(req_raw):
        return False
    if intent_str in ("OPEN_APPLICATION", "VOLUME_CONTROL", "MEDIA_CONTROL", "BRIGHTNESS_CONTROL") and not is_explicit_visual_request(req_raw):
        return False

    # Normal knowledge questions
    KNOWLEDGE_STARTS = (
        "what is ", "what are ", "who is ", "who was ", "who were ", "where is ",
        "where are ", "when was ", "when did ", "why is ", "why do ", "why does ",
        "how does ", "how do ", "how is ", "explain ", "tell me about ", "describe ",
        "how can ", "can you explain "
    )
    if any(cleaned_req.startswith(k) for k in KNOWLEDGE_STARTS) and not is_explicit_visual_request(req_raw):
        is_comp, _, _ = is_complex_or_information_dense(resp_text, result, intent)
        if not is_comp:
            return False

    # ── 2. ALLOWED VISUAL CONDITIONS ──────────────────────────────────────────

    # Condition A: Explicit visual request by user
    if is_explicit_visual_request(req_raw):
        return True

    # Condition B: Inherently visual entity (Pairing code / Verification code / Table / Task / Calendar / Email / Code)
    if resp_type_str in ("PAIRING_CODE", "VERIFICATION_CODE", "TABLE", "TASK_STATUS", "CALENDAR_EVENT", "EMAIL_INFO", "DEVICE_INFO", "PROCEDURE_STEPS", "TECHNICAL_DETAILS", "CODE"):
        return True

    # Condition C: Explicitly structured table / graph / chart payload or Task / Calendar / Email
    if isinstance(result, dict):
        if result.get("table") or result.get("chart") or result.get("graph") or result.get("matrix"):
            return True
        if result.get("task_id") or result.get("calendar_event") or result.get("email"):
            return True
        if resp_type_str == "TABLE":
            return True

    # Condition D: Explicit hardware monitor / dashboard intent
    if intent_str in ("VISUAL_SURFACE", "DASHBOARD", "SYSTEM_MONITOR"):
        if any(cleaned_req.startswith(k) for k in KNOWLEDGE_STARTS) or any(cleaned_req.startswith(c) for c in CONV_STARTS):
            return False
        return True

    # Condition E: Proactive display for important, complex, technical, or information-dense content
    is_comp, _, _ = is_complex_or_information_dense(resp_text, result, intent)
    if is_comp:
        return True

    # Default UI policy: NO popup
    return False


def extract_visual_title(user_input: str, response_text: str = "", default: str = "RESULT") -> str:
    """Extract a concise, readable title from the user prompt or response content."""
    if not user_input or not isinstance(user_input, str):
        return default
    text = user_input.strip()

    # Strip leading trigger phrases
    patterns_to_strip = [
        r'^(?:can\s+(?:you|i)\s+|could\s+(?:you|i)\s+|please\s+)?(?:show\s+me|show|display|let\s+me\s+see|put\s+on\s+screen)\s+',
        r'^(?:what\s+you\s+know\s+about|what\s+do\s+you\s+know\s+about|an\s+explanation\s+of|information\s+about|details\s+about|facts\s+about|a\s+summary\s+of|an\s+overview\s+of)\s+',
        r'^(?:who\s+the|who\s+is\s+the|who\s+is|what\s+is\s+the|what\s+is|what\s+are\s+the|what\s+are|where\s+is\s+the|where\s+is|how\s+is\s+the|how\s+is)\s+',
        r'^(?:what|who|where|how|why)\s+',
        r'^(?:tell\s+me\s+about|explain|describe)\s+',
        r'^(?:the\s+)?',
    ]
    cleaned = text
    for pat in patterns_to_strip:
        cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE).strip()

    # Strip trailing punctuation and filler
    cleaned = re.sub(r'[\?\.\!]+$', '', cleaned).strip()
    cleaned = re.sub(r'\s+(?:is|are|was|were|again|please|on\s+screen|on\s+the\s+screen)$', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'^(?:the\s+)', '', cleaned, flags=re.IGNORECASE).strip()

    if cleaned and len(cleaned) <= 35:
        return cleaned.upper()
    elif cleaned and len(cleaned) > 35:
        words = cleaned.split()[:4]
        return " ".join(words).upper()
    return default


def format_knowledge_content(text: str) -> str:
    """Format answer text cleanly for visual presentation without a second LLM request."""
    if not text:
        return ""
    cleaned = text.strip()
    # Strip redundant conversational prefixes
    cleaned = re.sub(r'^(?:Here\s+(?:is|are)\s+(?:what\s+I\s+found|the\s+information|details):\s*)+', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'^(?:According\s+to\s+(?:my\s+knowledge|the\s+database),\s*)+', '', cleaned, flags=re.IGNORECASE)
    # Normalize excessive newlines
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


# ─────────────────────────────────────────────────────────────────────────────
# AUTOMATIC VISUAL RESPONSE DETECTOR
# ─────────────────────────────────────────────────────────────────────────────
_CASUAL_CHAT_PATTERNS = [
    r'^(?:hi|hello|hey|good\s+(?:morning|afternoon|evening)|howdy)\b',
    r'^(?:how\s+are\s+you|what(?:\'s|\s+is)\s+up|sup)\b',
    r'^(?:thank\s+you|thanks|sure|okay|ok|cool|great|bye|goodbye)\b',
    r'^(?:what(?:\'s|\s+is)\s+(?:the\s+)?time|what\s+time\s+is\s+it)\b',
    r'^(?:what(?:\'s|\s+is)\s+(?:the\s+)?date|what\s+day\s+is\s+it)\b',
]

def is_casual_or_trivial(user_input: str, response: str) -> bool:
    """Return True if interaction is casual conversation not benefiting from visual display."""
    input_low = user_input.strip().lower()
    for pat in _CASUAL_CHAT_PATTERNS:
        if re.search(pat, input_low):
            return True
    resp_low = response.strip().lower()
    for pat in _CASUAL_CHAT_PATTERNS:
        if re.search(pat, resp_low):
            return True
    if resp_low.startswith("the current time is") or resp_low.startswith("the time is"):
        return True
    if resp_low.startswith("today's date is") or resp_low.startswith("today is"):
        return True
    if any(resp_low.startswith(w) for w in ["sure", "done", "okay", "hello", "hi ", "i'm here", "good morning", "good afternoon"]):
        return True
    return False


def detect_visual_response(
    result: Union[Dict[str, Any], str],
    user_input: str = "",
    user_id: str = "default",
    goal_id: Optional[str] = None,
    source_context: str = ""
) -> Optional[VisualResponse]:
    """
    Analyzes an execution result and determines whether it should produce
    a visual response surface (either from explicit 'show me' request or
    action results benefiting from visual presentation).
    """
    if result is None:
        return None

    if isinstance(result, str):
        result_dict = {"response": result}
        response_text = result.strip()
    elif isinstance(result, dict):
        result_dict = result
        response_text = str(result.get("response") or result.get("message") or "").strip()
    else:
        result_dict = {"response": str(result)}
        response_text = str(result).strip()

    status = str(result_dict.get("status") or "").lower()

    # Never display secrets or passwords automatically (Requirement 19)
    if contains_sensitive_data(result_dict) or contains_sensitive_data(user_input) or contains_sensitive_data(response_text):
        return None

    # Do not create new visual responses for VISUAL_SURFACE internal messages, cached replays, or refusal notices
    if (
        result_dict.get("intent") in ("VISUAL_SURFACE", "Intent.VISUAL_SURFACE", 29)
        or result_dict.get("reused_cache") is True
        or any(k in response_text.lower() for k in [
            "there is no recent information to display",
            "there is no active pairing code",
            "i no longer have a current version",
            "which one would you like me to show",
            "failed to restore visual response"
        ])
    ):
        return None

    explicit_request = is_explicit_visual_request(user_input)

    # Check centralized visual surface policy
    if not should_show_visual_surface(
        intent=result_dict.get("intent"),
        response_type=None,
        user_request=user_input,
        result=result_dict,
        context={"source_context": source_context, "goal_id": goal_id}
    ):
        code = result_dict.get("code")
        is_pairing = bool(code and ("pairing" in user_input.lower() or "phone" in user_input.lower() or "mobile" in user_input.lower() or "connect" in user_input.lower() or result_dict.get("status") in ("pairing_started", "pairing_code_active")))
        is_table = bool(result_dict.get("table") or result_dict.get("headers") or ("|" in response_text and "-|-" in response_text))
        if not is_pairing and not is_table and not explicit_request:
            return None

    # Trivial / short casual responses do not popup unless explicitly requested
    if not explicit_request and is_casual_or_trivial(user_input, response_text):
        return None

    resp_id = str(uuid.uuid4())[:8]
    now = time.time()

    # 0. EXPLICIT DEVICE INFO DICTIONARY (Smart switches, lights, IoT)
    if isinstance(result_dict, dict) and (
        result_dict.get("device_name") 
        or result_dict.get("type") in ("smart_switch", "light", "switch")
        or "brightness" in result_dict
    ):
        dev_name = result_dict.get("device_name") or "Device"
        st = result_dict.get("status", "online")
        return VisualResponse(
            response_id=resp_id,
            user_id=str(user_id),
            response_type=VisualResponseType.DEVICE_INFO,
            title="DEVICE INFO",
            primary_value=f"{dev_name} ({st})",
            secondary_text=f"Status: {st} | Type: {result_dict.get('type', 'device')}",
            raw_content=result_dict,
            actions=[VisualResponseAction(label="Copy", action_type="copy", payload=dev_name)],
            created_at=now,
            ttl_seconds=300.0,
            source_context=source_context or "device_info",
            related_goal_id=goal_id
        )

    # 1. PAIRING CODE (Top Priority)
    code = result_dict.get("code")
    if not code and response_text:
        m_code = re.search(r'\b(?:pairing\s+code\s+(?:is\s+)?|code:\s*)([0-9]{6})\b', response_text, re.IGNORECASE)
        if m_code:
            code = m_code.group(1).strip()

    if code and (
        result_dict.get("status") in ("pairing_started", "pairing_code_active")
        or "pairing" in user_input.lower()
        or "pairing" in response_text.lower()
        or "phone" in user_input.lower()
        or "mobile" in user_input.lower()
        or "connect" in user_input.lower()
    ):
        code_str = str(code).strip()

        # Extract Gateway (Host:Port)
        gw_host = result_dict.get("gateway_host")
        gw_port = result_dict.get("gateway_port")
        if gw_host and gw_port:
            gateway_val = f"{gw_host}:{gw_port}"
        elif gw_host:
            gateway_val = str(gw_host)
        else:
            m_gw = re.search(r'(?:gateway\s+(?:is\s+)?(?:available\s+at\s+)?|at\s+)(\d{1,3}(?:\.\d{1,3}){3}:\d+)', response_text, re.IGNORECASE)
            gateway_val = m_gw.group(1) if m_gw else None

        # Extract Expiry
        expiry_val = None
        if result_dict.get("expires_at"):
            exp_raw = str(result_dict["expires_at"])
            try:
                from datetime import datetime, timezone
                exp_dt = datetime.fromisoformat(exp_raw)
                now_dt = datetime.now(timezone.utc)
                if exp_dt > now_dt:
                    rem = int((exp_dt - now_dt).total_seconds())
                    rem_mins = max(1, rem // 60)
                    expiry_val = f"{rem_mins} minutes"
            except Exception:
                pass
        if not expiry_val:
            m_exp = re.search(r'expires\s+in\s+([^\.]+)', response_text, re.IGNORECASE)
            expiry_val = m_exp.group(1).strip() if m_exp else "5 minutes"

        # Construct structured secondary text exactly matching Section 3:
        # Gateway:\n192.168.1.11:8765\n\nExpires:\n5 minutes
        sec_parts = []
        if gateway_val:
            sec_parts.append(f"Gateway:\n{gateway_val}")
        if expiry_val:
            sec_parts.append(f"Expires:\n{expiry_val}")
        sec_msg = "\n\n".join(sec_parts) if sec_parts else "Enter this code on your phone."

        title_text = "MOBILE PAIRING" if ("mobile" in user_input.lower() or "mobile" in response_text.lower() or gateway_val) else "PAIRING CODE"

        return VisualResponse(
            response_id=resp_id,
            user_id=str(user_id),
            response_type=VisualResponseType.PAIRING_CODE,
            title=title_text,
            primary_value=code_str,
            secondary_text=sec_msg,
            raw_content={"code": code_str, "gateway": gateway_val, "expires": expiry_val, "status": result_dict.get("status")},
            actions=[VisualResponseAction(label="Copy", action_type="copy", payload=code_str)],
            created_at=now,
            ttl_seconds=300.0,  # 5 min freshness for pairing code
            source_context=source_context or "device_pairing",
            related_goal_id=goal_id
        )

    # 1b. Check if response text has an explicit 6-digit pairing code
    m_code = re.search(r'\b(?:pairing\s+code\s+(?:is\s+)?|code:\s*)([0-9]{6})\b', response_text, re.IGNORECASE)
    if m_code:
        code_str = m_code.group(1).strip()
        title_text = "MOBILE PAIRING" if ("mobile" in user_input.lower() or "mobile" in response_text.lower()) else "PAIRING CODE"
        return VisualResponse(
            response_id=resp_id,
            user_id=str(user_id),
            response_type=VisualResponseType.PAIRING_CODE,
            title=title_text,
            primary_value=code_str,
            secondary_text="Enter this code on your phone.",
            raw_content={"code": code_str},
            actions=[VisualResponseAction(label="Copy", action_type="copy", payload=code_str)],
            created_at=now,
            ttl_seconds=300.0,
            source_context=source_context or "device_pairing",
            related_goal_id=goal_id
        )

    # 2. VERIFICATION CODE / OTP / PIN
    m_otp = re.search(r'\b(?:verification\s+code|otp|pin|passcode)\s+(?:is\s+)?([0-9A-Z]{4,8})\b', response_text, re.IGNORECASE)
    if m_otp:
        otp_str = m_otp.group(1).strip()
        return VisualResponse(
            response_id=resp_id,
            user_id=str(user_id),
            response_type=VisualResponseType.VERIFICATION_CODE,
            title="VERIFICATION CODE",
            primary_value=otp_str,
            secondary_text="One-time verification code.",
            raw_content={"code": otp_str},
            actions=[VisualResponseAction(label="Copy", action_type="copy", payload=otp_str)],
            created_at=now,
            ttl_seconds=300.0,
            source_context="verification",
            related_goal_id=goal_id
        )

    # 3. IP ADDRESS
    ip_val = result_dict.get("ip") or result_dict.get("ip_address") or result_dict.get("gateway_host")
    if not ip_val:
        m_ip = re.search(r'\b(?:ip\s+(?:address\s+)?(?:of\s+[^\s]+\s+)?(?:is\s+)?|address:\s*)(\d{1,3}(?:\.\d{1,3}){3})\b', response_text, re.IGNORECASE)
        if m_ip:
            ip_val = m_ip.group(1)
        elif any(k in user_input.lower() for k in ["ip address", "my ip", "what is the ip", "device address"]) or "ip" in source_context.lower() or "network" in source_context.lower() or "ip address" in response_text.lower():
            m_raw_ip = re.search(r'\b(\d{1,3}(?:\.\d{1,3}){3})\b', response_text)
            if m_raw_ip:
                ip_val = m_raw_ip.group(1)

    if ip_val:
        ip_str = str(ip_val).strip()
        return VisualResponse(
            response_id=resp_id,
            user_id=str(user_id),
            response_type=VisualResponseType.IP_ADDRESS,
            title="IP ADDRESS",
            primary_value=ip_str,
            secondary_text="Local network address.",
            raw_content={"ip": ip_str},
            actions=[VisualResponseAction(label="Copy", action_type="copy", payload=ip_str)],
            created_at=now,
            ttl_seconds=600.0,
            source_context=source_context or "network_address",
            related_goal_id=goal_id
        )

    # 4. URL / WEB LINK
    is_dense_or_steps, _, _ = is_complex_or_information_dense(response_text, result_dict)
    url_val = result_dict.get("url")
    if not url_val and not is_dense_or_steps:
        m_url = re.search(r'(https?://[^\s<>"]+)', response_text)
        if m_url:
            url_val = m_url.group(1)
    if url_val and len(str(url_val)) > 15:
        url_str = str(url_val).strip()
        site_name = result_dict.get("site_name") or "Web Link"
        return VisualResponse(
            response_id=resp_id,
            user_id=str(user_id),
            response_type=VisualResponseType.URL,
            title="OPEN IN BROWSER",
            primary_value=url_str,
            secondary_text=f"Target: {site_name}",
            raw_content={"url": url_str},
            actions=[
                VisualResponseAction(label="Open", action_type="open_url", payload=url_str),
                VisualResponseAction(label="Copy", action_type="copy", payload=url_str)
            ],
            created_at=now,
            ttl_seconds=600.0,
            source_context=source_context or "web_navigation",
            related_goal_id=goal_id
        )

    # 5. FILE PATH / DOCUMENT CREATION
    file_path = result_dict.get("filepath") or result_dict.get("file_path") or result_dict.get("path") or result_dict.get("saved_path")
    if not file_path:
        # Check if response references a created or exported file path
        m_path = re.search(r'\b([A-Za-z]:\\[^\s<>"\n\r]+|\b[\w\-./\\]+\.(?:docx|pdf|xlsx|pptx|txt|py|csv|json|md))\b', response_text)
        if m_path and any(w in response_text.lower() for w in ["saved", "created", "generated", "exported", "wrote", "file", "path"]):
            file_path = m_path.group(1)

    if file_path:
        path_str = str(file_path).strip()
        is_full_path = bool(re.match(r'^[A-Za-z]:[\\/]', path_str) or path_str.startswith('/'))
        if is_full_path or source_context in ("file_export", "file_system") or "file" in source_context:
            res_type = VisualResponseType.FILE_PATH
            title_text = "FILE PATH"
        else:
            res_type = VisualResponseType.DOCUMENT_INFO if any(path_str.lower().endswith(ext) for ext in [".docx", ".pdf", ".xlsx", ".pptx"]) else VisualResponseType.FILE_PATH
            title_text = "DOCUMENT" if res_type == VisualResponseType.DOCUMENT_INFO else "FILE PATH"

        return VisualResponse(
            response_id=resp_id,
            user_id=str(user_id),
            response_type=res_type,
            title=title_text,
            primary_value=path_str,
            secondary_text=response_text[:80] if len(response_text) > len(path_str) else "File generated.",
            raw_content={"file_path": path_str},
            actions=[
                VisualResponseAction(label="Open", action_type="open_file", payload=path_str),
                VisualResponseAction(label="Copy", action_type="copy", payload=path_str)
            ],
            created_at=now,
            ttl_seconds=600.0,
            source_context=source_context or "file_system",
            related_goal_id=goal_id
        )

    # 6. STRUCTURED LIST (e.g. devices list, search results, tasks)
    devices = result_dict.get("devices")
    if devices is not None and isinstance(devices, list):
        if len(devices) > 0:
            lines = []
            for d in devices:
                if isinstance(d, dict):
                    name = d.get("name") or d.get("device_id") or "Device"
                    status_lbl = d.get("status") or ("Online" if d.get("online") else "Offline")
                    lines.append(f"• {name} ({status_lbl})")
                else:
                    lines.append(f"• {d}")
            list_text = "\n".join(lines)
            return VisualResponse(
                response_id=resp_id,
                user_id=str(user_id),
                response_type=VisualResponseType.LIST,
                title="AVAILABLE DEVICES",
                primary_value=list_text,
                secondary_text=f"{len(devices)} device(s) found",
                raw_content={"devices": devices},
                actions=[VisualResponseAction(label="Copy", action_type="copy", payload=list_text)],
                created_at=now,
                ttl_seconds=600.0,
                source_context=source_context or "device_list",
                related_goal_id=goal_id
            )

    # 7. SEARCH RESULTS
    files = result_dict.get("files")
    if files and isinstance(files, list) and len(files) > 0:
        lines = []
        for f in files[:8]:
            if isinstance(f, dict):
                fname = f.get("name") or f.get("path") or "Item"
                lines.append(f"• {fname}")
            else:
                lines.append(f"• {f}")
        search_text = "\n".join(lines)
        return VisualResponse(
            response_id=resp_id,
            user_id=str(user_id),
            response_type=VisualResponseType.SEARCH_RESULTS,
            title="SEARCH RESULTS",
            primary_value=search_text,
            secondary_text=f"{len(files)} result(s) found",
            raw_content={"files": files},
            actions=[VisualResponseAction(label="Copy", action_type="copy", payload=search_text)],
            created_at=now,
            ttl_seconds=600.0,
            source_context=source_context or "file_search",
            related_goal_id=goal_id
        )

    # 8. TASK QUEUE / STATUS (Distinguish pending vs confirmed)
    if result_dict.get("task_id"):
        t_id = str(result_dict["task_id"])
        t_goal = result_dict.get("goal") or user_input
        is_pending = status in ("running", "in_progress", "pending", "executing") or result_dict.get("pending") is True or result_dict.get("verified") is False
        title_txt = f"TASK #{t_id} (IN PROGRESS)" if is_pending else f"TASK #{t_id}"
        sec_txt = f"Goal: {t_goal} [PENDING CONFIRMATION]" if is_pending else f"Goal: {t_goal} [CONFIRMED]"
        status_val = "Pending verification..." if is_pending else "Completed."
        return VisualResponse(
            response_id=resp_id,
            user_id=str(user_id),
            response_type=VisualResponseType.TASK_STATUS,
            title=title_txt,
            primary_value=f"Task #{t_id}: {status_val}",
            secondary_text=sec_txt,
            raw_content={"task_id": t_id, "goal": t_goal, "status": "pending" if is_pending else "completed"},
            actions=[VisualResponseAction(label="Copy", action_type="copy", payload=t_id)],
            created_at=now,
            ttl_seconds=600.0,
            source_context=source_context or "task_management",
            related_goal_id=goal_id
        )

    # 8b. CALENDAR EVENT DETAILS
    if (
        result_dict.get("calendar_event")
        or result_dict.get("event")
        or (isinstance(result_dict.get("events"), list) and len(result_dict["events"]) == 1)
        or result_dict.get("event_title")
    ):
        ev_data = result_dict.get("calendar_event") or result_dict.get("event") or (result_dict.get("events")[0] if isinstance(result_dict.get("events"), list) and result_dict["events"] else result_dict)
        if isinstance(ev_data, dict) and any(k in ev_data for k in ["title", "summary", "event_name", "date", "start_time"]):
            return VisualResponse.for_calendar_event(
                ev_data,
                user_id=str(user_id),
                related_goal_id=goal_id,
                source_context=source_context or "calendar_event_details"
            )

    # 8c. EMAIL DETAILS
    if result_dict.get("email") or (isinstance(result_dict.get("emails"), list) and len(result_dict["emails"]) == 1):
        em_data = result_dict.get("email") or (result_dict.get("emails")[0] if isinstance(result_dict.get("emails"), list) and result_dict["emails"] else result_dict)
        if isinstance(em_data, dict) and any(k in em_data for k in ["subject", "from", "sender", "body"]):
            return VisualResponse.for_email(
                em_data,
                user_id=str(user_id),
                related_goal_id=goal_id,
                source_context=source_context or "email_details"
            )

    # 9. DEVICE INFO / BATTERY / SYSTEM STATUS
    if isinstance(result_dict, dict) and (any(k in result_dict for k in ["battery_level", "percent", "cpu_percent", "memory_percent"]) or "battery" in user_input.lower()):
        val = ""
        if result_dict.get("battery_level") is not None:
            val = f"{result_dict['battery_level']}%"
        elif result_dict.get("percent") is not None:
            val = f"{result_dict['percent']}%"
        if val:
            return VisualResponse(
                response_id=resp_id,
                user_id=str(user_id),
                response_type=VisualResponseType.DEVICE_INFO,
                title="DEVICE STATUS",
                primary_value=val,
                secondary_text=response_text,
                raw_content=result_dict,
                created_at=now,
                ttl_seconds=300.0,
                source_context=source_context or "device_status",
                related_goal_id=goal_id
            )

    # 10. IMPORTANT ERROR DETAILS
    if status in ("error", "failed") and result_dict.get("error"):
        err_msg = str(result_dict["error"])
        if len(err_msg) > 10:
            return VisualResponse(
                response_id=resp_id,
                user_id=str(user_id),
                response_type=VisualResponseType.ERROR,
                title="ERROR DETAILS",
                primary_value=err_msg[:120],
                secondary_text=response_text[:80],
                raw_content={"error": err_msg},
                actions=[VisualResponseAction(label="Copy", action_type="copy", payload=err_msg)],
                created_at=now,
                ttl_seconds=300.0,
                source_context=source_context or "error_details",
                related_goal_id=goal_id
            )

    # 11. EXPLICIT VISUAL REQUEST (Knowledge answers, weather, reminders, results)
    if explicit_request and response_text:
        req_low = user_input.lower()
        resp_low = response_text.lower()

        # Determine appropriate visual response type
        if "weather" in req_low or "weather" in resp_low or "temperature" in req_low:
            resp_type = VisualResponseType.STATUS
            default_title = "WEATHER"
        elif "reminder" in req_low or "reminders" in req_low:
            resp_type = VisualResponseType.LIST
            default_title = "MY REMINDERS"
        elif any(k in req_low for k in ["step", "steps", "procedure", "how to"]):
            resp_type = VisualResponseType.PROCEDURE_STEPS
            default_title = "STEP-BY-STEP PROCEDURE"
        elif any(k in req_low for k in ["technical", "code", "command"]):
            resp_type = VisualResponseType.TECHNICAL_DETAILS
            default_title = "TECHNICAL DETAILS"
        elif "\n" in response_text and ("•" in response_text or "-" in response_text or re.search(r'^\s*\d+\.', response_text, re.MULTILINE)):
            resp_type = VisualResponseType.LIST
            default_title = "DETAILS"
        else:
            resp_type = VisualResponseType.KNOWLEDGE
            default_title = "DETAILS"

        title_str = extract_visual_title(user_input, response_text, default=default_title)
        formatted_val = format_knowledge_content(response_text)

        return VisualResponse(
            response_id=resp_id,
            user_id=str(user_id),
            response_type=resp_type,
            title=title_str,
            primary_value=formatted_val,
            raw_content={"text": response_text},
            actions=[VisualResponseAction(label="Copy", action_type="copy", payload=formatted_val)],
            created_at=now,
            ttl_seconds=600.0,
            source_context=source_context or "explicit_visual_display",
            related_goal_id=goal_id
        )

    # 12. PROACTIVE DISPLAY FOR COMPLEX, TECHNICAL, OR INFORMATION-DENSE RESPONSES
    is_comp, comp_reason, comp_type = is_complex_or_information_dense(response_text, result_dict)
    if is_comp:
        title_str = extract_visual_title(user_input, response_text, default=comp_type.value)
        formatted_val = format_knowledge_content(response_text)
        return VisualResponse(
            response_id=resp_id,
            user_id=str(user_id),
            response_type=comp_type,
            title=title_str,
            primary_value=formatted_val,
            secondary_text="Important details displayed for visual reference.",
            raw_content=result_dict,
            actions=[VisualResponseAction(label="Copy", action_type="copy", payload=formatted_val)],
            created_at=now,
            ttl_seconds=600.0,
            source_context=source_context or f"proactive_{comp_reason}",
            related_goal_id=goal_id
        )

    # 13. AUTOMATIC MULTI-LINE / STRUCTURED TEXT (Tables or multi-column data)
    if "\n" in response_text and len(response_text.splitlines()) >= 2:
        if ("|" in response_text and "-|-" in response_text) or explicit_request:
            return VisualResponse(
                response_id=resp_id,
                user_id=str(user_id),
                response_type=VisualResponseType.TABLE if ("|" in response_text) else VisualResponseType.LIST,
                title="RESULT",
                primary_value=response_text,
                raw_content={"text": response_text},
                actions=[VisualResponseAction(label="Copy", action_type="copy", payload=response_text)],
                created_at=now,
                ttl_seconds=600.0,
                source_context="structured_result",
                related_goal_id=goal_id
            )

    return None

