from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.report import Report
from app.schemas.listing_report import ListingReportCreate, ListingReportRead
from app.services.auth_service import get_current_user
from app.services import item_service

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.post("/{item_id}", response_model=ListingReportRead, status_code=status.HTTP_201_CREATED)
def report_listing(
    item_id: int,
    payload: ListingReportCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = item_service.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not item.is_public:
        raise HTTPException(status_code=403, detail="Cannot report a private listing")
    if item.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot report your own listing")

    report = Report(
        reporter_user_id=current_user.id,
        target_type="listing",
        target_id=item_id,
        reason=payload.reason,
        note=payload.details,
        status=Report.STATUS_PENDING,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return ListingReportRead(
        id=report.id,
        item_id=report.target_id,
        reporter_user_id=report.reporter_user_id,
        reason=report.reason,
        details=report.note,
        created_at=report.created_at,
    )
