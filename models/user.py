"""User model for ORCID-authenticated users."""
from sqlalchemy import Column, Integer, String, DateTime, JSON, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base

class User(Base):
    """User model for ORCID-authenticated users."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    orcid_id = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    google_scholar_url = Column(String, nullable=True)
    rankless_url = Column(String, nullable=True)
    affiliation = Column(String, nullable=True)

    # Badge system based on ORCID publication count
    badge = Column(String, nullable=True)  # 'gold', 'silver', 'copper', 'noob'
    works_count = Column(Integer, default=0)
    badge_updated_at = Column(DateTime, nullable=True)

    # ORCID data cache
    orcid_works = Column(JSON, nullable=True)  # Latest 5 journal articles

    # Terms of Service acceptance
    terms_accepted_at = Column(DateTime, nullable=True)

    # Messaging preferences
    open_to_messaging = Column(Boolean, default=True, nullable=False)

    # Google Scholar citations (fetched client-side)
    scholar_citations = Column(Integer, nullable=True)
    scholar_h_index = Column(Integer, nullable=True)
    scholar_i10_index = Column(Integer, nullable=True)
    scholar_updated_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    papers = relationship("PaperHumanAuthor", back_populates="user")
    comments = relationship("Comment", back_populates="user")
    comment_votes = relationship("CommentVote", back_populates="user")
    paper_votes = relationship("PaperVote", back_populates="user")
    endorsements = relationship("Endorsement", back_populates="user")
    editorial_board_membership = relationship("EditorialBoardMember", back_populates="user", uselist=False)
    emails = relationship("UserEmail", back_populates="user", cascade="all, delete-orphan", order_by="UserEmail.is_primary.desc()")
    community_prompts = relationship("CommunityPrompt", back_populates="user", cascade="all, delete-orphan")
    discussion_posts = relationship("DiscussionPost", back_populates="user", cascade="all, delete-orphan")

    @property
    def primary_email(self):
        """Get the primary email from user_emails, falling back to cached email column."""
        for ue in self.emails:
            if ue.is_primary:
                return ue.email
        return self.email

    @property
    def can_endorse(self):
        """Whether user has sufficient badge level to endorse papers (bronze+)."""
        return self.badge in ('bronze', 'silver', 'gold')

    def __repr__(self):
        return f"<User {self.name} ({self.orcid_id})>"
