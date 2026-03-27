"""Paper submission routes."""
from fastapi import APIRouter, BackgroundTasks, Request, Depends, HTTPException, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from models.database import get_db
from models.user import User
from models.paper import Paper, PaperVersion, PaperHumanAuthor, PaperAIAuthor, PaperField, PaperCategory
from models.submission_screening import SubmissionScreening
from services.file_storage import file_storage
from services.pdf_handler import pdf_handler
from services.openalex import openalex_service
from services.email import email_service
from services.user_email import add_email_if_new
from services.screening import screen_paper_background, get_active_cooldown
from models.user_email import UserEmail
from typing import List, Optional
import json
import secrets
import config

router = APIRouter(prefix="/submit", tags=["submit"])
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)

def require_auth(request: Request):
    """Dependency to require authentication."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user

@router.get("", response_class=HTMLResponse)
async def submit_form(request: Request):
    """Show paper submission form."""
    user = request.session.get("user")

    # Redirect to login if not authenticated
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    return templates.TemplateResponse(
        "submit.html",
        {
            "request": request,
            "user": user
        }
    )

@router.post("/fetch-fields")
async def fetch_openalex_fields(
    request: Request,
    title: str = Form(""),
    abstract: str = Form("")
):
    """HTMX endpoint to fetch OpenAlex field suggestions."""
    # Debug logging
    print(f"Fetching fields for title: {title[:50]}...")
    print(f"Abstract length: {len(abstract) if abstract else 0}")

    if not title:
        return templates.TemplateResponse(
            "components/field_suggestions.html",
            {
                "request": request,
                "suggestions": [],
                "error": "Please enter a title first"
            }
        )

    try:
        suggestions = await openalex_service.suggest_fields(title, abstract)
        print(f"Got {len(suggestions)} suggestions from OpenAlex")

        return templates.TemplateResponse(
            "components/field_suggestions.html",
            {
                "request": request,
                "suggestions": suggestions
            }
        )
    except Exception as e:
        print(f"Error fetching OpenAlex suggestions: {e}")
        return templates.TemplateResponse(
            "components/field_suggestions.html",
            {
                "request": request,
                "suggestions": [],
                "error": f"Error: {str(e)}"
            }
        )

@router.post("")
async def submit_paper(
    request: Request,
    db: Session = Depends(get_db),
    title: str = Form(...),
    abstract: str = Form(...),
    submitter_email: str = Form(...),
    pdf_file: UploadFile = File(...),
    image_file: UploadFile = File(None),
    human_authors: str = Form(...),  # JSON string
    ai_authors: str = Form(None),  # JSON string
    fields: str = Form(None),  # JSON string
    categories: str = Form(None),  # JSON string
):
    """Submit new paper."""
    user_data = require_auth(request)

    # Get user from database
    user = db.query(User).filter(User.id == user_data["id"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Concurrent submission gate — limit active pipeline papers by badge
    _BADGE_LIMITS = {"new": 1, "copper": 1, "bronze": 2, "silver": 3, "gold": 5}
    badge = user.badge or "new"
    limit = _BADGE_LIMITS.get(badge, 1)
    active_count = (
        db.query(Paper)
        .join(PaperHumanAuthor)
        .filter(
            PaperHumanAuthor.user_id == user.id,
            Paper.status.in_(["pending_verification", "pending_screening", "published"]),
            Paper.review_stage.in_([0, 1, 2, 3, 4]),
        )
        .count()
    )
    if active_count >= limit:
        raise HTTPException(
            status_code=400,
            detail=(
                f"You have reached your concurrent submission limit ({active_count} of {limit} "
                f"active paper{'s' if limit != 1 else ''} allowed for {badge} badge). "
                "A paper slot frees up when a paper is accepted (stage\u00a05) or desk rejected."
            ),
        )

    # Cooldown check — user may be paused after hard rejection or 3 borderlines
    cooldown = get_active_cooldown(user.id, db)
    if cooldown:
        until_str = cooldown.cooldown_until.strftime("%Y-%m-%d %H:%M UTC")
        raise HTTPException(
            status_code=400,
            detail=f"Your account is on a submission pause until {until_str} due to a recent screening rejection.",
        )

    # Capture submitter email into multi-email table
    if submitter_email:
        add_email_if_new(
            user_id=user.id,
            email=submitter_email,
            source="submission",
            db=db,
        )

    # Validate PDF
    pdf_content = await pdf_handler.validate_pdf(pdf_file)

    # Validate image if provided
    image_content = None
    image_extension = None
    if image_file and image_file.filename:
        image_content = await pdf_handler.validate_image(image_file)
        image_extension = pdf_handler.get_extension_from_filename(image_file.filename)

    # Parse JSON data
    try:
        human_authors_data = json.loads(human_authors) if human_authors else []
        ai_authors_data = json.loads(ai_authors) if ai_authors else []
        fields_data = json.loads(fields) if fields else []
        categories_data = json.loads(categories) if categories else []
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON data")

    # Validate categories (minimum 1 required)
    if len(categories_data) < 1:
        raise HTTPException(status_code=400, detail="Please select at least 1 category")

    # Generate verification token
    verification_token = secrets.token_urlsafe(32)

    # Create paper with pending_verification status
    paper = Paper(
        title=title,
        abstract=abstract,
        current_version=1,
        submission_date=datetime.utcnow(),
        published_date=datetime.utcnow(),
        status="pending_verification",
        submitter_email=submitter_email,
        verification_token=verification_token
    )
    db.add(paper)
    db.flush()  # Get paper ID

    # Save PDF and generate HTML/Markdown versions
    pdf_filename, pdf_path = await file_storage.save_pdf(
        pdf_content,
        paper.id,
        1,
        paper.published_date,
        paper.title,
        paper.abstract
    )

    # Save image if provided
    if image_content:
        image_filename, image_path = await file_storage.save_image(
            image_content,
            paper.id,
            image_extension,
            paper.published_date
        )
        paper.image_filename = image_filename

    # Create first version
    version = PaperVersion(
        paper_id=paper.id,
        version_number=1,
        pdf_filename=pdf_filename,
        change_log="Initial submission"
    )
    db.add(version)

    # Add human authors
    for idx, author_data in enumerate(human_authors_data):
        # For the submitting user, use their user_id
        if author_data.get("is_self"):
            # Update user's profile with Google Scholar and Rankless URLs
            if author_data.get("google_scholar"):
                user.google_scholar_url = author_data.get("google_scholar")
            if author_data.get("rankless"):
                user.rankless_url = author_data.get("rankless")

            author = PaperHumanAuthor(
                paper_id=paper.id,
                user_id=user.id,
                author_order=idx + 1,
                contribution=author_data.get("contribution")
            )
            db.add(author)
        else:
            # For other authors, look up or create user by ORCID
            orcid_id = author_data.get("orcid_id")
            if orcid_id:
                # Look for existing user
                other_user = db.query(User).filter(User.orcid_id == orcid_id).first()
                if not other_user:
                    # Create placeholder user (they'll complete profile when they login)
                    other_user = User(
                        orcid_id=orcid_id,
                        name=author_data.get("name", ""),
                        google_scholar_url=author_data.get("google_scholar"),
                        rankless_url=author_data.get("rankless")
                    )
                    db.add(other_user)
                    db.flush()

                author = PaperHumanAuthor(
                    paper_id=paper.id,
                    user_id=other_user.id,
                    author_order=idx + 1
                )
                db.add(author)

    # Add AI authors
    for idx, ai_data in enumerate(ai_authors_data):
        ai_author = PaperAIAuthor(
            paper_id=paper.id,
            ai_name=ai_data.get("name", ""),
            ai_version=ai_data.get("version"),
            ai_role=ai_data.get("role"),
            author_order=len(human_authors_data) + idx + 1
        )
        db.add(ai_author)

    # Add fields
    for field_data in fields_data:
        field = PaperField(
            paper_id=paper.id,
            field_type=field_data.get("type", "topic"),
            field_id=field_data.get("id"),
            field_name=field_data.get("name", ""),
            display_name=field_data.get("display_name", "")
        )
        db.add(field)

    # Add categories
    for category_data in categories_data:
        category_path = category_data.get("path", "")
        leaf_category = category_data.get("leaf", "")

        # Calculate level based on path depth
        level = len(category_path.split(" > "))

        category = PaperCategory(
            paper_id=paper.id,
            category_path=category_path,
            leaf_category=leaf_category,
            level=level
        )
        db.add(category)

    # Commit transaction
    db.commit()

    # Send verification email
    verification_url = f"{config.BASE_URL}/submit/verify/{verification_token}"
    email_service.send_verification_email(submitter_email, verification_url, title)

    # Redirect to verification pending page
    return RedirectResponse(url=f"/submit/verification-sent?email={submitter_email}", status_code=303)


@router.get("/verification-sent", response_class=HTMLResponse)
async def verification_sent(
    request: Request,
    email: str = ""
):
    """Show verification email sent confirmation."""
    user = request.session.get("user")
    return templates.TemplateResponse(
        "verification_sent.html",
        {
            "request": request,
            "user": user,
            "email": email
        }
    )


@router.get("/verify/{token}", response_class=HTMLResponse)
async def verify_paper(
    token: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Verify paper submission via email token, then queue AI screening."""
    paper = db.query(Paper).filter(Paper.verification_token == token).first()

    if not paper:
        raise HTTPException(status_code=404, detail="Invalid verification token")

    # Already past verification
    if paper.status in ("published", "pending_screening", "ai_screen_rejected"):
        return templates.TemplateResponse(
            "verification_result.html",
            {
                "request": request,
                "user": request.session.get("user"),
                "success": True,
                "already_verified": True,
                "paper": paper,
            },
        )

    paper_id = paper.id

    # Mark email as verified, queue screening
    paper.status = "pending_screening"
    paper.verified_at = datetime.utcnow()
    paper.verification_token = None

    # Mark the submitter email as verified in user_emails
    if paper.submitter_email:
        ue = db.query(UserEmail).filter(
            UserEmail.email == paper.submitter_email.strip().lower()
        ).first()
        if ue and not ue.verified_at:
            ue.verified_at = datetime.utcnow()

    db.commit()

    # Queue the AI screening as a background task
    background_tasks.add_task(screen_paper_background, paper_id)

    return templates.TemplateResponse(
        "verification_result.html",
        {
            "request": request,
            "user": request.session.get("user"),
            "success": True,
            "already_verified": False,
            "paper": paper,
        },
    )


@router.post("/{paper_id}/resend-verification", response_class=HTMLResponse)
async def resend_verification(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Resend verification email for a pending paper."""
    user_data = require_auth(request)

    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    if paper.status != "pending_verification":
        return HTMLResponse('<span class="ml-2 text-xs text-slate-500">Already verified</span>')

    # Check user is an author
    is_author = db.query(PaperHumanAuthor).filter(
        PaperHumanAuthor.paper_id == paper_id,
        PaperHumanAuthor.user_id == user_data["id"]
    ).first()
    if not is_author:
        raise HTTPException(status_code=403, detail="Only authors can resend verification")

    # Generate new token and send email
    new_token = secrets.token_urlsafe(32)
    paper.verification_token = new_token
    db.commit()

    verification_url = f"{config.BASE_URL}/submit/verify/{new_token}"
    email_service.send_verification_email(paper.submitter_email, verification_url, paper.title)

    return HTMLResponse(
        '<span class="ml-2 inline-flex items-center px-3 py-1 rounded-full text-xs font-medium '
        'bg-green-100 text-green-800 border border-green-300">'
        'Verification email sent!</span>'
    )


@router.get("/{paper_id}/update", response_class=HTMLResponse)
async def update_form(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Show form to submit new version of paper."""
    user_data = request.session.get("user")

    # Redirect to login if not authenticated
    if not user_data:
        return RedirectResponse(url="/auth/login", status_code=303)

    # Get paper
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Check if user is an author
    is_author = db.query(PaperHumanAuthor).filter(
        PaperHumanAuthor.paper_id == paper_id,
        PaperHumanAuthor.user_id == user_data["id"]
    ).first() is not None

    if not is_author:
        raise HTTPException(status_code=403, detail="Only authors can update this paper")

    if paper.is_locked:
        return RedirectResponse(url=f"/paper/{paper_id}", status_code=303)

    category_data = [{"category_path": c.category_path, "leaf_category": c.leaf_category} for c in paper.categories]

    return templates.TemplateResponse(
        "submit_update.html",
        {
            "request": request,
            "user": user_data,
            "paper": paper,
            "category_data": category_data
        }
    )

@router.post("/{paper_id}/update")
async def submit_update(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
    pdf_file: UploadFile = File(...),
    change_log: str = Form(...),
    title: str = Form(None),
    abstract: str = Form(None),
    image_file: UploadFile = File(None),
    categories: str = Form(None)  # JSON string
):
    """Submit new version of paper with optional metadata updates."""
    user_data = require_auth(request)

    # Get paper
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Check if user is an author
    is_author = db.query(PaperHumanAuthor).filter(
        PaperHumanAuthor.paper_id == paper_id,
        PaperHumanAuthor.user_id == user_data["id"]
    ).first() is not None

    if not is_author:
        raise HTTPException(status_code=403, detail="Only authors can update this paper")

    if paper.is_locked:
        raise HTTPException(status_code=403, detail="Paper is locked during review. Updates must go through the review process.")

    # Check version control: max 1 version per hour
    last_version = db.query(PaperVersion).filter(
        PaperVersion.paper_id == paper_id
    ).order_by(
        PaperVersion.version_number.desc()
    ).first()

    if last_version:
        # Check if last version was created within the past hour
        now = datetime.utcnow()
        time_since_last_version = now - last_version.created_at

        if time_since_last_version.total_seconds() < 3600:  # 3600 seconds = 1 hour
            seconds_remaining = int(3600 - time_since_last_version.total_seconds())
            minutes_remaining = seconds_remaining // 60
            seconds_display = seconds_remaining % 60

            # Render wait page with countdown instead of throwing exception
            return templates.TemplateResponse(
                "version_wait.html",
                {
                    "request": request,
                    "paper": paper,
                    "user": user_data,
                    "seconds_remaining": seconds_remaining,
                    "minutes_remaining": minutes_remaining,
                    "seconds_display": seconds_display,
                    "last_version_time": last_version.created_at,
                    "next_version_time": last_version.created_at + timedelta(hours=1)
                }
            )

    # Validate PDF
    pdf_content = await pdf_handler.validate_pdf(pdf_file)

    # Increment version number
    new_version_number = paper.current_version + 1

    # Update optional fields if provided
    updated_title = paper.title
    updated_abstract = paper.abstract

    if title and title.strip() and title.strip() != paper.title:
        paper.title = title.strip()
        updated_title = paper.title

    if abstract and abstract.strip() and abstract.strip() != paper.abstract:
        paper.abstract = abstract.strip()
        updated_abstract = paper.abstract

    # Save PDF and generate HTML/Markdown versions with updated metadata
    # Use paper.published_date so all versions are stored in the same date directory
    pdf_filename, pdf_path = await file_storage.save_pdf(
        pdf_content,
        paper.id,
        new_version_number,
        paper.published_date,
        updated_title,
        updated_abstract
    )

    # Handle image upload if provided
    if image_file and image_file.filename:
        # Validate image file
        allowed_types = ["image/jpeg", "image/jpg", "image/png"]
        if image_file.content_type not in allowed_types:
            raise HTTPException(status_code=400, detail="Image must be JPG or PNG")

        # Read image content
        image_content = await image_file.read()

        # Save image in same date directory as the paper
        image_filename, image_path = await file_storage.save_image(
            image_content,
            paper.id,
            image_file.filename,
            paper.published_date
        )

        paper.image_filename = image_filename

    # Create new version
    version = PaperVersion(
        paper_id=paper.id,
        version_number=new_version_number,
        pdf_filename=pdf_filename,
        change_log=change_log
    )
    db.add(version)

    # Update paper's current version
    paper.current_version = new_version_number
    paper.updated_at = datetime.utcnow()

    # Update categories if provided
    if categories:
        try:
            categories_data = json.loads(categories)

            # Remove old categories
            db.query(PaperCategory).filter(
                PaperCategory.paper_id == paper_id
            ).delete()

            # Add new categories
            for category_data in categories_data:
                category_path = category_data.get("path", "")
                leaf_category = category_data.get("leaf", "")
                level = len(category_path.split(" > "))

                category = PaperCategory(
                    paper_id=paper.id,
                    category_path=category_path,
                    leaf_category=leaf_category,
                    level=level
                )
                db.add(category)
        except json.JSONDecodeError:
            # If categories JSON is invalid, just skip updating them
            pass

    db.commit()

    # Redirect to paper page
    return RedirectResponse(url=f"/paper/{paper.id}", status_code=303)
