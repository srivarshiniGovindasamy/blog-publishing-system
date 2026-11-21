"""Detect a small configurable set of clearly abusive language."""

import re

from moderation.handler import CommentModerationHandler


DEFAULT_ABUSIVE_TERMS = (
    "stupid",
    "useless",
    "idiot",
    "moron",
    "dumbass",
    "jackass",
    "asshole",
    "bastard",
    "fucking",
    "fuck",
    "shit",
    "bitch",
)


class AbusiveLanguageFilter(CommentModerationHandler):
    """Reject comments containing clearly insulting or profane terms."""

    REASON = "Inappropriate or offensive language detected."

    def __init__(self, terms=None):
        super().__init__()
        configured_terms = DEFAULT_ABUSIVE_TERMS if terms is None else terms
        self._patterns = tuple(
            re.compile(r"\b" + re.escape(term.strip()) + r"\b", re.IGNORECASE)
            for term in configured_terms
            if term.strip()
        )

    def reject_reason(self, content):
        if any(pattern.search(content) for pattern in self._patterns):
            return self.REASON
        return ""
