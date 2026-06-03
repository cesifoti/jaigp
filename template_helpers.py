"""Template helpers for Jinja2 filters."""
from datetime import datetime
import re

def format_date(date_obj, format="%B %d, %Y"):
    """Format datetime object."""
    if date_obj:
        if isinstance(date_obj, str):
            return date_obj
        return date_obj.strftime(format)
    return ""

def smart_title_case(text):
    """
    Convert ALL CAPS titles to Title Case, preserving acronyms and proper formatting.
    Leaves already properly capitalized titles unchanged.
    """
    if not text:
        return text

    # Check if the title is mostly uppercase (more than 70% caps)
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return text

    caps_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)

    # If less than 70% uppercase, assume it's already properly formatted
    if caps_ratio < 0.7:
        return text

    # Words that should stay lowercase in titles (except at start)
    lowercase_words = {
        'a', 'an', 'and', 'as', 'at', 'but', 'by', 'for', 'from', 'in', 'into',
        'of', 'on', 'or', 'the', 'to', 'with', 'via', 'per', 'vs'
    }

    # Words that should stay all caps (common acronyms)
    acronyms = {'AI', 'ML', 'NLP', 'CV', 'US', 'UK', 'EU', 'USA', 'API', 'PDF',
                'HTML', 'CSS', 'SQL', 'RNA', 'DNA', 'GDP', 'CEO', 'PhD', 'MD'}

    words = text.split()
    result = []
    capitalize_next = True  # First word should be capitalized

    for i, word in enumerate(words):
        # Handle hyphenated words
        if '-' in word:
            parts = word.split('-')
            parts = [p.capitalize() if p.upper() not in acronyms else p.upper() for p in parts]
            result.append('-'.join(parts))
            capitalize_next = False
        # Keep acronyms as is
        elif word.upper() in acronyms:
            result.append(word.upper())
            capitalize_next = False
        # Capitalize after sentence punctuation (:, ?, !)
        elif capitalize_next or i == 0 or word.lower() not in lowercase_words:
            result.append(word.capitalize())
            capitalize_next = False
        # Lowercase words in the middle
        else:
            result.append(word.lower())
            capitalize_next = False

        # Check if this word ends with sentence-ending punctuation
        if result[-1] and result[-1][-1] in ':?!':
            capitalize_next = True

    return ' '.join(result)

def format_post(text):
    """Format user post text with basic markdown: **bold** and *italic*.

    Also unfurls /rules#slug links into inline preview cards.
    Text is auto-escaped first, then formatting markers are converted to HTML.
    """
    from markupsafe import Markup, escape
    if not text:
        return text
    # Escape HTML first to prevent XSS
    safe = str(escape(text))
    # **bold** (must come before *italic*)
    safe = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', safe)
    # *italic* (single asterisks, not inside **)
    safe = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', safe)
    # Unfurl /rules#slug links into preview cards
    safe = _unfurl_rule_links(safe)
    return Markup(safe)


def _unfurl_rule_links(html_text):
    """Detect /rules#slug patterns and replace with inline rule preview cards."""
    pattern = r'/rules#([\w_-]+)'

    def _replace(match):
        slug = match.group(1)
        try:
            from markupsafe import escape
            from models.database import SessionLocal
            from services.governance import get_rule_by_slug
            db = SessionLocal()
            try:
                rule = get_rule_by_slug(slug, db)
                if not rule:
                    return match.group(0)  # return as-is if slug not found
                label = rule.option_labels.get(rule.active_value, rule.active_value) if rule.is_votable else rule.active_value
                # Escape DB-sourced values before interpolating into HTML.
                # Defense-in-depth: rule titles/values aren't user-editable today,
                # but this guarantees no HTML can ever break out of these spans.
                safe_title = escape(rule.title)
                safe_label = escape(label)
                return (
                    f'<a href="/rules#{slug}" class="inline-block my-1 px-3 py-2 rounded-lg border border-slate-200 '
                    f'bg-slate-50 hover:bg-slate-100 transition text-xs no-underline">'
                    f'<span class="font-semibold text-secondary">{safe_title}</span>'
                    f' <span class="text-slate-400">·</span> '
                    f'<span class="font-medium text-emerald-700">{safe_label}</span>'
                    f'</a>'
                )
            finally:
                db.close()
        except Exception:
            return match.group(0)

    return re.sub(pattern, _replace, html_text)


# Register globally
def register_filters(env):
    """Register all custom filters and globals."""
    env.filters["format_date"] = format_date
    env.filters["smart_title"] = smart_title_case
    env.filters["format_post"] = format_post
    env.globals["app_name"] = "JAIGP - Journal for AI Generated Papers"
    return env
