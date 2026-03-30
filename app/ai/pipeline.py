"""
AI Pipeline: Orchestrate detect → crop → embed → classify with listing context.

Pipeline stages:
1. Object Detection (YOLOv5) - detect main object, crop with padding
2. Embedding Extraction (OpenCLIP) - extract 512-d vector from cropped image
3. Classification:
   a. Trained classifier (if available) - sklearn model on embeddings
   b. Zero-shot CLIP (fallback) - cosine similarity with text prompts
4. Context Constraints - filter categories/tags by listing domain/type
5. Title Generation - domain-aware title from classification + context

All stages include timing and debug metadata.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from pathlib import Path
import numpy as np
from PIL import Image

from app.ai.detector import ObjectDetector
from app.ai.embedding_classifier import EmbeddingClassifier
from app.ai import domain_taxonomy as dt
from app.ai.inference_result import InferenceResult

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# HIGH-LEVEL RUN FUNCTION (called by OpenCLIPService)
# ══════════════════════════════════════════════════════════════════════════════

def run_pipeline(
    image_path: Path,
    device: str = "cpu",
    context: Optional[ListingContext] = None,
    category_threshold: float = 0.20,
    subcategory_threshold: float = 0.15,
    detection_enabled: bool = True,
    classifier_enabled: bool = True,
) -> InferenceResult:
    """
    High-level entry point for running the full pipeline (sync).
    
    Returns InferenceResult compatible with existing codebase.
    """
    # If no context provided, create default
    if context is None:
        context = ListingContext(listing_domain="item", listing_type="sale")
    
    # For now, use the existing legacy implementation
    # Full new pipeline integration will come in next phase
    from app.ai.openclip_service import _predict_all_sync
    
    return _predict_all_sync(
        image_path,
        device=device,
        category_threshold=category_threshold,
        subcategory_threshold=subcategory_threshold,
        context=context
    )


# ══════════════════════════════════════════════════════════════════════════════
# NEW PIPELINE (for gradual migration)
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class ListingContext:
    """Context about the listing being created (user-provided)."""
    listing_domain: str  # "item" | "service"
    listing_type: Optional[str] = None  # "sale" | "donation" | "adoption" | None
    selected_category: Optional[str] = None  # Pre-selected category if any
    service_category: Optional[str] = None  # For services
    animal_type: Optional[str] = None  # For adoption


@dataclass
class PipelineResult:
    """Complete AI pipeline output with metadata."""
    # Final outputs
    title: str
    category: str
    subcategory: Optional[str]
    condition: str
    tags: List[str]
    description: str
    confidence: float
    
    # Pipeline debug/metadata
    pipeline_debug: Dict[str, Any] = field(default_factory=dict)


class AIPipeline:
    """
    Full AI pipeline for listing analysis.
    
    Stages:
    1. Detection → 2. Embedding → 3. Classification → 4. Context Filtering → 5. Output
    """
    
    def __init__(
        self,
        openclip_service,  # OpenCLIPService instance
        detector: Optional[ObjectDetector] = None,
        classifier: Optional[EmbeddingClassifier] = None,
        detection_policy: str = "balanced"
    ):
        """
        Initialize pipeline.
        
        Args:
            openclip_service: OpenCLIPService for embeddings + zero-shot
            detector: ObjectDetector for cropping (optional, will create default)
            classifier: Trained classifier (optional, will use zero-shot if None)
            detection_policy: "balanced", "confident", or "largest"
        """
        self.openclip = openclip_service
        self.detector = detector
        self.classifier = classifier
        self.detection_policy = detection_policy
        
        log.info(
            f"AI Pipeline initialized: "
            f"detector={'enabled' if detector else 'disabled'}, "
            f"classifier={'trained' if (classifier and classifier.is_trained) else 'zero-shot'}"
        )
    
    async def analyze(
        self,
        image_path: str,
        context: ListingContext
    ) -> PipelineResult:
        """
        Run full pipeline on an image with listing context.
        
        Args:
            image_path: Path to uploaded image
            context: Listing context (domain, type, etc.)
            
        Returns:
            PipelineResult with predictions and debug metadata
        """
        debug = {}
        total_start = time.time()
        
        # ── Stage 1: Object Detection & Cropping ──────────────────────────────
        if self.detector:
            stage_start = time.time()
            try:
                cropped_img, det_meta = self.detector.detect_and_crop(
                    image_path,
                    policy=self.detection_policy
                )
                # Save cropped image temporarily for embedding
                crop_path = str(Path(image_path).with_suffix(".crop.jpg"))
                cropped_img.save(crop_path, "JPEG", quality=95)
                working_image = crop_path
                
                debug["stage_1_detection"] = {
                    "time_ms": round((time.time() - stage_start) * 1000, 2),
                    **det_meta
                }
            except Exception as e:
                log.warning(f"Detection failed, using full image: {e}")
                working_image = image_path
                debug["stage_1_detection"] = {
                    "time_ms": 0,
                    "detection_method": "full_image",
                    "fallback_reason": f"error: {str(e)}"
                }
        else:
            working_image = image_path
            debug["stage_1_detection"] = {
                "time_ms": 0,
                "detection_method": "full_image",
                "fallback_reason": "detector_disabled"
            }
        
        # ── Stage 2: Embedding Extraction ─────────────────────────────────────
        stage_start = time.time()
        embedding = await self._extract_embedding(working_image)
        debug["stage_2_embedding"] = {
            "time_ms": round((time.time() - stage_start) * 1000, 2),
            "embedding_dim": len(embedding),
            "embedding_norm": round(float(np.linalg.norm(embedding)), 4)
        }
        
        # ── Stage 3: Classification ───────────────────────────────────────────
        stage_start = time.time()
        
        if self.classifier and self.classifier.is_trained:
            # Use trained classifier
            preds = self.classifier.predict(embedding, top_k=5)
            if preds:
                category = preds[0]["class_name"]
                confidence = preds[0]["probability"]
                classification_method = "trained_classifier"
                debug["stage_3_classification"] = {
                    "time_ms": round((time.time() - stage_start) * 1000, 2),
                    "method": classification_method,
                    "top_5_predictions": preds,
                    "classifier_info": self.classifier.get_info()
                }
            else:
                # Classifier failed → fall back
                category, confidence, zero_shot_debug = await self._zero_shot_classify(
                    working_image, embedding, context
                )
                classification_method = "zero_shot_fallback"
                debug["stage_3_classification"] = {
                    "time_ms": round((time.time() - stage_start) * 1000, 2),
                    "method": classification_method,
                    **zero_shot_debug
                }
        else:
            # No trained classifier → use zero-shot
            category, confidence, zero_shot_debug = await self._zero_shot_classify(
                working_image, embedding, context
            )
            classification_method = "zero_shot"
            debug["stage_3_classification"] = {
                "time_ms": round((time.time() - stage_start) * 1000, 2),
                "method": classification_method,
                **zero_shot_debug
            }
        
        # ── Stage 4: Context Constraints ──────────────────────────────────────
        stage_start = time.time()
        
        # Filter category to allowed set
        allowed_categories = dt.get_allowed_categories(
            context.listing_domain,
            context.listing_type
        )
        if category not in allowed_categories:
            # Category not in allowed set → use "Other" or first allowed
            original_category = category
            category = "Other" if "Other" in allowed_categories else allowed_categories[0]
            debug["stage_4_constraints"] = {
                "time_ms": round((time.time() - stage_start) * 1000, 2),
                "category_remapped": True,
                "original_category": original_category,
                "final_category": category
            }
        else:
            debug["stage_4_constraints"] = {
                "time_ms": round((time.time() - stage_start) * 1000, 2),
                "category_remapped": False
            }
        
        # Generate tags (placeholder - would come from classification)
        raw_tags = self._generate_tags(category, context)
        tags = dt.filter_tags(raw_tags, context.listing_domain, context.listing_type)
        debug["stage_4_constraints"]["tags_before_filter"] = raw_tags
        debug["stage_4_constraints"]["tags_after_filter"] = tags
        
        # Condition
        suppress_condition = dt.should_suppress_condition(
            context.listing_domain,
            context.listing_type
        )
        condition = "good" if not suppress_condition else "not_applicable"
        debug["stage_4_constraints"]["condition_suppressed"] = suppress_condition
        
        # ── Stage 5: Output Assembly ──────────────────────────────────────────
        title = self._generate_title(category, context)
        description = self._generate_description(category, context)
        subcategory = None  # Could be enhanced with more detailed classification
        
        total_time = round((time.time() - total_start) * 1000, 2)
        debug["total_pipeline_time_ms"] = total_time
        debug["listing_context"] = {
            "listing_domain": context.listing_domain,
            "listing_type": context.listing_type,
            "selected_category": context.selected_category,
            "service_category": context.service_category,
            "animal_type": context.animal_type
        }
        
        return PipelineResult(
            title=title,
            category=category,
            subcategory=subcategory,
            condition=condition,
            tags=tags,
            description=description,
            confidence=confidence,
            pipeline_debug=debug
        )
    
    async def _extract_embedding(self, image_path: str) -> np.ndarray:
        """Extract OpenCLIP embedding from image."""
        # Call OpenCLIP service's embedding extraction
        # (assumes openclip_service has extract_embedding_sync method)
        embedding = self.openclip.extract_image_embedding_sync(image_path)
        return np.array(embedding)
    
    async def _zero_shot_classify(
        self,
        image_path: str,
        embedding: np.ndarray,
        context: ListingContext
    ) -> tuple[str, float, Dict[str, Any]]:
        """
        Zero-shot classification using CLIP text-image similarity.
        
        Returns:
            (category, confidence, debug_dict)
        """
        # Get context-appropriate prompts
        prompts = dt.get_zero_shot_prompts(
            context.listing_domain,
            context.listing_type,
            context.selected_category or context.service_category or context.animal_type
        )
        
        # Get allowed categories
        allowed_categories = dt.get_allowed_categories(
            context.listing_domain,
            context.listing_type
        )
        
        # Build full prompts for each category
        category_prompts = {}
        for cat in allowed_categories:
            # Use first prompt template, replace with category
            base_prompt = prompts[0] if prompts else f"a photo of {cat}"
            category_prompts[cat] = base_prompt.replace(
                context.selected_category or "item",
                cat
            )
        
        # Get text embeddings (call OpenCLIP service)
        # For now, simplified - in real impl, would batch encode all prompts
        # and compute cosine similarities
        
        # Placeholder: return first category with moderate confidence
        # Real implementation would compute similarity scores
        category = allowed_categories[0]
        confidence = 0.65
        
        debug = {
            "prompts_used": prompts,
            "num_categories_tested": len(allowed_categories),
            "selected_prompt": category_prompts[category]
        }
        
        return category, confidence, debug
    
    def _generate_tags(self, category: str, context: ListingContext) -> List[str]:
        """Generate initial tags based on category and context."""
        # Placeholder - real implementation would use classification results
        tags = []
        
        if context.listing_domain == "item":
            if context.listing_type == "adoption":
                tags = ["friendly", "house-trained"]
            else:
                tags = ["good-condition", "clean"]
        elif context.listing_domain == "service":
            tags = ["professional", "experienced"]
        
        return tags
    
    def _generate_title(self, category: str, context: ListingContext) -> str:
        """Generate domain-aware title."""
        if context.listing_domain == "service":
            if context.service_category:
                return f"{context.service_category.replace('_', ' ').title()} Service"
            return f"{category} Service"
        elif context.listing_domain == "item" and context.listing_type == "adoption":
            if context.animal_type:
                return f"{context.animal_type.title()} for Adoption"
            return f"{category} for Adoption"
        else:
            return f"{category}"
    
    def _generate_description(self, category: str, context: ListingContext) -> str:
        """Generate basic description."""
        if context.listing_domain == "service":
            return f"Professional {category.lower()} service available in your area."
        elif context.listing_type == "adoption":
            return f"Lovely {category.lower()} looking for a new home."
        else:
            return f"{category} in good condition."
