import os
import json
from dotenv import load_dotenv
load_dotenv()
_legacy_env = os.path.join(os.path.dirname(__file__), '..', 'legacy', '.env')
if os.path.exists(_legacy_env):
    load_dotenv(_legacy_env, override=True)

# Path to store local runtime settings (like remembered user)
CONFIG_FILE = "runtime_config.json"

# -----------------------------
# Load / Save runtime config
# -----------------------------
def load_runtime_config():
    if not os.path.exists(CONFIG_FILE):
        return {"LAST_USER_ID": None}

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[CONFIG] Failed to load runtime config: {e}")
        return {"LAST_USER_ID": None}


def save_runtime_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


_runtime_cfg = load_runtime_config()


def set_last_user(user_id: int):
    _runtime_cfg["LAST_USER_ID"] = user_id
    save_runtime_config(_runtime_cfg)


def get_last_user():
    return _runtime_cfg.get("LAST_USER_ID")


# -----------------------------
# STATIC CONFIG
# -----------------------------
CONFIG = {
    # API Keys
    "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
    "OPENAI_API_BASE": os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
    "HF_API_KEY": os.getenv("HF_API_KEY", ""),
    "HF_MODEL_ID": os.getenv("HF_MODEL_ID", "mistralai/Mistral-7B-Instruct-v0.2"),
    "HUGGINGFACE_API_BASE": os.getenv("HUGGINGFACE_API_BASE"),
    "OPENAI_MODEL": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    "GROQ_API_KEY": os.getenv("GROQ_API_KEY", ""),
    "GROQ_MODEL": os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b"),
    "GROQ_FALLBACK_MODELS": ["qwen/qwen3.8-27b", "groq/compound", "groq/compound-mini"],
    "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
    "GEMINI_MODEL": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", ""),
    "DEEPSEEK_MODEL": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),

    # Assistant — no hardcoded "Nova" default; name is set at login from user_preferences
    "ASSISTANT_NAME": os.getenv("ASSISTANT_NAME", None) or None,
    "CURRENT_ASSISTANT_NAME": None,  # Populated on login
    "USE_OPENAI": os.getenv("USE_OPENAI", "true").lower() in ("true", "1", "yes"),
    "MAX_HISTORY_MESSAGES": int(os.getenv("MAX_HISTORY_MESSAGES", "12")),

    # Voice engine settings
    "VOICE_ENGINE": os.getenv("VOICE_ENGINE", "pyttsx3"),
    "VOICE_RATE": int(os.getenv("VOICE_RATE", "200")),
    "VOLUME": float(os.getenv("VOLUME", "1.0")),
    "LANGUAGE": os.getenv("LANGUAGE", "en-in"),

    # PostgreSQL DB
    "DB_HOST": os.getenv("DB_HOST"),
    "DB_NAME": os.getenv("DB_NAME"),
    "DB_USER": os.getenv("DB_USER"),
    "DB_PASSWORD": os.getenv("DB_PASSWORD"),
    "DB_PORT": int(os.getenv("DB_PORT", "5432")),

    # Runtime
    "CURRENT_USER": None
}
