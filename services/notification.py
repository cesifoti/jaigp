"""Service for creating and managing in-app notifications."""
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from models.notification import Notification


def create_notification(
    user_id: int,
    notification_type: str,
    link: str,
    db: Session,
    source_user_id: int | None = None,
    content_preview: str | None = None,
) -> Notification | None:
    """Create a notification. Skips if target user is the source user."""
    if source_user_id and source_user_id == user_id:
        return None

    if content_preview and len(content_preview) > 200:
        content_preview = content_preview[:197] + "..."

    notif = Notification(
        user_id=user_id,
        notification_type=notification_type,
        source_user_id=source_user_id,
        content_preview=content_preview,
        link=link,
        created_at=datetime.utcnow(),
    )
    db.add(notif)
    return notif


def get_unread_count(user_id: int, db: Session) -> int:
    """Get count of unread notifications. Single COUNT query."""
    return db.query(func.count(Notification.id)).filter(
        Notification.user_id == user_id,
        Notification.read_at.is_(None),
    ).scalar() or 0


def get_notifications(user_id: int, db: Session, limit: int = 50) -> list[Notification]:
    """Get recent notifications, unread first, then by recency."""
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(
            Notification.read_at.is_not(None).asc(),
            Notification.created_at.desc(),
        )
        .limit(limit)
        .all()
    )


def mark_all_as_read(user_id: int, db: Session) -> int:
    """Mark all unread notifications as read. Returns count updated."""
    count = (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
        .update({"read_at": datetime.utcnow()})
    )
    return count


def mark_as_read(notification_id: int, user_id: int, db: Session) -> bool:
    """Mark a single notification as read."""
    notif = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user_id,
    ).first()
    if not notif or notif.read_at:
        return False
    notif.read_at = datetime.utcnow()
    return True
