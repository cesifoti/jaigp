"""Configuration settings for JAIGP application."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Base directory
BASE_DIR = Path(__file__).resolve().parent

# Application settings
APP_NAME = os.getenv("APP_NAME", "JAIGP - Journal for AI Generated Papers")
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8002")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/data/jaigp.db")

# ORCID OAuth
ORCID_CLIENT_ID = os.getenv("ORCID_CLIENT_ID", "")
ORCID_CLIENT_SECRET = os.getenv("ORCID_CLIENT_SECRET", "")
ORCID_REDIRECT_URI = os.getenv("ORCID_REDIRECT_URI", f"{BASE_URL}/auth/callback")
ORCID_AUTH_URL = os.getenv("ORCID_AUTH_URL", "https://orcid.org/oauth/authorize")
ORCID_TOKEN_URL = os.getenv("ORCID_TOKEN_URL", "https://orcid.org/oauth/token")
ORCID_API_URL = os.getenv("ORCID_API_URL", "https://pub.orcid.org/v3.0")

# OpenAlex
OPENALEX_API_EMAIL = os.getenv("OPENALEX_API_EMAIL", "")
OPENALEX_API_URL = os.getenv("OPENALEX_API_URL", "https://api.openalex.org")

# File Storage
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
PAPERS_DIR = DATA_DIR / "papers"
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "20"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_PDF_TYPES = os.getenv("ALLOWED_PDF_TYPES", "application/pdf").split(",")
ALLOWED_IMAGE_TYPES = os.getenv("ALLOWED_IMAGE_TYPES", "image/jpeg,image/png,image/jpg").split(",")

# Server
PORT = int(os.getenv("PORT", "8002"))
WORKERS = int(os.getenv("WORKERS", "3"))
HOST = os.getenv("HOST", "127.0.0.1")

# Session
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", "86400"))  # 24 hours
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "jaigp_session")

# Admin
ADMIN_ORCIDS = os.getenv("ADMIN_ORCIDS", "0000-0002-6977-9492").split(",")

# Email (for verification)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "noreply@jaigp.org")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "JAIGP - Journal for AI Generated Papers")

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
PAPERS_DIR.mkdir(parents=True, exist_ok=True)
