"""Governance models for community-driven rule voting."""
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, JSON, String, Text,
    ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship

from models.database import Base


class GovernanceRule(Base):
    """A journal rule that may be voted on by the community."""
    __tablename__ = "governance_rules"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(80), unique=True, nullable=False, index=True)
    section = Column(String(40), nullable=False)  # submission, screening, endorsement, ai_review, deadlines, governance
    title = Column(String(200), nullable=False)
    description = Column(Text)
    options_json = Column(JSON)  # list of allowed option strings, e.g. ["optional", "required"]
    default_value = Column(String(80), nullable=False)
    active_value = Column(String(80), nullable=False)
    is_votable = Column(Boolean, default=True, nullable=False)
    display_group = Column(String(40), nullable=True)  # for matrix grouping
    display_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    votes = relationship("GovernanceVote", back_populates="rule", cascade="all, delete-orphan")
    tallies = relationship("GovernanceTally", back_populates="rule", cascade="all, delete-orphan")

    @property
    def options(self):
        """Return options as a Python list."""
        return self.options_json or []

    @property
    def option_labels(self):
        """Map of option value -> human-readable label.

        Bare-integer options mean different things per rule (10 days vs 10
        voters), so the unit is chosen by slug rather than by value alone.
        """
        # Fixed tokens whose label never depends on the rule
        token_labels = {
            # durations
            "24h": "24 hours", "48h": "48 hours", "72h": "72 hours",
            "1wk": "1 week", "30d": "30 days", "90d": "90 days",
            "180d": "180 days", "1yr": "1 year", "5yr": "5 years",
            # badges
            "any": "Any badge", "copper": "Copper+", "bronze": "Bronze+",
            "silver": "Silver+", "gold": "Gold only",
            # cover image
            "optional": "Optional", "required": "Required",
            # voting frequency
            "weekly": "Weekly", "monthly": "Monthly",
            "biannual": "Twice a year", "annual": "Once a year",
        }
        # Unit applied to bare-integer options, keyed by rule slug
        if self.slug in ("stage_deadline_days", "extension_days"):
            unit = "days"
        elif self.slug == "voting_quorum":
            unit = "voters"
        else:
            unit = None  # counts (endorsements, streaks, revisions, limits) stay bare

        def label_for(opt):
            if opt in token_labels:
                return token_labels[opt]
            if unit and opt.lstrip("-").isdigit():
                return f"{opt} {unit}"
            return opt

        return {opt: label_for(opt) for opt in self.options}


class GovernanceVote(Base):
    """A user's current vote on a governance rule. One vote per user per rule."""
    __tablename__ = "governance_votes"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("governance_rules.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    chosen_option = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    rule = relationship("GovernanceRule", back_populates="votes")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("rule_id", "user_id", name="uq_governance_rule_user_vote"),
        Index("idx_governance_votes_rule", "rule_id"),
    )


class GovernanceVoteHistory(Base):
    """Immutable audit log of every vote action. Never updated or deleted."""
    __tablename__ = "governance_vote_history"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("governance_rules.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rule_slug = Column(String(80), nullable=False)      # denormalized — survives rule deletion
    user_orcid = Column(String(40), nullable=True)       # denormalized — survives user deletion
    previous_option = Column(String(80), nullable=True)  # null on first vote
    new_option = Column(String(80), nullable=False)
    action = Column(String(20), nullable=False)          # 'cast' or 'changed'
    voting_period = Column(String(20), nullable=False)   # period label at time of vote
    ip_address = Column(String(45), nullable=True)       # for audit (IPv4 or IPv6)
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_vote_history_user", "user_id"),
        Index("idx_vote_history_rule", "rule_id"),
        Index("idx_vote_history_period", "voting_period"),
        Index("idx_vote_history_created", "created_at"),
    )


class GovernanceTally(Base):
    """Historical record of a voting period tally."""
    __tablename__ = "governance_tallies"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("governance_rules.id", ondelete="CASCADE"), nullable=False)
    period_label = Column(String(20), nullable=False)  # e.g. "2026-04"
    total_voters = Column(Integer, nullable=False)
    quorum_required = Column(Integer, nullable=False)
    quorum_met = Column(Boolean, nullable=False)
    results_json = Column(JSON)  # e.g. {"optional": 14, "required": 8}
    winning_option = Column(String(80), nullable=True)  # null if quorum not met
    previous_value = Column(String(80))
    new_value = Column(String(80))
    tallied_at = Column(DateTime, default=datetime.utcnow)

    rule = relationship("GovernanceRule", back_populates="tallies")

    __table_args__ = (
        Index("idx_governance_tallies_rule_period", "rule_id", "period_label"),
    )
