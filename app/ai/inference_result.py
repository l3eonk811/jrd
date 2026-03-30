"""
Structured result from the real inference pipeline (OpenCLIP + detection + context).

Used by OpenCLIPService.predict_all() and mapped to AIAnalysisResult
for the rest of the app. Holds per-field confidence and pipeline debug info.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class InferenceResult:
    """Raw output from the multi-stage pipeline; maps to AIAnalysisResult."""
    title: str
    category: str
    condition: str
    smart_tags: List[str]
    description: Optional[str] = None
    subcategory: Optional[str] = None
    category_confidence: float = 1.0
    subcategory_confidence: Optional[float] = None
    tag_scores: Optional[Dict[str, float]] = None
    pipeline_debug: Optional[Dict[str, Any]] = None

    def overall_confidence(self) -> float:
        """Single confidence score combining category and tag confidences."""
        if self.tag_scores:
            return (self.category_confidence + sum(self.tag_scores.values()) / max(1, len(self.tag_scores))) / 2.0
        return self.category_confidence
