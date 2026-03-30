"""
Upload routes — handle image uploads for display and similarity search.

Images are for display purposes only. No image-based AI classification is performed.
Embeddings are generated for visual similarity search functionality.
"""

import logging
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.item import ItemImage
from app.models.user import User
from app.services.auth_service import get_current_user
from app.services import item_service, embedding_service
from app.services.settings_service import get_max_images_per_listing
from app.services.listing_media_storage import ensure_item_image_dir, public_url_for_item_image
from app.config import get_settings

router = APIRouter(prefix="/api/upload", tags=["upload"])
settings = get_settings()
log = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_SIZE_MB = 5


# ── Attach image to existing item ─────────────────────────────────────────────

@router.post("/item/{item_id}/image")
async def upload_item_image(
    item_id: int,
    file: UploadFile = File(...),
    is_primary: bool = Form(default=False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Attach an image to an existing item. Max images per listing (see app_settings max_images_per_listing).
    Supported types: JPG, PNG, WEBP. Max 5 MB per image.
    If no primary image exists yet, the uploaded image becomes primary automatically.
    """
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Only JPG, PNG, and WEBP images are accepted.",
        )

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_IMAGE_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"Image too large ({size_mb:.1f} MB). Maximum size is {MAX_IMAGE_SIZE_MB} MB per image.",
        )

    # Ownership is verified inside add_image_to_item, but we need the count check here
    max_images = get_max_images_per_listing(db)
    existing_count = (
        db.query(ItemImage).filter(ItemImage.item_id == item_id).count()
    )
    if existing_count >= max_images:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {max_images} images per listing reached.",
        )

    # Auto-promote to primary when no primary image exists yet
    if not is_primary:
        primary_exists = (
            db.query(ItemImage)
            .filter(ItemImage.item_id == item_id, ItemImage.is_primary == True)
            .first()
        )
        if not primary_exists:
            is_primary = True

    # 1. Save via storage boundary (local disk; swappable later)
    ext = Path(file.filename or "upload").suffix or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    upload_dir = ensure_item_image_dir(item_id)
    file_path = upload_dir / filename
    try:
        file_path.write_bytes(content)
    except OSError as e:
        log.exception("image_write_failed item_id=%s: %s", item_id, e)
        raise HTTPException(
            status_code=503,
            detail="Could not store image. Check server disk space and permissions.",
        ) from e

    # 2. Create DB record
    url = public_url_for_item_image(item_id, filename)
    image = item_service.add_image_to_item(
        db=db,
        item_id=item_id,
        filename=filename,
        url=url,
        is_primary=is_primary,
        owner=current_user,
    )

    # 3. Generate and persist image embedding for similarity search only
    try:
        embedding_vec = await embedding_service.generate_embedding(
            file_path, device=settings.ai_device,
        )
        embedding_service.save_embedding(db, item_id, embedding_vec)
        log.info("embedding_saved item_id=%s dim=%s", item_id, len(embedding_vec))
    except Exception as exc:
        log.exception("Embedding generation failed (non-blocking): %s", exc)

    return {
        "id": image.id,
        "url": image.url,
        "is_primary": image.is_primary,
    }


# ── Delete image from item ────────────────────────────────────────────────────

@router.delete("/item/{item_id}/image/{image_id}")
async def delete_item_image(
    item_id: int,
    image_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete a specific image from a listing. Owner only.
    If the deleted image was primary, the next remaining image is promoted automatically.
    The image file is also removed from disk.
    """
    item_service.delete_image_from_item(
        db=db,
        item_id=item_id,
        image_id=image_id,
        owner=current_user,
    )
    return {"deleted": True}


# ── Set primary image ─────────────────────────────────────────────────────────

@router.patch("/item/{item_id}/image/{image_id}/primary")
async def set_primary_image(
    item_id: int,
    image_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Mark a specific image as the primary (cover) image for a listing. Owner only.
    """
    image = item_service.set_primary_image(
        db=db,
        item_id=item_id,
        image_id=image_id,
        owner=current_user,
    )
    return {
        "id": image.id,
        "url": image.url,
        "is_primary": image.is_primary,
    }
