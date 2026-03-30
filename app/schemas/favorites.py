from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class FavoriteCreate(BaseModel):
    item_id: int


class FavoriteRead(BaseModel):
    id: int
    user_id: int
    item_id: int
    created_at: datetime
    model_config = {"from_attributes": True}


class FavoriteToggleResponse(BaseModel):
    favorited: bool
    item_id: int
