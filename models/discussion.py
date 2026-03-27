"""Discussion post, comment, vote, and follow models."""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base


class DiscussionPost(Base):
    """A discussion post by a community member."""
    __tablename__ = "discussion_posts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    prompt_id = Column(Integer, ForeignKey("community_prompts.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="discussion_posts")
    prompt = relationship("CommunityPrompt", back_populates="discussion_posts")
    votes = relationship("DiscussionVote", back_populates="post", cascade="all, delete-orphan")
    comments = relationship("DiscussionComment", back_populates="post", cascade="all, delete-orphan",
                            order_by="DiscussionComment.created_at")

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
    def comment_count(self):
        return len(self.comments)


class DiscussionComment(Base):
    """A comment on a discussion post."""
    __tablename__ = "discussion_comments"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("discussion_posts.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    post = relationship("DiscussionPost", back_populates="comments")
    user = relationship("User")
    votes = relationship("DiscussionCommentVote", back_populates="comment", cascade="all, delete-orphan")

    @property
    def upvote_count(self):
        return sum(1 for v in self.votes if v.vote_type == "upvote")

    @property
    def downvote_count(self):
        return sum(1 for v in self.votes if v.vote_type == "downvote")

    @property
    def net_votes(self):
        return self.upvote_count - self.downvote_count


class DiscussionVote(Base):
    """Vote on a discussion post."""
    __tablename__ = "discussion_votes"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("discussion_posts.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    vote_type = Column(String(10), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    post = relationship("DiscussionPost", back_populates="votes")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint('post_id', 'user_id', name='uq_discussion_user_vote'),
    )


class DiscussionCommentVote(Base):
    """Vote on a discussion comment."""
    __tablename__ = "discussion_comment_votes"

    id = Column(Integer, primary_key=True, index=True)
    comment_id = Column(Integer, ForeignKey("discussion_comments.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    vote_type = Column(String(10), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    comment = relationship("DiscussionComment", back_populates="votes")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint('comment_id', 'user_id', name='uq_disc_comment_user_vote'),
    )


class UserFollow(Base):
    """A user follows another user. Feed filtering will be implemented later."""
    __tablename__ = "user_follows"

    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    followed_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    follower = relationship("User", foreign_keys=[follower_id], backref="following")
    followed = relationship("User", foreign_keys=[followed_id], backref="followers")

    __table_args__ = (
        UniqueConstraint('follower_id', 'followed_id', name='uq_user_follow'),
    )
