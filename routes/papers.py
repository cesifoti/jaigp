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

@router.get("/{paper_id}/html", response_class=HTMLResponse)
async def serve_html(
    paper_id: int,
    version: int = None,
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Serve HTML version of a paper with navigation."""
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

        # Extract just the body content (strip html/head/body tags)
        # Find content between <body> and </body>
        import re
        body_match = re.search(r'<body>(.*?)</body>', html_content, re.DOTALL)
        if body_match:
            html_content = body_match.group(1)

        # Replace relative image paths with absolute URLs
        # Pattern: paper-{id}-v{version}_images/figure_N.ext
        pdf_basename = paper_version.pdf_filename.replace('.pdf', '')
        image_pattern = rf'{pdf_basename}_images/([^"]+\.(png|jpg|jpeg|gif))"'

        def replace_image_path(match):
            figure_name = match.group(1)
            return f'/paper/{paper_id}/figures/{figure_name}?version={current_version}"'

        html_content = re.sub(image_pattern, replace_image_path, html_content)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading HTML file: {str(e)}")

    # Get user from session
    user = request.session.get("user") if request else None

    # Render template with navigation
    return templates.TemplateResponse(
        "paper_html.html",
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
    db: Session = Depends(get_db)
):
    """Serve Markdown version of a paper."""
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

    # Serve Markdown file as download
    return FileResponse(
        path=file_path,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f"attachment; filename=\"{md_filename}\""
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

    # Construct figure path
    pdf_filename = paper_version.pdf_filename.replace('.pdf', '')
    figure_dir = file_storage.get_date_path(paper.published_date) / f"{pdf_filename}_images"
    figure_path = figure_dir / figure_name

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

    return templates.TemplateResponse(
        "paper.html",
        {
            "request": request,
            "paper": paper,
            "user": user
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
