"""Comment and voting models."""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base

class Comment(Base):
    """Paper comments."""
    __tablename__ = "comments"
    __table_args__ = (
        Index('idx_comments_paper_id', 'paper_id'),
    )

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    paper = relationship("Paper", back_populates="comments")
    user = relationship("User", back_populates="comments")
    votes = relationship("CommentVote", back_populates="comment", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Comment {self.id} on Paper {self.paper_id}>"

    @property
    def vote_count(self):
        """Calculate net vote count (upvotes - downvotes)."""
        upvotes = sum(1 for v in self.votes if v.vote_type == "upvote")
        downvotes = sum(1 for v in self.votes if v.vote_type == "downvote")
        return upvotes - downvotes


class CommentVote(Base):
    """Comment voting system."""
    __tablename__ = "comment_votes"
    __table_args__ = (
        UniqueConstraint('comment_id', 'user_id', name='uq_comment_user_vote'),
        Index('idx_comment_votes_comment_id', 'comment_id'),
    )

    id = Column(Integer, primary_key=True, index=True)
    comment_id = Column(Integer, ForeignKey("comments.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    vote_type = Column(String(10), nullable=False)  # upvote, downvote
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    comment = relationship("Comment", back_populates="votes")
    user = relationship("User", back_populates="comment_votes")

    def __repr__(self):
        return f"<CommentVote {self.vote_type} on Comment {self.comment_id}>"
