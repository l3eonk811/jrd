"""App settings with simple in-memory cache over app_settings table."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting

_cache: dict[str, str] = {}


def clear_cache() -> None:
    """Clear in-memory cache (e.g. after bulk DB changes)."""
    _cache.clear()


def _validate_and_normalize_setting_value(key: str, value: str) -> str:
    """Validate known keys; return normalized stored string. Raises HTTPException(422) on invalid input."""
    v = value.strip()
    if key == "max_images_per_listing":
        try:
            n = int(v)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="max_images_per_listing must be an integer between 1 and 100",
            )
        if not (1 <= n <= 100):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="max_images_per_listing must be between 1 and 100",
            )
        return str(n)

    if key.startswith("enable_") or key == "default_show_phone_in_listing":
        low = v.lower()
        if low not in ("true", "false"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{key} must be 'true' or 'false'",
            )
        return "true" if low == "true" else "false"

    if key == "report_auto_hide_threshold":
        try:
            n = int(v)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="report_auto_hide_threshold must be an integer >= 1",
            )
        if n < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="report_auto_hide_threshold must be >= 1",
            )
        return str(n)

    return value


def get_setting(db: Session, key: str, default: Optional[str] = None) -> Optional[str]:
    """Return raw value string for key, using cache then DB."""
    if key in _cache:
        return _cache[key]
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is None:
        return default
    _cache[key] = row.value
    return row.value


def set_setting(
    db: Session,
    key: str,
    value: str,
    *,
    description: Optional[str] = None,
) -> AppSetting:
    """Insert or update a setting; updates cache and returns the row (caller commits).

    Always sets ``updated_at`` in Python so the UI shows a fresh timestamp (ORM ``onupdate`` alone is not relied on).
    """
    # TODO: invalidate cache across instances (Redis/pub-sub) for production — _cache is per-process only.
    normalized = _validate_and_normalize_setting_value(key, value)
    now = datetime.now(timezone.utc)
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = normalized
        row.updated_at = now
        if description is not None:
            row.description = description
        db.add(row)
    else:
        row = AppSetting(key=key, value=normalized, description=description, updated_at=now)
        db.add(row)
    db.flush()
    _cache[key] = normalized
    return row


def get_all_settings(db: Session) -> List[AppSetting]:
    """Return all settings ordered by key; refreshes cache entries for each."""
    rows = db.query(AppSetting).order_by(AppSetting.key.asc()).all()
    for r in rows:
        _cache[r.key] = r.value
    return rows


def parse_setting_value(raw: str) -> Any:
    """Parse stored string as JSON if possible, else bool/int/float heuristics, else original string."""
    s = raw.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return raw


def get_max_images_per_listing(db: Session) -> int:
    """Bounded integer for listing image uploads (default 20, min 1, max 100)."""
    raw = get_setting(db, "max_images_per_listing", "20")
    try:
        n = int(str(raw).strip())
        return max(1, min(100, n))
    except (ValueError, TypeError):
        return 20


def get_default_show_phone_in_listing(db: Session) -> bool:
    """Default visibility for phone on new listings when the client omits ``show_phone_in_listing``."""
    raw = get_setting(db, "default_show_phone_in_listing", "false") or "false"
    parsed = parse_setting_value(raw)
    if isinstance(parsed, bool):
        return parsed
    if isinstance(parsed, str):
        return parsed.lower() == "true"
    return False
