from datetime import datetime
from pydantic import BaseModel, Field


class UserBlockCreate(BaseModel):
    blocked_user_id: int = Field(..., ge=1)


class UserBlockRead(BaseModel):
    blocked_user_id: int
    created_at: datetime

    model_config = {"from_attributes": True}
