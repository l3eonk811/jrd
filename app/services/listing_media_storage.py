"""
Listing image storage — single boundary for local disk today.

Call sites should not concatenate `upload_dir` / `item_id` / `filename` by hand.
Future: replace implementations with object storage (S3-compatible) while keeping
the same public URL contract or a configurable URL base.
"""

import logging
import time
from pathlib import Path

from app.config import get_settings

log = logging.getLogger(__name__)


def upload_root() -> Path:
    return Path(get_settings().upload_dir)


def temp_upload_dir() -> Path:
    """Transient files (similarity probe, debug). Same volume as uploads today."""
    d = upload_root() / "temp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cleanup_old_temp_files(*, max_age_seconds: int = 3600, prefix: str = "sim_") -> int:
    """
    Best-effort removal of stale temp files (e.g. abandoned similarity uploads).
    Returns number of files removed. Never raises.
    """
    removed = 0
    try:
        d = temp_upload_dir()
        cutoff = time.time() - max_age_seconds
        for p in d.glob(f"{prefix}*"):
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except OSError:
                continue
    except OSError as e:
        log.warning("temp_cleanup_skipped: %s", e)
    return removed


def ensure_item_image_dir(item_id: int) -> Path:
    d = upload_root() / str(item_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def public_url_for_item_image(item_id: int, filename: str) -> str:
    """Relative URL served by StaticFiles mount at `/uploads`."""
    return f"/uploads/{item_id}/{filename}"


def full_path_for_item_image(item_id: int, filename: str) -> Path:
    """Absolute filesystem path for an existing stored image."""
    return upload_root() / str(item_id) / filename
