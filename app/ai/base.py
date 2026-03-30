from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path


@dataclass
class ListingContext:
    """
    Structured context from the product flow, passed into AI analysis
    so predictions are constrained by the listing's domain and type.
    """
    listing_domain: Optional[str] = None       # "item" | "service"
    listing_type: Optional[str] = None         # "sale" | "donation" | "adoption"
    user_category: Optional[str] = None        # category selected by user
    user_title: Optional[str] = None           # title draft from user
    service_category: Optional[str] = None     # e.g. "plumber"
    animal_type: Optional[str] = None          # for adoption


@dataclass
class AIAnalysisResult:
    """
    Canonical output shape for every AI service implementation.
    All fields are suggestions — the user always has final say.
    """
    title: str
    category: str
    condition: str          # new | like_new | good | fair | poor
    smart_tags: List[str] = field(default_factory=list)
    description: Optional[str] = None
    subcategory: Optional[str] = None
    confidence: float = 1.0
    ai_service: str = "unknown"
    category_confidence: Optional[float] = None
    subcategory_confidence: Optional[float] = None
    used_fallback: bool = False
    # Multi-stage pipeline metadata
    pipeline_debug: Optional[Dict[str, Any]] = None


class BaseAIService(ABC):
    """
    Abstract interface for AI-powered item/service/adoption analysis.

    The `analyze_image` method receives a local file path and an optional
    ListingContext so predictions can be constrained by domain/type.
    """

    @abstractmethod
    async def analyze_image(
        self,
        image_path: Path,
        context: Optional[ListingContext] = None,
    ) -> AIAnalysisResult:
        """Analyse a single image and return structured metadata suggestions."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the AI backend is reachable and ready."""
        ...
