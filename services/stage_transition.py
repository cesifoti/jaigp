"""Stage transition service for the 5-stage peer review pipeline."""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models.paper import Paper, STAGE_NAMES
from models.endorsement import Endorsement
from models.review import AIReview, HumanReview
from models.editorial import EditorialDecision
from models.stage_history import StageHistory
from models.extension import ExtensionRequest
from services.governance import (
    get_rule_value,
    get_rule_value_int,
    badges_at_or_above,
    lowest_author_badge,
)


class StageTransitionService:
    """Orchestrates paper transitions through the 5-stage review pipeline."""

    def endorsements_required(self, paper_id: int, db: Session) -> int:
        """Return the number of endorsements required for this paper to advance.

        Looks up the governance rule based on the lowest badge among the paper's authors.
        """
        lowest_badge = lowest_author_badge(paper_id, db)
        return get_rule_value_int(f"endorsements_required_{lowest_badge}", db)

    def endorsement_requirements(self, paper_id: int, db: Session) -> dict:
        """Return the governed endorsement gate for a paper, for display/UI.

        All values are derived from the governance rules for this paper's
        lowest-badge author, so templates never hardcode counts or badges:
          - endorsements_required: how many qualifying endorsements are needed
          - allowed_badges: the set of endorser badges that count
          - min_endorser_badge: the minimum endorser badge (e.g. "bronze")
        """
        lowest_badge = lowest_author_badge(paper_id, db)
        min_badge = get_rule_value(f"endorser_min_badge_{lowest_badge}", db)
        return {
            "endorsements_required": get_rule_value_int(
                f"endorsements_required_{lowest_badge}", db
            ),
            "allowed_badges": badges_at_or_above(min_badge),
            "min_endorser_badge": min_badge,
        }

    def advance_to_screened(self, paper_id: int, screener_user_id: int, db: Session) -> bool:
        """Advance paper from Stage 0 (Submitted) to Stage 1 (AI Screened).

        Called automatically by the screening service when a paper passes
        the AI quality check. Also publishes the paper.
        """
        paper = db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper or paper.review_stage != 0:
            return False

        paper.status = "published"
        self._record_transition(
            paper=paper,
            from_stage=0,
            to_stage=1,
            triggered_by_user_id=screener_user_id,
            trigger_type="ai_screening_pass",
            db=db,
        )
        return True

    def advance_to_endorsed(self, paper_id: int, endorser_user_id: int, db: Session) -> bool:
        """Advance paper from Stage 1 (Submitted) to Stage 2 (Endorsed).

        Requires:
          - 1 bronze+ endorsement for authors with copper/bronze/silver/gold badge
          - 2 bronze+ endorsements if any author has 'new' badge (0 ORCID works)
        """
        paper = db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper or paper.review_stage != 1:
            return False

        # Determine which endorser badges qualify based on author's lowest badge
        from models.user import User
        lowest_badge = lowest_author_badge(paper_id, db)
        min_endorser = get_rule_value(f"endorser_min_badge_{lowest_badge}", db)
        allowed_badges = badges_at_or_above(min_endorser)
        endorsement_count = db.query(Endorsement).join(
            User, User.id == Endorsement.user_id
        ).filter(
            Endorsement.paper_id == paper_id,
            User.badge.in_(allowed_badges),
        ).count()

        required = self.endorsements_required(paper_id, db)
        if endorsement_count < required:
            return False

        self._record_transition(
            paper=paper,
            from_stage=1,
            to_stage=2,
            triggered_by_user_id=endorser_user_id,
            trigger_type="endorsement",
            db=db,
        )

        # Authors we can't reach by email get an in-app "ready for AI review"
        # nudge so they don't silently stall at this stage. Best-effort.
        try:
            from services.notification import notify_unreachable_authors_ready
            if notify_unreachable_authors_ready(paper_id, db):
                db.commit()
        except Exception as e:
            print(f"Error creating ai_review_ready notifications for paper {paper_id}: {e}")

        return True

    def _qualifying_endorser_id(self, paper_id: int, db: Session):
        """Return a user_id of an endorser who currently qualifies, else None.

        Used to attribute a re-evaluated transition to a real endorser.
        """
        from models.user import User
        lowest_badge = lowest_author_badge(paper_id, db)
        min_endorser = get_rule_value(f"endorser_min_badge_{lowest_badge}", db)
        allowed_badges = badges_at_or_above(min_endorser)
        endorsement = db.query(Endorsement).join(
            User, User.id == Endorsement.user_id
        ).filter(
            Endorsement.paper_id == paper_id,
            User.badge.in_(allowed_badges),
        ).order_by(Endorsement.created_at).first()
        return endorsement.user_id if endorsement else None

    def reevaluate_stage1_endorsements(self, db: Session, paper_ids=None) -> list:
        """Re-check Stage 1 papers against the *current* endorsement rules and
        advance any that now qualify. Returns the list of advanced paper ids.

        Advancement is normally evaluated only at the instant an endorsement is
        submitted, so a paper can be left stuck if it later becomes eligible —
        e.g. an endorser's badge is upgraded, or a governance rule changes the
        required count. This sweep closes that gap and is safe to call
        repeatedly: advance_to_endorsed re-validates every condition itself.

        Pass paper_ids to restrict the sweep (e.g. just the papers a freshly
        upgraded user has endorsed); omit it to sweep all Stage 1 papers.
        """
        query = db.query(Paper).filter(
            Paper.review_stage == 1, Paper.status == "published"
        )
        if paper_ids is not None:
            ids = list(paper_ids)
            if not ids:
                return []
            query = query.filter(Paper.id.in_(ids))
        advanced = []
        for paper in query.all():
            endorser_id = self._qualifying_endorser_id(paper.id, db)
            if endorser_id and self.advance_to_endorsed(paper.id, endorser_id, db):
                advanced.append(paper.id)
        return advanced

    def advance_to_ai_review(self, paper_id: int, user_id: int, db: Session) -> bool:
        """Advance paper from Stage 2 (Endorsed) to Stage 3 (AI Review).

        Triggered when author submits to reviewer3.com.
        """
        paper = db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper or paper.review_stage != 2:
            return False

        self._record_transition(
            paper=paper,
            from_stage=2,
            to_stage=3,
            triggered_by_user_id=user_id,
            trigger_type="ai_review_submitted",
            db=db,
        )
        return True

    def advance_to_human_review(self, paper_id: int, user_id: int, db: Session) -> bool:
        """Advance paper from Stage 3 (AI Review) to Stage 4 (Human Peer Review).

        Requires: AI review completed and comments addressed.
        """
        paper = db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper or paper.review_stage != 3:
            return False

        # Verify AI review is done and approved (re-review returned 0 comments)
        ai_review = db.query(AIReview).filter(
            AIReview.paper_id == paper_id,
            AIReview.review_cycle == paper.review_cycle,
            AIReview.status == "completed",
            AIReview.approved == True,
        ).first()

        if not ai_review:
            return False

        self._record_transition(
            paper=paper,
            from_stage=3,
            to_stage=4,
            triggered_by_user_id=user_id,
            trigger_type="ai_review_complete",
            db=db,
        )
        return True

    def advance_to_accepted(self, paper_id: int, editor_user_id: int, db: Session) -> bool:
        """Advance paper from Stage 4 (Human Peer Review) to Stage 5 (Accepted).

        Requires: editorial board 'accept' decision.
        """
        paper = db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper or paper.review_stage != 4:
            return False

        # Check for accept decision
        accept_decision = db.query(EditorialDecision).filter(
            EditorialDecision.paper_id == paper_id,
            EditorialDecision.decision == "accept",
        ).first()

        if not accept_decision:
            return False

        self._record_transition(
            paper=paper,
            from_stage=4,
            to_stage=5,
            triggered_by_user_id=editor_user_id,
            trigger_type="editorial_accept",
            db=db,
        )
        return True

    def force_advance(self, paper_id: int, to_stage: int, admin_user_id: int, db: Session, notes: str = None) -> bool:
        """Admin force-advance a paper to any higher stage."""
        paper = db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper or to_stage <= paper.review_stage or to_stage > 5:
            return False

        self._record_transition(
            paper=paper,
            from_stage=paper.review_stage,
            to_stage=to_stage,
            triggered_by_user_id=admin_user_id,
            trigger_type="admin_override",
            notes=notes or f"Admin force-advanced to stage {to_stage}",
            db=db,
        )
        return True

    def desk_reject_to_stage1(
        self, paper_id: int, triggered_by_user_id: int, db: Session, reason: str = None
    ) -> bool:
        """Return paper to Stage 1 after desk rejection or exhausted revisions.

        Increments review_cycle so the paper starts a fresh endorsement+review cycle.
        The previous endorser is automatically blocked from re-endorsing (their
        endorsement record still exists and the duplicate check prevents reuse).
        """
        paper = db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper:
            return False

        paper.review_cycle += 1
        paper.reviewer3_tracking_id = None
        paper.reviewer3_submission_date = None
        paper.draft_responses = None

        self._record_transition(
            paper=paper,
            from_stage=paper.review_stage,
            to_stage=1,
            triggered_by_user_id=triggered_by_user_id,
            trigger_type="desk_rejection",
            notes=reason or "Paper returned to Stage 1 via desk rejection",
            db=db,
        )
        return True

    def rewind(self, paper_id: int, to_stage: int, admin_user_id: int, db: Session, notes: str = None) -> bool:
        """Admin rewind a paper to any lower stage."""
        paper = db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper or to_stage >= paper.review_stage or to_stage < 1:
            return False

        # When rewinding to stage 1, start a new review cycle
        if to_stage == 1:
            paper.review_cycle += 1
            paper.reviewer3_tracking_id = None
            paper.reviewer3_submission_date = None

        self._record_transition(
            paper=paper,
            from_stage=paper.review_stage,
            to_stage=to_stage,
            triggered_by_user_id=admin_user_id,
            trigger_type="admin_rewind",
            notes=notes or f"Admin rewound to stage {to_stage}",
            db=db,
        )
        return True

    def _record_transition(
        self,
        paper: Paper,
        from_stage: int,
        to_stage: int,
        triggered_by_user_id: int,
        trigger_type: str,
        db: Session,
        notes: str = None,
    ):
        """Record a stage transition and update paper fields."""
        now = datetime.utcnow()

        # Create history record
        history = StageHistory(
            paper_id=paper.id,
            from_stage=from_stage,
            to_stage=to_stage,
            triggered_by_user_id=triggered_by_user_id,
            trigger_type=trigger_type,
            notes=notes,
            created_at=now,
        )
        db.add(history)

        # Update paper
        paper.review_stage = to_stage
        paper.stage_entered_at = now
        paper.stage_deadline_at = now + timedelta(days=get_rule_value_int("stage_deadline_days", db))

        db.commit()

    def check_staleness(self, db: Session):
        """Find papers that have exceeded their stage deadline."""
        now = datetime.utcnow()
        stale_papers = db.query(Paper).filter(
            Paper.stage_deadline_at < now,
            Paper.review_stage < 5,  # Don't flag accepted papers
            Paper.status == "published",
        ).all()
        return stale_papers

    def get_papers_approaching_deadline(self, db: Session, days_threshold: int = 30):
        """Find papers approaching their deadline within N days."""
        now = datetime.utcnow()
        threshold = now + timedelta(days=days_threshold)
        return db.query(Paper).filter(
            Paper.stage_deadline_at.isnot(None),
            Paper.stage_deadline_at <= threshold,
            Paper.stage_deadline_at > now,
            Paper.review_stage < 5,
            Paper.status == "published",
        ).all()

    def request_extension(
        self,
        paper_id: int,
        user_id: int,
        reason: str,
        db: Session,
    ) -> ExtensionRequest:
        """Request a deadline extension for a paper's current stage."""
        paper = db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper:
            return None

        # Check for existing pending request at this stage
        existing = db.query(ExtensionRequest).filter(
            ExtensionRequest.paper_id == paper_id,
            ExtensionRequest.stage == paper.review_stage,
            ExtensionRequest.status == "pending",
        ).first()

        if existing:
            return None  # Already has a pending request

        extension = ExtensionRequest(
            paper_id=paper_id,
            requested_by_user_id=user_id,
            stage=paper.review_stage,
            reason=reason,
            extension_days=get_rule_value_int("extension_days", db),
        )
        db.add(extension)
        db.commit()
        db.refresh(extension)
        return extension

    def approve_extension(self, extension_id: int, reviewer_user_id: int, db: Session) -> bool:
        """Approve an extension request, adding days to the paper's deadline."""
        extension = db.query(ExtensionRequest).filter(
            ExtensionRequest.id == extension_id,
            ExtensionRequest.status == "pending",
        ).first()

        if not extension:
            return False

        paper = db.query(Paper).filter(Paper.id == extension.paper_id).first()
        if not paper:
            return False

        extension.status = "approved"
        extension.reviewed_by_user_id = reviewer_user_id
        extension.reviewed_at = datetime.utcnow()

        # Extend the deadline
        if paper.stage_deadline_at:
            paper.stage_deadline_at += timedelta(days=extension.extension_days)

        db.commit()
        return True

    def deny_extension(self, extension_id: int, reviewer_user_id: int, db: Session) -> bool:
        """Deny an extension request."""
        extension = db.query(ExtensionRequest).filter(
            ExtensionRequest.id == extension_id,
            ExtensionRequest.status == "pending",
        ).first()

        if not extension:
            return False

        extension.status = "denied"
        extension.reviewed_by_user_id = reviewer_user_id
        extension.reviewed_at = datetime.utcnow()
        db.commit()
        return True


# Singleton
stage_transition_service = StageTransitionService()
