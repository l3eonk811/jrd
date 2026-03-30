"""
Seed the database with sample users and items for development.
Run: python seed.py

Exits with 0 on success, 1 on validation or DB error (clear message, no traceback
repeated on restart). Passwords are validated against the same rules as the API
(bcrypt 72-byte limit, non-empty).
"""

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# Development-only seed passwords: short, valid, and within bcrypt limit.
SEED_PASSWORD = "dev123"

# `is_admin` / `role` only where needed; others default to normal app users (viewer).
USERS = [
    {
        "email": "alice@example.com",
        "username": "alice",
        "lat": 40.7128,
        "lon": -74.0060,
        "is_admin": True,
        "role": "super_admin",
    },
    {"email": "bob@example.com", "username": "bob", "lat": 40.7200, "lon": -74.0100},
]

ITEMS = [
    {
        "title": "Vintage Desk Lamp",
        "description": "Beautiful brass desk lamp, works perfectly.",
        "category": "Furniture",
        "condition": "like_new",
        "is_public": True,
        "lat": 40.7128,
        "lon": -74.0060,
        "tags": ["vintage", "lighting"],
    },
    {
        "title": "Bluetooth Speaker",
        "description": "Portable speaker, minor scratches on the bottom.",
        "category": "Electronics",
        "condition": "good",
        "is_public": True,
        "lat": 40.7130,
        "lon": -74.0065,
        "tags": ["wireless", "portable"],
    },
    {
        "title": "Wooden Bookshelf",
        "description": "5-shelf unit, solid pine, dismantled for easy pickup.",
        "category": "Furniture",
        "condition": "good",
        "is_public": False,
        "lat": 40.7128,
        "lon": -74.0060,
        "tags": ["storage", "handmade"],
    },
    {
        "title": "Running Shoes (Size 10)",
        "description": "Used for 3 months, minimal wear.",
        "category": "Clothing",
        "condition": "good",
        "is_public": True,
        "lat": 40.7200,
        "lon": -74.0100,
        "tags": ["sports", "outdoor"],
    },
]


def run():
    from app.database import SessionLocal
    from app.models import User, Item, Tag, ItemTag
    from app.services.auth_service import hash_password, PasswordError

    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            log.info("Database already seeded. Skipping.")
            return

        # Validate seed password once before creating any users.
        try:
            hash_password(SEED_PASSWORD)
        except PasswordError as e:
            log.error("Seed password validation failed: %s", e)
            sys.exit(1)

        created_users = []
        for u in USERS:
            try:
                user = User(
                    email=u["email"],
                    username=u["username"],
                    hashed_password=hash_password(SEED_PASSWORD),
                    latitude=u["lat"],
                    longitude=u["lon"],
                    is_admin=bool(u.get("is_admin", False)),
                    role=(u.get("role") or "viewer"),
                )
                db.add(user)
                db.flush()
                created_users.append(user)
            except PasswordError as e:
                log.error("Invalid seed user %s: %s", u.get("username", "?"), e)
                db.rollback()
                sys.exit(1)
            except Exception as e:
                log.exception("Failed to create seed user %s", u.get("username", "?"))
                db.rollback()
                sys.exit(1)

        from app.models.item import ItemStatus
        for i, item_data in enumerate(ITEMS):
            owner = created_users[i % len(created_users)]
            status = ItemStatus.available if item_data["is_public"] else ItemStatus.draft
            item = Item(
                user_id=owner.id,
                title=item_data["title"],
                description=item_data["description"],
                category=item_data["category"],
                condition=item_data["condition"],
                status=status.value,
                is_public=item_data["is_public"],
                latitude=item_data["lat"],
                longitude=item_data["lon"],
            )
            db.add(item)
            db.flush()

            for tag_name in item_data["tags"]:
                tag = db.query(Tag).filter(Tag.name == tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    db.add(tag)
                    db.flush()
                db.add(ItemTag(item_id=item.id, tag_id=tag.id))

        db.commit()
        log.info("Seeded %d users and %d items. Seed password: %s", len(created_users), len(ITEMS), SEED_PASSWORD)
        log.info(
            "Admin console: POST /api/admin/login as alice@example.com / %s (super_admin).",
            SEED_PASSWORD,
        )
    except Exception as e:
        log.error("Seed failed: %s", e)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    run()
