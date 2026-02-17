"""Paper models for submissions and versions."""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint, Index, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base

class Paper(Base):
    """Core paper metadata."""
    __tablename__ = "papers"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    abstract = Column(Text, nullable=False)
    current_version = Column(Integer, default=1)
    submission_date = Column(DateTime, default=datetime.utcnow)
    published_date = Column(DateTime, default=datetime.utcnow, index=True)
    status = Column(String(20), default="pending_verification")  # pending_verification, submitted, under-review, published, archived
    image_filename = Column(String(255), nullable=True)

    # Email verification
    submitter_email = Column(String(255), nullable=True)  # Email for verification
    verification_token = Column(String(255), nullable=True, index=True)  # Token for email verification
    verified_at = Column(DateTime, nullable=True)  # When email was verified

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    versions = relationship("PaperVersion", back_populates="paper", cascade="all, delete-orphan")
    human_authors = relationship("PaperHumanAuthor", back_populates="paper", cascade="all, delete-orphan")
    ai_authors = relationship("PaperAIAuthor", back_populates="paper", cascade="all, delete-orphan")
    fields = relationship("PaperField", back_populates="paper", cascade="all, delete-orphan")
    categories = relationship("PaperCategory", back_populates="paper", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="paper", cascade="all, delete-orphan")
    votes = relationship("PaperVote", back_populates="paper", cascade="all, delete-orphan")

    @property
    def upvote_count(self):
        """Count of upvotes."""
        return sum(1 for vote in self.votes if vote.vote_type == 'upvote')

    @property
    def downvote_count(self):
        """Count of downvotes."""
        return sum(1 for vote in self.votes if vote.vote_type == 'downvote')

    @property
    def net_votes(self):
        """Net votes (upvotes - downvotes)."""
        return self.upvote_count - self.downvote_count

    @property
    def total_votes(self):
        """Total number of votes (upvotes + downvotes)."""
        return len(self.votes)

    @property
    def controversy_score(self):
        """Controversy score: higher when paper has many votes but low net score."""
        # Papers with many upvotes AND downvotes are controversial
        if self.total_votes < 2:
            return 0
        # Score is higher when both upvotes and downvotes are present
        return min(self.upvote_count, self.downvote_count) * 2 + self.total_votes

    def __repr__(self):
        return f"<Paper {self.id}: {self.title[:50]}>"


class PaperVersion(Base):
    """Paper version history."""
    __tablename__ = "paper_versions"
    __table_args__ = (
        UniqueConstraint('paper_id', 'version_number', name='uq_paper_version'),
        Index('idx_paper_versions_paper_id', 'paper_id'),
    )

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    pdf_filename = Column(String(255), nullable=False)
    change_log = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    paper = relationship("Paper", back_populates="versions")

    def __repr__(self):
        return f"<PaperVersion {self.paper_id} v{self.version_number}>"


class PaperHumanAuthor(Base):
    """Human prompters/authors."""
    __tablename__ = "paper_human_authors"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    author_order = Column(Integer, nullable=False)
    contribution = Column(String(500), nullable=True)

    # Relationships
    paper = relationship("Paper", back_populates="human_authors")
    user = relationship("User", back_populates="papers")

    def __repr__(self):
        return f"<PaperHumanAuthor paper={self.paper_id} user={self.user_id}>"


class PaperAIAuthor(Base):
    """AI co-authors."""
    __tablename__ = "paper_ai_authors"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False, index=True)
    ai_name = Column(String(100), nullable=False)  # e.g., "Claude", "GPT-4"
    ai_version = Column(String(100), nullable=True)  # e.g., "3.5 Sonnet", "4-turbo"
    ai_role = Column(String(200), nullable=True)  # e.g., "Writing", "Data Analysis"
    author_order = Column(Integer, nullable=False)
    additional_info = Column(JSON, nullable=True)  # For extra metadata

    # Relationships
    paper = relationship("Paper", back_populates="ai_authors")

    def __repr__(self):
        return f"<PaperAIAuthor {self.ai_name} v{self.ai_version}>"


class PaperField(Base):
    """OpenAlex field classification."""
    __tablename__ = "paper_fields"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False, index=True)
    field_type = Column(String(20), nullable=False)  # domain, field, subfield, topic
    field_id = Column(String(50), nullable=True)  # OpenAlex ID
    field_name = Column(String(200), nullable=False)
    display_name = Column(String(200), nullable=False)

    # Relationships
    paper = relationship("Paper", back_populates="fields")

    def __repr__(self):
        return f"<PaperField {self.field_type}: {self.display_name}>"


class PaperCategory(Base):
    """Hierarchical academic discipline categorization."""
    __tablename__ = "paper_categories"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False, index=True)

    # Full hierarchical path (e.g., "Humanities > History > European History > Scandinavian History")
    category_path = Column(String(500), nullable=False)

    # Only the deepest/most specific category (e.g., "Scandinavian History")
    leaf_category = Column(String(200), nullable=False, index=True)

    # Level in hierarchy (1=top, 2=second, etc.)
    level = Column(Integer, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    paper = relationship("Paper", back_populates="categories")

    def __repr__(self):
        return f"<PaperCategory {self.leaf_category}>"
