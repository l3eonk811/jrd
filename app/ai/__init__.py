from app.ai.base import BaseAIService, AIAnalysisResult, ListingContext
from app.ai.mock_service import MockAIService
from app.ai.classifier import (
    classify,
    read_image_input,
    AIClassificationInput,
    AIClassificationOutput,
)


def get_ai_service(service_name: str = "mock", device: str = "cpu") -> BaseAIService:
    """
    Factory — return the requested AI service implementation.
    device is used for OpenCLIP (cpu | cuda | auto).
    """
    import logging
    logger = logging.getLogger(__name__)

    key = service_name.lower()
    logger.info("AI Factory: service=%s device=%s", service_name, device)

    if key == "openclip":
        from app.ai.openclip_service import OpenCLIPService
        return OpenCLIPService(device=device, fallback_to_mock=True)

    return MockAIService()


__all__ = [
    "BaseAIService",
    "AIAnalysisResult",
    "ListingContext",
    "MockAIService",
    "get_ai_service",
    "classify",
    "read_image_input",
    "AIClassificationInput",
    "AIClassificationOutput",
]
