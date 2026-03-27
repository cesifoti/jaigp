"""Service for managing user emails (multi-email support)."""
from sqlalchemy.orm import Session
from datetime import datetime
from models.user_email import UserEmail
from models.user import User


def add_email_if_new(
    user_id: int,
    email: str,
    source: str,
    db: Session,
    verified: bool = False,
    make_primary_if_first: bool = True,
) -> UserEmail | None:
    """Add an email to a user if not already known globally.

    Returns the UserEmail row (new or existing) or None if the email
    belongs to a different user.
    """
    email = email.strip().lower()
    if not email:
        return None

    # Check if this email already exists in the table
    existing = db.query(UserEmail).filter(UserEmail.email == email).first()
    if existing:
        if existing.user_id == user_id:
            # Already known for this user — update verified if needed
            if verified and not existing.verified_at:
                existing.verified_at = datetime.utcnow()
                db.flush()
            return existing
        # Email belongs to a different user — don't steal it
        return None

    # Count existing emails for this user
    has_any = db.query(UserEmail).filter(UserEmail.user_id == user_id).first() is not None

    is_primary = make_primary_if_first and not has_any

    new_email = UserEmail(
        user_id=user_id,
        email=email,
        is_primary=is_primary,
        source=source,
        verified_at=datetime.utcnow() if verified else None,
    )
    db.add(new_email)
    db.flush()

    # Sync users.email cache if this is the primary
    if is_primary:
        _sync_primary_cache(user_id, email, db)

    return new_email


def set_primary_email(user_id: int, email_id: int, db: Session) -> bool:
    """Set a different email as primary. Returns True on success."""
    target = db.query(UserEmail).filter(
        UserEmail.id == email_id,
        UserEmail.user_id == user_id,
    ).first()
    if not target:
        return False

    # Clear current primary
    db.query(UserEmail).filter(
        UserEmail.user_id == user_id,
        UserEmail.is_primary == True,
    ).update({"is_primary": False})

    target.is_primary = True
    _sync_primary_cache(user_id, target.email, db)
    db.flush()
    return True


def remove_email(user_id: int, email_id: int, db: Session) -> bool:
    """Remove a non-primary email. Returns True on success."""
    target = db.query(UserEmail).filter(
        UserEmail.id == email_id,
        UserEmail.user_id == user_id,
    ).first()
    if not target or target.is_primary:
        return False

    db.delete(target)
    db.flush()
    return True


def _sync_primary_cache(user_id: int, email: str, db: Session):
    """Keep users.email in sync with the primary UserEmail."""
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.email = email
