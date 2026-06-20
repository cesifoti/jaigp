"""Service for managing user emails (multi-email support)."""
from sqlalchemy.orm import Session
from datetime import datetime
from itsdangerous import URLSafeTimedSerializer, BadData

import config
from models.user_email import UserEmail
from models.user import User

# Signed, self-contained tokens for confirming ownership of a self-added email.
# No DB column needed — the token carries the (signed) email_id and expires.
_EMAIL_VERIFY_SALT = "email-ownership-verify-v1"
_EMAIL_VERIFY_MAX_AGE = 14 * 24 * 3600  # 14 days


def make_email_verify_token(email_id: int) -> str:
    s = URLSafeTimedSerializer(config.SECRET_KEY, salt=_EMAIL_VERIFY_SALT)
    return s.dumps(email_id)


def verify_email_token(token: str, db: Session) -> "UserEmail | None":
    """Validate a verification token and mark the email verified.

    Returns the UserEmail row on success, or None if the token is invalid,
    expired, or the email no longer exists.
    """
    s = URLSafeTimedSerializer(config.SECRET_KEY, salt=_EMAIL_VERIFY_SALT)
    try:
        email_id = s.loads(token, max_age=_EMAIL_VERIFY_MAX_AGE)
    except BadData:
        return None
    ue = db.query(UserEmail).filter(UserEmail.id == email_id).first()
    if not ue:
        return None
    if not ue.verified_at:
        ue.verified_at = datetime.utcnow()
        db.flush()
    return ue


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
    """Set a different email as primary. Returns True on success.

    An email must be verified (ownership confirmed) before it can become the
    primary contact address — otherwise notifications could be redirected to
    an address the user doesn't control.
    """
    target = db.query(UserEmail).filter(
        UserEmail.id == email_id,
        UserEmail.user_id == user_id,
    ).first()
    if not target:
        return False
    if not target.verified_at:
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
