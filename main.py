"""Main FastAPI application for JAIGP - Journal for AI Generated Papers."""
from fastapi import FastAPI, Request
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
    debug=config.DEBUG
)

# Add security middlewares
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, requests_per_minute=120)

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
