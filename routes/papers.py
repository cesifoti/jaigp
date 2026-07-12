"""Paper viewing and file serving routes."""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters
from sqlalchemy.orm import Session
from models.database import get_db
from models.paper import Paper, PaperVersion
from services.file_storage import file_storage
from pathlib import Path

router = APIRouter(prefix="/paper", tags=["papers"])
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)

@router.get("/{paper_id}/pdf")
async def serve_pdf(
    paper_id: int,
    version: int = None,
    db: Session = Depends(get_db)
):
    """Serve PDF file for a paper."""
    # Get paper
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Get requested version or current version
    if version:
        paper_version = db.query(PaperVersion).filter(
            PaperVersion.paper_id == paper_id,
            PaperVersion.version_number == version
        ).first()
    else:
        paper_version = db.query(PaperVersion).filter(
            PaperVersion.paper_id == paper_id,
            PaperVersion.version_number == paper.current_version
        ).first()

    if not paper_version:
        raise HTTPException(status_code=404, detail="Paper version not found")

    # Get file path
    file_path = file_storage.get_file_path(
        paper_version.pdf_filename,
        paper.published_date
    )

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found")

    # Serve file inline (for viewing) not as attachment (for download)
    from fastapi.responses import Response
    with open(file_path, "rb") as f:
        pdf_content = f.read()

    return Response(
        content=pdf_content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "inline"
        }
    )

def _sanitize_paper_html(html_content: str, pdf_basename: str, paper_id: int,
                         current_version: int) -> str:
    """Extract body, rewrite figure paths to routes, and sanitize (XSS from crafted PDFs)."""
    import re
    import nh3

    body_match = re.search(r'<body.*?>(.*?)</body>', html_content, re.DOTALL)
    if body_match:
        html_content = body_match.group(1)

    image_pattern = rf'{re.escape(pdf_basename)}_images/([^"]+\.(png|jpg|jpeg|gif))"'

    def replace_image_path(match):
        figure_name = match.group(1)
        return f'/paper/{paper_id}/figures/{figure_name}?version={current_version}"'

    html_content = re.sub(image_pattern, replace_image_path, html_content)

    return nh3.clean(
        html_content,
        tags={"p", "br", "b", "i", "em", "strong", "h1", "h2", "h3", "h4", "h5", "h6",
              "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
              "img", "a", "span", "div", "figure", "figcaption", "blockquote",
              "pre", "code", "sub", "sup", "hr", "section", "article",
              # MathML (LaTeXML output); browsers render MathML Core natively
              "math", "semantics", "annotation", "mrow", "mi", "mo", "mn", "ms",
              "mtext", "mspace", "msup", "msub", "msubsup", "mfrac", "msqrt",
              "mroot", "mstyle", "merror", "mpadded", "mphantom", "mfenced",
              "menclose", "munder", "mover", "munderover", "mmultiscripts",
              "mtable", "mtr", "mtd", "mlabeledtr", "none"},
        attributes={
            "img": {"src", "alt", "width", "height", "class", "style"},
            "a": {"href", "title", "class"},
            "td": {"colspan", "rowspan", "class", "style"},
            "th": {"colspan", "rowspan", "class", "style"},
            "span": {"class", "style"},
            "div": {"class", "style"},
            "p": {"class", "style"},
            "table": {"class", "style"},
            "math": {"display", "alttext", "xmlns"},
            "mo": {"stretchy", "form", "fence", "separator", "lspace", "rspace"},
            "mtable": {"columnalign", "rowalign"},
            "mtd": {"columnalign", "columnspan", "rowspan"},
            "mspace": {"width", "height"},
            "annotation": {"encoding"},
            "*": {"id", "class", "mathvariant", "displaystyle", "scriptlevel"},
        },
        url_schemes={"http", "https"},
    )


def _strip_artifact_preamble(html: str) -> str:
    """Trim the artifact's own title/authors/abstract and footer note.

    On the paper page those are shown by the page header and the abstract lead,
    so the article body should start at the first real section.
    """
    import re

    first_h2 = re.search(r'<h2[\s>]', html)
    if not first_h2:
        return html
    # Preamble = title + author lines. If it's suspiciously large, something is
    # unusual about this artifact — better to repeat than to eat content.
    if first_h2.start() > 6000:
        return html
    rest = html[first_h2.start():]

    # Drop the "Abstract" section (the lead block already shows it). It is not
    # always the first section — e.g. an "Author Note" may precede it — so look
    # anywhere near the top of the document.
    m = re.search(r'<h2[^>]*>\s*(?:\d+\.?\s*)?abstract\s*[.:]?\s*</h2>', rest[:8000], re.IGNORECASE)
    if m:
        nxt = re.search(r'<h[1-4][\s>]', rest[m.end():])
        if nxt:
            rest = rest[:m.start()] + rest[m.end() + nxt.start():]
        # No later heading: abstract-only artifact — leave it alone rather
        # than emptying the page (the lead would duplicate it, harmlessly)

    # Drop the artifact's trailing provenance note (now shown in the toolbar)
    rest = re.sub(
        r'<hr\s*/?>\s*<p><em>This (reading version|document) was (generated|automatically generated)[^<]*</em></p>\s*$',
        '', rest,
    )
    return rest


@router.get("/{paper_id}/html", response_class=HTMLResponse)
async def serve_html(
    paper_id: int,
    version: int = None,
    embed: bool = False,
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Serve HTML version of a paper with navigation (embed=1: bare reading pane)."""
    # Get paper
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Get requested version or current version
    if version:
        paper_version = db.query(PaperVersion).filter(
            PaperVersion.paper_id == paper_id,
            PaperVersion.version_number == version
        ).first()
        current_version = version
    else:
        paper_version = db.query(PaperVersion).filter(
            PaperVersion.paper_id == paper_id,
            PaperVersion.version_number == paper.current_version
        ).first()
        current_version = paper.current_version

    if not paper_version:
        raise HTTPException(status_code=404, detail="Paper version not found")

    # Construct HTML filename from PDF filename
    html_filename = paper_version.pdf_filename.replace('.pdf', '.html')

    # Get file path
    file_path = file_storage.get_file_path(
        html_filename,
        paper.published_date
    )

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="HTML version not found")

    # Read HTML content
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        pdf_basename = paper_version.pdf_filename.replace('.pdf', '')
        html_content = _sanitize_paper_html(html_content, pdf_basename, paper_id, current_version)

    except Exception as e:
        raise HTTPException(status_code=500, detail="Error reading HTML file")

    # Get user from session
    user = request.session.get("user") if request else None

    # Render template with navigation (or the bare embed pane for the paper-page tab)
    return templates.TemplateResponse(
        "paper_embed.html" if embed else "paper_html.html",
        {
            "request": request,
            "paper": paper,
            "user": user,
            "html_content": html_content,
            "current_version": current_version,
            "version_number": version
        }
    )

@router.get("/{paper_id}/markdown")
async def serve_markdown(
    paper_id: int,
    version: int = None,
    raw: bool = False,
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Serve Markdown version of a paper: rendered page by default, raw=1 downloads the .md."""
    # Get paper
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Get requested version or current version
    if version:
        paper_version = db.query(PaperVersion).filter(
            PaperVersion.paper_id == paper_id,
            PaperVersion.version_number == version
        ).first()
    else:
        paper_version = db.query(PaperVersion).filter(
            PaperVersion.paper_id == paper_id,
            PaperVersion.version_number == paper.current_version
        ).first()

    if not paper_version:
        raise HTTPException(status_code=404, detail="Paper version not found")

    # Construct Markdown filename from PDF filename
    md_filename = paper_version.pdf_filename.replace('.pdf', '.md')

    # Get file path
    file_path = file_storage.get_file_path(
        md_filename,
        paper.published_date
    )

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Markdown version not found")

    if raw:
        # Raw .md download (previous default behavior)
        return FileResponse(
            path=file_path,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f"attachment; filename=\"{md_filename}\""
            }
        )

    # Rendered, readable page
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            md_text = f.read()

        from services.ai_converter import ai_converter
        html_doc = ai_converter.markdown_to_html(md_text, paper_version.pdf_filename)
        pdf_basename = paper_version.pdf_filename.replace('.pdf', '')
        current_version = paper_version.version_number
        html_content = _sanitize_paper_html(html_doc, pdf_basename, paper_id, current_version)
    except Exception:
        raise HTTPException(status_code=500, detail="Error rendering Markdown file")

    user = request.session.get("user") if request else None
    return templates.TemplateResponse(
        "paper_html.html",
        {
            "request": request,
            "paper": paper,
            "user": user,
            "html_content": html_content,
            "current_version": current_version,
            "version_number": version,
            "markdown_view": True,
        }
    )

@router.get("/{paper_id}/image")
async def serve_image(
    paper_id: int,
    db: Session = Depends(get_db)
):
    """Serve cover image for a paper."""
    # Get paper
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper or not paper.image_filename:
        # Return placeholder for papers without images
        placeholder_path = Path("/var/www/ai_journal/static/images/placeholder-paper.jpg")
        return FileResponse(
            path=placeholder_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=2592000, immutable"}
        )

    # Get file path
    file_path = file_storage.get_file_path(
        paper.image_filename,
        paper.published_date
    )

    if not file_path.exists():
        # Return placeholder if file is missing
        placeholder_path = Path("/var/www/ai_journal/static/images/placeholder-paper.jpg")
        return FileResponse(
            path=placeholder_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=2592000, immutable"}
        )

    # Determine media type from extension
    extension = Path(paper.image_filename).suffix.lower()
    media_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png'
    }
    media_type = media_types.get(extension, 'image/jpeg')

    # Serve file
    return FileResponse(
        path=file_path,
        media_type=media_type
    )

@router.get("/{paper_id}/thumbnail")
async def serve_thumbnail(
    paper_id: int,
    db: Session = Depends(get_db)
):
    """Serve optimized thumbnail for homepage cards (600px max width)."""
    # Get paper
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper or not paper.image_filename:
        # Return placeholder for papers without images
        placeholder_path = Path("/var/www/ai_journal/static/images/placeholder-paper.jpg")
        return FileResponse(
            path=placeholder_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=2592000, immutable"}
        )

    # Try to serve thumbnail first
    # Thumbnail naming: paper-X-image.jpg -> paper-X-image_thumb.jpg
    original_path = file_storage.get_file_path(paper.image_filename, paper.published_date)
    thumb_filename = f"{original_path.stem}_thumb.jpg"
    thumb_path = original_path.parent / thumb_filename

    if thumb_path.exists():
        # Serve optimized thumbnail
        return FileResponse(
            path=thumb_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=2592000, immutable"}
        )

    # Fallback: generate thumbnail on-the-fly if missing
    try:
        from services.image_processor import image_processor
        thumb_path = image_processor.generate_thumbnail(original_path)
        return FileResponse(
            path=thumb_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=2592000, immutable"}
        )
    except Exception as e:
        # Last resort: serve full image
        return FileResponse(
            path=original_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=2592000, immutable"}
        )

@router.get("/{paper_id}/figures/{figure_name}")
async def serve_figure(
    paper_id: int,
    figure_name: str,
    version: int = None,
    db: Session = Depends(get_db)
):
    """Serve extracted figure images from PDF."""
    # Get paper
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Get version
    if version:
        paper_version = db.query(PaperVersion).filter(
            PaperVersion.paper_id == paper_id,
            PaperVersion.version_number == version
        ).first()
    else:
        paper_version = db.query(PaperVersion).filter(
            PaperVersion.paper_id == paper_id,
            PaperVersion.version_number == paper.current_version
        ).first()

    if not paper_version:
        raise HTTPException(status_code=404, detail="Paper version not found")

    # Construct figure path (with path traversal protection)
    pdf_filename = paper_version.pdf_filename.replace('.pdf', '')
    figure_dir = file_storage.get_date_path(paper.published_date) / f"{pdf_filename}_images"
    figure_path = (figure_dir / figure_name).resolve()

    # Ensure the resolved path is inside the expected directory
    if not str(figure_path).startswith(str(figure_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid figure name")

    if not figure_path.exists():
        raise HTTPException(status_code=404, detail="Figure not found")

    # Determine media type from extension
    extension = Path(figure_name).suffix.lower()
    media_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif'
    }
    media_type = media_types.get(extension, 'image/png')

    # Serve file
    return FileResponse(
        path=figure_path,
        media_type=media_type
    )

@router.get("/{paper_id}", response_class=HTMLResponse)
async def view_paper(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """View paper detail page."""
    # Get paper with all relationships
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Get user from session
    user = request.session.get("user")

    # Get user DB object for endorsement eligibility check
    from models.user import User
    user_db = None
    has_endorsed = False
    if user:
        user_db = db.query(User).filter(User.id == user["id"]).first()
        if user_db:
            from models.endorsement import Endorsement
            has_endorsed = db.query(Endorsement).filter(
                Endorsement.paper_id == paper_id,
                Endorsement.user_id == user["id"],
            ).first() is not None

    # Get AI reviews for current cycle (latest for stage banners, all for transparency section)
    from models.review import AIReview
    all_ai_reviews = db.query(AIReview).filter(
        AIReview.paper_id == paper_id,
        AIReview.review_cycle == paper.review_cycle,
    ).order_by(AIReview.review_round.asc()).all()
    latest_ai_review = all_ai_reviews[-1] if all_ai_reviews else None

    # Governed endorsement gate (counts + qualifying badges come from the rules)
    from services.stage_transition import stage_transition_service
    endorse_ctx = stage_transition_service.endorsement_requirements(paper_id, db)
    can_endorse = bool(
        user_db and (user_db.badge or "new") in endorse_ctx["allowed_badges"]
    )

    # Load the reading view inline (sanitized HTML artifact); None -> fallback notice
    reading_html = None
    current_pv = db.query(PaperVersion).filter(
        PaperVersion.paper_id == paper_id,
        PaperVersion.version_number == paper.current_version
    ).first()
    if current_pv:
        html_path = file_storage.get_file_path(
            current_pv.pdf_filename.replace('.pdf', '.html'), paper.published_date
        )
        if html_path.exists():
            try:
                with open(html_path, 'r', encoding='utf-8') as f:
                    raw_html = f.read()
                reading_html = _sanitize_paper_html(
                    raw_html,
                    current_pv.pdf_filename.replace('.pdf', ''),
                    paper_id,
                    current_pv.version_number,
                )
                reading_html = _strip_artifact_preamble(reading_html)
            except Exception as e:
                print(f"[paper] Could not load reading view for paper {paper_id}: {e!r}")

    return templates.TemplateResponse(
        "paper.html",
        {
            "request": request,
            "paper": paper,
            "user": user,
            "user_db": user_db,
            "reading_html": reading_html,
            "endorsements": paper.endorsements if hasattr(paper, 'endorsements') else [],
            "has_endorsed": has_endorsed,
            "can_endorse": can_endorse,
            "latest_ai_review": latest_ai_review,
            "all_ai_reviews": all_ai_reviews,
            **endorse_ctx,
        }
    )

@router.get("/{paper_id}/versions")
async def get_versions(
    paper_id: int,
    db: Session = Depends(get_db)
):
    """Get version history for a paper."""
    versions = db.query(PaperVersion).filter(
        PaperVersion.paper_id == paper_id
    ).order_by(
        PaperVersion.version_number.desc()
    ).all()

    return {
        "paper_id": paper_id,
        "versions": [
            {
                "version_number": v.version_number,
                "change_log": v.change_log,
                "created_at": v.created_at.isoformat() if v.created_at else None
            }
            for v in versions
        ]
    }
