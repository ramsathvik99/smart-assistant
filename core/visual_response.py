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
from typing import Dict, Any, List, Optional, Union


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
            if "pairing code" in text_low or "pairing_code" in text_low:
                continue
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# EXPLICIT "SHOW ME" & VISUAL PRESENTATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────
_EXPLICIT_SHOW_PATTERNS = [
    r'^(?:can\s+(?:you|i)\s+|could\s+(?:you|i)\s+|please\s+)?(?:show\s+me|show\s+it|show\s+that|show|display|let\s+me\s+see|put\s+on\s+screen|put\b.*\bon\s+screen)\b',
    r'^(?:show\s+to\s+me|bring\s+up|pop\s+up|visually\s+show)\b',
    r'\b(?:on\s+(?:the\s+)?screen|on\s+my\s+screen|visually|on\s+display)\b',
]

def is_explicit_visual_request(user_input: str) -> bool:
    """Return True if user explicitly asked to see/display/show something visually."""
    if not user_input or not isinstance(user_input, str):
        return False
    text = user_input.strip().lower()
    for pat in _EXPLICIT_SHOW_PATTERNS:
        if re.search(pat, text):
            return True
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

    explicit_request = is_explicit_visual_request(user_input)

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
    if code and (
        result_dict.get("status") in ("pairing_started", "pairing_code_active")
        or "pairing" in user_input.lower()
        or "pairing code" in response_text.lower()
    ):
        code_str = str(code).strip()
        sec_msg = "Enter this code on your phone."
        if result_dict.get("expires_at"):
            sec_msg += " Expires in 5 minutes."
        return VisualResponse(
            response_id=resp_id,
            user_id=str(user_id),
            response_type=VisualResponseType.PAIRING_CODE,
            title="PAIRING CODE",
            primary_value=code_str,
            secondary_text=sec_msg,
            raw_content={"code": code_str, "status": result_dict.get("status")},
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
        return VisualResponse(
            response_id=resp_id,
            user_id=str(user_id),
            response_type=VisualResponseType.PAIRING_CODE,
            title="PAIRING CODE",
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
    url_val = result_dict.get("url")
    if not url_val:
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
    file_path = result_dict.get("file_path") or result_dict.get("path") or result_dict.get("saved_path")
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

    # 8. TASK QUEUE / STATUS
    if result_dict.get("task_id"):
        t_id = str(result_dict["task_id"])
        t_goal = result_dict.get("goal") or user_input
        return VisualResponse(
            response_id=resp_id,
            user_id=str(user_id),
            response_type=VisualResponseType.TASK_STATUS,
            title="TASK STATUS",
            primary_value=f"Task #{t_id}",
            secondary_text=f"Goal: {t_goal}",
            raw_content={"task_id": t_id, "goal": t_goal},
            actions=[VisualResponseAction(label="Copy", action_type="copy", payload=t_id)],
            created_at=now,
            ttl_seconds=600.0,
            source_context=source_context or "task_management",
            related_goal_id=goal_id
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
        elif "\n" in response_text and ("•" in response_text or "-" in response_text or re.search(r'^\s*\d+\.', response_text, re.MULTILINE)):
            resp_type = VisualResponseType.LIST
            default_title = "LIST"
        else:
            resp_type = VisualResponseType.KNOWLEDGE
            default_title = "KNOWLEDGE"

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

    # 12. AUTOMATIC MULTI-LINE / STRUCTURED TEXT (Only for genuinely structured lists/tables)
    if "\n" in response_text and len(response_text.splitlines()) >= 2:
        if "•" in response_text or "-" in response_text or re.search(r'^\s*\d+\.', response_text, re.MULTILINE) or "|" in response_text:
            return VisualResponse(
                response_id=resp_id,
                user_id=str(user_id),
                response_type=VisualResponseType.LIST,
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

