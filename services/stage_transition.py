"""Stage transition service for the 5-stage peer review pipeline."""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models.paper import Paper, STAGE_NAMES
from models.endorsement import Endorsement
from models.review import AIReview, HumanReview
from models.editorial import EditorialDecision
from models.stage_history import StageHistory
from models.extension import ExtensionRequest


STAGE_DEADLINE_DAYS = 180
EXTENSION_DAYS = 20


class StageTransitionService:
    """Orchestrates paper transitions through the 5-stage review pipeline."""

    def endorsements_required(self, paper_id: int, db: Session) -> int:
        """Return the number of bronze+ endorsements required for this paper to advance.

        Papers where any registered author has badge='new' (0 ORCID works) require 2;
        all other papers require 1.
        """
        from models.user import User
        from models.paper import PaperHumanAuthor
        new_badge_author = db.query(PaperHumanAuthor).join(
            User, User.id == PaperHumanAuthor.user_id
        ).filter(
            PaperHumanAuthor.paper_id == paper_id,
            User.badge == "new",
        ).first()
        return 2 if new_badge_author else 1

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

        # Count only bronze+ endorsers
        from models.user import User
        endorsement_count = db.query(Endorsement).join(
            User, User.id == Endorsement.user_id
        ).filter(
            Endorsement.paper_id == paper_id,
            User.badge.in_(["bronze", "silver", "gold"]),
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
        return True

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
        paper.stage_deadline_at = now + timedelta(days=STAGE_DEADLINE_DAYS)

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
            extension_days=EXTENSION_DAYS,
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
