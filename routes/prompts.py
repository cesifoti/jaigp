"""Open Prompt routes — archive of building prompts and community suggestions."""
import json
import os
import glob
from fastapi import APIRouter, Request, Depends, HTTPException, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters
from sqlalchemy.orm import Session
from sqlalchemy import func
from models.database import get_db
from models.prompt import CommunityPrompt, PromptComment, PromptCommentVote, PromptVote
from models.user import User
from datetime import datetime
from services.notification import create_notification

router = APIRouter(tags=["prompts"])
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)

CONVERSATIONS_SRC = "/root/.claude/projects/-var-www-ai-journal"
CONVERSATIONS_DIR = "/var/www/ai_journal/data/conversations"

# Prefixes that indicate system-generated messages, not human input
SYSTEM_PREFIXES = (
    "<task-notification>",
    "<local-command-caveat>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<command-name>",
    "<user-prompt-submit-hook>",
    "[Request interrupted",
    "This session is being continued from a previous conversation",
    "Implement the following plan",
)

# Load archive once at module level
_archive_cache = None
_archive_mtime = 0


def _load_archive():
    global _archive_cache, _archive_mtime
    archive_path = os.path.join(os.path.dirname(__file__), "..", "data", "prompts_archive.json")
    archive_path = os.path.normpath(archive_path)
    try:
        mtime = os.path.getmtime(archive_path)
        if _archive_cache is None or mtime > _archive_mtime:
            with open(archive_path) as f:
                _archive_cache = json.load(f)
            _archive_mtime = mtime
    except FileNotFoundError:
        _archive_cache = {"sessions": [], "total_prompts": 0, "total_sessions": 0}
    return _archive_cache



def _get_all_archive_prompts():
    """Get a flat list of all archive prompts, ordered by global_index."""
    archive = _load_archive()
    prompts = []
    for session in archive.get("sessions", []):
        for p in session.get("prompts", []):
            prompts.append({
                "text": p["text"],
                "timestamp": p.get("timestamp", ""),
                "global_index": p["global_index"],
                "session_title": session["title"],
                "prompt_type": p.get("prompt_type", "key"),
            })
    prompts.sort(key=lambda p: p["global_index"])
    return prompts


def _get_prompt_at_index(index=None):
    """Get a prompt by global_index (1-based). None = last prompt.

    Returns dict with text, timestamp, global_index, total, has_prev, has_next.
    """
    prompts = _get_all_archive_prompts()
    if not prompts:
        return None

    total = len(prompts)

    if index is None or index > total:
        index = total
    if index < 1:
        index = 1

    p = prompts[index - 1]

    # Trim to ~100 words for display
    words = p["text"].split()
    full_length = len(words)
    display_text = " ".join(words[:100]) + "..." if full_length > 100 else p["text"]

    return {
        "text": display_text,
        "timestamp": p["timestamp"],
        "full_length": full_length,
        "global_index": p["global_index"],
        "session_title": p["session_title"],
        "total": total,
        "has_prev": index > 1,
        "has_next": index < total,
    }


def require_auth(request: Request):
    """Require ORCID authentication."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


@router.post("/prompts/summarize/archive", response_class=HTMLResponse)
async def summarize_archive(
    request: Request,
    db: Session = Depends(get_db),
):
    """Generate AI summary of the most recent archive prompts."""
    from services.summarizer import summarize_archive_prompts
    all_prompts = _get_all_archive_prompts()
    if not all_prompts:
        return HTMLResponse('<p class="text-sm text-slate-500 italic">No archive prompts to summarize.</p>')
    recent = all_prompts[-50:]
    count = len(recent)
    combined = "\n---\n".join(p["text"][:200] for p in recent)
    try:
        summary = await summarize_archive_prompts(combined, count)
    except Exception as e:
        return HTMLResponse(f'<p class="text-sm text-red-500">Summarization failed: {e}</p>')
    return templates.TemplateResponse(
        "components/summary_card.html",
        {"request": request, "summary": summary, "count": count, "label": "prompts"},
    )


@router.post("/prompts/summarize/community", response_class=HTMLResponse)
async def summarize_community(
    request: Request,
    db: Session = Depends(get_db),
):
    """Generate AI summary of the community feed — posts and their replies."""
    from services.summarizer import summarize_community_prompts
    from models.prompt import CommunityPrompt
    posts = db.query(CommunityPrompt).order_by(CommunityPrompt.created_at.desc()).limit(30).all()
    if not posts:
        return HTMLResponse('<p class="text-sm text-slate-500 italic">No posts to summarize.</p>')
    count = len(posts)
    type_labels = {"prompt": "Prompt", "rule": "Rule", "comment": "Comment"}
    # Build threaded text: each post + all replies with engagement signals
    parts = []
    for p in posts:
        votes_info = f" [{p.net_votes:+d} votes]" if p.net_votes else ""
        thread = f"[{type_labels.get(p.post_type, 'Post')}]{votes_info} {p.prompt_text}"
        if p.comments:
            for r in sorted(p.comments, key=lambda c: c.created_at):
                rv = f" [{r.net_votes:+d}]" if r.net_votes else ""
                thread += f"\n  Reply by {r.user.name}{rv}: {r.content}"
        parts.append(thread)
    combined = "\n---\n".join(parts)
    try:
        summary = await summarize_community_prompts(combined, count)
    except Exception as e:
        return HTMLResponse(f'<p class="text-sm text-red-500">Summarization failed: {e}</p>')
    return templates.TemplateResponse(
        "components/summary_card.html",
        {"request": request, "summary": summary, "count": count, "label": "posts"},
    )


@router.get("/prompts/feed", response_class=HTMLResponse)
async def prompts_feed(
    request: Request,
    before_id: int = Query(None),
    after_id: int = Query(None),
    db: Session = Depends(get_db),
):
    """Cursor-based feed for community prompts."""
    user = request.session.get("user")
    query = db.query(CommunityPrompt)

    if before_id:
        query = query.filter(CommunityPrompt.id < before_id)
    elif after_id:
        query = query.filter(CommunityPrompt.id > after_id)

    prompts = query.order_by(CommunityPrompt.created_at.desc()).limit(20).all()

    user_votes = {}
    if user:
        pids = [p.id for p in prompts]
        if pids:
            votes = db.query(PromptVote).filter(
                PromptVote.prompt_id.in_(pids),
                PromptVote.user_id == user["id"],
            ).all()
            user_votes = {v.prompt_id: v.vote_type for v in votes}

    preview_comments = {
        p.id: max(p.comments, key=lambda c: (c.net_votes, -c.created_at.timestamp()))
        for p in prompts if p.comments
    }

    # Follow data for feed fragments
    user_following = set()
    if user:
        from models.discussion import UserFollow
        follows = db.query(UserFollow.followed_id).filter(UserFollow.follower_id == user["id"]).all()
        user_following = {f[0] for f in follows}

    html_parts = []
    for prompt in prompts:
        html_parts.append(
            templates.get_template("components/prompt_card.html").render(
                prompt=prompt, user=user, user_votes=user_votes, is_new=False,
                request=request, preview_comments=preview_comments, user_following=user_following
            )
        )
    return HTMLResponse("".join(html_parts))


@router.get("/prompts/feed/count")
async def prompts_feed_count(
    after_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Count of new community prompts since after_id."""
    count = db.query(CommunityPrompt).filter(CommunityPrompt.id > after_id).count()
    return JSONResponse({"count": count})


@router.get("/prompts/{prompt_id}", response_class=HTMLResponse)
async def prompt_detail(
    prompt_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Individual prompt permalink page."""
    prompt = db.query(CommunityPrompt).filter(CommunityPrompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    user = request.session.get("user")
    user_vote = None
    comment_votes = {}
    user_following = set()

    if user:
        vote = db.query(PromptVote).filter(
            PromptVote.prompt_id == prompt_id,
            PromptVote.user_id == user["id"],
        ).first()
        user_vote = vote.vote_type if vote else None

        # Comment votes for the current user
        cids = [c.id for c in prompt.comments]
        if cids:
            cv = db.query(PromptCommentVote).filter(
                PromptCommentVote.comment_id.in_(cids),
                PromptCommentVote.user_id == user["id"],
            ).all()
            comment_votes = {v.comment_id: v.vote_type for v in cv}

        # Follow data
        from models.discussion import UserFollow
        follows = db.query(UserFollow.followed_id).filter(UserFollow.follower_id == user["id"]).all()
        user_following = {f[0] for f in follows}

    related_posts = []

    return templates.TemplateResponse(
        "prompt_detail.html",
        {
            "request": request,
            "user": user,
            "prompt": prompt,
            "user_vote": user_vote,
            "comment_votes": comment_votes,
            "user_following": user_following,
            "related_posts": related_posts,
        },
    )


@router.get("/prompts.json")
async def prompts_json(request: Request):
    """Machine-readable JSON of all human prompts used to build JAIGP. Requires ORCID login."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Sign in with ORCID to access the prompt archive")
    archive = _load_archive()
    return JSONResponse(
        content=archive,
        headers={"Content-Disposition": "attachment; filename=jaigp-prompts.json"},
    )


@router.get("/prompts/download")
async def prompts_download(request: Request):
    """Download all human prompts as a JSON file. Requires ORCID login."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Sign in with ORCID to access the prompt archive")
    archive = _load_archive()
    return JSONResponse(
        content=archive,
        headers={"Content-Disposition": "attachment; filename=jaigp-prompts.json"},
    )


@router.get("/prompts", response_class=HTMLResponse)
async def prompts_page(
    request: Request,
    tab: str = Query("community", regex="^(archive|community)$"),
    sort: str = Query("newest", regex="^(newest|top|controversial|divisive)$"),
    type: str = Query("", regex="^(prompt|rule|comment|)$"),
    ptype: str = Query("", regex="^(key|procedural|)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=5, le=100),
    q: str = Query(""),
    db: Session = Depends(get_db),
):
    """Open Prompt page — community suggestions (default) and archive."""
    user = request.session.get("user")

    # Archive tab requires ORCID login
    if tab == "archive" and not user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/auth/login", status_code=303)

    archive = _load_archive()

    filter_type = type if type else ""

    # Community prompts — initial load (20 newest for feed)
    base_query = db.query(CommunityPrompt)
    if filter_type:
        base_query = base_query.filter(CommunityPrompt.post_type == filter_type)

    community_prompts = (
        base_query
        .order_by(CommunityPrompt.created_at.desc())
        .limit(20)
        .all()
    )

    # Apply computed sorts for non-default sorts (loads all for proper ranking)
    if sort != "newest":
        community_prompts = base_query.all()
        if sort == "top":
            community_prompts.sort(key=lambda p: p.net_votes, reverse=True)
        elif sort == "controversial":
            community_prompts.sort(key=lambda p: p.total_votes, reverse=True)
        elif sort == "divisive":
            community_prompts.sort(key=lambda p: (p.divisiveness, p.total_votes), reverse=True)
        community_prompts = community_prompts[:20]

    total_community = db.query(CommunityPrompt).count()

    newest_prompt_id = community_prompts[0].id if community_prompts else 0
    oldest_prompt_id = community_prompts[-1].id if community_prompts else 0
    has_more_prompts = len(community_prompts) == 20

    # Get user's follow list (for follow buttons on cards)
    user_following = set()
    if user:
        from models.discussion import UserFollow
        follows = db.query(UserFollow.followed_id).filter(UserFollow.follower_id == user["id"]).all()
        user_following = {f[0] for f in follows}

    # Get user's votes on visible prompts
    user_votes = {}
    if user:
        prompt_ids = [p.id for p in community_prompts]
        if prompt_ids:
            votes = db.query(PromptVote).filter(
                PromptVote.prompt_id.in_(prompt_ids),
                PromptVote.user_id == user["id"],
            ).all()
            user_votes = {v.prompt_id: v.vote_type for v in votes}

    # Pre-compute archive summary (last 100 prompts).
    # Refreshes every 20 new prompts: stores the total count at summary time
    # in Redis and only regenerates when 20+ new prompts have appeared.
    archive_summary = None
    archive_summary_count = 0
    try:
        from services.summarizer import summarize_archive_prompts
        from services.cache import CacheService
        all_archive = _get_all_archive_prompts()
        if all_archive:
            total_now = len(all_archive)
            recent = all_archive[-100:]
            archive_summary_count = len(recent)

            # Check if we have a cached summary and when it was generated
            cached_meta = CacheService.get("summary:archive:meta")
            cached_summary = CacheService.get("summary:archive:latest")

            needs_refresh = True
            if cached_meta and cached_summary:
                last_count = cached_meta.get("total_prompts", 0)
                if total_now < last_count + 20:
                    # Not enough new prompts — use cached
                    archive_summary = cached_summary
                    needs_refresh = False

            if needs_refresh:
                combined = "\n---\n".join(p["text"][:200] for p in recent)
                archive_summary = await summarize_archive_prompts(combined, archive_summary_count)
                # Store the summary and the count at generation time
                CacheService.set("summary:archive:latest", archive_summary, timeout=604800)  # 7 days
                CacheService.set("summary:archive:meta", {"total_prompts": total_now}, timeout=604800)
                # Persist to DB for permanent archive
                try:
                    from sqlalchemy import text as sa_text
                    db.execute(
                        sa_text(
                            "INSERT INTO archive_summaries (summary_text, prompt_count, total_prompts_at_generation, model) "
                            "VALUES (:text, :count, :total, :model)"
                        ),
                        {"text": archive_summary, "count": archive_summary_count, "total": total_now, "model": "claude-haiku-4-5-20251001"},
                    )
                    db.commit()
                    print(f"[archive-summary] Persisted summary ({total_now} prompts)")
                except Exception as e:
                    print(f"[archive-summary] DB persist failed: {e}")
                    db.rollback()
    except Exception:
        pass  # gracefully degrade — page still renders without summary

    # Archive tab: flat reverse-chronological list with pagination + search
    archive_prompts = []
    archive_total = 0
    archive_total_pages = 1
    search_query = q.strip()
    prompt_type_filter = ptype if ptype else ""
    if tab == "archive":
        all_archive = _get_all_archive_prompts()
        # Reverse chronological (newest first)
        all_archive = list(reversed(all_archive))
        # Filter by prompt type (key vs procedural)
        if prompt_type_filter:
            all_archive = [p for p in all_archive if p.get("prompt_type") == prompt_type_filter]
        # Filter by search query
        if search_query:
            all_archive = [
                p for p in all_archive
                if search_query.lower() in p["text"].lower()
            ]
        archive_total = len(all_archive)
        archive_total_pages = max(1, (archive_total + per_page - 1) // per_page)
        if page > archive_total_pages:
            page = archive_total_pages
        start = (page - 1) * per_page
        archive_prompts = all_archive[start:start + per_page]

    return templates.TemplateResponse(
        "prompts.html",
        {
            "request": request,
            "user": user,
            "tab": tab,
            "sort": sort,
            "archive": archive,
            "community_prompts": community_prompts,
            "user_votes": user_votes,
            "total_community": total_community,
            "newest_prompt_id": newest_prompt_id,
            "oldest_prompt_id": oldest_prompt_id,
            "has_more_prompts": has_more_prompts,
            "archive_summary": archive_summary,
            "archive_summary_count": archive_summary_count,
            "archive_prompts": archive_prompts,
            "archive_total": archive_total,
            "archive_total_pages": archive_total_pages,
            "archive_page": page,
            "archive_per_page": per_page,
            "filter_type": filter_type,
            "prompt_type_filter": prompt_type_filter,
            "search_query": search_query,
            "preview_comments": {
                p.id: max(p.comments, key=lambda c: (c.net_votes, -c.created_at.timestamp()))
                for p in community_prompts if p.comments
            },
            "user_following": user_following,
        },
    )



@router.post("/prompts/suggest", response_class=HTMLResponse)
async def suggest_prompt(
    request: Request,
    prompt_text: str = Form(...),
    post_type: str = Form("comment"),
    db: Session = Depends(get_db),
):
    """Submit a new community post (prompt, rule, or comment)."""
    user = require_auth(request)

    prompt_text = prompt_text.strip()
    if post_type not in ("prompt", "rule", "comment"):
        post_type = "comment"

    min_len = 10 if post_type == "comment" else 20
    if not prompt_text or len(prompt_text) < min_len:
        raise HTTPException(status_code=400, detail=f"Post must be at least {min_len} characters")
    if len(prompt_text) > 5000:
        raise HTTPException(status_code=400, detail="Post must be 5000 characters or fewer")

    # Auto-generate title from first line/sentence
    first_line = prompt_text.split("\n")[0][:80]
    title = (first_line + "...") if len(first_line) >= 80 else first_line

    prompt = CommunityPrompt(
        user_id=user["id"],
        title=title,
        prompt_text=prompt_text,
        post_type=post_type,
        created_at=datetime.utcnow(),
    )
    db.add(prompt)
    db.commit()

    # Return the new prompt card as HTML (for HTMX)
    db.refresh(prompt)

    return templates.TemplateResponse(
        "components/prompt_card.html",
        {
            "request": request,
            "prompt": prompt,
            "user": user,
            "user_votes": {},
            "preview_comments": {},
            "user_following": set(),
            "is_new": True,
        },
    )


@router.post("/prompts/{prompt_id}/vote")
async def vote_prompt(
    prompt_id: int,
    request: Request,
    vote_type: str = Form(...),
    db: Session = Depends(get_db),
):
    """Vote on a community prompt."""
    user = require_auth(request)

    prompt = db.query(CommunityPrompt).filter(CommunityPrompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    if vote_type not in ("upvote", "downvote"):
        raise HTTPException(status_code=400, detail="Invalid vote type")

    existing = db.query(PromptVote).filter(
        PromptVote.prompt_id == prompt_id,
        PromptVote.user_id == user["id"],
    ).first()

    toggled_off = False
    if existing:
        if existing.vote_type == vote_type:
            db.delete(existing)  # Toggle off
            toggled_off = True
        else:
            existing.vote_type = vote_type  # Switch vote
    else:
        vote = PromptVote(
            prompt_id=prompt_id,
            user_id=user["id"],
            vote_type=vote_type,
            created_at=datetime.utcnow(),
        )
        db.add(vote)

    db.commit()
    db.refresh(prompt)

    if not toggled_off:
        create_notification(
            user_id=prompt.user_id, notification_type="prompt_vote",
            link=f"/prompts/{prompt_id}", db=db,
            source_user_id=user["id"],
            content_preview=f"{'liked' if vote_type == 'upvote' else 'disliked'} your prompt",
        )
        db.commit()

    current_vote = db.query(PromptVote).filter(
        PromptVote.prompt_id == prompt_id,
        PromptVote.user_id == user["id"],
    ).first()

    return JSONResponse({
        "success": True,
        "upvotes": prompt.upvote_count,
        "downvotes": prompt.downvote_count,
        "net_votes": prompt.net_votes,
        "user_vote": current_vote.vote_type if current_vote else None,
    })


@router.post("/prompts/{prompt_id}/comment", response_class=HTMLResponse)
async def add_prompt_comment(
    prompt_id: int,
    request: Request,
    content: str = Form(...),
    db: Session = Depends(get_db),
):
    """Add a comment to a community prompt."""
    user = require_auth(request)
    content = content.strip()

    if not content or len(content) < 2:
        raise HTTPException(status_code=400, detail="Comment too short")
    if len(content) > 2000:
        raise HTTPException(status_code=400, detail="Comment must be 2000 characters or fewer")

    prompt = db.query(CommunityPrompt).filter(CommunityPrompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    comment = PromptComment(
        prompt_id=prompt_id,
        user_id=user["id"],
        content=content,
        created_at=datetime.utcnow(),
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    create_notification(
        user_id=prompt.user_id, notification_type="prompt_comment",
        link=f"/prompts/{prompt_id}#pcomment-{comment.id}", db=db,
        source_user_id=user["id"], content_preview=content[:150],
    )
    db.commit()

    return templates.TemplateResponse(
        "components/prompt_comment.html",
        {"request": request, "comment": comment, "user": user, "comment_votes": {}, "is_new": True},
    )


@router.get("/prompts/{prompt_id}/comments", response_class=HTMLResponse)
async def get_prompt_comments(
    prompt_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get all comments for a prompt."""
    user = request.session.get("user")
    prompt = db.query(CommunityPrompt).filter(CommunityPrompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    comment_votes = {}
    if user:
        cids = [c.id for c in prompt.comments]
        if cids:
            cv = db.query(PromptCommentVote).filter(
                PromptCommentVote.comment_id.in_(cids),
                PromptCommentVote.user_id == user["id"],
            ).all()
            comment_votes = {v.comment_id: v.vote_type for v in cv}

    return templates.TemplateResponse(
        "components/prompt_comments_list.html",
        {"request": request, "prompt": prompt, "user": user, "comment_votes": comment_votes},
    )


@router.post("/prompts/comment/{comment_id}/vote")
async def vote_prompt_comment(
    comment_id: int,
    request: Request,
    vote_type: str = Form(...),
    db: Session = Depends(get_db),
):
    """Vote on a prompt comment."""
    user = require_auth(request)
    comment = db.query(PromptComment).filter(PromptComment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404)
    if vote_type not in ("upvote", "downvote"):
        raise HTTPException(status_code=400)

    existing = db.query(PromptCommentVote).filter(
        PromptCommentVote.comment_id == comment_id,
        PromptCommentVote.user_id == user["id"],
    ).first()

    toggled_off = False
    if existing:
        if existing.vote_type == vote_type:
            db.delete(existing)
            toggled_off = True
        else:
            existing.vote_type = vote_type
    else:
        db.add(PromptCommentVote(
            comment_id=comment_id, user_id=user["id"],
            vote_type=vote_type, created_at=datetime.utcnow(),
        ))

    db.commit()
    db.refresh(comment)

    if not toggled_off:
        create_notification(
            user_id=comment.user_id, notification_type="prompt_comment_vote",
            link=f"/prompts/{comment.prompt_id}", db=db,
            source_user_id=user["id"],
            content_preview=f"{'liked' if vote_type == 'upvote' else 'disliked'} your comment",
        )
        db.commit()

    cv = db.query(PromptCommentVote).filter(
        PromptCommentVote.comment_id == comment_id,
        PromptCommentVote.user_id == user["id"],
    ).first()

    return JSONResponse({
        "success": True, "net_votes": comment.net_votes,
        "upvotes": comment.upvote_count, "downvotes": comment.downvote_count,
        "user_vote": cv.vote_type if cv else None,
    })


@router.post("/prompts/{prompt_id}/edit")
async def edit_prompt(
    prompt_id: int,
    request: Request,
    content: str = Form(...),
    db: Session = Depends(get_db),
):
    """Edit a community post (author only, within 1 hour)."""
    user = require_auth(request)
    prompt = db.query(CommunityPrompt).filter(CommunityPrompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404)
    if prompt.user_id != user["id"]:
        raise HTTPException(status_code=403, detail="Only the author can edit this post")
    # 1-hour edit window
    from datetime import timedelta
    if datetime.utcnow() - prompt.created_at > timedelta(hours=1):
        raise HTTPException(status_code=403, detail="Posts can only be edited within the first hour")
    content = content.strip()
    if not content or len(content) < 2:
        raise HTTPException(status_code=400, detail="Content too short")
    prompt.prompt_text = content
    prompt.title = (content.split("\n")[0][:80] + "...") if len(content.split("\n")[0]) >= 80 else content.split("\n")[0][:80]
    prompt.edited_at = datetime.utcnow()
    db.commit()
    return JSONResponse({"success": True, "content": content})


@router.post("/prompts/comment/{comment_id}/edit")
async def edit_prompt_comment(
    comment_id: int,
    request: Request,
    content: str = Form(...),
    db: Session = Depends(get_db),
):
    """Edit a comment (author only, within 1 hour)."""
    user = require_auth(request)
    comment = db.query(PromptComment).filter(PromptComment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404)
    if comment.user_id != user["id"]:
        raise HTTPException(status_code=403, detail="Only the author can edit this comment")
    from datetime import timedelta
    if datetime.utcnow() - comment.created_at > timedelta(hours=1):
        raise HTTPException(status_code=403, detail="Comments can only be edited within the first hour")
    content = content.strip()
    if not content or len(content) < 2:
        raise HTTPException(status_code=400, detail="Content too short")
    comment.content = content
    comment.edited_at = datetime.utcnow()
    db.commit()
    return JSONResponse({"success": True, "content": content})


@router.post("/prompts/{prompt_id}/delete")
async def delete_prompt(
    prompt_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Delete a community prompt (author only)."""
    user = require_auth(request)
    prompt = db.query(CommunityPrompt).filter(CommunityPrompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404)
    if prompt.user_id != user["id"]:
        raise HTTPException(status_code=403, detail="Only the author can delete this prompt")
    db.delete(prompt)
    db.commit()
    return JSONResponse({"success": True})


@router.post("/prompts/comment/{comment_id}/delete")
async def delete_prompt_comment(
    comment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Delete a prompt comment (author only)."""
    user = require_auth(request)
    comment = db.query(PromptComment).filter(PromptComment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404)
    if comment.user_id != user["id"]:
        raise HTTPException(status_code=403, detail="Only the author can delete this comment")
    db.delete(comment)
    db.commit()
    return JSONResponse({"success": True})


@router.post("/user/{user_id}/follow")
async def follow_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Follow or unfollow a user."""
    from models.discussion import UserFollow
    current_user = require_auth(request)

    if current_user["id"] == user_id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    existing = db.query(UserFollow).filter(
        UserFollow.follower_id == current_user["id"],
        UserFollow.followed_id == user_id,
    ).first()

    if existing:
        db.delete(existing)
        db.commit()
        following = False
    else:
        follow = UserFollow(
            follower_id=current_user["id"],
            followed_id=user_id,
            created_at=datetime.utcnow(),
        )
        db.add(follow)
        db.commit()
        following = True

    follower_count = db.query(UserFollow).filter(UserFollow.followed_id == user_id).count()
    return JSONResponse({"success": True, "following": following, "follower_count": follower_count})
