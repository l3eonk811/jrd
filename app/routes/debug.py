"""
Debug endpoints for inspecting AI configuration, pipeline state, and analysis results.
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional

from app.database import get_db
from app.ai import get_ai_service
from app.ai.base import ListingContext
from app.ai.taxonomy import MAIN_CATEGORIES, MAIN_CATEGORY_IDS
from app.ai import domain_taxonomy as dt
from app.models.item import Item, ItemAIAnalysis
from app.config import get_settings

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/ai-config")
def get_ai_config() -> Dict[str, Any]:
    """
    Get current AI service configuration at runtime.
    Shows what service is actually being used, not what's in config files.
    """
    import os
    from app.config import get_settings
    settings = get_settings()
    
    ai_service = get_ai_service(settings.ai_service, device=settings.ai_device)
    
    # Get taxonomy info
    taxonomy_info = {
        "total_categories": len(MAIN_CATEGORIES),
        "category_ids": list(MAIN_CATEGORY_IDS),
        "categories_with_subcategories": {
            cat.id: [s.id for s in cat.subcategories]
            for cat in MAIN_CATEGORIES if cat.subcategories
        },
    }
    
    # Build comprehensive config
    config = {
        "environment": {
            "AI_SERVICE": os.environ.get("AI_SERVICE", "(not set)"),
            "AI_DEVICE": os.environ.get("AI_DEVICE", "(not set)"),
        },
        "settings": {
            "ai_service": settings.ai_service,
            "ai_device": settings.ai_device,
        },
        "runtime": {
            "service_class": type(ai_service).__name__,
            "service_name": getattr(ai_service, "SERVICE_NAME", "unknown"),
            "is_mock": type(ai_service).__name__ == "MockAIService",
        },
        "taxonomy": taxonomy_info,
    }
    
    # If OpenCLIP, add model info
    if type(ai_service).__name__ == "OpenCLIPService":
        try:
            from app.ai.openclip_service import _model_cache
            if _model_cache:
                config["openclip"] = {
                    "model_loaded": True,
                    "device": str(_model_cache.get("device", "unknown")),
                    "num_category_features": len(_model_cache.get("category_features", [])),
                    "num_tag_features": len(_model_cache.get("tag_features", [])),
                    "category_main_ids": _model_cache.get("category_main_ids", []),
                }
            else:
                config["openclip"] = {
                    "model_loaded": False,
                    "note": "Model cache not initialized yet",
                }
        except Exception as e:
            config["openclip"] = {
                "error": str(e),
            }
    
    return config


@router.get("/ai-analysis/{item_id}")
def get_ai_analysis_debug(item_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Get detailed AI analysis debug info for a specific item.
    Shows the actual analysis that was performed, with full breakdown.
    """
    # Get item
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    # Get all AI analyses for this item (ordered by created_at desc)
    analyses = (
        db.query(ItemAIAnalysis)
        .filter(ItemAIAnalysis.item_id == item_id)
        .order_by(ItemAIAnalysis.created_at.desc())
        .all()
    )
    
    if not analyses:
        return {
            "item_id": item_id,
            "has_analyses": False,
            "message": "No AI analyses found for this item",
        }
    
    latest = analyses[0]
    
    # Build debug response
    return {
        "item_id": item_id,
        "has_analyses": True,
        "total_analyses": len(analyses),
        "latest_analysis": {
            "id": latest.id,
            "created_at": latest.created_at.isoformat(),
            "ai_service": latest.ai_service,
            "title": latest.title,
            "category": latest.category,
            "subcategory": latest.subcategory,
            "condition": latest.condition,
            "smart_tags": latest.smart_tags,
            "description": latest.description,
            "confidence": latest.confidence,
            "category_confidence": latest.category_confidence,
            "subcategory_confidence": latest.subcategory_confidence,
            "used_fallback": latest.used_fallback,
        },
        "all_analyses": [
            {
                "id": a.id,
                "created_at": a.created_at.isoformat(),
                "ai_service": a.ai_service,
                "category": a.category,
                "subcategory": a.subcategory,
                "confidence": a.confidence,
                "used_fallback": a.used_fallback,
            }
            for a in analyses
        ],
        "item_current_state": {
            "title": item.title,
            "category": item.category,
            "condition": item.condition,
            "tags": item.tags,
        },
    }


@router.get("/ai-pipeline")
def get_pipeline_info() -> Dict[str, Any]:
    """Show the full multi-stage AI pipeline configuration and domain constraints."""
    settings = get_settings()
    return {
        "pipeline_stages": [
            "1. Object Detection (YOLOv5s) → crop main object",
            "2. Embedding Extraction (OpenCLIP ViT-B-32) → 512-d vector",
            "3. Classification (trained classifier → zero-shot fallback)",
            "4. Context Constraints (domain/type filtering)",
            "5. Output Assembly (title, category, tags, description)",
        ],
        "detection": {
            "model": "yolov5su (ultralytics)",
            "min_confidence": 0.25,
            "selection_policy": "balanced",
            "fallback": "full image if no reliable detection",
        },
        "classifier": {
            "backbone": "OpenCLIP ViT-B-32",
            "embedding_dim": 512,
            "trained_model_available": Path(__file__).parent.parent.joinpath(
                "ai", "trained_models", "category_classifier.pkl"
            ).exists(),
            "fallback": "zero-shot cosine similarity",
        },
        "domain_constraints": {
            "item_sale": {"blocked_tags": 0, "suppress_condition": False},
            "item_donation": {"blocked_tags": 0, "suppress_condition": False},
            "item_adoption": {
                "allowed_categories": list(dt.ADOPTION_CATEGORIES),
                "allowed_tags": list(dt.ADOPTION_TAGS),
                "blocked_tags": len(dt.ADOPTION_BLOCKED_TAGS),
                "suppress_condition": True,
            },
            "service": {
                "allowed_categories": list(dt.SERVICE_CATEGORIES),
                "allowed_tags": list(dt.SERVICE_TAGS),
                "blocked_tags": len(dt.SERVICE_BLOCKED_TAGS),
                "suppress_condition": True,
            },
        },
        "config": {
            "ai_service": settings.ai_service,
            "ai_device": settings.ai_device,
            "debug": settings.debug,
        },
    }


@router.get("/ai-pipeline")
def get_pipeline_config() -> Dict[str, Any]:
    """
    Get current AI pipeline configuration including domain constraints.
    Shows what stages are enabled and what domain-specific taxonomies are active.
    """
    from app.config import get_settings
    settings = get_settings()
    
    return {
        "stages": {
            "object_detection": {
                "enabled": True,
                "model": "yolov5s",
                "policies": ["balanced", "confident", "largest"],
                "default_policy": "balanced",
            },
            "embedding_extraction": {
                "enabled": True,
                "model": "OpenCLIP ViT-B-32",
                "embedding_dim": 512,
            },
            "classification": {
                "trained_classifier": {
                    "available": False,
                    "note": "Will use zero-shot fallback until trained on labeled data"
                },
                "zero_shot_fallback": {
                    "enabled": True,
                    "method": "CLIP text-image similarity"
                },
            },
        },
        "domain_taxonomy": {
            "item": {
                "categories": dt.ITEM_CATEGORIES,
                "tags": list(dt.ITEM_TAGS),
                "listing_types": ["sale", "donation"],
            },
            "adoption": {
                "categories": dt.ADOPTION_CATEGORIES,
                "tags": list(dt.ADOPTION_TAGS),
                "blocked_tags": list(dt.ITEM_TAGS - dt.ADOPTION_TAGS),
                "condition_suppressed": True,
            },
            "service": {
                "categories": dt.SERVICE_CATEGORIES,
                "tags": list(dt.SERVICE_TAGS),
                "blocked_tags": list(dt.ITEM_TAGS - dt.SERVICE_TAGS),
                "condition_suppressed": True,
            },
        },
        "device": settings.ai_device,
        "service_type": settings.ai_service,
    }


@router.post("/ai-pipeline/test")
async def test_pipeline(
    file: UploadFile = File(...),
    listing_domain: Optional[str] = Form(default=None),
    listing_type: Optional[str] = Form(default=None),
    user_category: Optional[str] = Form(default=None),
    service_category: Optional[str] = Form(default=None),
    animal_type: Optional[str] = Form(default=None),
) -> Dict[str, Any]:
    """
    Run the full AI pipeline on an image with optional context and return
    all stage debug info. For development/testing only.
    """
    settings = get_settings()
    context = ListingContext(
        listing_domain=listing_domain,
        listing_type=listing_type,
        user_category=user_category,
        service_category=service_category,
        animal_type=animal_type,
    )

    temp_dir = Path(settings.upload_dir) / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "upload").suffix or ".jpg"
    temp_path = temp_dir / f"debug_{uuid.uuid4().hex}{ext}"

    try:
        content = await file.read()
        temp_path.write_bytes(content)
        ai = get_ai_service(settings.ai_service, device=settings.ai_device)
        result = await ai.analyze_image(temp_path, context=context)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    return {
        "result": {
            "title": result.title,
            "category": result.category,
            "subcategory": result.subcategory,
            "condition": result.condition,
            "smart_tags": result.smart_tags,
            "description": result.description,
            "confidence": result.confidence,
            "ai_service": result.ai_service,
            "used_fallback": result.used_fallback,
            "category_confidence": result.category_confidence,
        },
        "pipeline_debug": result.pipeline_debug,
        "context": {
            "listing_domain": listing_domain,
            "listing_type": listing_type,
            "user_category": user_category,
            "service_category": service_category,
            "animal_type": animal_type,
        },
    }
