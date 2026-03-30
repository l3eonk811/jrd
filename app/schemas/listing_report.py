from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime

VALID_REASONS = {"spam", "misleading", "inappropriate", "wrong_category", "other"}


class ListingReportCreate(BaseModel):
    reason: str
    details: Optional[str] = None

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        if v not in VALID_REASONS:
            raise ValueError(f"reason must be one of: {', '.join(sorted(VALID_REASONS))}")
        return v


class ListingReportRead(BaseModel):
    id: int
    item_id: int
    reporter_user_id: int
    reason: str
    details: Optional[str] = None
    created_at: datetime
