"""Database setup and session management."""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
import config

# Create database engine with connection pooling for PostgreSQL
if "postgresql" in config.DATABASE_URL:
    engine = create_engine(
        config.DATABASE_URL,
        poolclass=QueuePool,
        pool_size=20,              # Keep 20 connections ready
        max_overflow=40,           # Allow 40 more if needed (total: 60)
        pool_pre_ping=True,        # Check connections are alive
        pool_recycle=3600,         # Recycle connections after 1 hour
        echo=config.DEBUG
    )
else:
    # SQLite configuration (for development)
    engine = create_engine(
        config.DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=config.DEBUG
    )

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create base class for models
Base = declarative_base()

def get_db():
    """Dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initialize database tables."""
    # Import all models to ensure they're registered
    from models.user import User
    from models.paper import Paper, PaperVersion, PaperHumanAuthor, PaperAIAuthor, PaperField, PaperCategory
    from models.comment import Comment, CommentVote
    from models.paper_vote import PaperVote
    from models.endorsement import Endorsement
    from models.review import AIReview, HumanReview
    from models.editorial import EditorialBoardMember, EditorialDecision
    from models.stage_history import StageHistory
    from models.extension import ExtensionRequest
    from models.user_email import UserEmail
    from models.notification import Notification
    from models.message import DirectMessage

    # Create all tables
    Base.metadata.create_all(bind=engine)

    # Data migration: set review_stage for existing published papers
    _migrate_existing_papers()


def _migrate_existing_papers():
    """Set review_stage=1 for existing published papers that don't have it set."""
    from datetime import datetime, timedelta
    db = SessionLocal()
    try:
        from models.paper import Paper
        papers = db.query(Paper).filter(
            Paper.status == "published",
            Paper.stage_entered_at.is_(None)
        ).all()
        for paper in papers:
            paper.review_stage = 1
            paper.stage_entered_at = paper.verified_at or paper.published_date or paper.created_at
            paper.stage_deadline_at = paper.stage_entered_at + timedelta(days=180)
        if papers:
            db.commit()
            print(f"  Migrated {len(papers)} existing papers to review_stage=1")
    except Exception as e:
        db.rollback()
        print(f"  Migration note: {e}")
    finally:
        db.close()
