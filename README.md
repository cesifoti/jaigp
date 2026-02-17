# JAIP - The Journal for AI Generated Papers

> "We are not sure if these papers are good, after all, we are only human."

A scientific journal platform dedicated to AI-generated research papers, fostering collaboration between human prompters and AI systems.

## Features

### Core Functionality
- ✅ **ORCID Authentication** - Secure login via ORCID OAuth 2.0
- ✅ **Paper Submission** - Upload PDFs with metadata and cover images
- ✅ **Dual Authorship** - Support for both human prompters and AI co-authors
- ✅ **Version Control** - Maximum 1 version per day with change logs
- ✅ **Date-based Storage** - Files organized as `/YYYY/Month/DD/`
- ✅ **Comment System** - Threaded comments with upvote/downvote
- ✅ **Issues Navigation** - Browse papers by year/month/day
- ✅ **Field Classification** - OpenAlex-powered research field suggestions
- ✅ **Mobile Responsive** - Beautiful design optimized for all devices
- ✅ **PDF Viewing** - Embedded viewer that works on mobile

## Technology Stack

- **Backend**: FastAPI + Python 3.12
- **Database**: SQLite (migration path to PostgreSQL available)
- **Frontend**: Jinja2 templates + Tailwind CSS + HTMX
- **Server**: Uvicorn (port 8002, 3 workers)
- **Authentication**: ORCID OAuth 2.0
- **File Storage**: Date-based filesystem structure

## Project Structure

```
/var/www/ai_journal/
├── main.py                 # FastAPI application entry
├── config.py               # Configuration settings
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables
├── models/                 # Database models
│   ├── database.py        # Database setup
│   ├── user.py            # User model
│   ├── paper.py           # Paper models
│   └── comment.py         # Comment models
├── routes/                 # API routes
│   ├── home.py            # Homepage and about
│   ├── auth.py            # ORCID OAuth
│   ├── papers.py          # Paper viewing
│   ├── submit.py          # Paper submission
│   ├── issues.py          # Date navigation
│   └── comments.py        # Comment system
├── services/              # Business logic
│   ├── orcid.py           # ORCID integration
│   ├── openalex.py        # OpenAlex integration
│   ├── file_storage.py    # File management
│   └── pdf_handler.py     # PDF processing
├── templates/             # HTML templates
├── static/                # CSS, JS, images
└── data/                  # Database and uploaded files
```

## Quick Start

### Prerequisites
- Python 3.12+
- ORCID Developer Account (for OAuth credentials)

### Installation

1. **Clone or navigate to the project**:
```bash
cd /var/www/ai_journal
```

2. **Create virtual environment** (if not already created):
```bash
python3 -m venv venv
source venv/bin/activate
```

3. **Install dependencies** (if not already installed):
```bash
pip install -r requirements.txt
```

4. **Configure environment variables**:
```bash
# Copy example and edit
cp .env.example .env
nano .env
```

Required settings:
- `SECRET_KEY` - Generate with: `openssl rand -hex 32`
- `ORCID_CLIENT_ID` - Get from https://orcid.org/developer-tools
- `ORCID_CLIENT_SECRET` - Get from ORCID developer tools
- `OPENALEX_API_EMAIL` - Your email for polite API usage

5. **Initialize database** (if not already initialized):
```bash
python -c "from models.database import init_db; init_db()"
```

6. **Run the application**:
```bash
python main.py
```

The application will be available at `http://localhost:8002`

## ORCID Setup

To enable authentication, you need to register an ORCID application:

1. Go to https://orcid.org/developer-tools
2. Create a new application
3. Set redirect URI to: `http://localhost:8002/auth/callback` (development) or `https://yourdomain.com/auth/callback` (production)
4. Copy Client ID and Client Secret to `.env`

## Database Schema

### Tables
- **users** - ORCID-authenticated users
- **papers** - Core paper metadata
- **paper_versions** - Version history (max 1/day)
- **paper_human_authors** - Human prompters
- **paper_ai_authors** - AI co-authors
- **paper_fields** - OpenAlex classification
- **comments** - Paper comments
- **comment_votes** - Upvote/downvote system

## API Endpoints

### Navigation
- `GET /` - Homepage
- `GET /about` - About page
- `GET /issues` - Browse by year
- `GET /issues/{year}` - Browse by month
- `GET /issues/{year}/{month}` - Browse by day
- `GET /issues/{year}/{month}/{day}` - Papers for date

### Authentication
- `GET /auth/login` - ORCID login
- `GET /auth/callback` - OAuth callback
- `GET /auth/logout` - Logout
- `GET /auth/profile` - User profile

### Papers
- `GET /paper/{id}` - Paper detail page
- `GET /paper/{id}/pdf` - Serve PDF
- `GET /paper/{id}/image` - Serve cover image
- `GET /paper/{id}/versions` - Version history

### Submission
- `GET /submit` - Submission form
- `POST /submit` - Submit new paper
- `GET /submit/{id}/update` - Update form
- `POST /submit/{id}/update` - Submit new version

### Comments
- `POST /paper/{id}/comment` - Add comment
- `POST /comment/{id}/vote` - Vote on comment

## File Storage

Files are organized in a date-based structure:

```
/data/papers/{YYYY}/{Month}/{DD}/
  - paper-{id}-v{version}.pdf
  - paper-{id}-image.{jpg|png}
```

Example:
```
/data/papers/2026/February/14/
  - paper-1-v1.pdf
  - paper-1-v2.pdf
  - paper-1-image.jpg
```

## Version Control

- Papers can have multiple versions
- **Maximum 1 version per day** per paper
- Each version requires a change log
- Previous versions remain accessible
- PDF files are immutable once uploaded

## Development

### Running in Development Mode

```bash
# Activate virtual environment
source venv/bin/activate

# Run with auto-reload
python main.py
```

Debug mode is enabled when `DEBUG=True` in `.env`.

### Running Tests

```bash
pytest
```

### Code Formatting

```bash
black .
```

## Deployment

See `DEPLOYMENT.md` for production deployment instructions including:
- Systemd service configuration
- Nginx reverse proxy setup
- SSL certificate installation
- Production environment variables

## Security Considerations

- ORCID OAuth with CSRF protection (state parameter)
- Secure session cookies (HTTPOnly, Secure, SameSite)
- File upload validation (type, size, structure)
- SQL injection prevention (SQLAlchemy ORM)
- XSS prevention (Jinja2 auto-escaping)
- Access control (only authors can update papers)
- Rate limiting (1 version per day)

## Contributing

This is a custom-built application for a specific use case. For issues or suggestions, please contact the administrator.

## License

All rights reserved.

## About

JAIP pioneers a new frontier in scientific publishing by providing a dedicated platform for AI-generated research papers. We foster collaboration between human prompters and AI systems while maintaining transparency about AI's role in research generation.

### Our Mission
To create a collaborative platform where human prompters and AI systems work together to advance knowledge, while maintaining transparency about the nature of AI-generated content.

### Our Motto
"We are not sure if these papers are good, after all, we are only human."

This motto reflects our humble acknowledgment that evaluating AI-generated research is new territory for all of us. We don't pretend to have all the answers. Instead, we're building a community to explore these questions together.

---

Built with FastAPI, Tailwind CSS, and HTMX.
