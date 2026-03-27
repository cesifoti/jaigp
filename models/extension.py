"""Extension request model for stage deadline extensions."""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base


class ExtensionRequest(Base):
    """Request for deadline extension on a paper's current stage."""
    __tablename__ = "extension_requests"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False, index=True)
    requested_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    stage = Column(Integer, nullable=False)
    reason = Column(Text, nullable=True)
    extension_days = Column(Integer, default=20)
    status = Column(String(20), default="pending")  # pending, approved, denied
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    paper = relationship("Paper", back_populates="extension_requests")
    requested_by = relationship("User", foreign_keys=[requested_by_user_id], backref="extension_requests_made")
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_user_id])

    def __repr__(self):
        return f"<ExtensionRequest paper={self.paper_id} stage={self.stage} status={self.status}>"
