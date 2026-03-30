import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "Nearby Marketplace API"
    debug: bool = False
    secret_key: str = "changeme-super-secret-key"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours

    # Database
    database_url: str = "postgresql://postgres:postgres@db:5432/nearby_inventory"
    # SQLAlchemy pool — tune for Docker / internal deployment (see HARDENING_REPORT.md)
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 1800
    db_pool_timeout: float = 30.0

    # Uploads
    upload_dir: str = "/app/uploads"
    max_upload_size_mb: int = 10

    # Search defaults — location-first discovery (see item_service search defaults)
    default_search_radius_km: float = 10.0
    max_search_radius_km: float = 100.0
    search_max_page_size: int = 100  # cap for /api/search page_size
    search_bounds_max_page_size: int = 150  # cap for /api/search/bounds (map)
    # Reject map queries over huge viewports; bounds search also caps SQL candidates (item_service)
    search_bounds_max_degrees_span: float = 6.0
    search_bounds_max_sql_candidates: int = 8000
    # Radius search — max rows after bbox prefilter before Haversine (matches bounds safeguard)
    search_radius_max_sql_candidates: int = 8000

    # Conversation list — upper bound on rows returned (inbox payload)
    conversation_inbox_max_rows: int = 400
    conversation_messages_max_limit: int = 250
    # Saved listings — cap list payload (mobile/web pass ?limit=)
    favorites_max_page_size: int = 200

    # Similarity (non-core): brute-force scan cap; newest listings first when truncated
    similarity_max_brute_force_items: int = 4000

    # Listing text embeddings (Phase 1+) — separate from AI_SERVICE / image OpenCLIP
    # mock: deterministic hash-based vectors (tests, offline). sentence_transformers: E5 multilingual.
    text_embedding_provider: str = "sentence_transformers"
    text_embedding_model_name: str = "intfloat/multilingual-e5-large"
    # cpu | cuda | auto (cuda if torch sees a GPU, else cpu)
    text_embedding_device: str = "cpu"

    # Phase 2 — text vector search (query embedding + app-side cosine; pgvector-ready abstraction)
    enable_text_vector_search: bool = True
    search_vector_candidate_cap: int = 500
    search_hybrid_lexical_weight: float = 0.35
    search_hybrid_vector_weight: float = 0.65
    search_hybrid_exact_title_floor: float = 0.92

    # Degrade non-core features under load (core API stays registered)
    enable_similarity_search: bool = True
    enable_ai_suggest_tags: bool = True

    # Hints for polling clients (also exposed via GET /api/settings)
    chat_poll_inbox_interval_ms: int = 60_000
    chat_poll_thread_interval_ms: int = 35_000

    # Slow-request warning threshold (ms) for operational logging
    log_slow_request_ms: float = 2500.0

    # AI service — env vars always win (avoids .env override in mounted volumes)
    ai_service: str = "openclip"  # "openclip" | "mock" (mock = explicit fallback)
    ai_device: str = "cpu"       # "cpu" | "cuda" | "auto" (auto = cuda if available)

    # Email verification — disable for testing/development
    email_verification_enabled: bool = True  # Set to False to bypass all verification checks

    # CORS — comma-separated origins appended to the built-in local dev list (see main.py)
    cors_extra_origins: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False

    @model_validator(mode="after")
    def _ai_from_env(self) -> "Settings":
        """Force AI_SERVICE and AI_DEVICE from os.environ when set (Docker env_file/.env can override otherwise)."""
        if "AI_SERVICE" in os.environ:
            self.ai_service = os.environ["AI_SERVICE"].strip()
        if "AI_DEVICE" in os.environ:
            self.ai_device = os.environ["AI_DEVICE"].strip()
        if "TEXT_EMBEDDING_PROVIDER" in os.environ:
            self.text_embedding_provider = os.environ["TEXT_EMBEDDING_PROVIDER"].strip()
        if "TEXT_EMBEDDING_MODEL_NAME" in os.environ:
            self.text_embedding_model_name = os.environ["TEXT_EMBEDDING_MODEL_NAME"].strip()
        if "TEXT_EMBEDDING_DEVICE" in os.environ:
            self.text_embedding_device = os.environ["TEXT_EMBEDDING_DEVICE"].strip()
        return self


@lru_cache()
def get_settings() -> Settings:
    return Settings()
