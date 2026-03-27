# JAIGP - Journal for AI Generated Papers

> **https://jaigp.org** — Where humans and machines are welcomed.

## How This Journal Is Built

JAIGP is developed entirely through conversational prompting — a human operator instructs an AI coding assistant (Claude) via the command line, and the AI implements features, fixes bugs, and manages the infrastructure. Every prompt used to build and operate the journal is publicly archived at [jaigp.org/prompts?tab=archive](https://jaigp.org/prompts?tab=archive).

**This repository exists for:**
- **Reuse** — Anyone wanting to fork and run their own AI-generated paper journal
- **Archival & backup** — A permanent record of the codebase at each milestone

The live site at jaigp.org is deployed directly from the server, not from this repository. Changes flow: human prompt → AI implementation → server → periodic push to GitHub.

---

## Features

- **5-Stage Review Pipeline** — Screening → Endorsement → AI Review (Reviewer3.com) → Human Peer Review → Acceptance
- **ORCID Authentication** — All users identified by their academic ORCID iD
- **Community Feed** — Unified social feed for prompts, rules, and comments with voting
- **AI Summarization** — Claude Haiku 4.5 summaries of the archive and community feed
- **In-App Notifications** — Bell icon with unread count for replies, votes, endorsements
- **Badge System** — Gold/Silver/Bronze/Copper/New based on ORCID publication count
- **Open Prompt Archive** — Every building prompt archived and searchable, updated every minute
- **Terms Consent** — Explicit terms acceptance on first login with audit trail

## Technology Stack

- **Backend**: FastAPI + Python 3.12
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Frontend**: Jinja2 templates + Tailwind CSS (CDN) + HTMX
- **Session**: Redis-backed for horizontal scaling (3 Uvicorn workers)
- **AI Services**: Anthropic Claude (screening, summarization), Reviewer3.com (AI peer review)
- **Authentication**: ORCID OAuth 2.0
- **Server**: Nginx reverse proxy → 3 Uvicorn instances

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

MIT License. See [LICENSE](LICENSE) for details.

## About

JAIP pioneers a new frontier in scientific publishing by providing a dedicated platform for AI-generated research papers. We foster collaboration between human prompters and AI systems while maintaining transparency about AI's role in research generation.

### Our Mission
To create a collaborative platform where human prompters and AI systems work together to advance knowledge, while maintaining transparency about the nature of AI-generated content.

### Our Motto
"We are not sure if these papers are good, after all, we are only human."

This motto reflects our humble acknowledgment that evaluating AI-generated research is new territory for all of us. We don't pretend to have all the answers. Instead, we're building a community to explore these questions together.

---

Built with FastAPI, Tailwind CSS, and HTMX.
