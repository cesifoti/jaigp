"""AI quality screening service using Claude Haiku.

Papers are screened asynchronously after email verification.
PASS  → advance to Stage 1 (AI Screened), publish.
BORDERLINE → delete paper, send soft-rejection email.
             3 consecutive borderlines → 48 h cooldown (treated as strike).
REJECT → delete paper, send hard-rejection email, apply 48 h cooldown.
Low-confidence REJECT is treated as BORDERLINE.
"""
import re
import asyncio
import traceback
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

import config
from models.submission_screening import SubmissionScreening
from models.paper import Paper, PaperHumanAuthor
from services.stage_transition import stage_transition_service


_SCREENING_PROMPT = """\
You are a quality-control screener for JAIGP (Journal for AI Generated Papers).
Your job is to identify submissions that lack basic academic substance — spam, \
placeholder text, or content with no scholarly value.

IMPORTANT — do NOT reject based on:
- The paper being AI-generated (this is expected and desired)
- Writing style, grammar, or prose quality
- Topic novelty or perceived importance
- Short length (a concise paper can still be substantial)

REJECT only if the submission:
- Contains no real academic content (gibberish, lorem ipsum, test text)
- Is clearly promotional material or spam
- Contains harmful, abusive, or unethical content
- Has no discernible research question, methodology, or findings

BORDERLINE if:
- The paper has some academic framing but the abstract is almost content-free
- Claims are stated with zero supporting reasoning or evidence
- The contribution is so vague it is impossible to assess

PASS if:
- A coherent research question or objective is present
- Some methodology, findings, or argument is described (even briefly)

Title: {title}

Abstract:
{abstract}

Respond in exactly this format (no extra text):
OUTCOME: [PASS|BORDERLINE|REJECT]
CONFIDENCE: [HIGH|MEDIUM|LOW]
CONCERN: [one sentence, or "None"]
"""


def _call_claude_sync(title: str, abstract: str) -> tuple[str, str, str]:
    """Call Claude Haiku synchronously and return (outcome, confidence, concern)."""
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    prompt = _SCREENING_PROMPT.format(title=title, abstract=abstract)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    return _parse_response(raw)


def _parse_response(text: str) -> tuple[str, str, str]:
    """Parse Claude's response into (outcome, confidence, concern)."""
    outcome = "pass"
    confidence = "low"
    concern = None

    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"OUTCOME:\s*(\w+)", line, re.IGNORECASE)
        if m:
            outcome = m.group(1).lower()
        m = re.match(r"CONFIDENCE:\s*(\w+)", line, re.IGNORECASE)
        if m:
            confidence = m.group(1).lower()
        m = re.match(r"CONCERN:\s*(.+)", line, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            concern = None if val.lower() == "none" else val

    # Normalise
    if outcome not in ("pass", "borderline", "reject"):
        outcome = "pass"
    if confidence not in ("high", "medium", "low"):
        confidence = "low"

    return outcome, confidence, concern


def _count_consecutive_borderlines(user_id: int, db: Session) -> int:
    """Count unbroken streak of non-strike borderlines, most-recent first."""
    screenings = (
        db.query(SubmissionScreening)
        .filter(SubmissionScreening.user_id == user_id)
        .order_by(SubmissionScreening.screened_at.desc())
        .all()
    )
    count = 0
    for s in screenings:
        if s.outcome == "borderline" and not s.triggered_strike:
            count += 1
        else:
            break  # PASS, REJECT, or a previous strike resets the streak
    return count


def _count_total_rejections(user_id: int, db: Session) -> int:
    """Count total hard rejections for a user (all time)."""
    return (
        db.query(SubmissionScreening)
        .filter(
            SubmissionScreening.user_id == user_id,
            SubmissionScreening.outcome == "reject",
        )
        .count()
    )


def get_active_cooldown(user_id: int, db: Session):
    """Return the SubmissionScreening record with an active cooldown, or None."""
    now = datetime.utcnow()
    return (
        db.query(SubmissionScreening)
        .filter(
            SubmissionScreening.user_id == user_id,
            SubmissionScreening.cooldown_until > now,
        )
        .order_by(SubmissionScreening.cooldown_until.desc())
        .first()
    )


async def screen_paper_background(paper_id: int) -> None:
    """FastAPI background task: screen a paper after email verification.

    Creates its own DB session so it can run safely after the request
    that verified the email has already closed its session.
    """
    from models.database import SessionLocal

    db = SessionLocal()
    try:
        await _screen_paper(paper_id, db)
    except Exception:
        traceback.print_exc()
    finally:
        db.close()


async def _screen_paper(paper_id: int, db: Session) -> None:
    """Core screening logic."""
    from services.email import email_service

    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper or paper.status != "pending_screening":
        return

    # Find primary author
    author_link = (
        db.query(PaperHumanAuthor)
        .filter(
            PaperHumanAuthor.paper_id == paper_id,
            PaperHumanAuthor.author_order == 1,
        )
        .first()
    )
    user_id = author_link.user_id if author_link else None

    # Snapshot paper data before potential deletion
    title = paper.title
    abstract = paper.abstract
    submitter_email = paper.submitter_email
    submitted_at = paper.submission_date

    # Call Claude (run in thread to avoid blocking event loop)
    try:
        outcome, confidence, concern = await asyncio.to_thread(
            _call_claude_sync, title, abstract
        )
    except Exception as e:
        print(f"[screening] Claude API error for paper {paper_id}: {e}")
        # On API failure default to PASS — don't block legitimate submissions
        outcome, confidence, concern = "pass", "low", None

    # Low-confidence reject → treat as borderline
    if outcome == "reject" and confidence == "low":
        outcome = "borderline"

    # Consecutive borderline count *before* this screening
    consecutive_before = _count_consecutive_borderlines(user_id, db) if user_id else 0

    triggered_strike = False
    cooldown_until = None

    if outcome == "borderline":
        new_streak = consecutive_before + 1
        if new_streak >= 3:
            triggered_strike = True
            cooldown_until = datetime.utcnow() + timedelta(hours=48)
        stored_consecutive = new_streak
    elif outcome == "reject":
        # Count total rejections (including this one)
        total_rejections = (_count_total_rejections(user_id, db) if user_id else 0) + 1
        if total_rejections >= 3:
            # 3 rejections → 6 month block
            cooldown_until = datetime.utcnow() + timedelta(days=180)
        else:
            cooldown_until = datetime.utcnow() + timedelta(hours=48)
        stored_consecutive = 0
    else:  # pass
        stored_consecutive = 0

    # Build screening record (paper_id stays set only for passing papers)
    screening = SubmissionScreening(
        paper_id=paper_id if outcome == "pass" else None,
        user_id=user_id,
        title=title,
        submitted_at=submitted_at,
        screened_at=datetime.utcnow(),
        outcome=outcome,
        confidence=confidence,
        concern=concern,
        consecutive_borderlines=stored_consecutive,
        triggered_strike=triggered_strike,
        cooldown_until=cooldown_until,
    )
    db.add(screening)

    if outcome == "pass":
        # advance_to_screened sets status="published", review_stage=1, commits
        advanced = stage_transition_service.advance_to_screened(paper_id, user_id or 0, db)
        if not advanced:
            # Paper was already past stage 0 (edge case); just publish it
            paper_obj = db.query(Paper).filter(Paper.id == paper_id).first()
            if paper_obj:
                paper_obj.status = "published"
            db.commit()
        email_service.send_screening_pass(submitter_email, title, f"/paper/{paper_id}")

    else:
        # Delete paper (cascade removes authors, versions, etc.)
        try:
            db.delete(paper)
            db.commit()  # commits both the screening record and the deletion
        except Exception as e:
            db.rollback()
            print(f"ERROR: Failed to delete screened paper {paper_id}: {e}")
            raise

        if outcome == "borderline":
            if triggered_strike:
                email_service.send_borderline_strike(
                    submitter_email, title, cooldown_until
                )
            else:
                email_service.send_borderline_rejection(
                    submitter_email, title, stored_consecutive
                )
        else:  # hard reject
            email_service.send_hard_rejection(
                submitter_email, title, concern, cooldown_until
            )


async def screen_paper_retroactive(paper_id: int, db: Session) -> str:
    """Screen an already-published paper (retroactive audit).

    Unlike live screening, a failed paper is NOT deleted — it is demoted
    to stage 0 with status 'ai_screen_rejected' so it stays visible in
    the audit trail.  Returns the outcome string.
    """
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        return "error"

    author_link = (
        db.query(PaperHumanAuthor)
        .filter(
            PaperHumanAuthor.paper_id == paper_id,
            PaperHumanAuthor.author_order == 1,
        )
        .first()
    )
    user_id = author_link.user_id if author_link else None

    try:
        outcome, confidence, concern = await asyncio.to_thread(
            _call_claude_sync, paper.title, paper.abstract
        )
    except Exception as e:
        print(f"[screening] Claude API error for paper {paper_id}: {e}")
        outcome, confidence, concern = "pass", "low", None

    if outcome == "reject" and confidence == "low":
        outcome = "borderline"

    screening = SubmissionScreening(
        paper_id=paper_id,
        user_id=user_id,
        title=paper.title,
        submitted_at=paper.submission_date,
        screened_at=datetime.utcnow(),
        outcome=outcome,
        confidence=confidence,
        concern=concern,
        consecutive_borderlines=0,
        triggered_strike=False,
        cooldown_until=None,
    )
    db.add(screening)

    if outcome == "pass":
        # Ensure stage is 1 for passing papers (they're already at 1 after migration)
        if paper.review_stage == 0:
            stage_transition_service.advance_to_screened(paper_id, user_id or 0, db)
        else:
            db.commit()
    else:
        # Demote: keep published but mark as screened-rejected at stage 0
        paper.review_stage = 0
        paper.status = "ai_screen_rejected"
        db.commit()

    return outcome
