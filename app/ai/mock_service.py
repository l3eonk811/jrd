"""
Mock AI service — thin async wrapper around the deterministic classifier.

This is the default service used in development and CI.
Swap it out by setting AI_SERVICE=openclip (or any future key) in .env.
"""

import asyncio
from pathlib import Path

from app.ai.base import BaseAIService, AIAnalysisResult, ListingContext
from app.ai.classifier import classify, read_image_input
from typing import Optional


class MockAIService(BaseAIService):
    """
    Deterministic mock that exercises the full AI pipeline without a real model.

    Every call to `analyze_image` is:
      - Reproducible  — same image → same output every time
      - Offline-safe  — no network, no GPU required
      - Fast          — pure Python + Pillow, < 20 ms per image
    """

    SERVICE_NAME = "mock"

    async def analyze_image(
        self,
        image_path: Path,
        context: Optional[ListingContext] = None,
    ) -> AIAnalysisResult:
        inp = await asyncio.to_thread(read_image_input, image_path)
        out = await asyncio.to_thread(classify, inp)

        return AIAnalysisResult(
            title=out.title,
            category=out.category,
            condition=out.condition,
            smart_tags=out.smart_tags,
            description=out.description,
            confidence=out.confidence,
            ai_service=self.SERVICE_NAME,
            category_confidence=None,
            used_fallback=False,
        )

    async def health_check(self) -> bool:
        return True
