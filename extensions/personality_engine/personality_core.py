"""
Smart Assistant Personality Core
Defines assistant identity, core personality traits, per-account presets,
and conversational response generation with strict anti-repetition guarantees.
"""

from __future__ import annotations

import logging
import random
import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("assistant.personality")

@dataclass
class PersonalityProfile:
    """Per-user personality profile"""
    name: str
    traits: List[str]
    tone: str
    style: str
    greeting_style: str
    error_style: str
    confirmation_style: str
    proactive_style: str
    preset: str = "friendly"
    formality_pct: int = 50
    warmth_pct: int = 60
    humor_pct: int = 60
    directness_pct: int = 60
    verbosity: str = "concise"
    proactivity: str = "suggestive"
    language: str = "en"


CANONICAL_PRESETS: Dict[str, Dict[str, Any]] = {
    "professional": {
        "traits": ["precise", "composed", "concise", "efficient", "respectful"],
        "tone": "composed and professional",
        "style": "clear, professional, structured, and concise",
        "greeting_style": "Standing by for your instructions.",
        "error_style": "An issue occurred while processing the request.",
        "confirmation_style": "Understood. Proceeding.",
        "proactive_style": "I am available if you require assistance with your tasks.",
    },
    "friendly": {
        "traits": ["warm", "approachable", "helpful", "encouraging", "empathetic"],
        "tone": "warm and approachable",
        "style": "friendly, conversational, natural, and supportive",
        "greeting_style": "Hello! Ready to help you today.",
        "error_style": "Sorry about that, something didn't go quite right.",
        "confirmation_style": "You got it!",
        "proactive_style": "Need anything, or should I suggest something useful?",
    },
    "witty": {
        "traits": ["clever", "playful", "witty", "sharp", "engaging"],
        "tone": "clever and slightly humorous",
        "style": "playful and clever with dry humor when appropriate, never forced or repetitive",
        "greeting_style": "Ready when you are. Let's make things happen.",
        "error_style": "Well, that didn't go according to plan.",
        "confirmation_style": "On it.",
        "proactive_style": "Ready for your next challenge, or should I find one for you?",
    },
    "analytical": {
        "traits": ["analytical", "methodical", "logical", "detailed", "objective"],
        "tone": "analytical and objective",
        "style": "structured reasoning, logical explanations, and clear distinctions",
        "greeting_style": "System initialized and ready for analysis.",
        "error_style": "Execution terminated due to an unresolved parameter.",
        "confirmation_style": "Parameters verified. Proceeding.",
        "proactive_style": "Would you like a diagnostic review of recent workspace items?",
    },
    "minimal": {
        "traits": ["direct", "laconic", "crisp", "efficient"],
        "tone": "direct and minimal",
        "style": "ultra-concise, direct answers with zero fluff or conversational filler",
        "greeting_style": "Ready.",
        "error_style": "Command failed.",
        "confirmation_style": "Done.",
        "proactive_style": "Standing by.",
    },
    "energetic": {
        "traits": ["expressive", "enthusiastic", "upbeat", "dynamic", "motivating"],
        "tone": "enthusiastic and upbeat",
        "style": "dynamic, engaging, and encouraging without being annoying",
        "greeting_style": "Hey there! What awesome project are we working on today?",
        "error_style": "Oops! Hit a bump there, but ready to try again!",
        "confirmation_style": "Awesome, let's do it!",
        "proactive_style": "I'm fired up and ready for whatever's next!",
    },
}

OFFLINE_JOKES: Dict[str, List[str]] = {
    "tech": [
        "There are 10 types of people in the world: those who understand binary, and those who don't.",
        "A SQL query walks into a bar, walks up to two tables and asks, 'Can I join you?'",
        "Why do programmers always mix up Halloween and Christmas? Because Oct 31 equals Dec 25!",
        "There's no place like 127.0.0.1.",
        "A programmer's wife tells him, 'Go to the store and get a loaf of bread. If they have eggs, get a dozen.' He returns with 12 loaves of bread.",
        "How many programmers does it take to change a lightbulb? None, that's a hardware problem.",
        "Debugging: being the detective in a crime movie where you are also the murderer.",
        "An SEO expert walks into a bar, pub, tavern, grill, brewery, beer, whiskey...",
        "Why did the JavaScript developer wear glasses? Because they didn't C#.",
    ],
    "science": [
        "Why can't you trust an atom? Because they make up everything!",
        "A neutron walks into a café and asks how much for a drink. The barista says, 'For you, no charge!'",
        "Schrödinger's cat walks into a bar... and doesn't.",
        "Why did the white bear dissolve in water? Because it was polar!",
        "Two electrons are sitting in a car. One says, 'Are you sure you have the energy for this?' The other replies, 'I'm positive!'",
        "What did the biologist wear to impress their date? Designer genes.",
    ],
    "math": [
        "Why was the equal sign so humble? Because it knew it wasn't less than or greater than anyone else.",
        "Parallel lines have so much in common. It's a shame they'll never meet.",
        "Why should you never argue with a 90-degree angle? Because it's always right!",
        "Infinitely many mathematicians walk into a bar. The first orders a pint, the second half a pint, the third a quarter pint. The bartender pours two pints and says, 'Know your limits!'",
        "Why do plants hate math? Because it gives them square roots.",
    ],
    "general": [
        "Why don't skeletons fight each other? They don't have the guts.",
        "I told my suitcase there will be no vacation this year. Now I'm dealing with emotional baggage.",
        "What do you call fake spaghetti? An impasta!",
        "Why did the scarecrow win an award? Because he was outstanding in his field.",
        "I'm reading a book on anti-gravity. I just can't put it down.",
        "How do you organize a space party? You planet.",
    ],
}


def normalize_preset_name(raw: Optional[str]) -> str:
    """Normalize any user-provided preset string to a canonical preset key."""
    if not raw:
        return "friendly"
    s = str(raw).lower().strip()
    if any(k in s for k in ("prof", "executive", "formal")):
        return "professional"
    if any(k in s for k in ("witt", "clever", "muse", "humor", "playful")):
        return "witty"
    if any(k in s for k in ("analy", "tech", "logical")):
        return "analytical"
    if any(k in s for k in ("mini", "terse", "brief", "laconic")):
        return "minimal"
    if any(k in s for k in ("energ", "upbeat", "expressive")):
        return "energetic"
    return "friendly"


class PersonalityCore:
    """Core personality management with strict per-account isolation."""

    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger("assistant.personality")
        self._user_patterns: Dict[str, Any] = {}
        self._interaction_count = 0
        self._user_told_jokes: Dict[int, List[str]] = {}
        self._user_joke_category_idx: Dict[int, int] = {}
        self._user_profiles_cache: Dict[int, PersonalityProfile] = {}

        # Default context variations
        self._context_variations = {
            "system": {
                "style": "direct, efficient",
                "confirmation_style": "Done.",
                "error_style": "System issue detected."
            },
            "reminder": {
                "style": "caring, attentive",
                "confirmation_style": "I'll remind you.",
                "error_style": "Reminder setup failed."
            },
            "browser": {
                "style": "helpful, guiding",
                "confirmation_style": "Opening that for you.",
                "error_style": "Browser action failed."
            },
            "ai": {
                "style": "thoughtful, conversational",
                "confirmation_style": "Let me think about that.",
                "error_style": "I couldn't process that."
            }
        }

        # Response variations
        self._response_variations = {
            "greetings": [
                "Ready to help.",
                "I'm here.",
                "What can I do?",
                "Listening."
            ],
            "confirmations": [
                "Got it.",
                "Done.",
                "Understood.",
                "On it."
            ],
            "errors": [
                "That didn't go as planned.",
                "Something went wrong.",
                "Let me try that differently.",
                "Technical issue encountered."
            ],
            "proactive": [
                "Need anything, or should I suggest something?",
                "Anything else I can help with?",
                "Want me to suggest something useful?",
                "Ready for your next command?"
            ]
        }

    def _resolve_user_id(self, user_id: Any = None) -> int:
        """Resolve numeric user ID from parameter, active settings, or AssistantCore."""
        if isinstance(user_id, int) and user_id > 0:
            return user_id
        if isinstance(user_id, str) and user_id.strip().isdigit():
            return int(user_id.strip())
        if isinstance(user_id, dict):
            uid = user_id.get("user_id") or user_id.get("id")
            if uid and str(uid).isdigit():
                return int(uid)

        try:
            from instance.config import settings as _cfg
            curr = getattr(_cfg, "CURRENT_USER_ID", None)
            if curr and int(curr) > 0:
                return int(curr)
        except Exception:
            pass

        try:
            from core.assistant_core import assistant_core
            ctx = assistant_core.get_user_context()
            if ctx.get("user_id"):
                return int(ctx["user_id"])
        except Exception:
            pass

        return 1

    def get_personality(self, context: str | None = None, user_id: int | None = None) -> PersonalityProfile:
        """Get personality profile for the specific user, optionally context-adjusted."""
        eff_uid = self._resolve_user_id(user_id)

        # Retrieve per-user preferences from Centralized Configuration Service
        asst_name = "Friday"
        raw_preset = "friendly"
        formality = 50
        warmth = 60
        humor = 60
        directness = 60
        verbosity = "concise"
        proactivity = "suggestive"
        language = "en"

        try:
            from core.configuration_service import get_configuration_service
            cfg = get_configuration_service()
            asst_name = cfg.get_preference(eff_uid, "assistant_name") or cfg.get_preference(eff_uid, "CURRENT_ASSISTANT_NAME")
            raw_preset = cfg.get_preference(eff_uid, "personality_preset") or cfg.get_preference(eff_uid, "persona") or "friendly"
            
            f_val = cfg.get_preference(eff_uid, "formality_pct")
            if f_val is not None:
                formality = int(f_val) if str(f_val).isdigit() else 50
                
            w_val = cfg.get_preference(eff_uid, "warmth_pct")
            if w_val is not None:
                warmth = int(w_val) if str(w_val).isdigit() else 60
                
            h_val = cfg.get_preference(eff_uid, "humor_pct")
            if h_val is not None:
                humor = int(h_val) if str(h_val).isdigit() else 60
                
            d_val = cfg.get_preference(eff_uid, "directness_pct")
            if d_val is not None:
                directness = int(d_val) if str(d_val).isdigit() else 60

            v_val = cfg.get_preference(eff_uid, "verbosity")
            if v_val:
                verbosity = str(v_val).strip().lower()

            p_val = cfg.get_preference(eff_uid, "proactivity") or cfg.get_preference(eff_uid, "proactivity_pct")
            if p_val:
                proactivity = str(p_val).strip().lower()

            lang_val = cfg.get_preference(eff_uid, "language") or cfg.get_preference(eff_uid, "assistant_language")
            if lang_val:
                language = str(lang_val).strip()
        except Exception:
            pass

        if not asst_name or not str(asst_name).strip():
            try:
                from instance.config import settings as _cfg
                asst_name = _cfg.get_assistant_name() or "Friday"
            except Exception:
                asst_name = "Friday"

        canonical_key = normalize_preset_name(raw_preset)
        preset_info = CANONICAL_PRESETS.get(canonical_key, CANONICAL_PRESETS["friendly"])

        # Dynamically tailor traits based on numerical slider values
        traits = list(preset_info["traits"])
        if humor > 70 and "witty" not in traits:
            traits.append("witty")
        if formality > 70 and "formal" not in traits:
            traits.append("formal")
        elif formality < 30 and "casual" not in traits:
            traits.append("casual")
        if warmth > 70 and "warm" not in traits:
            traits.append("warm")
        if directness > 70 and "direct" not in traits:
            traits.append("direct")

        profile = PersonalityProfile(
            name=str(asst_name).strip(),
            traits=traits,
            tone=preset_info["tone"],
            style=preset_info["style"],
            greeting_style=preset_info["greeting_style"],
            error_style=preset_info["error_style"],
            confirmation_style=preset_info["confirmation_style"],
            proactive_style=preset_info["proactive_style"],
            preset=canonical_key,
            formality_pct=formality,
            warmth_pct=warmth,
            humor_pct=humor,
            directness_pct=directness,
            verbosity=verbosity,
            proactivity=proactivity,
            language=language
        )

        if context and context in self._context_variations:
            var = self._context_variations[context]
            profile.style = var.get("style", profile.style)
            profile.confirmation_style = var.get("confirmation_style", profile.confirmation_style)
            profile.error_style = var.get("error_style", profile.error_style)

        return profile

    def build_prompt_directives(self, user_id: int | None = None) -> str:
        """
        Generate behavioral prompt directives reflecting the active user's
        personality profile and anti-repetition rules for LLM generation.
        """
        profile = self.get_personality(user_id=user_id)
        directives = [
            f"Assistant Identity: You are {profile.name}, with a {profile.tone} presence.",
            f"Personality Preset: {profile.preset.capitalize()} (traits: {', '.join(profile.traits)}).",
            f"Formality Level: {profile.formality_pct}% ({'formal' if profile.formality_pct > 66 else ('casual' if profile.formality_pct < 33 else 'balanced')}).",
            f"Warmth & Approachability: {profile.warmth_pct}%.",
            f"Humor & Playfulness: {profile.humor_pct}%.",
            f"Directness: {profile.directness_pct}%.",
            f"Verbosity Preference: {profile.verbosity.capitalize()}.",
        ]

        if profile.language and str(profile.language).lower() not in ("english", "en", "default", "none", ""):
            directives.append(f"Language: Reply in {profile.language.capitalize()}.")

        # Preset-specific operational instructions
        if profile.preset == "professional":
            directives.append("Tone Guidance: Maintain a polished, composed, and dignified executive presence. Focus on clarity and efficiency.")
        elif profile.preset == "witty":
            directives.append("Tone Guidance: Incorporate clever, sharp wit and subtle humor when appropriate, but never force jokes into serious requests.")
        elif profile.preset == "minimal":
            directives.append("Tone Guidance: Be extremely concise and direct. Answer questions with zero conversational filler or unprompted elaboration.")
        elif profile.preset == "analytical":
            directives.append("Tone Guidance: Use structured, logical reasoning. Clearly distinguish facts from inferences and offer precise explanations.")
        elif profile.preset == "energetic":
            directives.append("Tone Guidance: Be expressive, upbeat, and motivating without becoming repetitive or over-the-top.")
        else:
            directives.append("Tone Guidance: Be warm, approachable, natural, and helpful.")

        # Anti-repetition and contextual continuity rules
        directives.extend([
            "Conversation Continuity & Anti-Repetition:",
            "- Review recent conversation turns in Current Context carefully.",
            "- NEVER repeat the same joke, anecdote, canned response, or stock phrasing you recently gave.",
            "- If the user asks for 'another one', 'tell me some other joke', or 'a different kind', switch topics completely and provide a genuinely fresh response.",
            "- If the user asks to stop joking, be serious, or asks a real question, immediately drop humor and answer seriously.",
            "- If the user asks 'What are you doing?', give a natural response grounded in your actual current assistant state."
        ])

        return "\n[BEHAVIORAL & PERSONA SETTINGS]\n" + "\n".join(f"- {d}" for d in directives) + "\n"

    def get_offline_joke(self, user_id: int | None = None, requested_text: str = "", exclude_jokes: Optional[List[str]] = None) -> str:
        """
        Select a fresh, varied offline joke for the specific user.
        Rotates through categories and ensures no consecutive repetitions.
        """
        eff_uid = self._resolve_user_id(user_id)
        told = self._user_told_jokes.setdefault(eff_uid, [])
        excluded = set(told)
        if exclude_jokes:
            excluded.update(exclude_jokes)

        # Inspect if user specifically requested a category
        low = requested_text.lower()
        req_cat = None
        if any(w in low for w in ("tech", "programming", "code", "coder", "programmer", "software")):
            req_cat = "tech"
        elif any(w in low for w in ("science", "physics", "chemistry", "biology", "atom")):
            req_cat = "science"
        elif any(w in low for w in ("math", "geometry", "calculus", "algebra", "number")):
            req_cat = "math"

        categories = ["tech", "science", "math", "general"]
        if req_cat and req_cat in OFFLINE_JOKES:
            cat_candidates = [j for j in OFFLINE_JOKES[req_cat] if j not in excluded]
            if cat_candidates:
                chosen = cat_candidates[0]
                told.append(chosen)
                return chosen

        # Rotate through categories to guarantee variety on subsequent requests ("another one")
        cur_idx = self._user_joke_category_idx.get(eff_uid, 0)
        ordered_cats = categories[cur_idx:] + categories[:cur_idx]
        self._user_joke_category_idx[eff_uid] = (cur_idx + 1) % len(categories)

        for cat in ordered_cats:
            available = [j for j in OFFLINE_JOKES[cat] if j not in excluded]
            if available:
                chosen = available[0]
                told.append(chosen)
                return chosen

        # If all jokes in all categories were already told, clear history except the very last one
        last_told = told[-1] if told else None
        self._user_told_jokes[eff_uid] = [last_told] if last_told else []
        for cat in ordered_cats:
            available = [j for j in OFFLINE_JOKES[cat] if j != last_told]
            if available:
                chosen = available[0]
                self._user_told_jokes[eff_uid].append(chosen)
                return chosen

        return OFFLINE_JOKES["general"][0]

    def get_offline_conversational_response(
        self,
        user_input: str,
        user_id: int | None = None,
        context: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate a persona-aligned local conversational response when LLM providers are offline.
        """
        eff_uid = self._resolve_user_id(user_id)
        profile = self.get_personality(user_id=eff_uid)
        clean = re.sub(r'[,.?!]+', '', user_input.strip().lower()).strip()
        clean_no_name = re.sub(rf'\b(?:{re.escape(profile.name.lower())}|friday|trevon|nova|jarvis|assistant)\b', '', clean).strip()

        # 1. Stop joking / Serious tone request
        if any(p in clean_no_name for p in ("stop joking", "be serious", "no more jokes", "stop making jokes", "answer seriously")):
            if profile.preset == "minimal":
                return "Understood. Standing by for instructions."
            elif profile.preset == "professional":
                return "Understood. We will keep our interaction strictly professional. How may I assist you?"
            return "Understood, I'll keep it serious. What can I help you with?"

        # 2. Jokes and Humor Requests
        if any(p in clean_no_name for p in ("tell me a joke", "make me laugh", "say something funny", "tell me another joke", "tell me some other joke", "another one", "a different kind", "another joke")):
            joke = self.get_offline_joke(user_id=eff_uid, requested_text=clean_no_name)
            if profile.preset == "witty":
                return f"Here's one for you: {joke}"
            elif profile.preset == "minimal":
                return joke
            elif profile.preset == "energetic":
                return f"Oh, I love this one! {joke}"
            return joke

        # 3. What are you doing / Current activity (Grounded in real state)
        if any(p in clean_no_name for p in ("what are you doing", "what're you doing", "what are you up to", "what's your status")):
            try:
                from core.task_execution_manager import get_task_execution_manager
                tem = get_task_execution_manager()
                active = tem.list_tasks(user_id=eff_uid)
                if active:
                    return tem.get_active_tasks_summary(user_id=eff_uid)
            except Exception:
                pass

            if profile.preset == "minimal":
                return "Standing by for instructions."
            elif profile.preset == "professional":
                return f"I am currently standing by and monitoring the workspace for your requests."
            elif profile.preset == "witty":
                return f"Just here pondering the digital cosmos and waiting for your next command. What's on your mind?"
            elif profile.preset == "analytical":
                return f"System idle. All operational modules running nominally and ready for input."
            return f"I'm right here and ready to help. What can I do for you today?"

        # 4. Identity inquiries
        if any(p in clean for p in ("who are you", "what is your name", "what's your name", "introduce yourself")):
            if profile.preset == "professional":
                return f"I am {profile.name}, your personal assistant configured to streamline your workspace and desktop operations."
            elif profile.preset == "witty":
                return f"I'm {profile.name}—your AI co-pilot, troubleshooter, and occasional teller of questionable jokes."
            elif profile.preset == "minimal":
                return f"I am {profile.name}."
            return f"I am {profile.name}, your personal desktop assistant. How can I help you today?"

        # 5. Greetings
        if clean in ("hey", "hello", "hi") or clean_no_name in ("hey", "hello", "hi"):
            return profile.greeting_style

        return None

    def get_response_variation(self, response_type: str) -> str:
        """Get a varied response to avoid repetition"""
        variations = self._response_variations.get(response_type, [])
        if variations:
            index = self._interaction_count % len(variations)
            self._interaction_count += 1
            return variations[index]
        return ""

    def adapt_to_user_pattern(self, pattern_type: str, frequency: int):
        """Adapt personality based on user behavior patterns"""
        self._user_patterns[pattern_type] = {
            "frequency": frequency,
            "last_seen": self._interaction_count
        }

    def should_be_proactive(self, idle_time: int) -> bool:
        """Determine if assistant should be proactive based on personality and context"""
        return idle_time > 1200

    def get_proactive_suggestion(self, context: Dict[str, Any]) -> str | None:
        """Get personality-driven proactive suggestion"""
        for pattern, data in self._user_patterns.items():
            if data.get("frequency", 0) > 3:
                if pattern == "youtube":
                    return "You use YouTube often. Want me to open it?"
                elif pattern == "music":
                    return "Time for some music?"
                elif pattern == "search":
                    return "Need help finding something?"
        return self.get_response_variation("proactive")

    def format_greeting(self, user_id: int | None = None) -> str:
        """Get personality-appropriate greeting for user"""
        profile = self.get_personality(user_id=user_id)
        return profile.greeting_style

    def format_confirmation(self, context: str | None = None, user_id: int | None = None) -> str:
        """Get personality-appropriate confirmation for user"""
        profile = self.get_personality(context, user_id=user_id)
        return profile.confirmation_style

    def format_error(self, context: str | None = None, error_detail: str = "", user_id: int | None = None) -> str:
        """Get personality-appropriate error message for user"""
        profile = self.get_personality(context, user_id=user_id)
        base_error = profile.error_style
        return f"{base_error} {error_detail}".strip() if error_detail else base_error


# Global personality instance
_personality_core = None

def get_personality() -> PersonalityCore:
    """Get the global personality core instance"""
    global _personality_core
    if _personality_core is None:
        _personality_core = PersonalityCore()
    return _personality_core

def reset_personality():
    """Reset the global personality instance (for testing)"""
    global _personality_core
    _personality_core = None

