"""
Real AI service using OpenCLIP for local vision-language inference.

- Category: zero-shot similarity vs taxonomy category labels.
- Smart tags: similarity vs predefined tag labels; return top-k with scores.
- Condition: heuristic placeholder (modular; replace with classifier later).
- Title: deterministic template from category + condition + top tags.
- Model loaded once and cached (CPU or GPU via config).
"""

import asyncio
import logging
from pathlib import Path
from typing import List, Tuple, Optional

from app.ai.base import BaseAIService, AIAnalysisResult, ListingContext
from app.ai.inference_result import InferenceResult
from app.ai.taxonomy import (
    get_main_category_prompts,
    get_subcategory_prompts,
    get_all_tag_prompts,
    get_allowed_tags_for_category,
    filter_allowed_tags,
    normalize_category,
    normalize_tag,
    normalize_condition,
    build_title,
)
from app.ai.condition_heuristic import estimate_condition_from_image_path

logger = logging.getLogger(__name__)

# ── Cached model (loaded once per process) ────────────────────────────────────

_model_cache: Optional[dict] = None


def _get_model_cache(device: str = "cpu"):
    """Load OpenCLIP model and precompute text embeddings once. Thread-safe for our use."""
    global _model_cache
    if _model_cache is not None:
        return _model_cache

    try:
        import torch
        import open_clip
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(
            "OpenCLIP dependencies missing. Install: pip install open-clip-torch torch Pillow"
        ) from e

    # Prefer CPU for portability; override with CUDA if available and desired.
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    dev = torch.device(device)

    # ViT-B-32 is small and CPU-friendly. Pretrained: openai or laion400m_e32.
    model_name, pretrained = "ViT-B-32", "openai"
    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained, device=dev
        )
    except Exception:
        # Fallback pretrained if openai not available
        model, _, preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained="laion400m_e32", device=dev
        )
    model.eval()
    tokenizer = open_clip.get_tokenizer(model_name)

    # Category: use taxonomy main category prompts (id, label_en, prompt)
    main_prompts = get_main_category_prompts()
    category_prompts = [p[2] for p in main_prompts]
    category_main_ids = [p[0] for p in main_prompts]
    category_labels = [p[1] for p in main_prompts]
    with torch.no_grad():
        cat_tokens = tokenizer(category_prompts).to(dev)
        category_features = model.encode_text(cat_tokens)
        category_features = category_features / category_features.norm(dim=-1, keepdim=True)

    # Tags: approved set only (taxonomy.get_all_tag_prompts())
    tag_texts = get_all_tag_prompts()
    with torch.no_grad():
        tag_tokens = tokenizer(tag_texts).to(dev)
        tag_features = model.encode_text(tag_tokens)
        tag_features = tag_features / tag_features.norm(dim=-1, keepdim=True)

    _model_cache = {
        "model": model,
        "preprocess": preprocess,
        "tokenizer": tokenizer,
        "category_features": category_features,
        "tag_features": tag_features,
        "category_main_ids": category_main_ids,
        "category_labels": category_labels,
        "tag_names": tag_texts,
        "device": dev,
    }
    return _model_cache


# ── Inference (sync; run in thread from async) ────────────────────────────────

def _load_and_preprocess_image(image_path: Path, preprocess, device):
    import torch
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    x = preprocess(img).unsqueeze(0).to(device)
    return x


def _predict_category_sync(image_path: Path, device: str = "cpu", top_k: int = 5) -> Tuple[str, str, float, Optional[List[Tuple[str, str, float]]]]:
    """
    Returns (main_id, label_en, confidence, top_k_predictions).
    top_k_predictions: List of (main_id, label_en, confidence) for top k categories.
    """
    cache = _get_model_cache(device)
    import torch
    image = _load_and_preprocess_image(
        image_path, cache["preprocess"], cache["device"]
    )
    with torch.no_grad():
        image_features = cache["model"].encode_image(image)
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)
        logits = (100.0 * image_features @ cache["category_features"].T).squeeze(0)
        probs = logits.softmax(dim=-1)
        
        # Get top-k predictions for diagnostics
        top_k_actual = min(top_k, len(probs))
        top_k_probs, top_k_indices = probs.topk(top_k_actual)
        
        top_k_predictions = [
            (cache["category_main_ids"][idx], cache["category_labels"][idx], float(top_k_probs[i].item()))
            for i, idx in enumerate(top_k_indices.tolist())
        ]
        
        idx = probs.argmax().item()
    
    main_id = cache["category_main_ids"][idx]
    label_en = cache["category_labels"][idx]
    confidence = float(probs[idx].item())
    
    return main_id, label_en, confidence, top_k_predictions


def _predict_subcategory_sync(
    image_path: Path, main_id: str, device: str = "cpu", top_k: int = 3
) -> Tuple[Optional[str], Optional[str], Optional[float], Optional[List[Tuple[str, str, float]]]]:
    """
    Predict subcategory for a given main category using zero-shot classification.
    
    Returns (sub_id, label_en, confidence, top_k_predictions) or (None, None, None, None) if no subcategories.
    top_k_predictions: List of (sub_id, label_en, confidence) for top k subcategories.
    """
    # Get subcategory prompts for this main category
    sub_prompts = get_subcategory_prompts(main_id)
    if not sub_prompts:
        return None, None, None, None
    
    cache = _get_model_cache(device)
    import torch
    
    # Encode subcategory prompts on-the-fly (not cached since they're category-specific)
    sub_texts = [p[2] for p in sub_prompts]  # (sub_id, label_en, prompt)
    sub_ids = [p[0] for p in sub_prompts]
    sub_labels = [p[1] for p in sub_prompts]
    
    with torch.no_grad():
        sub_tokens = cache["tokenizer"](sub_texts).to(cache["device"])
        sub_features = cache["model"].encode_text(sub_tokens)
        sub_features = sub_features / sub_features.norm(dim=-1, keepdim=True)
        
        # Load and encode image
        image = _load_and_preprocess_image(
            image_path, cache["preprocess"], cache["device"]
        )
        image_features = cache["model"].encode_image(image)
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)
        
        # Compute similarity
        logits = (100.0 * image_features @ sub_features.T).squeeze(0)
        probs = logits.softmax(dim=-1)
        
        # Get top-k predictions
        top_k_actual = min(top_k, len(probs))
        top_k_probs, top_k_indices = probs.topk(top_k_actual)
        
        top_k_predictions = [
            (sub_ids[idx], sub_labels[idx], float(top_k_probs[i].item()))
            for i, idx in enumerate(top_k_indices.tolist())
        ]
        
        idx = probs.argmax().item()
    
    return sub_ids[idx], sub_labels[idx], float(probs[idx].item()), top_k_predictions


def _predict_smart_tags_sync(
    image_path: Path, top_k: int = 5, device: str = "cpu", main_id: Optional[str] = None
) -> Tuple[List[str], Optional[dict]]:
    """Returns (tag list, score dict). If main_id given, tags are filtered to allowed for that category."""
    cache = _get_model_cache(device)
    import torch
    image = _load_and_preprocess_image(
        image_path, cache["preprocess"], cache["device"]
    )
    with torch.no_grad():
        image_features = cache["model"].encode_image(image)
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)
        # Request more candidates so we can filter to allowed and still get top_k
        k = min(top_k * 3, len(cache["tag_names"])) if main_id else min(top_k, len(cache["tag_names"]))
        scores = (image_features @ cache["tag_features"].T).squeeze(0)
    values, indices = scores.topk(k)
    tag_names = cache["tag_names"]
    raw_tags = [tag_names[i] for i in indices.tolist()]
    tag_scores = {tag_names[i]: float(values[j].item()) for j, i in enumerate(indices.tolist())}
    if main_id:
        filtered = filter_allowed_tags(raw_tags, main_id, max_tags=top_k)
        scores_filtered = {t: tag_scores[t] for t in filtered if t in tag_scores}
        return filtered, scores_filtered
    return raw_tags[:top_k], {t: tag_scores[t] for t in raw_tags[:top_k] if t in tag_scores}


def extract_image_embedding_sync(image_path: Path, device: str = "cpu") -> List[float]:
    """
    Extract a normalized image embedding vector from an image file.

    Returns a plain Python list of floats (ViT-B-32 produces 512-d vectors).
    The vector is L2-normalized so cosine similarity == dot product.
    """
    cache = _get_model_cache(device)
    import torch
    image = _load_and_preprocess_image(
        image_path, cache["preprocess"], cache["device"]
    )
    with torch.no_grad():
        features = cache["model"].encode_image(image)
        features = features / features.norm(dim=-1, keepdim=True)
    return features.squeeze(0).cpu().tolist()


def _predict_condition_sync(image_path: Path) -> str:
    return estimate_condition_from_image_path(image_path)


def _predict_all_sync(
    image_path: Path, 
    device: str = "cpu",
    category_confidence_threshold: float = 0.20,
    subcategory_confidence_threshold: float = 0.15,
) -> InferenceResult:
    """
    Full inference pipeline with confidence thresholds.
    
    If confidence is below threshold, falls back to safer categories:
    - Main category: falls back to "other"
    - Subcategory: falls back to None (no subcategory)
    
    Args:
        image_path: Path to image file
        device: Device for inference (cpu/cuda)
        category_confidence_threshold: Minimum confidence for main category (default 0.20)
        subcategory_confidence_threshold: Minimum confidence for subcategory (default 0.15)
    """
    # Log runtime configuration
    logger.info("="*80)
    logger.info(f"🔍 OpenCLIP Inference Runtime Analysis")
    logger.info(f"Image: {image_path.name}")
    logger.info(f"Device: {device}")
    logger.info(f"Category confidence threshold: {category_confidence_threshold}")
    logger.info(f"Subcategory confidence threshold: {subcategory_confidence_threshold}")
    
    # Get model cache info
    cache = _get_model_cache(device)
    logger.info(f"Model: OpenCLIP (cached)")
    logger.info(f"Total taxonomy categories: {len(cache['category_main_ids'])}")
    logger.info(f"Category IDs: {cache['category_main_ids']}")
    logger.info("="*80)
    
    # Stage 1: Predict main category with top-k
    main_id, label_en, cat_conf, top_k_cats = _predict_category_sync(image_path, device, top_k=5)
    
    # Log top-k predictions for debugging
    logger.info(f"📊 Top-5 Main Category Predictions:")
    for rank, (cat_id, cat_label, conf) in enumerate(top_k_cats, 1):
        marker = "✓" if rank == 1 else " "
        logger.info(f"  {marker} {rank}. {cat_label:20s} ({cat_id:20s}) confidence: {conf:.4f} ({conf*100:.1f}%)")
    logger.info(f"")
    logger.info(f"🎯 Initial selection: {label_en} ({main_id}) with confidence {cat_conf:.4f} ({cat_conf*100:.1f}%)")
    
    # Apply confidence threshold for main category
    if cat_conf < category_confidence_threshold:
        logger.warning(
            f"⚠️  LOW CONFIDENCE: {cat_conf:.4f} ({cat_conf*100:.1f}%) < threshold {category_confidence_threshold} ({category_confidence_threshold*100:.0f}%)"
        )
        logger.warning(
            f"⚠️  FALLBACK TRIGGERED: Changing category from '{label_en}' to 'Other'"
        )
        main_id = "other"
        label_en = "Other"
        # Don't modify cat_conf - keep original to show it was uncertain
    
    # Stage 2: Predict subcategory (if main category has subcategories and confidence is sufficient)
    sub_id, sub_label, sub_conf, top_k_subs = None, None, None, None
    if main_id != "other":  # Don't predict subcategory for fallback "other"
        sub_id, sub_label, sub_conf, top_k_subs = _predict_subcategory_sync(
            image_path, main_id, device, top_k=3
        )
        
        if sub_id is not None and top_k_subs:
            logger.info(f"")
            logger.info(f"📊 Top-3 Subcategory Predictions for {label_en}:")
            for rank, (s_id, s_label, s_conf) in enumerate(top_k_subs, 1):
                marker = "✓" if rank == 1 else " "
                logger.info(f"  {marker} {rank}. {s_label:20s} ({s_id:20s}) confidence: {s_conf:.4f} ({s_conf*100:.1f}%)")
            logger.info(f"🎯 Selected subcategory: {sub_label} ({sub_id}) with confidence {sub_conf:.4f} ({sub_conf*100:.1f}%)")
            
            # Apply confidence threshold for subcategory
            if sub_conf < subcategory_confidence_threshold:
                logger.warning(
                    f"⚠️  LOW SUBCATEGORY CONFIDENCE: {sub_conf:.4f} ({sub_conf*100:.1f}%) < threshold {subcategory_confidence_threshold} ({subcategory_confidence_threshold*100:.0f}%)"
                )
                logger.warning(
                    f"⚠️  Using main category only (no subcategory)"
                )
                sub_id, sub_label = None, None
                # Keep sub_conf for diagnostics
    
    # Other predictions
    condition_raw = _predict_condition_sync(image_path)
    condition = normalize_condition(condition_raw) or condition_raw
    tags, tag_scores = _predict_smart_tags_sync(
        image_path, top_k=5, device=device, main_id=main_id
    )
    
    logger.info(f"")
    logger.info(f"🏷️  Condition: {condition}")
    logger.info(f"🏷️  Tags: {', '.join(tags)}")
    logger.info(f"")
    logger.info(f"✅ Final Classification:")
    logger.info(f"   Category: {label_en}" + (f" / {sub_label}" if sub_label else ""))
    logger.info(f"   Confidence: {cat_conf:.4f} ({cat_conf*100:.1f}%)")
    logger.info(f"   Used fallback: {cat_conf < category_confidence_threshold}")
    logger.info("="*80)
    
    # Build title with subcategory if available and above threshold
    title = build_title(main_id, condition, tags, sub_id=sub_id, max_tags=2)
    
    # Build description with uncertainty indicator for low confidence
    if cat_conf < category_confidence_threshold:
        description = (
            f"Classification uncertain (confidence {cat_conf:.1%}). "
            f"Detected as: {label_en}, condition {condition.replace('_', ' ')}. "
            f"Tags: {', '.join(tags)}."
        )
    elif sub_label:
        description = (
            f"Detected: {label_en} / {sub_label}, condition {condition.replace('_', ' ')}. "
            f"Tags: {', '.join(tags)}."
        )
    else:
        description = (
            f"Detected: {label_en}, condition {condition.replace('_', ' ')}. "
            f"Tags: {', '.join(tags)}."
        )
    
    return InferenceResult(
        title=title,
        category=label_en,
        subcategory=sub_label,
        condition=condition,
        smart_tags=tags,
        description=description,
        category_confidence=cat_conf,
        subcategory_confidence=sub_conf,
        tag_scores=tag_scores,
    )


# ── Service implementation ───────────────────────────────────────────────────

class OpenCLIPService(BaseAIService):
    """
    Multi-stage AI pipeline built on OpenCLIP embeddings.

    Pipeline:
      1. Object detection + crop (YOLOv5s)
      2. OpenCLIP embedding extraction
      3. Classification (trained classifier → zero-shot fallback)
      4. Context-constrained tag/category filtering
      5. Domain-aware output assembly

    On any failure, falls back to mock service so uploads never break.
    """

    SERVICE_NAME = "openclip"

    def __init__(
        self,
        device: str = "cpu",
        fallback_to_mock: bool = True,
        detection_enabled: bool = True,
        classifier_enabled: bool = True,
    ):
        self._device = device
        self._fallback_to_mock = fallback_to_mock
        self._detection_enabled = detection_enabled
        self._classifier_enabled = classifier_enabled

    def predict_category(self, image_path: Path) -> str:
        _, label_en, _, _ = _predict_category_sync(image_path, self._device)
        return label_en

    def predict_condition(self, image_path: Path) -> str:
        return _predict_condition_sync(image_path)

    def predict_smart_tags(self, image_path: Path, top_k: int = 5) -> List[str]:
        main_id, _, _, _ = _predict_category_sync(image_path, self._device)
        tags, _ = _predict_smart_tags_sync(
            image_path, top_k=top_k, device=self._device, main_id=main_id
        )
        return tags

    def predict_title(self, image_path: Path) -> str:
        main_id, _, _, _ = _predict_category_sync(image_path, self._device)
        condition_raw = _predict_condition_sync(image_path)
        condition = normalize_condition(condition_raw) or condition_raw
        tags, _ = _predict_smart_tags_sync(
            image_path, top_k=3, device=self._device, main_id=main_id
        )
        return build_title(main_id, condition, tags, sub_id=None, max_tags=2)

    def predict_all(self, image_path: Path, context=None) -> InferenceResult:
        """Full multi-stage pipeline (sync). Run via asyncio.to_thread."""
        from app.ai.pipeline import run_pipeline
        return run_pipeline(
            image_path,
            device=self._device,
            context=context,
            detection_enabled=self._detection_enabled,
            classifier_enabled=self._classifier_enabled,
        )

    async def analyze_image(self, image_path: Path, context=None) -> AIAnalysisResult:
        try:
            from app.ai.pipeline import run_pipeline
            result = await asyncio.to_thread(
                run_pipeline,
                image_path,
                self._device,
                context,
                0.20,   # category_threshold
                0.15,   # subcategory_threshold
                self._detection_enabled,
                self._classifier_enabled,
            )
            return AIAnalysisResult(
                title=result.title,
                category=result.category,
                subcategory=result.subcategory,
                condition=result.condition,
                smart_tags=result.smart_tags,
                description=result.description,
                confidence=round(result.overall_confidence(), 3),
                ai_service=self.SERVICE_NAME,
                category_confidence=result.category_confidence,
                subcategory_confidence=result.subcategory_confidence,
                used_fallback=False,
                pipeline_debug=result.pipeline_debug,
            )
        except Exception:
            logger.exception(
                "OpenCLIP pipeline failed, falling back to mock"
            )
            if self._fallback_to_mock:
                from app.ai.mock_service import MockAIService
                mock_result = await MockAIService().analyze_image(image_path, context)
                return AIAnalysisResult(
                    title=mock_result.title,
                    category=mock_result.category,
                    condition=mock_result.condition,
                    smart_tags=mock_result.smart_tags,
                    description=mock_result.description,
                    confidence=mock_result.confidence,
                    ai_service="mock",
                    category_confidence=mock_result.category_confidence,
                    used_fallback=True,
                )
            raise

    async def health_check(self) -> bool:
        try:
            _get_model_cache(self._device)
            return True
        except Exception as e:
            logger.warning("OpenCLIP health_check failed: %s", e)
            return False
