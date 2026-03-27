"""Stage history model for tracking paper review stage transitions."""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base


class StageHistory(Base):
    """Record of paper stage transitions."""
    __tablename__ = "stage_history"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False, index=True)
    from_stage = Column(Integer, nullable=True)  # null for initial submission
    to_stage = Column(Integer, nullable=False)
    triggered_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    trigger_type = Column(String(50), nullable=False)  # submission, endorsement, ai_review_complete, human_review_complete, editorial_accept
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    paper = relationship("Paper", back_populates="stage_history")
    triggered_by = relationship("User", backref="stage_transitions")

    def __repr__(self):
        return f"<StageHistory paper={self.paper_id} {self.from_stage}->{self.to_stage}>"
