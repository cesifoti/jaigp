"""Direct message model for user-to-user messaging."""
from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base


class DirectMessage(Base):
    """A private message between two users."""
    __tablename__ = "direct_messages"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    recipient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    sender = relationship("User", foreign_keys=[sender_id])
    recipient = relationship("User", foreign_keys=[recipient_id])

    __table_args__ = (
        Index('ix_dm_recipient_unread', 'recipient_id', 'read_at'),
        Index('ix_dm_conversation', 'sender_id', 'recipient_id', 'created_at'),
    )

    def __repr__(self):
        return f"<DirectMessage {self.sender_id}->{self.recipient_id}>"
