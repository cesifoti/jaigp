"""Paper vote model for thumbs up/down voting."""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base


class PaperVote(Base):
    """Paper vote model for upvote/downvote on papers."""
    __tablename__ = "paper_votes"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    vote_type = Column(String, nullable=False)  # 'upvote' or 'downvote'
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    paper = relationship("Paper", back_populates="votes")
    user = relationship("User", back_populates="paper_votes")

    # Unique constraint: one vote per user per paper
    __table_args__ = (
        UniqueConstraint('paper_id', 'user_id', name='_paper_user_vote_uc'),
    )

    def __repr__(self):
        return f"<PaperVote paper_id={self.paper_id} user_id={self.user_id} vote_type={self.vote_type}>"
