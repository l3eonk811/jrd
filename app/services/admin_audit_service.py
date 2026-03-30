from typing import Optional

from sqlalchemy.orm import Session

from app.models.admin_audit_log import AdminAuditLog


def log_admin_action(
    db: Session,
    *,
    admin_id: int,
    action: str,
    target_type: str,
    target_id: int,
    details: Optional[str] = None,
) -> None:
    """Append audit row. Caller should commit the session."""
    db.add(
        AdminAuditLog(
            admin_user_id=admin_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
        )
    )
