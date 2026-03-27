"""Submission screening model for AI-based quality control."""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base


class SubmissionScreening(Base):
    """Record of each AI screening outcome for submitted papers.

    Persists even after paper deletion, giving an audit trail for
    cooldown enforcement and abuse detection.
    """
    __tablename__ = "submission_screenings"

    id = Column(Integer, primary_key=True, index=True)
    # NULL after paper deletion (rejected papers are deleted)
    paper_id = Column(Integer, nullable=True)
    # Submitting user (1st author)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Stored in case the paper is later deleted
    title = Column(String(500), nullable=False)
    submitted_at = Column(DateTime, nullable=True)
    screened_at = Column(DateTime, nullable=True)

    # Outcome
    outcome = Column(String(20), nullable=False)  # 'pass', 'borderline', 'reject'
    confidence = Column(String(20), nullable=True)  # 'high', 'medium', 'low'
    # AI-identified concern (quoted verbatim in hard-rejection emails)
    concern = Column(Text, nullable=True)

    # Consecutive-borderline tracking (snapshot at time of this screening)
    consecutive_borderlines = Column(Integer, default=0)
    triggered_strike = Column(Boolean, default=False)

    # Non-null when this record imposed a submission cooldown
    cooldown_until = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", backref="screenings")

    def __repr__(self):
        return f"<SubmissionScreening paper={self.paper_id} outcome={self.outcome}>"
