"""Direct messaging routes."""
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_, case
from models.database import get_db
from models.user import User
from models.message import DirectMessage
from models.discussion import UserFollow
from services.notification import create_notification
from datetime import datetime

router = APIRouter(tags=["messaging"])
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)


def require_auth(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def can_message(sender_id: int, recipient_id: int, db: Session) -> bool:
    """Check if sender can message recipient."""
    if sender_id == recipient_id:
        return False
    recipient = db.query(User).filter(User.id == recipient_id).first()
    if not recipient:
        return False
    if recipient.open_to_messaging:
        return True
    # Check mutual follow
    a_follows_b = db.query(UserFollow).filter(
        UserFollow.follower_id == sender_id,
        UserFollow.followed_id == recipient_id,
    ).first()
    b_follows_a = db.query(UserFollow).filter(
        UserFollow.follower_id == recipient_id,
        UserFollow.followed_id == sender_id,
    ).first()
    return bool(a_follows_b and b_follows_a)


@router.get("/messages", response_class=HTMLResponse)
async def inbox(request: Request, db: Session = Depends(get_db)):
    """Inbox — list of conversations grouped by user."""
    user = require_auth(request)
    uid = user["id"]

    # Get all users the current user has exchanged messages with,
    # along with the latest message and unread count
    all_messages = db.query(DirectMessage).filter(
        or_(DirectMessage.sender_id == uid, DirectMessage.recipient_id == uid)
    ).order_by(DirectMessage.created_at.desc()).all()

    # Group into conversations by the other user
    conversations = {}
    for msg in all_messages:
        other_id = msg.recipient_id if msg.sender_id == uid else msg.sender_id
        if other_id not in conversations:
            conversations[other_id] = {
                "other_user": msg.recipient if msg.sender_id == uid else msg.sender,
                "last_message": msg,
                "unread": 0,
            }
        if msg.recipient_id == uid and not msg.read_at:
            conversations[other_id]["unread"] += 1

    # Sort by last message time
    conv_list = sorted(conversations.values(), key=lambda c: c["last_message"].created_at, reverse=True)

    return templates.TemplateResponse("messages.html", {
        "request": request,
        "user": user,
        "conversations": conv_list,
    })


@router.get("/messages/{other_user_id}", response_class=HTMLResponse)
async def conversation(other_user_id: int, request: Request, db: Session = Depends(get_db)):
    """View conversation thread with a specific user."""
    user = require_auth(request)
    uid = user["id"]

    other_user = db.query(User).filter(User.id == other_user_id).first()
    if not other_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get messages between the two users
    messages = db.query(DirectMessage).filter(
        or_(
            and_(DirectMessage.sender_id == uid, DirectMessage.recipient_id == other_user_id),
            and_(DirectMessage.sender_id == other_user_id, DirectMessage.recipient_id == uid),
        )
    ).order_by(DirectMessage.created_at.asc()).all()

    # Mark unread messages as read
    unread = db.query(DirectMessage).filter(
        DirectMessage.sender_id == other_user_id,
        DirectMessage.recipient_id == uid,
        DirectMessage.read_at.is_(None),
    ).all()
    for msg in unread:
        msg.read_at = datetime.utcnow()
    if unread:
        db.commit()

    can_send = can_message(uid, other_user_id, db)

    return templates.TemplateResponse("conversation.html", {
        "request": request,
        "user": user,
        "other_user": other_user,
        "messages": messages,
        "can_send": can_send,
    })


@router.post("/messages/{other_user_id}/send")
async def send_message(
    other_user_id: int,
    request: Request,
    content: str = Form(...),
    db: Session = Depends(get_db),
):
    """Send a direct message."""
    user = require_auth(request)
    uid = user["id"]
    content = content.strip()

    if not content or len(content) < 1:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(content) > 5000:
        raise HTTPException(status_code=400, detail="Message must be 5000 characters or fewer")

    if not can_message(uid, other_user_id, db):
        raise HTTPException(status_code=403, detail="You cannot message this user. They only accept messages from mutual followers.")

    msg = DirectMessage(
        sender_id=uid,
        recipient_id=other_user_id,
        content=content,
        created_at=datetime.utcnow(),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    # Send notification
    create_notification(
        user_id=other_user_id,
        notification_type="direct_message",
        link=f"/messages/{uid}",
        db=db,
        source_user_id=uid,
        content_preview=content[:150],
    )
    db.commit()

    # Send email notification
    recipient = db.query(User).filter(User.id == other_user_id).first()
    if recipient and recipient.email:
        try:
            from services.email import EmailService
            email_service = EmailService()
            email_service.send_new_message_notification(
                to_email=recipient.email,
                sender_name=user["name"],
                message_preview=content,
            )
        except Exception as e:
            print(f"[messaging] Email notification failed: {e}")

    # Return the rendered message fragment
    return templates.TemplateResponse("components/message_bubble.html", {
        "request": request,
        "msg": msg,
        "user": user,
        "is_mine": True,
    })


def get_unread_message_count(user_id: int, db: Session) -> int:
    """Get count of unread messages for nav badge."""
    return db.query(func.count(DirectMessage.id)).filter(
        DirectMessage.recipient_id == user_id,
        DirectMessage.read_at.is_(None),
    ).scalar() or 0
