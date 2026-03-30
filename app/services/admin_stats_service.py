"""
Operational statistics for the admin console — bounded queries, no vanity analytics.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.admin_audit_log import AdminAuditLog
from app.models.item import Item, ItemStatus
from app.models.messaging import Conversation, Message
from app.models.report import Report
from app.models.user import User

ALLOWED_RANGES = frozenset({"day", "7d", "month", "year"})

# Cap top-N city breakdown to keep aggregation cheap
LISTINGS_BY_CITY_LIMIT = 15


def window_for_range(range_key: str) -> Tuple[datetime, datetime]:
    """Return [start, end] inclusive window in UTC. End is 'now' for all ranges."""
    if range_key not in ALLOWED_RANGES:
        raise ValueError(f"range must be one of: {', '.join(sorted(ALLOWED_RANGES))}")

    now = datetime.now(timezone.utc)
    if range_key == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif range_key == "7d":
        start = now - timedelta(days=7)
    elif range_key == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # year
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, now


def _item_ts():
    return func.coalesce(Item.updated_at, Item.created_at)


def compute_admin_stats(db: Session, range_key: str) -> Dict[str, Any]:
    start, end = window_for_range(range_key)

    total_users = db.query(func.count(User.id)).scalar() or 0
    total_listings = db.query(func.count(Item.id)).scalar() or 0
    total_conversations = db.query(func.count(Conversation.id)).scalar() or 0
    total_blocked_users = db.query(func.count(User.id)).filter(User.is_blocked.is_(True)).scalar() or 0
    total_pending_reports = (
        db.query(func.count(Report.id))
        .filter(
            Report.target_type == "listing",
            Report.status == Report.STATUS_PENDING,
        )
        .scalar()
        or 0
    )

    new_users = (
        db.query(func.count(User.id))
        .filter(User.created_at >= start, User.created_at <= end)
        .scalar()
        or 0
    )

    new_listings = (
        db.query(func.count(Item.id))
        .filter(Item.created_at >= start, Item.created_at <= end)
        .scalar()
        or 0
    )

    published_listings = (
        db.query(func.count(Item.id))
        .filter(
            Item.created_at >= start,
            Item.created_at <= end,
            Item.is_public.is_(True),
            Item.status == ItemStatus.available.value,
        )
        .scalar()
        or 0
    )

    # Unpublished (not public) but still "available" state — moderation / draft-off public surface
    hidden_listings = (
        db.query(func.count(Item.id))
        .filter(
            _item_ts() >= start,
            _item_ts() <= end,
            Item.is_public.is_(False),
            Item.status == ItemStatus.available.value,
        )
        .scalar()
        or 0
    )

    archived_listings = (
        db.query(func.count(Item.id))
        .filter(
            _item_ts() >= start,
            _item_ts() <= end,
            Item.status == ItemStatus.archived.value,
        )
        .scalar()
        or 0
    )

    reports_created = (
        db.query(func.count(Report.id))
        .filter(
            Report.target_type == "listing",
            Report.created_at >= start,
            Report.created_at <= end,
        )
        .scalar()
        or 0
    )

    status_rows = (
        db.query(Report.status, func.count(Report.id))
        .filter(
            Report.target_type == "listing",
            Report.created_at >= start,
            Report.created_at <= end,
        )
        .group_by(Report.status)
        .all()
    )
    reports_by_status: Dict[str, int] = {
        Report.STATUS_PENDING: 0,
        Report.STATUS_REVIEWED: 0,
        Report.STATUS_ACTION_TAKEN: 0,
        Report.STATUS_DISMISSED: 0,
    }
    for st, n in status_rows:
        if st in reports_by_status:
            reports_by_status[st] = int(n)

    conversations_created = (
        db.query(func.count(Conversation.id))
        .filter(Conversation.created_at >= start, Conversation.created_at <= end)
        .scalar()
        or 0
    )

    messages_sent = (
        db.query(func.count(Message.id))
        .filter(Message.created_at >= start, Message.created_at <= end)
        .scalar()
        or 0
    )

    admin_actions_count = (
        db.query(func.count(AdminAuditLog.id))
        .filter(AdminAuditLog.created_at >= start, AdminAuditLog.created_at <= end)
        .scalar()
        or 0
    )

    type_rows = (
        db.query(Item.listing_type, func.count(Item.id))
        .filter(Item.created_at >= start, Item.created_at <= end)
        .group_by(Item.listing_type)
        .all()
    )
    listings_by_type: Dict[str, int] = {}
    for lt, n in type_rows:
        key = lt if lt else "(none)"
        listings_by_type[key] = int(n)

    # Owner city for listings created in window (top N, null city excluded)
    city_rows = (
        db.query(User.city, func.count(Item.id))
        .join(Item, Item.user_id == User.id)
        .filter(
            Item.created_at >= start,
            Item.created_at <= end,
            User.city.isnot(None),
            User.city != "",
        )
        .group_by(User.city)
        .order_by(func.count(Item.id).desc())
        .limit(LISTINGS_BY_CITY_LIMIT)
        .all()
    )
    listings_by_city: List[Dict[str, Any]] = [{"city": c, "count": int(n)} for c, n in city_rows if c]

    return {
        "totals": {
            "total_users": int(total_users),
            "total_listings": int(total_listings),
            "total_conversations": int(total_conversations),
            "total_blocked_users": int(total_blocked_users),
            "total_pending_reports": int(total_pending_reports),
        },
        "activity": {
            "time_range": range_key,
            "period_start": start,
            "period_end": end,
            "new_users": int(new_users),
            "new_listings": int(new_listings),
            "published_listings": int(published_listings),
            "hidden_listings": int(hidden_listings),
            "archived_listings": int(archived_listings),
            "reports_created": int(reports_created),
            "reports_by_status": reports_by_status,
            "conversations_created": int(conversations_created),
            "messages_sent": int(messages_sent),
            "admin_actions_count": int(admin_actions_count),
            "listings_by_type": listings_by_type,
            "listings_by_city": listings_by_city,
        },
    }
