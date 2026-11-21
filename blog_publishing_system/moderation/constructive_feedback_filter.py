"""Final permissive handler to preserve respectful opinions and criticism."""

from moderation.handler import CommentModerationHandler


class ConstructiveFeedbackFilter(CommentModerationHandler):
    """Pass content-related feedback without sentiment or keyword policing."""

    def reject_reason(self, content):
        return ""
