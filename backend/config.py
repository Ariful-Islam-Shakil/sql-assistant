import os
from dotenv import load_dotenv

# Load .env file once at import time
load_dotenv()

class Settings:
    """Application configuration loaded from environment variables.

    All configurable values are kept here so that the rest of the codebase
    can import a single source of truth. Default fall‑backs are provided for
    development; production should set the corresponding variables in the
    ``.env`` file.
    """

    # Provider selection – currently supports "ollama"; other providers can be added later
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama").strip().lower()

    # Ollama settings
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip()

    # Model names – two separate models for planning and coding
    PLANNER_MODEL: str = os.getenv("PLANNER_MODEL", "llama3.1:8b-instruct-q8_0").strip()
    CODER_MODEL: str = os.getenv("CODER_MODEL", "qwen2.5-coder:7b-instruct-q8_0").strip()

    # Database connection string – must be provided by the user
    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()

    # Optional API keys for other providers (place‑holders)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "").strip()
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()

    # Logging level (INFO, DEBUG, etc.)
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").strip().upper()

    @classmethod
    def as_dict(cls) -> dict:
        """Return a dictionary representation useful for debugging or UI display."""
        return {
            "LLM_PROVIDER": cls.LLM_PROVIDER,
            "OLLAMA_HOST": cls.OLLAMA_HOST,
            "PLANNER_MODEL": cls.PLANNER_MODEL,
            "CODER_MODEL": cls.CODER_MODEL,
            "DATABASE_URL": "<provided>" if cls.DATABASE_URL else "",
            "LOG_LEVEL": cls.LOG_LEVEL,
        }
