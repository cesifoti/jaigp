"""Main FastAPI application for JAIGP - Journal for AI Generated Papers."""
import os
from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from starlette.middleware.cors import CORSMiddleware
import config
from models.database import init_db
from middleware.security import SecurityHeadersMiddleware, RateLimitMiddleware
from services.redis_session import RedisSessionMiddleware

# Create FastAPI app
app = FastAPI(
    title=config.APP_NAME,
    description="The Journal for AI Generated Papers",
    version="1.0.0",
    debug=config.DEBUG,
    docs_url=None if not config.DEBUG else "/docs",
    redoc_url=None if not config.DEBUG else "/redoc",
    openapi_url=None if not config.DEBUG else "/openapi.json",
)

# Notification count middleware — injects unread count into request.state
from starlette.middleware.base import BaseHTTPMiddleware

class NotificationCountMiddleware(BaseHTTPMiddleware):
    _online_count_cache = 0
    _online_count_ts = 0

    async def dispatch(self, request, call_next):
        request.state.notification_count = 0
        request.state.unread_messages = 0
        request.state.online_count = 0
        request.state.is_admin = False
        try:
            path = request.url.path
            # Skip for static/API/polling paths
            if not (path.startswith("/static/") or path.endswith(("/feed/count", "/thumbnail", ".json"))):
                # Track online presence via Redis (5-min TTL per session)
                import time as _time
                try:
                    from services.cache import redis_client, check_redis_connection
                    if check_redis_connection():
                        session_id = None
                        if hasattr(request, "cookies"):
                            session_id = request.cookies.get(config.SESSION_COOKIE_NAME)
                        if session_id:
                            redis_client.setex(f"online:{session_id}", 300, "1")  # 5-min TTL
                        # Cache online count for 30 seconds
                        now = _time.time()
                        if now - NotificationCountMiddleware._online_count_ts > 30:
                            keys = redis_client.keys("online:*")
                            NotificationCountMiddleware._online_count_cache = len(keys) if keys else 0
                            NotificationCountMiddleware._online_count_ts = now
                        request.state.online_count = NotificationCountMiddleware._online_count_cache
                except Exception:
                    pass

                user = request.session.get("user") if hasattr(request, "session") else None
                if user:
                    from models.database import SessionLocal
                    from services.notification import get_unread_count
                    from routes.messaging import get_unread_message_count
                    db = SessionLocal()
                    try:
                        request.state.notification_count = get_unread_count(user["id"], db)
                        request.state.unread_messages = get_unread_message_count(user["id"], db)
                        # Check admin status (ADMIN_ORCIDS or active editorial board member)
                        orcid_id = user.get("orcid_id", "")
                        if orcid_id in config.ADMIN_ORCIDS:
                            request.state.is_admin = True
                        else:
                            from models.editorial import EditorialBoardMember
                            board = db.query(EditorialBoardMember).filter(
                                EditorialBoardMember.user_id == user["id"],
                                EditorialBoardMember.is_active == True,
                            ).first()
                            if board:
                                request.state.is_admin = True
                    finally:
                        db.close()
        except Exception:
            pass
        return await call_next(request)

# Add security middlewares
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, requests_per_minute=300)
app.add_middleware(NotificationCountMiddleware)

# Add Redis session middleware (for horizontal scaling)
app.add_middleware(
    RedisSessionMiddleware,
    session_cookie=config.SESSION_COOKIE_NAME,
    max_age=config.SESSION_MAX_AGE,
    https_only=not config.DEBUG,
    same_site="lax"
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Set up Jinja2 templates
from template_helpers import register_filters
templates = Jinja2Templates(directory="templates")

# Register custom filters
templates.env = register_filters(templates.env)
templates.env.globals["app_name"] = config.APP_NAME

# Initialize database
@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    init_db()
    print(f"✓ Database initialized")
    print(f"✓ {config.APP_NAME} starting on {config.HOST}:{config.PORT}")

# Import and include routers
from routes import home, auth, papers, submit, issues, comments, delete, paper_votes, api, admin
from routes import endorsements, ai_review, human_review, extensions, prompts, rules, activity, notifications, messaging, search

app.include_router(home.router)
app.include_router(auth.router)
app.include_router(papers.router)
app.include_router(submit.router)
app.include_router(issues.router)
app.include_router(comments.router)
app.include_router(delete.router)
app.include_router(paper_votes.router)
app.include_router(api.router)
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(endorsements.router)
app.include_router(ai_review.router)
app.include_router(human_review.router)
app.include_router(extensions.router)
app.include_router(prompts.router)
app.include_router(rules.router)
app.include_router(activity.router)
app.include_router(notifications.router)
app.include_router(messaging.router)
app.include_router(search.router)

# Redirect legacy /discussion to /prompts
from fastapi.responses import RedirectResponse as _RedirectResponse

@app.get("/discussion")
async def discussion_redirect():
    return _RedirectResponse(url="/prompts", status_code=301)

@app.get("/discussion/{path:path}")
async def discussion_path_redirect(path: str):
    return _RedirectResponse(url="/prompts", status_code=301)

# robots.txt
from fastapi.responses import PlainTextResponse as _PlainTextResponse
from starlette.responses import FileResponse as _FileResponse

@app.get("/robots.txt", response_class=_PlainTextResponse)
async def robots_txt():
    """Serve robots.txt from project root."""
    import os
    path = os.path.join(config.BASE_DIR, "robots.txt")
    with open(path) as f:
        return _PlainTextResponse(f.read())

@app.get("/favicon.ico")
async def favicon_ico():
    """Serve favicon.ico (redirects to SVG for browsers that request /favicon.ico)."""
    return _FileResponse(
        os.path.join(config.BASE_DIR, "static", "images", "favicon.svg"),
        media_type="image/svg+xml",
    )

# Sitemap (dynamic — always reflects current papers)
from fastapi.responses import Response as _Response
from sqlalchemy.orm import Session as _Session
from models.database import get_db as _get_db

@app.get("/sitemap.xml")
async def sitemap_xml(db: _Session = Depends(_get_db)):
    """Generate sitemap.xml dynamically from the database."""
    from services.cache import CacheService
    from models.paper import Paper

    # Cache for 1 hour
    cached = CacheService.get("sitemap:xml")
    if cached:
        return _Response(content=cached, media_type="application/xml")

    base = "https://jaigp.org"
    urls = [
        (f"{base}/", "daily", "1.0"),
        (f"{base}/about", "weekly", "0.8"),
        (f"{base}/about/history", "weekly", "0.7"),
        (f"{base}/rules", "weekly", "0.8"),
        (f"{base}/issues", "daily", "0.7"),
        (f"{base}/prompts", "daily", "0.8"),
        (f"{base}/terms", "monthly", "0.3"),
        (f"{base}/privacy", "monthly", "0.3"),
    ]

    # Add all published papers
    papers = db.query(Paper).filter(
        Paper.status.in_(["published", "ai_screen_rejected"])
    ).order_by(Paper.published_date.desc()).all()

    for p in papers:
        lastmod = (p.updated_at or p.published_date).strftime("%Y-%m-%d") if p.published_date else ""
        urls.append((f"{base}/paper/{p.id}", "weekly", "0.6", lastmod))

    # Add browse year/month pages
    years = set()
    for p in papers:
        if p.published_date:
            years.add(p.published_date.year)
    for y in sorted(years, reverse=True):
        urls.append((f"{base}/issues/{y}", "weekly", "0.5"))

    # Build XML
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for entry in urls:
        loc, freq, priority = entry[0], entry[1], entry[2]
        lastmod = entry[3] if len(entry) > 3 else ""
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append(f"    <changefreq>{freq}</changefreq>")
        lines.append(f"    <priority>{priority}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")

    xml = "\n".join(lines)
    CacheService.set("sitemap:xml", xml, timeout=3600)  # 1 hour cache
    return _Response(content=xml, media_type="application/xml")


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "app": config.APP_NAME}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.DEBUG
    )
