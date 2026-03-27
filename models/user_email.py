"""UserEmail model for multi-email support."""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base


class UserEmail(Base):
    """Stores all known email addresses for a user."""
    __tablename__ = "user_emails"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    is_primary = Column(Boolean, default=False, nullable=False)
    source = Column(String, nullable=False)  # 'orcid', 'submission', 'profile_edit', 'migration'
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Globally unique email per user (same email can't belong to two users)
    __table_args__ = (
        UniqueConstraint('email', name='uq_user_emails_email'),
    )

    # Relationships
    user = relationship("User", back_populates="emails")

    def __repr__(self):
        return f"<UserEmail {self.email} (user={self.user_id}, primary={self.is_primary})>"
