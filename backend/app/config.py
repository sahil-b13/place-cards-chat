import os
from dataclasses import dataclass, field


def _bool(v: str | None, default: bool) -> bool:
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    mock_mode: bool = True
    # Mock fixtures are picked by this setting or by request order, never by filename.
    # Empty = cycle leopold, gateway, ambiguous, generic by photo order.
    # One name = every photo; comma list = per photo index (cycles).
    mock_scenario: str = ""
    vision_provider: str = "gemini"  # gemini | anthropic
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"  # check Google's current model list; override via GEMINI_MODEL
    anthropic_api_key: str = ""
    vision_model: str = "claude-haiku-5-5"
    google_places_api_key: str = ""
    allowed_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173"])
    cache_ttl_seconds: int = 86400
    max_images: int = 10
    max_image_bytes: int = 2 * 1024 * 1024
    rate_limit_per_minute: int = 20  # POST /api/* per client IP; 0 disables
    trust_proxy: bool = False  # true behind Render/Railway/Fly so the real client IP is read from X-Forwarded-For
    log_level: str = "INFO"


def load_settings() -> Settings:
    """Read settings from env (and backend/.env if present, without overriding real env)."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173")
    return Settings(
        mock_mode=_bool(os.environ.get("MOCK_MODE"), True),
        mock_scenario=os.environ.get("MOCK_SCENARIO", "").strip(),
        vision_provider=os.environ.get("VISION_PROVIDER", "gemini").strip().lower() or "gemini",
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite",
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        vision_model=os.environ.get("VISION_MODEL", "claude-haiku-5-5").strip() or "claude-haiku-5-5",
        google_places_api_key=os.environ.get("GOOGLE_PLACES_API_KEY", ""),
        allowed_origins=[o.strip() for o in origins.split(",") if o.strip()],
        cache_ttl_seconds=int(os.environ.get("CACHE_TTL_SECONDS", "86400")),
        rate_limit_per_minute=int(os.environ.get("RATE_LIMIT_PER_MINUTE", "20")),
        trust_proxy=_bool(os.environ.get("TRUST_PROXY"), False),
        log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper() or "INFO",
    )
