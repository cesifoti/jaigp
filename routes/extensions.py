"""Extension request routes for deadline extensions."""
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from models.database import get_db
from models.paper import Paper, PaperHumanAuthor
from services.stage_transition import stage_transition_service

router = APIRouter(prefix="/paper", tags=["extensions"])


@router.post("/{paper_id}/request-extension", response_class=HTMLResponse)
async def request_extension(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
    reason: str = Form(""),
):
    """Author requests a 20-day deadline extension."""
    session_user = request.session.get("user")
    if not session_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Must be an author
    is_author = db.query(PaperHumanAuthor).filter(
        PaperHumanAuthor.paper_id == paper_id,
        PaperHumanAuthor.user_id == session_user["id"],
    ).first()
    if not is_author:
        raise HTTPException(status_code=403, detail="Only paper authors can request extensions")

    extension = stage_transition_service.request_extension(
        paper_id=paper_id,
        user_id=session_user["id"],
        reason=reason,
        db=db,
    )

    if not extension:
        return HTMLResponse(
            '<div class="p-3 bg-amber-50 border border-amber-200 rounded-md text-sm text-amber-800">'
            'An extension request is already pending for this stage.'
            '</div>'
        )

    return HTMLResponse(
        '<div class="p-3 bg-green-50 border border-green-200 rounded-md text-sm text-green-800">'
        'Extension request submitted! An admin will review it shortly.'
        '</div>'
    )


@router.get("/{paper_id}/extension-status", response_class=HTMLResponse)
async def extension_status(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """HTMX partial showing extension request status."""
    from models.extension import ExtensionRequest

    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    extensions = db.query(ExtensionRequest).filter(
        ExtensionRequest.paper_id == paper_id,
    ).order_by(ExtensionRequest.created_at.desc()).all()

    if not extensions:
        return HTMLResponse('<p class="text-sm text-slate-500">No extension requests.</p>')

    html_parts = []
    for ext in extensions:
        status_class = {
            "pending": "bg-yellow-100 text-yellow-800",
            "approved": "bg-green-100 text-green-800",
            "denied": "bg-red-100 text-red-800",
        }.get(ext.status, "bg-slate-100 text-slate-800")

        html_parts.append(
            f'<div class="flex items-center gap-2 text-sm">'
            f'<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium {status_class}">'
            f'{ext.status.capitalize()}</span>'
            f'<span class="text-slate-500">Stage {ext.stage} - {ext.extension_days} days</span>'
            f'</div>'
        )

    return HTMLResponse('<div class="space-y-2">' + ''.join(html_parts) + '</div>')
