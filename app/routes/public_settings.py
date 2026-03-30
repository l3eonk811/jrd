"""Public, non-sensitive app settings for clients (mobile/web)."""

from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.settings_service import get_setting, parse_setting_value
from app.config import get_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Fixed whitelist only — do not add sensitive keys here; extend deliberately when a value is safe for any client.
_SAFE_KEYS = (
    "max_images_per_listing",
    "enable_provider_ratings",
    "default_show_phone_in_listing",
)


@router.get("")
def get_public_settings(db: Session = Depends(get_db)) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in _SAFE_KEYS:
        raw = get_setting(db, key)
        if raw is None:
            continue
        out[key] = parse_setting_value(raw)
    cfg = get_settings()
    # Operational hints for polling clients (no secrets)
    out["chat_poll_inbox_ms"] = cfg.chat_poll_inbox_interval_ms
    out["chat_poll_thread_ms"] = cfg.chat_poll_thread_interval_ms
    out["favorites_list_max"] = cfg.favorites_max_page_size
    return out
