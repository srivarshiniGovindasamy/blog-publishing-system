"""Simple local spam-pattern checks for comments."""

import re

from moderation.handler import CommentModerationHandler


class SpamFilter(CommentModerationHandler):
    """Reject comments with repeated patterns or excessive links."""

    MAX_URLS = 2
    MAX_REPEATED_CHARACTERS = 7
    MAX_REPEATED_WORDS = 3
    REASON = "Spam or irrelevant promotional content detected."
    PROMOTIONAL_PATTERNS = tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bvisit\s+my\s+(?:website|site|store)\b",
            r"\b(?:buy|order)\s+now\b",
            r"\bsubscribe\s+to\s+my\s+(?:channel|page)\b",
            r"\b(?:make|earn)\s+money\s+fast\b",
            r"\b(?:discount|promo)\s+code\b",
        )
    )

    def reject_reason(self, content):
        urls = re.findall(r"https?://\S+|www\.\S+", content, re.IGNORECASE)
        if len(urls) > self.MAX_URLS:
            return self.REASON

        if any(pattern.search(content) for pattern in self.PROMOTIONAL_PATTERNS):
            return self.REASON

        repeated_character_pattern = (
            r"(.)\1{" + str(self.MAX_REPEATED_CHARACTERS) + r",}"
        )
        if re.search(repeated_character_pattern, content):
            return self.REASON

        words = re.findall(r"\b[\w']+\b", content.casefold())
        repeated_words = 1
        for previous, current in zip(words, words[1:]):
            repeated_words = repeated_words + 1 if current == previous else 1
            if repeated_words >= self.MAX_REPEATED_WORDS:
                return self.REASON

        return ""
