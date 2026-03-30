from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.blocks import UserBlockCreate, UserBlockRead
from app.services.auth_service import get_current_user
from app.services import block_service

router = APIRouter(prefix="/api/me/blocks", tags=["blocks"])


@router.post("", response_model=UserBlockRead, status_code=status.HTTP_201_CREATED)
def block_user(
    payload: UserBlockCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = block_service.create_user_block(db, current_user.id, payload.blocked_user_id)
    return UserBlockRead(blocked_user_id=row.blocked_id, created_at=row.created_at)


@router.delete("/{blocked_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def unblock_user(
    blocked_user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    removed = block_service.remove_user_block(db, current_user.id, blocked_user_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Block not found")
