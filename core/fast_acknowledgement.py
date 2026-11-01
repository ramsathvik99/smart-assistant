"""
Fast Contextual Acknowledgement Engine.
Provides sub-5ms contextual acknowledgements for incoming voice and text commands,
enabling immediate (<300ms) user feedback before execution begins.
"""

import re
from typing import Optional, Tuple, Dict, Any

# Fast regex patterns for instantaneous contextual acknowledgement
_ACK_PATTERNS = [
    # ── Mobile Screen Mirroring & Live Screen View ──
    (r'\b(?:stop|close|kill|exit|end)\s+(?:(?:phone|mobile|screen|live)\s+)?(?:mirroring|mirror|stream|cast|scrcpy|screen)\b', "Stopping screen mirroring."),
    (r'^(?!.*\b(?:stop|close|kill|exit|end)\b).*\b(?:show|view|display|see|start|open|launch)\s+(?:me\s+)?(?:the\s+|my\s+)?(?:live\s+)?(?:phone\s+|mobile\s+|redmi\s+)?(?:screen\s+mirror(?:ing)?|live\s+screen|screen|mirror(?:ing)?|stream|cast|scrcpy)(?:\s+(?:of|for|on)\s+(?:(?:my|the)\s+)?(?:phone|mobile|redmi[a-z0-9_\-\s]*))?\b', "Starting screen mirroring."),
    (r'^(?!.*\b(?:stop|close|kill|exit|end)\b).*\b(?:live\s+screen\s+mirror|phone\s+live\s+screen|live\s+phone\s+screen|live\s+screen|screen\s+mirror(?:ing)?|phone\s+screen\s+mirror|mirror\s+phone\s+screen)\b', "Starting screen mirroring."),
    (r'^(?!.*\b(?:stop|close|kill|exit|end)\b).*\b(?:mirror|stream|cast)\s+(?:my\s+)?(?:phone|mobile|redmi|screen)(?:\s+screen)?\b', "Starting screen mirroring."),
    (r'^(?!.*\b(?:stop|close|kill|exit|end)\b).*\b(?:show|view|display)\s+(?:me\s+)?(?:the\s+|my\s+)?(?:phone|mobile)\s+screen\b', "Starting screen mirroring."),

    # ── Mobile Connection & Status ──
    (r'\b(?:is|check|verify|tell\s+me)\b.*\b(?:phone|mobile|redmi|device)\b.*\b(?:connected|online|status|connection|debugging)\b', "Checking your phone connection."),
    (r'\b(?:phone|mobile|redmi|device)\s+(?:connection|status|online)\b', "Checking your phone connection."),
    (r'\b(?:connect|reconnect)\s+(?:to\s+)?(?:my\s+)?(?:phone|mobile|android|redmi)\b', "Connecting to your phone."),
    (r'\b(?:disconnect|unconnect)\s+(?:from\s+)?(?:my\s+)?(?:phone|mobile|android|redmi)\b', "Disconnecting your phone."),

    # ── Mobile In-App Search ──
    (r'\b(?:open|launch)\s+youtube\s+(?:and\s+)?(?:find|search(?:\s+for)?|look\s+for)\s+(.+?)(?:\s+(?:on|in)\s+(?:my\s+)?phone)?$', lambda m: f"Searching YouTube for {m.group(1).strip()}."),
    (r'\b(?:find|search(?:\s+for)?)\s+(.+?)\s+(?:on|in)\s+youtube\b', lambda m: f"Searching YouTube for {m.group(1).strip()}."),
    (r'\b(?:open|launch)\s+spotify\s+(?:and\s+)?(?:find|search(?:\s+for)?|play)\s+(.+?)$', lambda m: f"Searching Spotify for {m.group(1).strip()}."),
    (r'\b(?:open|launch)\s+([a-zA-Z0-9_\s]+?)\s+(?:and\s+)?(?:find|search(?:\s+for)?)\s+(.+?)$', lambda m: f"Searching {m.group(1).strip().title()} for {m.group(2).strip()}."),

    # ── Mobile Messaging & WhatsApp ──
    (r'\b(?:tell|message|text)\s+([a-zA-Z0-9_\s]+?)\s+(?:that|to|saying)\b', lambda m: f"Drafting message for {m.group(1).strip().title()}."),
    (r'\b(?:i\s+need\s+to\s+message|send\s+(?:a\s+)?message\s+to|send\s+whatsapp\s+to)\s+([a-zA-Z0-9_\s]+?)$', lambda m: f"Opening chat with {m.group(1).strip().title()}."),
    (r'\bopen\s+([a-zA-Z0-9_]+)(?:\x27s|\s+)?\s*chat\b', lambda m: f"Opening chat with {m.group(1).strip().title()}."),
    (r'\b(?:send\s+it|confirm\s+send|yes\s+send)\b', "Sending message."),

    # ── Mobile Notifications ──
    (r'\b(?:check|read|show|list|get|what\s+are)\s+(?:what\s+)?(?:the\s+|my\s+)?notifications\b', "Checking your notifications."),

    # ── Mobile Navigation ──
    (r'\b(?:go\s+to\s+(?:the\s+)?previous\s+screen|previous\s+screen|go\s+back\b)', "Going back."),
    (r'\b(?:go\s+(?:to\s+)?(?:(?:my|the|phone|mobile)\s+)?(?:the\s+)?home(?:\s+screen)?|return\s+home|press\s+home)\b', "Going to home screen."),
    (r'\b(?:recent\s+apps|app\s+switcher|open\s+recents)\b', "Opening recent apps."),

    # ── Mobile Settings & Toggles ──
    (r'\b(?:turn\s+on|enable|activate|switch\s+on)\s+bluetooth\b', "Turning on Bluetooth."),
    (r'\b(?:turn\s+off|disable|deactivate|switch\s+off)\s+bluetooth\b', "Turning off Bluetooth."),
    (r'\b(?:turn\s+on|enable|activate|switch\s+on)\s+wi-?fi\b', "Turning on Wi-Fi."),
    (r'\b(?:turn\s+off|disable|deactivate|switch\s+off)\s+wi-?fi\b', "Turning off Wi-Fi."),
    (r'\b(?:turn\s+on|enable)\s+(?:flashlight|torch)\b', "Turning on flashlight."),
    (r'\b(?:turn\s+off|disable)\s+(?:flashlight|torch)\b', "Turning off flashlight."),

    # ── Volume Controls ──
    (r'\b(?:increase|turn\s+up|raise|higher|boost)\s+(?:(?:my|the)\s+)?(?:phone\s+|system\s+)?volume\b', "Turning up volume."),
    (r'\b(?:decrease|turn\s+down|lower|reduce)\s+(?:(?:my|the)\s+)?(?:phone\s+|system\s+)?volume\b', "Turning down volume."),
    (r'\b(?:mute|silence)\s+(?:(?:my|the)\s+)?(?:phone|system|sound|volume)\b', "Muting volume."),

    # ── App Launching (Mobile or PC) ──
    (r'\b(?:open|launch|start|run)\s+whatsapp\b', "Opening WhatsApp."),
    (r'\b(?:open|launch|start|run)\s+youtube\b', "Opening YouTube."),
    (r'\b(?:open|launch|start|run)\s+chrome\b', "Opening Chrome."),
    (r'\b(?:open|launch|start|run)\s+camera\b', "Opening camera."),
    (r'\b(?:open|launch|start|run)\s+gallery\b', "Opening Gallery."),
    (r'\b(?:open|launch|start|run)\s+settings\b', "Opening Settings."),
    (r'\b(?:open|launch|start|run)\s+notepad\b', "Opening Notepad."),
    (r'\b(?:open|launch|start|run)\s+calculator\b', "Opening Calculator."),
    (r'\b(?:open|launch|start|run)\s+spotify\b', "Opening Spotify."),
    (r'\b(?:open|launch|start|run)\s+([a-zA-Z0-9_\s]{2,25})\b', lambda m: f"Opening {m.group(1).strip().title()}."),

    # ── Close App ──
    (r'\b(?:close|quit|stop|exit|kill)\s+([a-zA-Z0-9_\s]{2,25})\b', lambda m: f"Closing {m.group(1).strip().title()}."),

    # ── Calling ──
    (r'\b(?:make\s+a\s+)?whatsapp\s+(?:video\s+)?call\s+(?:to\s+)?(.+?)$', lambda m: f"Calling {m.group(1).strip().title()} on WhatsApp."),
    (r'\b(?:call|dial)\s+([a-zA-Z0-9_\s\+]+?)$', lambda m: f"Calling {m.group(1).strip().title()}."),

    # ── Screenshot ──
    (r'\b(?:take\s+a\s+screenshot|screenshot|capture\s+screen)\b', "Taking screenshot."),

    # ── Battery / Telemetry ──
    (r'\b(?:battery|charge)\b', "Checking battery level."),
    (r'\b(?:storage|disk\s+space|free\s+space)\b', "Checking storage space."),
    (r'\b(?:ram|memory)\b', "Checking memory."),
    (r'\b(?:cpu|processor)\b', "Checking CPU status."),

    # ── Location Intelligence, GPS, Maps & Navigation ──
    (r'\b(?:where\s+am\s+i|where\s+am\s+i\s+located|what(?:\x27s|\s+is)\s+(?:my\s+)?(?:current\s+)?location|check\s+(?:my\s+)?(?:current\s+)?location|get\s+(?:my\s+)?(?:current\s+)?location|find\s+(?:my\s+)?(?:current\s+)?location|my\s+current\s+location|current\s+location|refresh\s+my\s+location|update\s+my\s+location)\b', "Checking your current location."),
    (r'\b(?:where\s+do\s+i\s+live|where(?:\x27s|\s+is)\s+my\s+home|what(?:\x27s|\s+is)\s+my\s+home\s+address)\b', "Checking your home address."),
    (r'\b(?:where(?:\x27s|\s+is)\s+my\s+(?:phone|connected\s+phone|mobile|android|redmi)|locate\s+(?:my\s+)?(?:phone|mobile)|find\s+my\s+phone|track\s+my\s+phone|phone\s+location)\b', "Locating your connected phone."),
    (r'\b(?:where(?:\x27s|\s+is)\s+my\s+(?:computer|pc|laptop)|locate\s+(?:my\s+)?(?:computer|pc|laptop)|find\s+my\s+(?:computer|pc|laptop)|computer\s+location|pc\s+location)\b', "Locating your computer."),
    (r'\b(?:show|open|view)\s+(?:(?:my\s+)?(?:current\s+|device\s+)?location\s+)?(?:on\s+(?:the\s+)?map|in\s+(?:google\s+)?maps?|on\s+map|map)\b', "Opening your location on the map."),
    (r'\b(?:navigate|directions?|route|drive|walk|cycle)\s+(?:to|towards)\s+(.+)', lambda m: f"Routing to {m.group(1).strip().title()}."),
    (r'\b(?:navigate|directions?|route)\b', "Calculating route."),
    (r'\b(?:how\s+far\s+is|distance\s+to|calculate\s+(?:the\s+)?distance\s+to)\s+(.+)', lambda m: f"Calculating distance to {m.group(1).strip().title()}."),
    (r'\b(?:find|search|show|locate)\s+(?:a\s+|an\s+|the\s+)?(?:nearest\s+|nearby\s+)?([a-zA-Z0-9_\s]+?)(?:\s+near\s+me|\s+nearby)?$', lambda m: f"Searching for nearby {m.group(1).strip()}."),
    (r'\b(?:nearby|nearest)\s+([a-zA-Z0-9_\s]+)', lambda m: f"Searching for nearby {m.group(1).strip()}."),
    (r'\b(?:save\s+(?:this\s+place|this\s+location|current\s+location|here)\s+as\s+([a-zA-Z0-9_\s]+))\b', lambda m: f"Saving location as {m.group(1).strip().title()}."),
    (r'\b(?:saved\s+places?|list\s+saved\s+places?|where\s+is\s+my\s+saved\b)', "Checking saved places."),
    (r'\b(?:exact\s+coordinates|show\s+my\s+coordinates|what\s+are\s+my\s+coordinates|my\s+coordinates)\b', "Retrieving exact GPS coordinates."),
    (r'\b(?:how\s+accurate\s+is\s+my\s+location|location\s+accuracy|location\s+source|location\s+provider|location\s+status|location\s+diagnostics)\b', "Checking location diagnostics."),

    # ── Time / Date / Weather ──
    (r'\b(?:what\s+time|what\'s\s+the\s+time|current\s+time)\b', "Checking the time."),
    (r'\b(?:what\s+date|what\'s\s+the\s+date|today\'s\s+date)\b', "Checking today's date."),
    (r'\b(?:weather|temperature|forecast)\b', "Checking the weather forecast."),
]


def get_fast_acknowledgement(user_input: str) -> Optional[str]:
    """
    Returns a short, contextually appropriate acknowledgement string
    for immediate feedback (within 1-5ms), or a sensible default.
    Never falsely claims an operation succeeded.
    """
    if not user_input or not user_input.strip():
        return None

    clean = user_input.strip()
    clean_low = clean.lower()

    # Match against fast regex patterns
    for pattern, template in _ACK_PATTERNS:
        m = re.search(pattern, clean_low)
        if m:
            if callable(template):
                try:
                    return template(m)
                except Exception:
                    continue
            return template

    # Fallback contextual acknowledgements by high-level verbs
    if any(clean_low.startswith(w) for w in ("how", "what", "who", "when", "where", "why", "which", "can you explain", "tell me about")):
        return "Looking into that."
    if any(w in clean_low for w in ("search", "find", "look up", "google")):
        return "Searching for that."
    if any(w in clean_low for w in ("create", "generate", "write", "make")):
        return "Working on that."
    if any(w in clean_low for w in ("delete", "remove", "clean")):
        return "Processing request."

    return "On it."
