"""Detect direct attacks against the author or another person."""

import re

from moderation.handler import CommentModerationHandler


class PersonalAttackFilter(CommentModerationHandler):
    """Reject common explicit personal attacks while allowing content critique."""

    REASON = (
        "Personal attacks are not allowed. Please provide respectful, "
        "constructive feedback about the content."
    )
    _PATTERNS = tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\byou\s+(?:don't|do not)\s+know\s+anything\b",
            r"\byou\s+(?:are|'re)\s+(?:a\s+)?(?:terrible|awful|useless|stupid|idiot|moron)\b",
            r"\byou\s+(?:are|'re)\s+(?:a\s+)?(?:bad|incompetent)\s+writer\b",
            r"\bthe\s+author\s+(?:is|'s)\s+(?:useless|stupid|an?\s+idiot|a\s+moron)\b",
            r"\bonly\s+an?\s+(?:idiot|moron)\s+would\b",
        )
    )

    def reject_reason(self, content):
        if any(pattern.search(content) for pattern in self._PATTERNS):
            return self.REASON
        return ""
