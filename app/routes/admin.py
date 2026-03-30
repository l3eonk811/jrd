"""Admin-only API (separate from mobile/user flows)."""

from pathlib import Path
from typing import Optional

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, aliased, joinedload

from app.config import get_settings
from app.services.listing_media_storage import ensure_item_image_dir, public_url_for_item_image
from app.database import get_db
from app.models.admin_audit_log import AdminAuditLog
from app.models.item import Item, ItemImage, ItemStatus, ListingDomain
from app.models.messaging import Conversation, Message
from app.models.report import Report
from app.models.provider_rating import ProviderRating
from app.models.user import User
from app.routes.conversations import _last_message_preview
from app.schemas.admin import (
    AdminAuditListResponse,
    AdminAuditRow,
    AdminConversationDetail,
    AdminConversationListResponse,
    AdminConversationParticipantBrief,
    AdminConversationSummary,
    AdminListingBrief,
    AdminListingDetail,
    AdminListingImageBrief,
    AdminListingListResponse,
    AdminListingOkResponse,
    AdminListingOwnerBrief,
    AdminListingRow,
    AdminMeResponse,
    AdminMessageRow,
    AdminProviderListResponse,
    AdminProviderRatingListResponse,
    AdminProviderRatingRow,
    AdminProviderRatingSummary,
    AdminProviderRow,
    AdminReportListResponse,
    AdminReportReporterBrief,
    AdminReportRow,
    AdminReportStatusResponse,
    AdminStatsResponse,
    AdminSettingListResponse,
    AdminSettingPatch,
    AdminSettingRow,
    AdminUserDetail,
    AdminUserFlagResponse,
    AdminUserListResponse,
    AdminUserRolePatch,
    AdminUserRow,
    AdminUserStaffPatch,
)
from app.schemas.item import ItemUpdate
from app.schemas.user import LoginRequest, Token
from app.services.admin_login_rate_limit import (
    clear_admin_login_failures,
    enforce_admin_login_rate_limit,
    record_failed_admin_login,
)
from app.services.admin_audit_service import log_admin_action
from app.services.auth_service import (
    ADMIN_ROLES,
    ROLE_MODERATOR,
    ROLE_SUPER_ADMIN,
    ROLE_VIEWER,
    authenticate_user,
    create_access_token,
    require_admin,
    require_min_role,
    require_valid_admin_role,
)
from app.services import block_service
from app.services import conversation_service
from app.services import embedding_service
from app.services import item_service as item_service_mod
from app.services.admin_stats_service import compute_admin_stats
from app.services.settings_service import get_all_settings, get_max_images_per_listing, set_setting

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/audit", response_model=AdminAuditListResponse)
def admin_list_audit(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = Query(None, description="Search action, target type, admin name/username, or target id"),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_min_role(ROLE_MODERATOR)),
):
    base = db.query(AdminAuditLog, User).outerjoin(User, AdminAuditLog.admin_user_id == User.id)
    if q and q.strip():
        term = f"%{q.strip()}%"
        parts = [
            AdminAuditLog.action.ilike(term),
            AdminAuditLog.target_type.ilike(term),
            User.username.ilike(term),
            User.display_name.ilike(term),
        ]
        qs = q.strip()
        if qs.lstrip("-").isdigit():
            parts.append(AdminAuditLog.target_id == int(qs))
        base = base.filter(or_(*parts))
    total = base.count()
    rows = (
        base.order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items: list[AdminAuditRow] = []
    for log_row, admin_user in rows:
        items.append(
            AdminAuditRow(
                id=log_row.id,
                admin_user_id=log_row.admin_user_id,
                admin_display_name=admin_user.display_name if admin_user else None,
                admin_username=admin_user.username if admin_user else None,
                action=log_row.action,
                target_type=log_row.target_type,
                target_id=log_row.target_id,
                details=log_row.details,
                created_at=log_row.created_at,
            )
        )
    return AdminAuditListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/settings", response_model=AdminSettingListResponse)
def admin_list_settings(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_min_role(ROLE_SUPER_ADMIN)),
):
    rows = get_all_settings(db)
    return AdminSettingListResponse(
        items=[
            AdminSettingRow(
                key=r.key,
                value=r.value,
                description=r.description,
                updated_at=r.updated_at,
            )
            for r in rows
        ]
    )


@router.patch("/settings/{key}", response_model=AdminSettingRow)
def admin_patch_setting(
    key: str,
    body: AdminSettingPatch,
    db: Session = Depends(get_db),
    admin: User = Depends(require_min_role(ROLE_SUPER_ADMIN)),
):
    row = set_setting(db, key, body.value)
    log_admin_action(
        db,
        admin_id=admin.id,
        action="update_setting",
        target_type="app_setting",
        target_id=row.id,
        details=f"{key} changed",
    )
    db.commit()
    db.refresh(row)
    return AdminSettingRow(
        key=row.key,
        value=row.value,
        description=row.description,
        updated_at=row.updated_at,
    )


@router.post("/login", response_model=Token)
def admin_login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    enforce_admin_login_rate_limit(request)
    user = authenticate_user(db, payload.email, payload.password)
    if not user:
        record_failed_admin_login(request)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if user.is_blocked:
        record_failed_admin_login(request)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    if not user.is_admin:
        record_failed_admin_login(request)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    clear_admin_login_failures(request)
    role = require_valid_admin_role(user)
    return Token(
        access_token=create_access_token(user.id, is_admin=True, role=role),
        token_type="bearer",
    )


@router.get("/me", response_model=AdminMeResponse)
def admin_me(admin: User = Depends(require_admin)):
    r = require_valid_admin_role(admin)
    return AdminMeResponse(id=admin.id, email=admin.email, username=admin.username, role=r)


@router.get("/text-embedding-reindex/pending")
def admin_text_embedding_reindex_pending(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
    limit: int = Query(50, ge=1, le=500, description="Max item ids to return"),
):
    """
    Operational: count and sample listings pending text-embedding reindex (explicit flag).
    Does not trigger indexing; run ``python -m tools.index_text_embeddings`` separately.
    """
    from app.services.text_embedding_reindex import (
        count_listings_pending_text_embedding_reindex,
        sample_listing_ids_pending_text_embedding_reindex,
    )

    return {
        "pending_count": count_listings_pending_text_embedding_reindex(db),
        "sample_item_ids": sample_listing_ids_pending_text_embedding_reindex(db, limit=limit),
    }


@router.get("/stats", response_model=AdminStatsResponse)
def admin_get_stats(
    range_param: str = Query(..., alias="range", description="day | 7d | month | year"),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Operational counts (totals + time-window activity). All timestamps UTC."""
    rk = (range_param or "").strip()
    try:
        payload = compute_admin_stats(db, rk)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return AdminStatsResponse.model_validate(payload)


def _build_user_detail(db: Session, user: User) -> AdminUserDetail:
    listings_count = db.query(func.count(Item.id)).filter(Item.user_id == user.id).scalar() or 0

    reports_count = (
        db.query(func.count(Report.id))
        .join(Item, Report.target_id == Item.id)
        .filter(Report.target_type == "listing", Item.user_id == user.id)
        .scalar()
        or 0
    )

    rating_row = (
        db.query(func.avg(ProviderRating.stars), func.count(ProviderRating.id))
        .filter(ProviderRating.provider_user_id == user.id)
        .first()
    )
    provider_summary: Optional[AdminProviderRatingSummary] = None
    if rating_row and (rating_row[1] or 0) > 0:
        provider_summary = AdminProviderRatingSummary(
            average_rating=round(float(rating_row[0] or 0), 2),
            rating_count=int(rating_row[1]),
        )

    recent = (
        db.query(Item)
        .filter(Item.user_id == user.id)
        .order_by(Item.created_at.desc())
        .limit(10)
        .all()
    )
    recent_listings = [
        AdminListingBrief(
            id=it.id,
            title=it.title,
            listing_domain=it.listing_domain,
            status=it.status,
            is_public=it.is_public,
            created_at=it.created_at,
        )
        for it in recent
    ]

    return AdminUserDetail(
        id=user.id,
        email=user.email,
        name=user.display_name,
        username=user.username,
        phone=user.phone_number,
        created_at=user.created_at,
        is_active=user.is_active,
        is_blocked=user.is_blocked,
        is_admin=user.is_admin,
        role=getattr(user, "role", None) or "viewer",
        listings_count=int(listings_count),
        reports_count=int(reports_count),
        provider_rating_summary=provider_summary,
        recent_listings=recent_listings,
    )


@router.get("/users", response_model=AdminUserListResponse)
def admin_list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = Query(None, description="Search email, username, display name"),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    base = db.query(User)
    if q and q.strip():
        term = f"%{q.strip()}%"
        base = base.filter(
            or_(
                User.email.ilike(term),
                User.username.ilike(term),
                User.display_name.ilike(term),
            )
        )
    total = base.count()
    users = (
        base.order_by(User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items: list[AdminUserRow] = []
    for u in users:
        n = db.query(func.count(Item.id)).filter(Item.user_id == u.id).scalar() or 0
        items.append(
            AdminUserRow(
                id=u.id,
                name=u.display_name,
                username=u.username,
                phone=u.phone_number,
                created_at=u.created_at,
                is_active=u.is_active,
                is_blocked=u.is_blocked,
                is_admin=bool(u.is_admin),
                role=getattr(u, "role", None) or "viewer",
                listings_count=int(n),
            )
        )
    return AdminUserListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/users/{user_id}", response_model=AdminUserDetail)
def admin_get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _build_user_detail(db, user)


@router.patch("/users/{user_id}/block", response_model=AdminUserFlagResponse)
def admin_block_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_min_role(ROLE_MODERATOR)),
):
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot block yourself")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.is_blocked = True
    db.add(user)
    log_admin_action(
        db,
        admin_id=admin.id,
        action="block_user",
        target_type="user",
        target_id=user_id,
    )
    db.commit()
    return AdminUserFlagResponse(user_id=user_id, is_blocked=True)


@router.patch("/users/{user_id}/unblock", response_model=AdminUserFlagResponse)
def admin_unblock_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_min_role(ROLE_MODERATOR)),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.is_blocked = False
    db.add(user)
    log_admin_action(
        db,
        admin_id=admin.id,
        action="unblock_user",
        target_type="user",
        target_id=user_id,
    )
    db.commit()
    return AdminUserFlagResponse(user_id=user_id, is_blocked=False)


@router.patch("/users/{user_id}/role", response_model=AdminMeResponse)
def admin_set_user_role(
    user_id: int,
    body: AdminUserRolePatch,
    db: Session = Depends(get_db),
    admin: User = Depends(require_min_role(ROLE_SUPER_ADMIN)),
):
    """Change admin role for another staff user. Cannot change your own role."""
    if body.role not in ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid role",
        )
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own role",
        )
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not target.is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role can only be set for admin users",
        )
    if getattr(target, "role", None) == ROLE_SUPER_ADMIN and body.role != ROLE_SUPER_ADMIN:
        super_count = (
            db.query(func.count(User.id))
            .filter(User.is_admin == True, User.role == ROLE_SUPER_ADMIN)
            .scalar()
            or 0
        )
        if super_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote the last super admin",
            )
    target.role = body.role
    db.add(target)
    log_admin_action(
        db,
        admin_id=admin.id,
        action="update_user_role",
        target_type="user",
        target_id=user_id,
        details=f"role={body.role}",
    )
    db.commit()
    db.refresh(target)
    return AdminMeResponse(
        id=target.id,
        email=target.email,
        username=target.username,
        role=body.role,
    )


# ── Listings moderation ───────────────────────────────────────────────────────


def _listing_report_subquery(db: Session):
    return (
        db.query(Report.target_id.label("iid"), func.count(Report.id).label("rcount"))
        .filter(Report.target_type == "listing")
        .group_by(Report.target_id)
        .subquery()
    )


def _to_listing_row(item: Item, owner: User, reports_count: int) -> AdminListingRow:
    return AdminListingRow(
        id=item.id,
        title=item.title,
        listing_domain=item.listing_domain,
        listing_type=item.listing_type,
        owner=AdminListingOwnerBrief(
            id=owner.id,
            name=owner.display_name,
            username=owner.username,
        ),
        status=item.status,
        is_hidden=not item.is_public,
        created_at=item.created_at,
        reports_count=int(reports_count),
    )


def _fetch_listing_with_meta(db: Session, item_id: int):
    rc = _listing_report_subquery(db)
    row = (
        db.query(Item, User, func.coalesce(rc.c.rcount, 0))
        .join(User, Item.user_id == User.id)
        .outerjoin(rc, Item.id == rc.c.iid)
        .options(joinedload(Item.images))
        .filter(Item.id == item_id)
        .first()
    )
    if not row:
        return None
    item, owner, rcount = row
    return item, owner, int(rcount)


def _admin_listing_detail_response(db: Session, item_id: int) -> AdminListingDetail:
    meta = _fetch_listing_with_meta(db, item_id)
    if meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    item, owner, rcount = meta
    row = _to_listing_row(item, owner, rcount)
    imgs = sorted(item.images or [], key=lambda im: (not im.is_primary, im.id))
    image_rows = [AdminListingImageBrief(id=im.id, url=im.url, is_primary=bool(im.is_primary)) for im in imgs]
    return AdminListingDetail(
        **row.model_dump(),
        description=item.description,
        latitude=item.latitude,
        longitude=item.longitude,
        show_phone_in_listing=bool(item.show_phone_in_listing),
        allow_messages=bool(item.allow_messages),
        images=image_rows,
    )


@router.get("/listings", response_model=AdminListingListResponse)
def admin_list_listings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = Query(None, description="Search title / description"),
    owner_user_id: Optional[int] = Query(None, description="Filter by listing owner user id"),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    rc = _listing_report_subquery(db)
    base = (
        db.query(Item, User, func.coalesce(rc.c.rcount, 0).label("rcount"))
        .join(User, Item.user_id == User.id)
        .outerjoin(rc, Item.id == rc.c.iid)
    )
    if owner_user_id is not None:
        base = base.filter(Item.user_id == owner_user_id)
    if q and q.strip():
        term = f"%{q.strip()}%"
        base = base.filter(or_(Item.title.ilike(term), Item.description.ilike(term)))
    total = base.count()
    rows = (
        base.order_by(Item.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [_to_listing_row(it, owner, int(rcount or 0)) for it, owner, rcount in rows]
    return AdminListingListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/listings/{item_id}", response_model=AdminListingDetail)
def admin_get_listing(
    item_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return _admin_listing_detail_response(db, item_id)


@router.patch("/listings/{item_id}/hide", response_model=AdminListingOkResponse)
def admin_hide_listing(
    item_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_min_role(ROLE_MODERATOR)),
):
    item_service_mod.admin_set_listing_public(db, item_id, is_public=False)
    log_admin_action(
        db,
        admin_id=admin.id,
        action="hide_listing",
        target_type="listing",
        target_id=item_id,
    )
    db.commit()
    return AdminListingOkResponse(listing_id=item_id, is_hidden=True)


@router.patch("/listings/{item_id}/unhide", response_model=AdminListingOkResponse)
def admin_unhide_listing(
    item_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_min_role(ROLE_MODERATOR)),
):
    item_service_mod.admin_set_listing_public(db, item_id, is_public=True)
    log_admin_action(
        db,
        admin_id=admin.id,
        action="unhide_listing",
        target_type="listing",
        target_id=item_id,
    )
    db.commit()
    return AdminListingOkResponse(listing_id=item_id, is_hidden=False)


@router.delete("/listings/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_listing_route(
    item_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_min_role(ROLE_SUPER_ADMIN)),
):
    item_service_mod.admin_delete_listing(db, item_id)
    log_admin_action(
        db,
        admin_id=admin.id,
        action="delete_listing",
        target_type="listing",
        target_id=item_id,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Listing reports (moderation) ──────────────────────────────────────────────


def _to_admin_report_row(report: Report, reporter: User) -> AdminReportRow:
    return AdminReportRow(
        id=report.id,
        reporter=AdminReportReporterBrief(
            id=reporter.id,
            username=reporter.username,
            display_name=reporter.display_name,
        ),
        target_type=report.target_type,
        target_id=report.target_id,
        reason=report.reason,
        note=report.note,
        status=report.status,
        created_at=report.created_at,
    )


def _admin_reports_base_query(db: Session):
    return (
        db.query(Report, User)
        .join(User, Report.reporter_user_id == User.id)
        .filter(Report.target_type == "listing")
    )


@router.get("/reports", response_model=AdminReportListResponse)
def admin_list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status", description="pending|reviewed|action_taken|dismissed"),
    q: Optional[str] = Query(None, description="Search reason, reporter, or target id"),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    base = _admin_reports_base_query(db)
    if status_filter and status_filter.strip():
        base = base.filter(Report.status == status_filter.strip())
    if q and q.strip():
        term = f"%{q.strip()}%"
        parts = [Report.reason.ilike(term), User.username.ilike(term), User.display_name.ilike(term)]
        qs = q.strip()
        if qs.lstrip("-").isdigit():
            parts.append(Report.target_id == int(qs))
        base = base.filter(or_(*parts))
    total = base.count()
    rows = (
        base.order_by(Report.created_at.desc(), Report.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [_to_admin_report_row(r, u) for r, u in rows]
    return AdminReportListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/reports/{report_id}", response_model=AdminReportRow)
def admin_get_report(
    report_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    row = _admin_reports_base_query(db).filter(Report.id == report_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    report, reporter = row
    return _to_admin_report_row(report, reporter)


@router.patch("/reports/{report_id}/review", response_model=AdminReportStatusResponse)
def admin_review_report(
    report_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_min_role(ROLE_MODERATOR)),
):
    report = db.query(Report).filter(Report.id == report_id, Report.target_type == "listing").first()
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    if report.status != Report.STATUS_PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending reports can be marked reviewed",
        )
    report.status = Report.STATUS_REVIEWED
    db.add(report)
    db.commit()
    db.refresh(report)
    return AdminReportStatusResponse(id=report.id, status=report.status)


@router.patch("/reports/{report_id}/dismiss", response_model=AdminReportStatusResponse)
def admin_dismiss_report(
    report_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_min_role(ROLE_MODERATOR)),
):
    report = db.query(Report).filter(Report.id == report_id, Report.target_type == "listing").first()
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    if report.status == Report.STATUS_ACTION_TAKEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot dismiss after action was taken",
        )
    report.status = Report.STATUS_DISMISSED
    db.add(report)
    db.commit()
    db.refresh(report)
    return AdminReportStatusResponse(id=report.id, status=report.status)


@router.patch("/reports/{report_id}/take-action", response_model=AdminReportStatusResponse)
def admin_take_action_report(
    report_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_min_role(ROLE_MODERATOR)),
):
    report = db.query(Report).filter(Report.id == report_id, Report.target_type == "listing").first()
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    if report.status == Report.STATUS_ACTION_TAKEN:
        return AdminReportStatusResponse(id=report.id, status=report.status)

    item = db.query(Item).filter(Item.id == report.target_id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found")

    was_public = bool(item.is_public)
    report.status = Report.STATUS_ACTION_TAKEN
    db.add(report)
    if was_public:
        item_service_mod.admin_set_listing_public(db, item.id, is_public=False)

    details = (
        f"Report #{report.id} → listing #{report.target_id} hidden"
        if was_public
        else f"Report #{report.id} → listing #{report.target_id} action taken (already private)"
    )
    log_admin_action(
        db,
        admin_id=admin.id,
        action="report_action_taken",
        target_type="listing",
        target_id=item.id,
        details=details,
    )
    db.commit()
    db.refresh(report)
    return AdminReportStatusResponse(id=report.id, status=report.status)


# ── User staff (promote/demote admin) ─────────────────────────────────────────


@router.patch("/users/{user_id}/staff", response_model=AdminMeResponse)
def admin_patch_user_staff(
    user_id: int,
    body: AdminUserStaffPatch,
    db: Session = Depends(get_db),
    admin: User = Depends(require_min_role(ROLE_SUPER_ADMIN)),
):
    """Promote a user to admin or demote; assign console role. Enforces last-super-admin safety."""
    if user_id == admin.id and not body.is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove your own admin access",
        )
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    def _super_admin_count() -> int:
        return (
            db.query(func.count(User.id))
            .filter(User.is_admin == True, User.role == ROLE_SUPER_ADMIN)
            .scalar()
            or 0
        )

    old_is_super = bool(target.is_admin and getattr(target, "role", None) == ROLE_SUPER_ADMIN)

    if body.is_admin:
        if not body.role or body.role not in ADMIN_ROLES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="role is required and must be a valid admin role when is_admin is true",
            )
        if old_is_super and body.role != ROLE_SUPER_ADMIN:
            if _super_admin_count() <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot demote the last super admin",
                )
        target.is_admin = True
        target.role = body.role
    else:
        if old_is_super and _super_admin_count() <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote the last super admin",
            )
        target.is_admin = False
        target.role = ROLE_VIEWER

    db.add(target)
    log_admin_action(
        db,
        admin_id=admin.id,
        action="update_user_staff",
        target_type="user",
        target_id=user_id,
        details=f"is_admin={body.is_admin} role={getattr(target, 'role', None)}",
    )
    db.commit()
    db.refresh(target)
    r = require_valid_admin_role(target) if target.is_admin else ROLE_VIEWER
    return AdminMeResponse(
        id=target.id,
        email=target.email,
        username=target.username,
        role=r,
    )


# ── Listing edit (moderator+) ───────────────────────────────────────────────────


@router.patch("/listings/{item_id}", response_model=AdminListingDetail)
def admin_patch_listing(
    item_id: int,
    body: ItemUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_min_role(ROLE_MODERATOR)),
):
    item_service_mod.admin_update_listing(db, item_id, body)
    log_admin_action(
        db,
        admin_id=admin.id,
        action="edit_listing",
        target_type="listing",
        target_id=item_id,
        details="admin ItemUpdate",
    )
    db.commit()
    return _admin_listing_detail_response(db, item_id)


@router.delete("/listings/{item_id}/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_listing_image(
    item_id: int,
    image_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_min_role(ROLE_MODERATOR)),
):
    settings = get_settings()
    item_service_mod.admin_delete_image_from_item(
        db, item_id, image_id, upload_dir=settings.upload_dir
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/listings/{item_id}/images/{image_id}/primary", response_model=AdminListingImageBrief)
def admin_set_listing_primary_image_route(
    item_id: int,
    image_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_min_role(ROLE_MODERATOR)),
):
    img = item_service_mod.admin_set_primary_image(db, item_id, image_id)
    return AdminListingImageBrief(id=img.id, url=img.url, is_primary=bool(img.is_primary))


_ADMIN_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_ADMIN_MAX_IMAGE_MB = 5


@router.post("/listings/{item_id}/images", response_model=AdminListingImageBrief)
async def admin_upload_listing_image(
    item_id: int,
    file: UploadFile = File(...),
    is_primary: bool = False,
    db: Session = Depends(get_db),
    admin: User = Depends(require_min_role(ROLE_MODERATOR)),
):
    if file.content_type not in _ADMIN_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Use JPG, PNG, or WEBP.",
        )
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > _ADMIN_MAX_IMAGE_MB:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image too large ({size_mb:.1f} MB). Max {_ADMIN_MAX_IMAGE_MB} MB.",
        )
    max_images = get_max_images_per_listing(db)
    existing_count = db.query(ItemImage).filter(ItemImage.item_id == item_id).count()
    if existing_count >= max_images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {max_images} images per listing reached.",
        )
    if not is_primary:
        primary_exists = (
            db.query(ItemImage)
            .filter(ItemImage.item_id == item_id, ItemImage.is_primary == True)
            .first()
        )
        if not primary_exists:
            is_primary = True

    settings = get_settings()
    upload_dir = ensure_item_image_dir(item_id)
    ext = Path(file.filename or "upload").suffix or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = upload_dir / filename
    file_path.write_bytes(content)
    url = public_url_for_item_image(item_id, filename)
    image = item_service_mod.add_image_to_item(
        db=db,
        item_id=item_id,
        filename=filename,
        url=url,
        is_primary=is_primary,
        owner=None,
    )
    try:
        embedding_vec = await embedding_service.generate_embedding(file_path, device=settings.ai_device)
        embedding_service.save_embedding(db, item_id, embedding_vec)
    except Exception:
        pass
    log_admin_action(
        db,
        admin_id=admin.id,
        action="admin_upload_listing_image",
        target_type="listing",
        target_id=item_id,
        details=f"image_id={image.id}",
    )
    db.commit()
    return AdminListingImageBrief(id=image.id, url=image.url, is_primary=bool(image.is_primary))


# ── Providers directory (service listings) ─────────────────────────────────────


@router.get("/providers", response_model=AdminProviderListResponse)
def admin_list_providers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = Query(None, description="Search username, display name, or email"),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    sub = (
        db.query(Item.user_id.label("uid"), func.count(Item.id).label("svc_n"))
        .filter(Item.listing_domain == ListingDomain.service.value)
        .filter(Item.status.notin_([ItemStatus.archived.value, ItemStatus.removed.value]))
        .group_by(Item.user_id)
        .subquery()
    )
    base = db.query(User, sub.c.svc_n).join(sub, User.id == sub.c.uid)
    if q and q.strip():
        term = f"%{q.strip()}%"
        base = base.filter(
            or_(User.username.ilike(term), User.display_name.ilike(term), User.email.ilike(term))
        )
    total = base.count()
    rows = (
        base.order_by(User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items: list[AdminProviderRow] = []
    for u, svc_n in rows:
        rating_row = (
            db.query(func.avg(ProviderRating.stars), func.count(ProviderRating.id))
            .filter(ProviderRating.provider_user_id == u.id)
            .first()
        )
        avg = None
        rc = 0
        if rating_row and (rating_row[1] or 0) > 0:
            avg = round(float(rating_row[0] or 0), 2)
            rc = int(rating_row[1])
        items.append(
            AdminProviderRow(
                user_id=u.id,
                username=u.username,
                display_name=u.display_name,
                city=u.city,
                active_service_listings=int(svc_n or 0),
                average_rating=avg,
                rating_count=rc,
            )
        )
    return AdminProviderListResponse(items=items, total=total, page=page, page_size=page_size)


# ── Provider ratings ────────────────────────────────────────────────────────────


@router.get("/provider-ratings", response_model=AdminProviderRatingListResponse)
def admin_list_provider_ratings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    PU = aliased(User)
    RU = aliased(User)
    base = (
        db.query(ProviderRating, PU, RU)
        .join(PU, ProviderRating.provider_user_id == PU.id)
        .join(RU, ProviderRating.rater_user_id == RU.id)
    )
    total = base.count()
    rows = (
        base.order_by(ProviderRating.created_at.desc(), ProviderRating.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        AdminProviderRatingRow(
            id=pr.id,
            provider_user_id=pu.id,
            provider_username=pu.username,
            rater_user_id=ru.id,
            rater_username=ru.username,
            stars=pr.stars,
            comment=pr.comment,
            created_at=pr.created_at,
        )
        for pr, pu, ru in rows
    ]
    return AdminProviderRatingListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/provider-ratings/{rating_id}", response_model=AdminProviderRatingRow)
def admin_get_provider_rating(
    rating_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    PU = aliased(User)
    RU = aliased(User)
    row = (
        db.query(ProviderRating, PU, RU)
        .join(PU, ProviderRating.provider_user_id == PU.id)
        .join(RU, ProviderRating.rater_user_id == RU.id)
        .filter(ProviderRating.id == rating_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rating not found")
    pr, pu, ru = row
    return AdminProviderRatingRow(
        id=pr.id,
        provider_user_id=pu.id,
        provider_username=pu.username,
        rater_user_id=ru.id,
        rater_username=ru.username,
        stars=pr.stars,
        comment=pr.comment,
        created_at=pr.created_at,
    )


@router.delete("/provider-ratings/{rating_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_provider_rating(
    rating_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_min_role(ROLE_SUPER_ADMIN)),
):
    pr = db.query(ProviderRating).filter(ProviderRating.id == rating_id).first()
    if pr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rating not found")
    db.delete(pr)
    log_admin_action(
        db,
        admin_id=admin.id,
        action="delete_provider_rating",
        target_type="provider_rating",
        target_id=rating_id,
        details=None,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Conversations (read-only admin) ─────────────────────────────────────────────


def _admin_conv_summary(
    db: Session, conv: Conversation, last_msg: Optional[Message] = None
) -> AdminConversationSummary:
    owner_u = conv.owner
    int_u = conv.interested_user
    preview = _last_message_preview(last_msg) if last_msg else None
    you_block, they_block, _ = block_service.block_flags_for_viewer(
        db, owner_u.id if owner_u else 0, int_u.id if int_u else 0
    )
    return AdminConversationSummary(
        id=conv.id,
        item_id=conv.item_id,
        item_title=conv.item.title if conv.item else None,
        owner=AdminConversationParticipantBrief(
            id=owner_u.id, username=owner_u.username, display_name=owner_u.display_name
        ),
        interested=AdminConversationParticipantBrief(
            id=int_u.id, username=int_u.username, display_name=int_u.display_name
        ),
        last_message_preview=preview,
        last_message_at=last_msg.created_at if last_msg else None,
        updated_at=conv.updated_at,
        created_at=conv.created_at,
        you_blocked_them=you_block,
        they_blocked_you=they_block,
    )


@router.get("/conversations", response_model=AdminConversationListResponse)
def admin_list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    rows, total = conversation_service.list_conversations_for_admin(db, page=page, page_size=page_size)
    last_by = conversation_service.last_messages_for_conversation_ids(db, [c.id for c in rows])
    items = [_admin_conv_summary(db, c, last_by.get(c.id)) for c in rows]
    return AdminConversationListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/conversations/{conversation_id}", response_model=AdminConversationDetail)
def admin_get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    conv = conversation_service.get_conversation_for_admin(db, conversation_id)
    owner_u = conv.owner
    int_u = conv.interested_user
    you_block, they_block, _ = block_service.block_flags_for_viewer(
        db, owner_u.id, int_u.id
    )
    msgs = [
        AdminMessageRow(
            id=m.id,
            sender_user_id=m.sender_user_id,
            sender_username=m.sender.username if m.sender else None,
            body=m.body,
            message_kind=(m.message_kind or "text"),
            latitude=m.latitude,
            longitude=m.longitude,
            created_at=m.created_at,
            read_at=m.read_at,
        )
        for m in conv.messages
    ]
    item = conv.item
    return AdminConversationDetail(
        id=conv.id,
        item_id=conv.item_id,
        item_title=item.title if item else None,
        listing_domain=item.listing_domain if item else None,
        listing_type=item.listing_type if item else None,
        owner=AdminConversationParticipantBrief(
            id=owner_u.id, username=owner_u.username, display_name=owner_u.display_name
        ),
        interested=AdminConversationParticipantBrief(
            id=int_u.id, username=int_u.username, display_name=int_u.display_name
        ),
        messages=msgs,
        you_blocked_them=you_block,
        they_blocked_you=they_block,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )
