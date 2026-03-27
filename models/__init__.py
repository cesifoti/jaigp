"""Database models package."""
from models.database import Base, get_db, engine
from models.user import User
from models.paper import Paper, PaperVersion, PaperHumanAuthor, PaperAIAuthor, PaperField, PaperCategory, STAGE_NAMES
from models.comment import Comment, CommentVote
from models.paper_vote import PaperVote
from models.endorsement import Endorsement
from models.review import AIReview, HumanReview
from models.editorial import EditorialBoardMember, EditorialDecision
from models.stage_history import StageHistory
from models.extension import ExtensionRequest
from models.user_email import UserEmail
from models.submission_screening import SubmissionScreening
from models.prompt import CommunityPrompt, PromptComment, PromptCommentVote, PromptVote
from models.discussion import DiscussionPost, DiscussionComment, DiscussionCommentVote, DiscussionVote, UserFollow
from models.notification import Notification
from models.message import DirectMessage

__all__ = [
    "Base",
    "get_db",
    "engine",
    "User",
    "Paper",
    "PaperVersion",
    "PaperHumanAuthor",
    "PaperAIAuthor",
    "PaperField",
    "PaperCategory",
    "STAGE_NAMES",
    "Comment",
    "CommentVote",
    "PaperVote",
    "Endorsement",
    "AIReview",
    "HumanReview",
    "EditorialBoardMember",
    "EditorialDecision",
    "StageHistory",
    "ExtensionRequest",
    "UserEmail",
    "SubmissionScreening",
    "CommunityPrompt",
    "PromptComment",
    "PromptCommentVote",
    "PromptVote",
    "DiscussionPost",
    "DiscussionComment",
    "DiscussionCommentVote",
    "DiscussionVote",
    "UserFollow",
    "Notification",
    "DirectMessage",
]
