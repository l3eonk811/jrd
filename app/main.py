import logging
import time
import subprocess
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from starlette.requests import Request

from app.config import get_settings
from app.routes import admin, auth, debug, items, search, similarity, upload, favorites, conversations, reports, ai_tags, blocks, provider_ratings, public_settings

settings = get_settings()
log = logging.getLogger(**name**)

def run_migrations():
try:
subprocess.run(["alembic", "upgrade", "head"], check=True)
log.info("Migrations applied successfully")
except Exception as e:
log.error("Migration failed: %s", e)

def _check_alembic_revision() -> dict:
try:
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from app.database import engine

```
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
```

@asynccontextmanager
async def lifespan(app: FastAPI):

```
# 🔥 هنا التعديل المهم
run_migrations()

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
        "migration_check BEHIND: db=%s head=%s",
        info["current_revision"], info["head_revision"],
    )
else:
    log.info("migration_check OK: revision=%s", info["current_revision"])

yield
```

def _db_ping() -> str:
try:
from sqlalchemy import text
from app.database import SessionLocal

```
    s = SessionLocal()
    try:
        s.execute(text("SELECT 1"))
        return "ok"
    finally:
        s.close()
except Exception as e:
    log.warning("db_ping_failed: %s", e)
    return "error"
```

app = FastAPI(
title=settings.app_name,
version="0.1.0",
docs_url="/docs",
lifespan=lifespan,
)

app.add_middleware(
CORSMiddleware,
allow_origins=["*"],
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],
)

@app.middleware("http")
async def slow_request_logging(request: Request, call_next):
t0 = time.perf_counter()
response = await call_next(request)
dt_ms = (time.perf_counter() - t0) * 1000
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

@app.get("/health")
def health_check():
info = _check_alembic_revision()
db_state = _db_ping()
return {
"status": "ok",
"database": db_state,
"migrations": info,
}
