"""Community prompt and prompt vote models."""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base


class CommunityPrompt(Base):
    """A prompt suggested by a community member."""
    __tablename__ = "community_prompts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(300), nullable=True)
    prompt_text = Column(Text, nullable=False)
    post_type = Column(String(20), default="comment", nullable=False, index=True)  # prompt, rule, comment
    context = Column(Text)  # optional explanation
    created_at = Column(DateTime, default=datetime.utcnow)
    edited_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="community_prompts")
    votes = relationship("PromptVote", back_populates="prompt", cascade="all, delete-orphan")
    comments = relationship("PromptComment", back_populates="prompt", cascade="all, delete-orphan",
                            order_by="PromptComment.created_at")
    discussion_posts = relationship("DiscussionPost", back_populates="prompt")

    @property
    def upvote_count(self):
        return sum(1 for v in self.votes if v.vote_type == "upvote")

    @property
    def downvote_count(self):
        return sum(1 for v in self.votes if v.vote_type == "downvote")

    @property
    def net_votes(self):
        return self.upvote_count - self.downvote_count

    @property
    def total_votes(self):
        return len(self.votes)

    @property
    def divisiveness(self):
        """Measure of how split the vote is. 1.0 = perfectly split, 0.0 = unanimous."""
        total = self.total_votes
        if total == 0:
            return 0.0
        minority = min(self.upvote_count, self.downvote_count)
        return (2.0 * minority) / total


    @property
    def comment_count(self):
        return len(self.comments)


class PromptComment(Base):
    """A comment on a community prompt."""
    __tablename__ = "prompt_comments"

    id = Column(Integer, primary_key=True, index=True)
    prompt_id = Column(Integer, ForeignKey("community_prompts.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    edited_at = Column(DateTime, nullable=True)

    prompt = relationship("CommunityPrompt", back_populates="comments")
    user = relationship("User")
    votes = relationship("PromptCommentVote", back_populates="comment", cascade="all, delete-orphan")

    @property
    def upvote_count(self):
        return sum(1 for v in self.votes if v.vote_type == "upvote")

    @property
    def downvote_count(self):
        return sum(1 for v in self.votes if v.vote_type == "downvote")

    @property
    def net_votes(self):
        return self.upvote_count - self.downvote_count


class PromptCommentVote(Base):
    """Vote on a prompt comment."""
    __tablename__ = "prompt_comment_votes"

    id = Column(Integer, primary_key=True, index=True)
    comment_id = Column(Integer, ForeignKey("prompt_comments.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    vote_type = Column(String(10), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    comment = relationship("PromptComment", back_populates="votes")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint('comment_id', 'user_id', name='uq_prompt_comment_user_vote'),
    )


class PromptVote(Base):
    """Vote on a community prompt."""
    __tablename__ = "prompt_votes"

    id = Column(Integer, primary_key=True, index=True)
    prompt_id = Column(Integer, ForeignKey("community_prompts.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    vote_type = Column(String(10), nullable=False)  # 'upvote' or 'downvote'
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    prompt = relationship("CommunityPrompt", back_populates="votes")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint('prompt_id', 'user_id', name='uq_prompt_user_vote'),
    )
