from typing import List, Set
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, status

from app.models.item import Favorite, Item, ItemImage
from app.models.tag import ItemTag, Tag


def _fav_item_options():
    return [
        joinedload(Favorite.item).joinedload(Item.images),
        joinedload(Favorite.item).joinedload(Item.item_tags).joinedload(ItemTag.tag),
        joinedload(Favorite.item).joinedload(Item.adoption_details),
        joinedload(Favorite.item).joinedload(Item.service_details),
        joinedload(Favorite.item).joinedload(Item.owner),
    ]


def toggle_favorite(db: Session, user_id: int, item_id: int) -> dict:
    """
    Toggle favorite status. Returns {"favorited": bool, "item_id": int}.
    """
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    existing = (
        db.query(Favorite)
        .filter(Favorite.user_id == user_id, Favorite.item_id == item_id)
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
        return {"favorited": False, "item_id": item_id}
    else:
        fav = Favorite(user_id=user_id, item_id=item_id)
        db.add(fav)
        db.commit()
        return {"favorited": True, "item_id": item_id}


def get_user_favorites(db: Session, user_id: int, *, limit: int) -> List[Item]:
    favs = (
        db.query(Favorite)
        .options(*_fav_item_options())
        .filter(Favorite.user_id == user_id)
        .order_by(Favorite.created_at.desc())
        .limit(limit)
        .all()
    )
    return [f.item for f in favs]


def is_favorited(db: Session, user_id: int, item_id: int) -> bool:
    return (
        db.query(Favorite)
        .filter(Favorite.user_id == user_id, Favorite.item_id == item_id)
        .first()
    ) is not None


def get_favorited_item_ids(db: Session, user_id: int) -> set[int]:
    rows = db.query(Favorite.item_id).filter(Favorite.user_id == user_id).all()
    return {r.item_id for r in rows}


def get_favorited_item_ids_for_items(db: Session, user_id: int, item_ids: List[int]) -> Set[int]:
    """Which of ``item_ids`` are favorited — avoids loading the user's full favorites set per page."""
    if not item_ids:
        return set()
    rows = (
        db.query(Favorite.item_id)
        .filter(Favorite.user_id == user_id, Favorite.item_id.in_(item_ids))
        .all()
    )
    return {r.item_id for r in rows}
