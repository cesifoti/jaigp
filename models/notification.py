"""In-app notification model."""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base


class Notification(Base):
    """Lightweight in-app notification for user interactions."""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    notification_type = Column(String(50), nullable=False)
    source_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    content_preview = Column(String(200), nullable=True)
    link = Column(String(500), nullable=False)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    source_user = relationship("User", foreign_keys=[source_user_id])

    __table_args__ = (
        Index('ix_notifications_user_unread', 'user_id', 'read_at'),
    )

    def __repr__(self):
        return f"<Notification {self.notification_type} for user={self.user_id}>"
