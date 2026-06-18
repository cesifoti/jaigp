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


# ── "Ready for AI review" nudge for authors we can't reach by email ──────────

def user_is_email_reachable(user_id: int, db: Session) -> bool:
    """True if we have any email for this user (cached primary or user_emails)."""
    from models.user import User
    from models.user_email import UserEmail
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.email:
        return True
    return (
        db.query(UserEmail.id).filter(UserEmail.user_id == user_id).first() is not None
    )


def ensure_ai_review_ready_notification(user_id: int, db: Session):
    """Create a one-time in-app nudge telling the user their paper reached the
    AI-review stage and that they must add an email to proceed.

    Idempotent: skips if the user already has an UNREAD ai_review_ready
    notification (the linked page lists all of their ready papers, so one is
    enough). Does NOT commit — caller owns the transaction.
    """
    existing = db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.notification_type == "ai_review_ready",
        Notification.read_at.is_(None),
    ).first()
    if existing:
        return None
    return create_notification(
        user_id=user_id,
        notification_type="ai_review_ready",
        link="/ready-for-ai-review",
        db=db,
        content_preview=(
            "Your paper has been endorsed and is ready for AI review. Add an "
            "email to your profile so we can send you the reviewers' feedback, "
            "then submit it for review."
        ),
    )


def notify_unreachable_authors_ready(paper_id: int, db: Session) -> int:
    """For a paper that just reached Stage 2 (Endorsed), nudge every human
    author we CANNOT email. Authors with an email get the campaign email
    instead, so they're skipped here. Returns the number of authors notified.
    Does NOT commit — caller owns the transaction.
    """
    from models.paper import Paper, PaperHumanAuthor
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper or paper.review_stage != 2:
        return 0
    notified = 0
    authors = db.query(PaperHumanAuthor).filter(
        PaperHumanAuthor.paper_id == paper_id,
        PaperHumanAuthor.user_id.isnot(None),
    ).all()
    for a in authors:
        if user_is_email_reachable(a.user_id, db):
            continue
        if ensure_ai_review_ready_notification(a.user_id, db) is not None:
            notified += 1
    return notified
