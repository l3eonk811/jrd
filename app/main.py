import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from starlette.requests import Request

from app.config import get_settings
from app.routes import admin, auth, debug, items, search, similarity, upload, favorites, conversations, reports, ai_tags, blocks, provider_ratings, public_settings

settings = get_settings()
log = logging.getLogger(__name__)


def _check_alembic_revision() -> dict:
    """Return current and head Alembic revisions without running migrations."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext
        from app.database import engine

        cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(cfg)
        head_rev = script.get_current_head()

        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            current_rev = ctx.get_current_revision()

        return {
            "current_revision": current_rev,
            "head_revision": head_rev,
            "is_up_to_date": current_rev == head_rev,
        }
    except Exception as e:
        return {"error": str(e)}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from app.services.listing_media_storage import cleanup_old_temp_files

        n = cleanup_old_temp_files()
        if n:
            log.info("temp_upload_cleanup removed %s stale file(s)", n)
    except Exception as e:
        log.warning("temp_upload_cleanup_failed: %s", e)

    info = _check_alembic_revision()
    if "error" in info:
        log.error("migration_check FAILED: %s", info["error"])
    elif not info["is_up_to_date"]:
        log.warning(
            "migration_check BEHIND: db=%s head=%s — run 'alembic upgrade head'",
            info["current_revision"], info["head_revision"],
        )
    else:
        log.info(
            "migration_check OK: revision=%s", info["current_revision"],
        )

    # AI backend: log resolved config (but don't block startup with model downloads)
    import os
    env_ai = os.environ.get("AI_SERVICE", "(not set)")
    env_dev = os.environ.get("AI_DEVICE", "(not set)")
    log.info(
        "AI config: env AI_SERVICE=%s AI_DEVICE=%s | resolved ai_service=%s ai_device=%s",
        env_ai, env_dev, settings.ai_service, settings.ai_device,
    )
    
    # Pre-warm AI service in background (truly non-blocking)
    def warmup_ai_sync():
        """Warmup AI in a separate thread to avoid blocking the event loop."""
        import time
        import threading
        time.sleep(5)  # Let app fully start first
        try:
            from app.ai import get_ai_service
            backend = settings.ai_service
            device = settings.ai_device
            log.info("AI warmup: starting background initialization for %s on %s", backend, device)
            ai = get_ai_service(backend, device=device)
            if backend.lower() == "openclip":
                # Note: health_check is async, so we can't call it from thread
                # Model will load on first use instead
                log.info("AI warmup: openclip service created (model will load on first use)")
            else:
                log.info("AI warmup: %s ready", type(ai).__name__)
        except Exception as e:
            log.warning("AI warmup failed (non-blocking): %s", e)
    
    import threading
    warmup_thread = threading.Thread(target=warmup_ai_sync, daemon=True)
    warmup_thread.start()

    yield


def _db_ping() -> str:
    """Return ok if the app can open a session and run SELECT 1."""
    try:
        from sqlalchemy import text
        from app.database import SessionLocal

        s = SessionLocal()
        try:
            s.execute(text("SELECT 1"))
            return "ok"
        finally:
            s.close()
    except Exception as e:
        log.warning("db_ping_failed: %s", e)
        return "error"


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API for a discovery-first local marketplace and services — listings, maps, and messaging.",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

def _cors_allow_origins() -> list[str]:
    """Browser origins allowed for cross-origin API calls (local Next.js, Expo Web, Docker web)."""
    # Multiple Next.js apps (main frontend + admin-panel) often use 3000, 3001, … when run together.
    hosts = ("localhost", "127.0.0.1")
    dev_next_ports = (3000, 3001, 3002, 3003, 3004, 3005)
    base = [f"http://{h}:{p}" for h in hosts for p in dev_next_ports]
    base += [
        "http://localhost:8081",
        "http://127.0.0.1:8081",
        "http://frontend:3000",
    ]
    extra = settings.cors_extra_origins.strip()
    if not extra:
        return base
    merged = base + [o.strip() for o in extra.split(",") if o.strip()]
    # dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for o in merged:
        if o not in seen:
            seen.add(o)
            out.append(o)
    return out


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def slow_request_logging(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    dt_ms = (time.perf_counter() - t0) * 1000
    if dt_ms >= settings.log_slow_request_ms:
        log.warning(
            "slow_request path=%s method=%s ms=%.0f status=%s",
            request.url.path,
            request.method,
            dt_ms,
            getattr(response, "status_code", "?"),
        )
    return response


app.include_router(auth.router)
app.include_router(public_settings.router)
app.include_router(admin.router)
app.include_router(debug.router)
app.include_router(items.router)
app.include_router(search.router)
app.include_router(similarity.router)
app.include_router(upload.router)
app.include_router(favorites.router)
app.include_router(conversations.router)
app.include_router(blocks.router)
app.include_router(provider_ratings.router)
app.include_router(reports.router)
app.include_router(ai_tags.router)

uploads_path = Path(settings.upload_dir)
uploads_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_path)), name="uploads")


@app.get("/health", tags=["health"])
def health_check():
    """Liveness + DB connectivity + migration state (for Docker / reverse proxies)."""
    info = _check_alembic_revision()
    db_state = _db_ping()
    db_ok = db_state == "ok"
    mig_ok = bool(info.get("is_up_to_date"))
    ok = db_ok and mig_ok and "error" not in info
    return {
        "status": "ok" if ok else "degraded",
        "service": settings.app_name,
        "database": db_state,
        "migrations": info,
        "ai_backend": settings.ai_service,
        "ai_device": settings.ai_device,
        "flags": {
            "similarity_search": settings.enable_similarity_search,
            "ai_suggest_tags": settings.enable_ai_suggest_tags,
        },
    }
