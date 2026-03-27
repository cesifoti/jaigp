"""Review models for AI and human peer reviews."""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base


class AIReview(Base):
    """AI review from reviewer3.com."""
    __tablename__ = "ai_reviews"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False, index=True)
    reviewer3_tracking_id = Column(String(100), nullable=True, unique=True, index=True)
    review_content = Column(Text, nullable=True)
    review_data = Column(JSON, nullable=True)
    raw_api_response = Column(JSON, nullable=True)  # Full unmodified Reviewer3 API response
    status = Column(String(20), default="pending")  # pending, submitted, in_progress, completed, failed
    submitted_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    comments_addressed = Column(Boolean, default=False)
    comments_addressed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Re-review fields
    review_round = Column(Integer, default=1, nullable=False)
    parent_review_id = Column(Integer, ForeignKey("ai_reviews.id"), nullable=True)
    author_responses = Column(JSON, nullable=True)  # {reviewerId: responseText}
    paper_version = Column(Integer, nullable=True)  # which paper version was reviewed
    approved = Column(Boolean, default=False)  # True when re-review returns 0 comments or all scores >= 3
    review_cycle = Column(Integer, default=1, nullable=False)  # matches paper.review_cycle at creation

    # Revision scoring fields (populated for round 2+ via /revise endpoint)
    revision_scores = Column(JSON, nullable=True)   # [{originalComment, authorResponse, reviewerResponse, score}]
    desk_rejected = Column(Boolean, default=False, nullable=False)
    author_response_path = Column(String(500), nullable=True)  # filename of uploaded author response PDF

    # Relationships
    paper = relationship("Paper", back_populates="ai_reviews")
    parent_review = relationship("AIReview", remote_side="AIReview.id", backref="child_reviews")

    def __repr__(self):
        return f"<AIReview paper={self.paper_id} round={self.review_round} status={self.status}>"


class HumanReview(Base):
    """Human peer review."""
    __tablename__ = "human_reviews"
    __table_args__ = (
        Index('idx_human_reviews_paper_id', 'paper_id'),
        Index('idx_human_reviews_invitation_token', 'invitation_token'),
    )

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)
    reviewer_type = Column(String(30), nullable=False)  # author_suggested, reference_cited
    reviewer_name = Column(String(255), nullable=True)
    reviewer_email = Column(String(255), nullable=True)
    reviewer_affiliation = Column(String(500), nullable=True)
    reviewer_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    invitation_token = Column(String(255), nullable=True, unique=True)
    invited_at = Column(DateTime, nullable=True)
    invitation_accepted_at = Column(DateTime, nullable=True)
    invitation_declined_at = Column(DateTime, nullable=True)
    review_content = Column(Text, nullable=True)
    recommendation = Column(String(30), nullable=True)  # accept, minor_revisions, major_revisions, reject
    review_submitted_at = Column(DateTime, nullable=True)
    assigned_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    assigned_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    paper = relationship("Paper", back_populates="human_reviews")
    reviewer = relationship("User", foreign_keys=[reviewer_user_id], backref="reviews_given")
    assigned_by = relationship("User", foreign_keys=[assigned_by_user_id])

    def __repr__(self):
        return f"<HumanReview paper={self.paper_id} type={self.reviewer_type}>"
