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
    return Markup(safe)


# Register globally
def register_filters(env):
    """Register all custom filters and globals."""
    env.filters["format_date"] = format_date
    env.filters["smart_title"] = smart_title_case
    env.filters["format_post"] = format_post
    env.globals["app_name"] = "JAIGP - Journal for AI Generated Papers"
    return env
