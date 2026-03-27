"""Endorsement model for paper endorsements."""
from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base


class Endorsement(Base):
    """Paper endorsement by bronze+ ORCID scholars."""
    __tablename__ = "endorsements"
    __table_args__ = (
        UniqueConstraint('paper_id', 'user_id', name='uq_endorsement_paper_user'),
    )

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    paper = relationship("Paper", back_populates="endorsements")
    user = relationship("User", back_populates="endorsements")

    def __repr__(self):
        return f"<Endorsement paper={self.paper_id} user={self.user_id}>"
