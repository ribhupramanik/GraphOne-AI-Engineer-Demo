import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    product_hunt_token: str = os.getenv("PRODUCT_HUNT_TOKEN", "")
    gemini_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    groq_key: str = os.getenv("GROQ_API_KEY", "")
    deepseek_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    openalex_api_key: str = os.getenv("OPENALEX_API_KEY", "")
    user_agent: str = os.getenv("USER_AGENT", "GraphOneDemo/1.0 (contact: demo@example.com)")
    concurrency: int = int(os.getenv("REQUEST_CONCURRENCY", "8"))
    host_interval: float = float(os.getenv("REQUEST_INTERVAL_SECONDS_PER_HOST", "0.35"))
