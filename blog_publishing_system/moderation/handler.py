"""Abstractions for a composable comment moderation chain."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ModerationResult:
    """Outcome returned by the moderation chain."""

    approved: bool
    reason: str = "Comment approved."


class CommentModerationHandler(ABC):
    """Base handler that checks a comment and delegates it to the next handler."""

    def __init__(self):
        self._next_handler = None

    def set_next(self, handler):
        """Connect a handler and return it for fluent chain construction."""
        self._next_handler = handler
        return handler

    @abstractmethod
    def reject_reason(self, content):
        """Return a rejection reason, or an empty value when this handler passes."""

    def handle(self, content):
        reason = self.reject_reason(content)
        if reason:
            return ModerationResult(approved=False, reason=reason)
        if self._next_handler is not None:
            return self._next_handler.handle(content)
        return ModerationResult(approved=True, reason="Comment approved.")
