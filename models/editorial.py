"""Editorial board and decision models."""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base


class EditorialBoardMember(Base):
    """Editorial board member."""
    __tablename__ = "editorial_board_members"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    role = Column(String(30), nullable=False, default="editor")  # editor-in-chief, editor, associate_editor
    specialty = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True)
    appointed_at = Column(DateTime, default=datetime.utcnow)
    removed_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="editorial_board_membership")

    def __repr__(self):
        return f"<EditorialBoardMember user={self.user_id} role={self.role}>"


class EditorialDecision(Base):
    """Editorial decision on a paper."""
    __tablename__ = "editorial_decisions"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False, index=True)
    editor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    decision = Column(String(30), nullable=False)  # accept, reject, revisions_needed
    reasoning = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    paper = relationship("Paper", back_populates="editorial_decisions")
    editor = relationship("User", backref="editorial_decisions_made")

    def __repr__(self):
        return f"<EditorialDecision paper={self.paper_id} decision={self.decision}>"
