import os

import json

# Load .env from project root and legacy folder
import os
from dotenv import load_dotenv

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
root_env_path = os.path.join(project_root, '.env')
legacy_env_path = os.path.join(project_root, 'legacy', '.env')

load_dotenv(root_env_path)
load_dotenv(legacy_env_path, override=True)



class MemoryType:

    USER_FACT = "user_memory"          # Declarative, factual user statements

    USER_PREFERENCE = "user_preferences" # Structured preferences

    SYSTEM_CONTEXT = "system_memory"    # Summaries, session context, internal state



class PrivacyState:

    NORMAL = "normal"

    PAUSED = "paused"    # "Pause memory" - No saving allowed

    VOLATILE = "volatile" # "Don't remember this" - Save for session only (not implemented in DB)



class Settings:

    """

    SINGLE CONFIG SOURCE (MANDATORY)

    Consolidates all legacy, module-specific, and environment-based settings.

    """

    def __init__(self):

        # --- API KEYS & BASES ---

        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

        self.OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")

        self.HF_API_KEY = os.getenv("HF_API_KEY", "")

        self.HF_MODEL_ID = os.getenv("HF_MODEL_ID", "mistralai/Mistral-7B-Instruct-v0.2")

        self.HUGGINGFACE_API_BASE = os.getenv("HUGGINGFACE_API_BASE")

        self.OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        self.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

        self.GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        
        # Support multiple keys per provider for failover
        self.OPENAI_API_KEYS = [key for key in [
            os.getenv("OPENAI_API_KEY", ""),
            os.getenv("OPENAI_API_KEY_1", ""),
            os.getenv("OPENAI_API_KEY_2", ""),
            os.getenv("OPENAI_API_KEY_3", ""),
        ] if key]
        
        self.GROQ_API_KEYS = [key for key in [
            os.getenv("GROQ_API_KEY", ""),
            os.getenv("GROQ_API_KEY_1", ""),
            os.getenv("GROQ_API_KEY_2", ""),
            os.getenv("GROQ_API_KEY_3", ""),
        ] if key]
        
        self.GEMINI_API_KEYS = [key for key in [
            os.getenv("GEMINI_API_KEY", ""),
            os.getenv("GEMINI_API_KEY_1", ""),
            os.getenv("GEMINI_API_KEY_2", ""),
            os.getenv("GEMINI_API_KEY_3", ""),
        ] if key]
        
        self.DEEPSEEK_API_KEYS = [key for key in [
            os.getenv("DEEPSEEK_API_KEY", ""),
            os.getenv("DEEPSEEK_API_KEY_1", ""),
            os.getenv("DEEPSEEK_API_KEY_2", ""),
            os.getenv("DEEPSEEK_API_KEY_3", ""),
        ] if key]
        
        self.HF_API_KEYS = [key for key in [
            os.getenv("HF_API_KEY", ""),
            os.getenv("HF_API_KEY_1", ""),
            os.getenv("HF_API_KEY_2", ""),
            os.getenv("HF_API_KEY_3", ""),
        ] if key]

        # --- SEARCH PROVIDERS (web search / live retrieval) ---
        self.SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "serpapi")

        # Multi-key array mirrors the LLM provider pattern.
        # Add SERPAPI_KEY_1, SERPAPI_KEY_2 etc. to .env for failover.
        self.SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
        raw_serpapi_keys = [
            os.getenv("SERPAPI_KEY", ""),
            os.getenv("SERPAPI_KEY_1", ""),
            os.getenv("SERPAPI_KEY_2", ""),
            os.getenv("SERPAPI_KEY_3", ""),
        ]
        # Deduplicate while preserving order
        self.SERPAPI_KEYS = list(dict.fromkeys([k.strip() for k in raw_serpapi_keys if k and k.strip()]))

        # Per-request timeout for each SerpAPI attempt (seconds).
        self.SERPAPI_TIMEOUT = int(os.getenv("SERPAPI_TIMEOUT", "10"))

        # Tavily search fallback provider
        self.TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
        raw_tavily_keys = [
            os.getenv("TAVILY_API_KEY", ""),
            os.getenv("TAVILY_API_KEY_1", ""),
            os.getenv("TAVILY_API_KEY_2", ""),
        ]
        self.TAVILY_API_KEYS = list(dict.fromkeys([k.strip() for k in raw_tavily_keys if k and k.strip()]))

        self.CALENDARIFIC_API_KEY = os.getenv("CALENDARIFIC_API_KEY", "")

        self.GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

        self.GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

        self.GROQ_FALLBACK_MODELS = ["qwen/qwen3.8-27b", "groq/compound", "groq/compound-mini"]

        self.DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

        self.DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

        self.GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

        self.NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")



        # --- ASSISTANT SETTINGS ---

        # ASSISTANT_NAME: loaded from env only (no hardcoded default).
        # Per-user runtime name is stored in CURRENT_ASSISTANT_NAME after login.
        self.ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", None) or None
        self.CURRENT_ASSISTANT_NAME = None  # Populated on login from user_preferences

        self.USE_OPENAI = os.getenv("USE_OPENAI", "true").lower() in ("true", "1", "yes")

        # When the OpenAI quota is exhausted, set OPENAI_ENABLED=false in .env
        # to skip OpenAI immediately without removing OpenAI support from code.
        # Set back to true when credits are restored.
        self.OPENAI_ENABLED = os.getenv("OPENAI_ENABLED", "true").lower() in ("true", "1", "yes")

        self.MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "12"))

        self.MAX_CONTEXT_HISTORY = 10

        self.DEFAULT_TIMEOUT = 300



        # --- VOICE ENGINE ---

        self.VOICE_ENGINE = os.getenv("VOICE_ENGINE", "pyttsx3")

        self.VOICE_RATE = int(os.getenv("VOICE_RATE", "200"))

        self.VOLUME = float(os.getenv("VOLUME", "1.0"))

        self.LANGUAGE = os.getenv("LANGUAGE", "en-in")



        # --- AUDIO STABILIZATION ---

        self.ENABLE_DUCKING = os.getenv("ENABLE_DUCKING", "false").lower() in ("true", "1", "yes")

        self.DUCKING_INTENSITY = int(os.getenv("DUCKING_INTENSITY", "5"))

        # --- HOTWORD DETECTION ---
        self.HOTWORD_WAKE_THRESHOLD = float(os.getenv("HOTWORD_WAKE_THRESHOLD", "0.35"))
        self.HOTWORD_ADAPTIVE_CALIBRATION = os.getenv("HOTWORD_ADAPTIVE_CALIBRATION", "true").lower() in ("true", "1", "yes")
        self.HOTWORD_PAUSED = False



        # --- DATABASE (PostgreSQL) ---

        self.DB_HOST = os.getenv("DB_HOST", "localhost")

        self.DB_NAME = os.getenv("DB_NAME", "nova_assistant")

        self.DB_USER = os.getenv("DB_USER", "postgres")

        self.DB_PASSWORD = os.getenv("DB_PASSWORD", "ramsathvik")

        self.DB_PORT = int(os.getenv("DB_PORT", "5432"))



        # --- EMAIL AGENT ---

        self.EMAIL_BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "modules", "email_agent")

        self.EMAIL_CREDENTIALS_FILE = os.path.join(self.EMAIL_BASE_DIR, "credentials.json")

        self.EMAIL_TOKEN_FILE = os.path.join(self.EMAIL_BASE_DIR, "token.json")

        self.EMAIL_SCOPES = [

            "https://www.googleapis.com/auth/gmail.readonly",

            "https://www.googleapis.com/auth/gmail.send"

        ]

        self.EMAIL_STOP_WORDS = ["stop mail", "stop gmail"]



        # --- MEMORY AGENT ---

        self.MemoryType = MemoryType

        self.PrivacyState = PrivacyState



        # --- RUNTIME STATE (Legacy support) ---
        self.RUNTIME_CONFIG_FILE = "runtime_config.json"
        
        # Initialize from last session
        self.CURRENT_USER_ID = self.get_last_user()
        self.CURRENT_USERNAME = None
        self.LAST_ASSISTANT_MSG = ""



    def load_runtime_config(self):

        if not os.path.exists(self.RUNTIME_CONFIG_FILE):

            return {"LAST_USER_ID": None}

        try:

            with open(self.RUNTIME_CONFIG_FILE, "r", encoding="utf-8") as f:

                return json.load(f)

        except Exception:

            return {"LAST_USER_ID": None}



    def save_runtime_config(self, cfg):

        with open(self.RUNTIME_CONFIG_FILE, "w", encoding="utf-8") as f:

            json.dump(cfg, f, indent=2)



    def set_last_user(self, user_id: int):

        cfg = self.load_runtime_config()

        cfg["LAST_USER_ID"] = user_id

        self.save_runtime_config(cfg)



    def get_last_user(self):
        """Get last user ID as integer for safe comparisons."""
        user_id = self.load_runtime_config().get("LAST_USER_ID")
        if user_id is not None:
            try:
                return int(user_id)
            except (ValueError, TypeError):
                return None
        return None



    def get_assistant_name(self):
        """
        Returns the active assistant name for the current session.
        Priority: CURRENT_ASSISTANT_NAME (per-user DB value) -> query DB via CURRENT_USER_ID -> ASSISTANT_NAME (env) -> None.
        Never returns a hardcoded 'Nova' default.
        """
        if self.CURRENT_ASSISTANT_NAME:
            return self.CURRENT_ASSISTANT_NAME
        if getattr(self, "CURRENT_USER_ID", None):
            try:
                from legacy.memory_manager import get_assistant_name_db
                name = get_assistant_name_db(self.CURRENT_USER_ID)
                if name:
                    self.CURRENT_ASSISTANT_NAME = name
                    return name
            except Exception:
                pass
        return self.ASSISTANT_NAME or None



    def __getitem__(self, key):

        """Allow dict-style access for legacy compat: CONFIG['KEY']"""

        return getattr(self, key)



    def __setitem__(self, key, value):

        """Allow dict-style access for legacy compat: CONFIG['KEY'] = value"""

        setattr(self, key, value)



    def get(self, key, default=None):

        return getattr(self, key, default)



settings = Settings()

